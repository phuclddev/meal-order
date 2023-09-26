from flask import Flask, request, jsonify, render_template, redirect, url_for
from ariadne import QueryType, MutationType, make_executable_schema, graphql_sync, load_schema_from_path
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from ariadne.explorer import ExplorerGraphiQL
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from ariadne import SchemaDirectiveVisitor
from graphql import default_field_resolver
from datetime import datetime, date
from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView

app = Flask(__name__)

explorer_html = ExplorerGraphiQL().html(None)
# Configure the database
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///todos.db'
db = SQLAlchemy(app)
admin = Admin(app, name='My admin', template_mode='bootstrap3')
# Models
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    entity = db.Column(db.Enum("GARENA", "OTHER"), nullable=False)
    location = db.Column(db.Enum("HN", "HCM"), nullable=False)
    phone = db.Column(db.String(15), nullable=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password = db.Column(db.String(60), nullable=False)
    orders = db.relationship('MealOrder', backref='user', lazy=True)
    registrations = db.relationship('Registration', backref='user', lazy=True)

class Meal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    location = db.Column(db.Enum("HN", "HCM"), nullable=False)
    date = db.Column(db.Date, nullable=False)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.String(255), nullable=True)
    price = db.Column(db.String(10), nullable=False)

class Setting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fromDate = db.Column(db.Date, nullable=False)
    toDate = db.Column(db.Date, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    year = db.Column(db.Integer, nullable=False)

class MealOrder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    location = db.Column(db.Enum("HN", "HCM"), nullable=False)
    date = db.Column(db.Date, nullable=False)
    type = db.Column(db.String(255), nullable=False)
    paid = db.Column(db.Boolean, default=False)
    meal_id = db.Column(db.Integer, db.ForeignKey('meal.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    # Define a relationship to the Meal model
    meal = db.relationship('Meal', backref='orders')

class Registration(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    month = db.Column(db.Integer, nullable=False)
    year = db.Column(db.Integer, nullable=False)
    choice = db.Column(db.Enum("yes", "no"), nullable=False)
    createdAt = db.Column(db.DateTime, default=datetime.utcnow)
    updatedAt = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

admin.add_view(ModelView(User, db.session))
admin.add_view(ModelView(Meal, db.session))
admin.add_view(ModelView(Setting, db.session))
admin.add_view(ModelView(MealOrder, db.session))
admin.add_view(ModelView(Registration, db.session))

# Configure Flask-Login
app.secret_key = 'your_secret_key'  # Replace with a strong secret key
login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.init_app(app)
@login_manager.user_loader
def load_user(user_id):
    # since the user_id is just the primary key of our user table, use it in the query for the user
    return User.query.get(int(user_id))


# Load the schema from the schema.graphql file
type_defs = load_schema_from_path("schema.graphql")

# Define your GraphQL resolvers
query = QueryType()
mutation = MutationType()
# GraphQL Resolvers
@query.field("currentUser")
def resolve_current_user(_, info):
    return current_user

@query.field("setting")
def resolve_setting(_, info):
    # Implement logic to fetch the current setting
    return Setting.query.first()

@query.field("meals")
def resolve_meals(_, info, location):
    # Implement logic to fetch meals based on the location
    return Meal.query.filter_by(location=location).all()

@query.field("registrations")
def resolve_registrations(_, info, location, month, year):
    # Implement logic to fetch registrations based on location, month, and year
    return Registration.query.filter_by(location=location, month=month, year=year).all()


@mutation.field("register")
def resolve_register(_, info, registerInput):
    # Implement logic to register a user
    user = current_user
    # Check if user's entity is GARENA
    if user.entity != "GARENA":
        raise Exception("Not eligible to register")

    # Check if choice is either 'yes' or 'no'
    if registerInput["choice"] not in ["yes", "no"]:
        raise Exception("Invalid input for 'choice'")

    # Check if there is a valid setting for the current date
    current_date = date.today()
    setting = Setting.query.filter(
        Setting.fromDate <= current_date,
        Setting.toDate >= current_date,
        Setting.month == registerInput["month"],
        Setting.year == registerInput["year"]
    ).first()

    if not setting:
        raise Exception("No setting found for the current date")

    # Check if the user already has a registration record for the current month
    existing_registration = Registration.query.filter(
        Registration.user_id == user.id,
        Registration.month == registerInput["month"],
        Registration.year == registerInput["year"]
    ).first()

    if existing_registration:
        # Update the existing registration
        existing_registration.choice = registerInput["choice"]
    else:
        # Create a new registration
        registration = Registration(
            user_id=user.id,
            month=registerInput["month"],
            year=registerInput["year"],
            choice=registerInput["choice"]
        )
        db.session.add(registration)
    db.session.commit()
    # Return the user object after registration
    return user


@mutation.field("orderMeal")
def resolve_order_meal(_, info, mealId):
    # Implement logic to order a meal and return MealOrderResult
    meal = Meal.query.get(mealId)
    if not meal:
        return {"success": False, "message": "Meal not found"}

    current_datetime = datetime.now()
    meal_date = meal.date

    # Calculate the cutoff time for ordering (10 AM on the meal date)
    ordering_cutoff_time = datetime(meal_date.year, meal_date.month, meal_date.day, 10, 0, 0)

    if current_datetime >= ordering_cutoff_time:
        return {"success": False, "message": "Cannot order after 10 AM on the meal date"}

    meal_order = MealOrder(
        location=meal.location,
        date=current_datetime.date(),
        type=meal.name,
        paid=False,
        user_id=current_user.id,
        meal_id=meal.id,
    )
    db.session.add(meal_order)
    db.session.commit()
    return {"success": True, "message": "Meal ordered successfully"}

@mutation.field("removeOrder")
def resolve_remove_order(_, info, mealOrderId):
    # Implement logic to remove a meal order and return MealOrderResult
    meal_order = MealOrder.query.get(mealOrderId)
    if not meal_order:
        return {"success": False, "message": "Meal order not found"}

    current_datetime = datetime.now()
    meal_date = meal_order.date

    # Calculate the cutoff time for removing (10 AM on the meal date)
    removal_cutoff_time = datetime(meal_date.year, meal_date.month, meal_date.day, 10, 0, 0)

    if current_datetime >= removal_cutoff_time:
        return {"success": False, "message": "Cannot remove after 10 AM on the meal date"}

    db.session.delete(meal_order)
    db.session.commit()
    return {"success": True, "message": "Meal order removed successfully"}


# Custom directive implementation
class UppercaseDirective(SchemaDirectiveVisitor):
    def visit_field_definition(self, field, object_type):
        original_resolve = field.resolve or default_field_resolver

        def uppercased_resolver(root, info, **kwargs):
            result = original_resolve(root, info, **kwargs)
            if isinstance(result, str):
                return result.upper()
            return result

        field.resolve = uppercased_resolver
        return field


class AuthDirective(SchemaDirectiveVisitor):
    def visit_field_definition(self, field, object_type):
        original_resolve = field.resolve or default_field_resolver

        def auth_resolver(root, info, **kwargs):
            if not current_user.is_authenticated:  # Check if the user is authenticated
                raise Exception("Unauthorized")  # You can customize this error message
            return original_resolve(root, info, **kwargs)

        field.resolve = auth_resolver
        return field


# Create a schema using the type definitions and add the directive
schema = make_executable_schema(type_defs, [query, mutation], directives={"uppercase": UppercaseDirective, "auth": AuthDirective})


# Login route
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        user = User.query.filter_by(username=username).first()
        print(user)
        if user and user.password == password:
            login_user(user)
            return redirect(url_for("graphql_explorer"))
    return render_template("login.html")


# Logout route
@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


# Serve the GraphQL Playground at the "/graphql" route for GET requests
@app.route("/graphql", methods=["GET"])
def graphql_explorer():
    return explorer_html, 200


# GraphQL endpoint
@app.route("/graphql", methods=["POST"])
def graphql_server():
    data = request.get_json()
    success, result = graphql_sync(schema, data, context_value={"request": request})
    status_code = 200 if success else 400
    return jsonify(result), status_code

if __name__ == "__main__":
    # Create the database tables if they don't exist
    with app.app_context():
        db.create_all()
    app.run(debug=True)
