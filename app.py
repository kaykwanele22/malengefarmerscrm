from datetime import datetime
from pathlib import Path
from functools import wraps
import csv
import io
import os

from flask import (
    Flask, Response, abort, redirect, send_file,
    render_template, render_template_string, request, session, url_for
)
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy import func, or_
from werkzeug.security import check_password_hash, generate_password_hash

# =========================================================
# FLASK APPLICATION
# =========================================================
app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["SECRET_KEY"] = "malenge-farmers-development-key"
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///malenge_farmers.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
migrate = Migrate(app, db)

# =========================================================
# DATABASE MODELS
# =========================================================
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fullname = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(30), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    farm_location = db.Column(db.String(150), nullable=False)
    password = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Cooperative(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    cooperative_type = db.Column(db.String(30), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=True)
    registration_number = db.Column(db.String(120), nullable=True)
    code = db.Column(db.String(50), nullable=True)
    location = db.Column(db.String(200), nullable=True)
    status = db.Column(db.String(30), default="Active", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    parent = db.relationship("Cooperative", remote_side=[id], backref=db.backref("primary_cooperatives", lazy=True))

class Farmer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=True)
    fullname = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(150), nullable=True)
    location = db.Column(db.String(200), nullable=False)
    farm_size = db.Column(db.Float, nullable=True)
    primary_crop = db.Column(db.String(100), nullable=True)
    status = db.Column(db.String(50), default="Active")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id], backref="cooperative_farmers")

class Farm(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=True)
    name = db.Column(db.String(150), nullable=False)
    farmer_id = db.Column(db.Integer, db.ForeignKey("farmer.id"), nullable=False)
    location = db.Column(db.String(200), nullable=False)
    size = db.Column(db.Float, nullable=True)
    farming_type = db.Column(db.String(100), nullable=True)
    main_crop = db.Column(db.String(100), nullable=True)
    registration_date = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(50), default="Active")
    farmer = db.relationship("Farmer", backref="farms")
    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id], backref="cooperative_farms")

class Crop(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=True)
    name = db.Column(db.String(120), nullable=False)
    farm_id = db.Column(db.Integer, db.ForeignKey("farm.id"), nullable=False)
    variety = db.Column(db.String(120), nullable=True)
    planting_date = db.Column(db.Date, nullable=True)
    expected_harvest_date = db.Column(db.Date, nullable=True)
    area_planted = db.Column(db.Float, nullable=True)
    status = db.Column(db.String(50), default="Planted")
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    farm = db.relationship("Farm", backref="crops")
    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id], backref="cooperative_crops")

class Harvest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=True)
    crop_id = db.Column(db.Integer, db.ForeignKey("crop.id"), nullable=False)
    harvest_date = db.Column(db.Date, nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(30), default="kg")
    quality_grade = db.Column(db.String(50), nullable=True)
    storage_location = db.Column(db.String(200), nullable=True)
    status = db.Column(db.String(50), default="Available")
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    crop = db.relationship("Crop", backref="harvests")
    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id], backref="cooperative_harvests")

class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=True)
    harvest_id = db.Column(db.Integer, db.ForeignKey("harvest.id"), nullable=False)
    buyer_name = db.Column(db.String(150), nullable=False)
    buyer_phone = db.Column(db.String(50), nullable=True)
    quantity = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(30), default="kg")
    price_per_unit = db.Column(db.Float, nullable=False)
    total_amount = db.Column(db.Float, nullable=False)
    sale_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(50), default="Pending")
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    harvest = db.relationship("Harvest", backref="sales")
    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id], backref="cooperative_sales")

class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=True)
    sale_id = db.Column(db.Integer, db.ForeignKey("sale.id"), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    payment_date = db.Column(db.Date, nullable=False)
    method = db.Column(db.String(50), nullable=True)
    reference = db.Column(db.String(120), nullable=True)
    status = db.Column(db.String(50), default="Received")
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    sale = db.relationship("Sale", backref="payments")
    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id], backref="cooperative_payments")

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=True)
    name = db.Column(db.String(150), nullable=False)
    contact_person = db.Column(db.String(150), nullable=True)
    phone = db.Column(db.String(50), nullable=True)
    email = db.Column(db.String(150), nullable=True)
    address = db.Column(db.String(250), nullable=True)
    customer_type = db.Column(db.String(80), nullable=True)
    status = db.Column(db.String(30), default="Active")
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id], backref="cooperative_customers")

class Supplier(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=True)
    name = db.Column(db.String(150), nullable=False)
    contact_person = db.Column(db.String(150), nullable=True)
    phone = db.Column(db.String(50), nullable=True)
    email = db.Column(db.String(150), nullable=True)
    address = db.Column(db.String(250), nullable=True)
    supplier_type = db.Column(db.String(100), nullable=True)
    status = db.Column(db.String(30), default="Active")
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id], backref="cooperative_suppliers")

class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=True)
    farm_id = db.Column(db.Integer, db.ForeignKey("farm.id"), nullable=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("supplier.id"), nullable=True)
    category = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(250), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    expense_date = db.Column(db.Date, nullable=False)
    payment_method = db.Column(db.String(50), nullable=True)
    reference = db.Column(db.String(120), nullable=True)
    status = db.Column(db.String(50), default="Paid")
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    farm = db.relationship("Farm", backref="expenses")
    supplier = db.relationship("Supplier", backref="expenses")
    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id], backref="cooperative_expenses")

class InventoryItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=True)
    name = db.Column(db.String(150), nullable=False)
    category = db.Column(db.String(100), nullable=True)
    unit = db.Column(db.String(30), default="units")
    quantity_on_hand = db.Column(db.Float, default=0)
    reorder_level = db.Column(db.Float, default=0)
    unit_cost = db.Column(db.Float, default=0)
    storage_location = db.Column(db.String(200), nullable=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("supplier.id"), nullable=True)
    status = db.Column(db.String(30), default="Active")
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    supplier = db.relationship("Supplier", backref="inventory_items")
    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id], backref="cooperative_inventory_items")

class InventoryTransaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=True)
    inventory_item_id = db.Column(db.Integer, db.ForeignKey("inventory_item.id"), nullable=False)
    transaction_type = db.Column(db.String(30), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    transaction_date = db.Column(db.Date, nullable=False)
    reference = db.Column(db.String(120), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    inventory_item = db.relationship("InventoryItem", backref="transactions")
    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id], backref="cooperative_inventory_transactions")

class Equipment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=True)
    name = db.Column(db.String(150), nullable=False)
    equipment_type = db.Column(db.String(100), nullable=True)
    serial_number = db.Column(db.String(120), nullable=True)
    farm_id = db.Column(db.Integer, db.ForeignKey("farm.id"), nullable=True)
    purchase_date = db.Column(db.Date, nullable=True)
    purchase_cost = db.Column(db.Float, nullable=True)
    last_service_date = db.Column(db.Date, nullable=True)
    next_service_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(50), default="Available")
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    farm = db.relationship("Farm", backref="equipment")
    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id], backref="cooperative_equipment")

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=True)
    title = db.Column(db.String(180), nullable=False)
    description = db.Column(db.Text, nullable=True)
    farm_id = db.Column(db.Integer, db.ForeignKey("farm.id"), nullable=True)
    assigned_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    due_date = db.Column(db.Date, nullable=True)
    priority = db.Column(db.String(30), default="Normal")
    status = db.Column(db.String(30), default="Open")
    completed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    farm = db.relationship("Farm", backref="tasks")
    assigned_user = db.relationship("User", backref="tasks")
    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id], backref="cooperative_tasks")

class FarmerInteraction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=True)
    farmer_id = db.Column(db.Integer, db.ForeignKey("farmer.id"), nullable=False)
    interaction_date = db.Column(db.Date, nullable=False)
    interaction_type = db.Column(db.String(80), nullable=False)
    subject = db.Column(db.String(180), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    follow_up_date = db.Column(db.Date, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    farmer = db.relationship("Farmer", backref="interactions")
    user = db.relationship("User", backref="farmer_interactions")
    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id], backref="cooperative_farmer_interactions")

class Membership(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=True)
    farmer_id = db.Column(db.Integer, db.ForeignKey("farmer.id"), nullable=False)
    member_number = db.Column(db.String(80), unique=True, nullable=False)
    membership_type = db.Column(db.String(80), default="Primary")
    join_date = db.Column(db.Date, nullable=True)
    fee_amount = db.Column(db.Float, default=0)
    fee_paid = db.Column(db.Float, default=0)
    status = db.Column(db.String(30), default="Active")
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    farmer = db.relationship("Farmer", backref="memberships")
    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id], backref="cooperative_memberships")

class Contribution(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=True)
    farmer_id = db.Column(db.Integer, db.ForeignKey("farmer.id"), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    contribution_date = db.Column(db.Date, nullable=False)
    category = db.Column(db.String(100), nullable=True)
    method = db.Column(db.String(50), nullable=True)
    reference = db.Column(db.String(120), nullable=True)
    status = db.Column(db.String(30), default="Received")
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    farmer = db.relationship("Farmer", backref="contributions")
    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id], backref="cooperative_contributions")

class UserAccess(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), unique=True, nullable=False)
    role = db.Column(db.String(30), default="Staff", nullable=False)
    status = db.Column(db.String(30), default="Active", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship("User", backref=db.backref("access_record", uselist=False))
    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id], backref="user_access_records")

class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    action = db.Column(db.String(80), nullable=False)
    entity_type = db.Column(db.String(80), nullable=False)
    entity_id = db.Column(db.Integer, nullable=True)
    details = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship("User", backref="audit_logs")
    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id], backref="cooperative_audit_logs")

# =========================================================
# HELPERS
# =========================================================
SECONDARY_ROLES = {"Admin", "Secondary Chairperson", "Secondary Secretary", "Secondary Treasurer", "Secondary Manager"}
PRIMARY_ROLES = {"Primary Chairperson", "Primary Secretary", "Primary Treasurer", "Primary Manager", "Staff", "Viewer"}
VALID_ACCESS_ROLES = SECONDARY_ROLES | PRIMARY_ROLES

def logged_in():
    return "user_id" in session

def current_user():
    if not logged_in():
        return None
    return db.session.get(User, session.get("user_id"))

def login_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if not logged_in():
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)
    return wrapped_view

def get_user_access(user_id):
    access = UserAccess.query.filter_by(user_id=user_id).first()
    if access:
        return access
    first_user_id = db.session.query(func.min(User.id)).scalar()
    role = "Admin" if user_id == first_user_id else "Staff"
    access = UserAccess(user_id=user_id, role=role, status="Active", cooperative_id=None)
    db.session.add(access)
    db.session.commit()
    return access

def current_access():
    if not logged_in():
        return None
    return get_user_access(session["user_id"])

def current_cooperative():
    access = current_access()
    if not access or not access.cooperative_id:
        return None
    return db.session.get(Cooperative, access.cooperative_id)

def accessible_cooperative_ids(user_id=None):
    if user_id is None:
        if not logged_in():
            return []
        user_id = session["user_id"]
    access = get_user_access(user_id)
    if access.status != "Active":
        return []
    if access.role == "Admin":
        return None
    if not access.cooperative_id:
        return []
    cooperative = db.session.get(Cooperative, access.cooperative_id)
    if not cooperative or cooperative.status != "Active":
        return []
    if access.role in SECONDARY_ROLES and cooperative.cooperative_type == "Secondary":
        child_ids = [child.id for child in cooperative.primary_cooperatives if child.status == "Active"]
        return [cooperative.id] + child_ids
    return [cooperative.id]

def can_access_cooperative(cooperative_id, user_id=None):
    if cooperative_id is None:
        return False
    allowed_ids = accessible_cooperative_ids(user_id)
    if allowed_ids is None:
        return True
    return cooperative_id in allowed_ids

def scope_cooperative_query(query, model, user_id=None, include_unassigned_for_admin=True):
    allowed_ids = accessible_cooperative_ids(user_id)
    if allowed_ids is None:
        return query
    if not allowed_ids:
        return query.filter(model.cooperative_id.in_([]))
    return query.filter(model.cooperative_id.in_(allowed_ids))

def scoped_model_query(model, user_id=None):
    return scope_cooperative_query(model.query, model, user_id=user_id)

def scoped_get(model, record_id, user_id=None):
    if record_id is None:
        return None
    return scoped_model_query(model, user_id=user_id).filter(model.id == record_id).first()

def scoped_get_or_404(model, record_id, user_id=None):
    record = scoped_get(model, record_id, user_id=user_id)
    if record is None:
        abort(404)
    return record

def accessible_cooperative_query():
    query = Cooperative.query
    allowed_ids = accessible_cooperative_ids()
    if allowed_ids is None:
        return query
    if not allowed_ids:
        return query.filter(Cooperative.id.in_([]))
    return query.filter(Cooperative.id.in_(allowed_ids))

def accessible_users_query():
    query = User.query.outerjoin(UserAccess, UserAccess.user_id == User.id)
    allowed_ids = accessible_cooperative_ids()
    if allowed_ids is None:
        return query
    if not allowed_ids:
        return query.filter(User.id.in_([]))
    return query.filter(UserAccess.cooperative_id.in_(allowed_ids)).distinct()

def default_record_cooperative_id(fallback_cooperative_id=None):
    if not logged_in():
        return fallback_cooperative_id
    access = get_user_access(session["user_id"])
    if access.role in PRIMARY_ROLES and access.cooperative_id:
        return access.cooperative_id
    return fallback_cooperative_id or access.cooperative_id

def roles_required(*allowed_roles):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped_view(*args, **kwargs):
            if not logged_in():
                return redirect(url_for("login"))
            access = get_user_access(session["user_id"])
            if access.status != "Active" or access.role not in allowed_roles:
                abort(403)
            return view_func(*args, **kwargs)
        return wrapped_view
    return decorator

def parse_float(value, default=None):
    if value is None:
        return default
    value = str(value).strip()
    if not value:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

def parse_int(value, default=None):
    if value is None:
        return default
    value = str(value).strip()
    if not value:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

def add_audit_log(action, entity_type, entity_id=None, details=None, cooperative_id=None):
    if cooperative_id is None and logged_in():
        access = UserAccess.query.filter_by(user_id=session.get("user_id")).first()
        if access:
            cooperative_id = access.cooperative_id
    log = AuditLog(
        user_id=session.get("user_id"),
        cooperative_id=cooperative_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
    )
    db.session.add(log)

def sale_paid_amount(sale):
    return sum(p.amount for p in sale.payments if p.status != "Reversed")

def sale_outstanding_amount(sale):
    return max(float(sale.total_amount or 0) - float(sale_paid_amount(sale) or 0), 0)

def harvest_sold_quantity(harvest, exclude_sale_id=None):
    total = 0.0
    for sale in harvest.sales:
        if exclude_sale_id and sale.id == exclude_sale_id:
            continue
        if sale.status == "Cancelled":
            continue
        total += float(sale.quantity or 0)
    return total

def make_csv_response(filename, headers, rows):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f'attachment; filename="{filename}"'})

def parse_date(value):
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()

def template_exists(template_name):
    template_path = Path(app.root_path) / (app.template_folder or "templates") / template_name
    return template_path.exists()

def render_optional_template(template_name, module_title, **context):
    if template_exists(template_name):
        return render_template(template_name, **context)
    return render_template_string("""
        <!DOCTYPE html>
        <html lang="en">
        <head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{{ module_title }} | Malenge Farmers CRM</title>
        <style>body{margin:0;font-family:Arial,Helvetica,sans-serif;background:#f4f7f5;color:#1f2937}
        .placeholder{max-width:720px;margin:80px auto;padding:40px;background:#fff;border-radius:14px;box-shadow:0 3px 15px rgba(0,0,0,0.06)}
        h1{margin-top:0;color:#173b2b}
        a{display:inline-block;margin-top:20px;padding:11px 18px;background:#2e7d4f;color:#fff;text-decoration:none;border-radius:8px}</style>
        </head><body>
        <div class="placeholder"><h1>{{ module_title }}</h1><p>The backend for this module is ready.</p>
        <p>The template <strong>{{ template_name }}</strong> has not been created yet.</p>
        <a href="{{ dashboard_url }}">Back to Dashboard</a></div></body></html>
    """, module_title=module_title, template_name=template_name, dashboard_url=url_for("dashboard"))

# =========================================================
# LANDING PAGE
# =========================================================
@app.route("/")
def home():
    return render_template("landing.html")

# =========================================================
# LOGIN
# =========================================================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            session["user_id"] = user.id
            session["fullname"] = user.fullname
            return redirect(url_for("dashboard"))
        return "Invalid email or password.", 401
    return render_template("login.html")

# =========================================================
# REGISTER
# =========================================================
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        fullname = request.form.get("fullname", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip().lower()
        farm_location = request.form.get("farm_location", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not all([fullname, phone, email, farm_location, password, confirm_password]):
            return "Please complete all required fields.", 400
        if password != confirm_password:
            return "Passwords do not match.", 400
        if len(password) < 8:
            return "Password must be at least 8 characters.", 400

        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            return "An account with this email already exists.", 400

        hashed_password = generate_password_hash(password)
        new_user = User(fullname=fullname, phone=phone, email=email, farm_location=farm_location, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for("login"))
    return render_template("register.html")

# =========================================================
# DASHBOARD
# =========================================================
@app.route("/dashboard")
def dashboard():
    if not logged_in():
        return redirect(url_for("login"))

    farmer_count = scoped_model_query(Farmer).count()
    farm_count = scoped_model_query(Farm).count()
    crop_count = scoped_model_query(Crop).count()
    harvest_count = scoped_model_query(Harvest).count()
    sales_count = scoped_model_query(Sale).count()
    payment_count = scoped_model_query(Payment).count()

    total_sales_value = scoped_model_query(Sale).with_entities(func.coalesce(func.sum(Sale.total_amount), 0)).scalar() or 0
    total_payments_value = scoped_model_query(Payment).with_entities(func.coalesce(func.sum(Payment.amount), 0)).scalar() or 0
    outstanding_balance = total_sales_value - total_payments_value

    recent_farmers = scoped_model_query(Farmer).order_by(Farmer.created_at.desc()).limit(5).all()
    recent_sales = scoped_model_query(Sale).order_by(Sale.created_at.desc()).limit(5).all()
    recent_payments = scoped_model_query(Payment).order_by(Payment.created_at.desc()).limit(5).all()

    customer_count = scoped_model_query(Customer).count()
    supplier_count = scoped_model_query(Supplier).count()
    expense_count = scoped_model_query(Expense).count()
    inventory_count = scoped_model_query(InventoryItem).count()
    equipment_count = scoped_model_query(Equipment).count()
    open_task_count = scoped_model_query(Task).filter(Task.status != "Completed").count()

    total_expenses_value = scoped_model_query(Expense).filter(Expense.status != "Cancelled").with_entities(func.coalesce(func.sum(Expense.amount), 0)).scalar() or 0
    total_contributions_value = scoped_model_query(Contribution).filter(Contribution.status == "Received").with_entities(func.coalesce(func.sum(Contribution.amount), 0)).scalar() or 0
    net_cash_position = float(total_payments_value) - float(total_expenses_value)

    secondary_cooperatives = accessible_cooperative_query().filter_by(cooperative_type="Secondary", status="Active").order_by(Cooperative.name.asc()).all()
    primary_cooperatives = accessible_cooperative_query().filter_by(cooperative_type="Primary", status="Active").order_by(Cooperative.name.asc()).all()

    primary_performance = []
    for cooperative in primary_cooperatives:
        coop_sales = db.session.query(func.coalesce(func.sum(Sale.total_amount), 0)).filter(Sale.cooperative_id == cooperative.id).scalar() or 0
        coop_payments = db.session.query(func.coalesce(func.sum(Payment.amount), 0)).filter(Payment.cooperative_id == cooperative.id, Payment.status != "Reversed").scalar() or 0
        coop_expenses = db.session.query(func.coalesce(func.sum(Expense.amount), 0)).filter(Expense.cooperative_id == cooperative.id, Expense.status != "Cancelled").scalar() or 0
        primary_performance.append({
            "cooperative": cooperative,
            "farmer_count": scoped_model_query(Farmer).filter_by(cooperative_id=cooperative.id).count(),
            "farm_count": scoped_model_query(Farm).filter_by(cooperative_id=cooperative.id).count(),
            "crop_count": scoped_model_query(Crop).filter_by(cooperative_id=cooperative.id).count(),
            "harvest_count": scoped_model_query(Harvest).filter_by(cooperative_id=cooperative.id).count(),
            "sales_value": float(coop_sales),
            "payments_value": float(coop_payments),
            "expenses_value": float(coop_expenses),
            "outstanding_balance": float(coop_sales) - float(coop_payments),
            "open_tasks": scoped_model_query(Task).filter(Task.cooperative_id == cooperative.id, Task.status != "Completed").count(),
            "low_stock_items": scoped_model_query(InventoryItem).filter(InventoryItem.cooperative_id == cooperative.id, InventoryItem.status == "Active", InventoryItem.quantity_on_hand <= InventoryItem.reorder_level).count(),
        })

    today = datetime.utcnow().date()
    overdue_task_count = scoped_model_query(Task).filter(Task.status != "Completed", Task.due_date.isnot(None), Task.due_date < today).count()
    low_stock_count = scoped_model_query(InventoryItem).filter(InventoryItem.status == "Active", InventoryItem.quantity_on_hand <= InventoryItem.reorder_level).count()
    service_due_count = scoped_model_query(Equipment).filter(Equipment.next_service_date.isnot(None), Equipment.next_service_date <= today, Equipment.status != "Retired").count()
    unpaid_membership_count = scoped_model_query(Membership).filter(Membership.status == "Active", Membership.fee_paid < Membership.fee_amount).count()

    recent_cooperative_activity = scoped_model_query(AuditLog).filter(AuditLog.cooperative_id.isnot(None)).order_by(AuditLog.created_at.desc()).limit(15).all()

    return render_template("dashboard.html",
        farmer_count=farmer_count, farm_count=farm_count, crop_count=crop_count,
        harvest_count=harvest_count, sales_count=sales_count, payment_count=payment_count,
        total_sales_value=total_sales_value, total_payments_value=total_payments_value,
        outstanding_balance=outstanding_balance, recent_farmers=recent_farmers,
        recent_sales=recent_sales, recent_payments=recent_payments,
        customer_count=customer_count, supplier_count=supplier_count,
        expense_count=expense_count, inventory_count=inventory_count,
        equipment_count=equipment_count, open_task_count=open_task_count,
        total_expenses_value=total_expenses_value, total_contributions_value=total_contributions_value,
        net_cash_position=net_cash_position, secondary_cooperatives=secondary_cooperatives,
        primary_cooperatives=primary_cooperatives, primary_performance=primary_performance,
        recent_cooperative_activity=recent_cooperative_activity,
        overdue_task_count=overdue_task_count, low_stock_count=low_stock_count,
        service_due_count=service_due_count, unpaid_membership_count=unpaid_membership_count,
        today=today, current_access=current_access(), current_cooperative=current_cooperative()
    )

# =========================================================
# FARMERS
# =========================================================
@app.route("/farmers")
def farmers():
    if not logged_in():
        return redirect(url_for("login"))
    search = request.args.get("search", "").strip()
    if search:
        farmers_list = scoped_model_query(Farmer).filter(or_(Farmer.fullname.ilike(f"%{search}%"), Farmer.phone.ilike(f"%{search}%"), Farmer.location.ilike(f"%{search}%"), Farmer.primary_crop.ilike(f"%{search}%"))).order_by(Farmer.created_at.desc()).all()
    else:
        farmers_list = scoped_model_query(Farmer).order_by(Farmer.created_at.desc()).all()
    return render_template("farmers.html", farmers=farmers_list, search=search)

@app.route("/farmers/add", methods=["GET", "POST"])
def add_farmer():
    if not logged_in():
        return redirect(url_for("login"))
    if request.method == "POST":
        fullname = request.form.get("fullname", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        location = request.form.get("location", "").strip()
        farm_size = request.form.get("farm_size", "").strip()
        primary_crop = request.form.get("primary_crop", "").strip()
        status = request.form.get("status", "Active").strip()

        if not fullname or not phone or not location:
            return "Name, phone number and location are required.", 400
        try:
            farm_size_value = float(farm_size) if farm_size else None
        except ValueError:
            return "Farm size must be a number.", 400

        new_farmer = Farmer(fullname=fullname, phone=phone, email=email or None, location=location, farm_size=farm_size_value, primary_crop=primary_crop or None, status=status, cooperative_id=default_record_cooperative_id())
        db.session.add(new_farmer)
        db.session.commit()
        return redirect(url_for("farmers"))
    return render_template("farmer_form.html", farmer=None)

@app.route("/farmers/edit/<int:farmer_id>", methods=["GET", "POST"])
def edit_farmer(farmer_id):
    if not logged_in():
        return redirect(url_for("login"))
    farmer = scoped_get_or_404(Farmer, farmer_id)
    if request.method == "POST":
        farmer.fullname = request.form.get("fullname", "").strip()
        farmer.phone = request.form.get("phone", "").strip()
        farmer.email = request.form.get("email", "").strip() or None
        farmer.location = request.form.get("location", "").strip()
        farm_size = request.form.get("farm_size", "").strip()
        try:
            farmer.farm_size = float(farm_size) if farm_size else None
        except ValueError:
            return "Farm size must be a number.", 400
        farmer.primary_crop = request.form.get("primary_crop", "").strip() or None
        farmer.status = request.form.get("status", "Active").strip()
        db.session.commit()
        return redirect(url_for("farmers"))
    return render_template("farmer_form.html", farmer=farmer)

@app.route("/farmers/delete/<int:farmer_id>", methods=["POST"])
def delete_farmer(farmer_id):
    if not logged_in():
        return redirect(url_for("login"))
    farmer = scoped_get_or_404(Farmer, farmer_id)
    if farmer.farms:
        return "This farmer cannot be deleted because farms are linked to the farmer.", 400
    db.session.delete(farmer)
    db.session.commit()
    return redirect(url_for("farmers"))

# =========================================================
# FARMS
# =========================================================
@app.route("/farms")
def farms():
    if not logged_in():
        return redirect(url_for("login"))
    search = request.args.get("search", "").strip()
    if search:
        farms_list = scoped_model_query(Farm).join(Farmer).filter(or_(Farm.name.ilike(f"%{search}%"), Farm.location.ilike(f"%{search}%"), Farm.farming_type.ilike(f"%{search}%"), Farm.main_crop.ilike(f"%{search}%"), Farmer.fullname.ilike(f"%{search}%"))).order_by(Farm.registration_date.desc()).all()
    else:
        farms_list = scoped_model_query(Farm).order_by(Farm.registration_date.desc()).all()
    return render_template("farms.html", farms=farms_list, search=search)

@app.route("/farms/add", methods=["GET", "POST"])
def add_farm():
    if not logged_in():
        return redirect(url_for("login"))
    farmers_list = scoped_model_query(Farmer).order_by(Farmer.fullname.asc()).all()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        farmer_id = request.form.get("farmer_id", "").strip()
        location = request.form.get("location", "").strip()
        size = request.form.get("size", "").strip()
        farming_type = request.form.get("farming_type", "").strip()
        main_crop = request.form.get("main_crop", "").strip()
        status = request.form.get("status", "Active").strip()

        if not name or not farmer_id or not location:
            return "Farm name, farmer and location are required.", 400
        try:
            farmer_id_value = int(farmer_id)
            size_value = float(size) if size else None
        except ValueError:
            return "Invalid farmer or farm size.", 400

        farmer = scoped_get(Farmer, farmer_id_value)
        if not farmer:
            return "Selected farmer does not exist.", 400

        new_farm = Farm(name=name, farmer_id=farmer.id, location=location, size=size_value, farming_type=farming_type or None, main_crop=main_crop or None, status=status, cooperative_id=default_record_cooperative_id(farmer.cooperative_id))
        db.session.add(new_farm)
        db.session.commit()
        return redirect(url_for("farms"))
    return render_template("farm_form.html", farm=None, farmers=farmers_list)

@app.route("/farms/edit/<int:farm_id>", methods=["GET", "POST"])
def edit_farm(farm_id):
    if not logged_in():
        return redirect(url_for("login"))
    farm = scoped_get_or_404(Farm, farm_id)
    farmers_list = scoped_model_query(Farmer).order_by(Farmer.fullname.asc()).all()
    if request.method == "POST":
        farm.name = request.form.get("name", "").strip()
        farmer_id = request.form.get("farmer_id", "").strip()
        farm.location = request.form.get("location", "").strip()
        size = request.form.get("size", "").strip()
        farm.farming_type = request.form.get("farming_type", "").strip() or None
        farm.main_crop = request.form.get("main_crop", "").strip() or None
        farm.status = request.form.get("status", "Active").strip()

        if not farm.name or not farmer_id or not farm.location:
            return "Farm name, farmer and location are required.", 400
        try:
            farmer_id_value = int(farmer_id)
            farm.size = float(size) if size else None
        except ValueError:
            return "Invalid farmer or farm size.", 400

        farmer = scoped_get(Farmer, farmer_id_value)
        if not farmer:
            return "Selected farmer does not exist.", 400
        farm.farmer_id = farmer.id
        farm.cooperative_id = default_record_cooperative_id(farmer.cooperative_id)
        db.session.commit()
        return redirect(url_for("farms"))
    return render_template("farm_form.html", farm=farm, farmers=farmers_list)

@app.route("/farms/delete/<int:farm_id>", methods=["POST"])
def delete_farm(farm_id):
    if not logged_in():
        return redirect(url_for("login"))
    farm = scoped_get_or_404(Farm, farm_id)
    if farm.crops:
        return "This farm cannot be deleted because crops are linked to it.", 400
    db.session.delete(farm)
    db.session.commit()
    return redirect(url_for("farms"))

# =========================================================
# CROPS
# =========================================================
@app.route("/crops")
def crops():
    if not logged_in():
        return redirect(url_for("login"))
    search = request.args.get("search", "").strip()
    query = scoped_model_query(Crop).join(Farm).join(Farmer)
    if search:
        query = query.filter(or_(Crop.name.ilike(f"%{search}%"), Crop.variety.ilike(f"%{search}%"), Crop.status.ilike(f"%{search}%"), Farm.name.ilike(f"%{search}%"), Farmer.fullname.ilike(f"%{search}%")))
    crops_list = query.order_by(Crop.created_at.desc()).all()
    return render_template("crops.html", crops=crops_list, search=search)

@app.route("/crops/add", methods=["GET", "POST"])
def add_crop():
    if not logged_in():
        return redirect(url_for("login"))
    farms_list = scoped_model_query(Farm).order_by(Farm.name.asc()).all()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        farm_id = request.form.get("farm_id", "").strip()
        variety = request.form.get("variety", "").strip()
        planting_date_text = request.form.get("planting_date", "").strip()
        expected_harvest_date_text = request.form.get("expected_harvest_date", "").strip()
        area_planted = request.form.get("area_planted", "").strip()
        status = request.form.get("status", "Planted").strip()
        notes = request.form.get("notes", "").strip()

        if not name or not farm_id:
            return "Crop name and farm are required.", 400
        try:
            farm_id_value = int(farm_id)
            area_planted_value = float(area_planted) if area_planted else None
            planting_date_value = parse_date(planting_date_text)
            expected_harvest_date_value = parse_date(expected_harvest_date_text)
        except ValueError:
            return "Please enter valid crop information.", 400

        farm = scoped_get(Farm, farm_id_value)
        if not farm:
            return "Selected farm does not exist.", 400

        new_crop = Crop(name=name, farm_id=farm.id, variety=variety or None, planting_date=planting_date_value, expected_harvest_date=expected_harvest_date_value, area_planted=area_planted_value, status=status, notes=notes or None, cooperative_id=default_record_cooperative_id(farm.cooperative_id))
        db.session.add(new_crop)
        db.session.commit()
        return redirect(url_for("crops"))
    return render_template("crop_form.html", crop=None, farms=farms_list)

@app.route("/crops/edit/<int:crop_id>", methods=["GET", "POST"])
def edit_crop(crop_id):
    if not logged_in():
        return redirect(url_for("login"))
    crop = scoped_get_or_404(Crop, crop_id)
    farms_list = scoped_model_query(Farm).order_by(Farm.name.asc()).all()
    if request.method == "POST":
        crop.name = request.form.get("name", "").strip()
        farm_id = request.form.get("farm_id", "").strip()
        crop.variety = request.form.get("variety", "").strip() or None
        planting_date_text = request.form.get("planting_date", "").strip()
        expected_harvest_date_text = request.form.get("expected_harvest_date", "").strip()
        area_planted = request.form.get("area_planted", "").strip()
        crop.status = request.form.get("status", "Planted").strip()
        crop.notes = request.form.get("notes", "").strip() or None

        if not crop.name or not farm_id:
            return "Crop name and farm are required.", 400
        try:
            farm_id_value = int(farm_id)
            crop.area_planted = float(area_planted) if area_planted else None
            crop.planting_date = parse_date(planting_date_text)
            crop.expected_harvest_date = parse_date(expected_harvest_date_text)
        except ValueError:
            return "Please enter valid crop information.", 400

        farm = scoped_get(Farm, farm_id_value)
        if not farm:
            return "Selected farm does not exist.", 400
        crop.farm_id = farm.id
        crop.cooperative_id = default_record_cooperative_id(farm.cooperative_id)
        db.session.commit()
        return redirect(url_for("crops"))
    return render_template("crop_form.html", crop=crop, farms=farms_list)

@app.route("/crops/delete/<int:crop_id>", methods=["POST"])
def delete_crop(crop_id):
    if not logged_in():
        return redirect(url_for("login"))
    crop = scoped_get_or_404(Crop, crop_id)
    if crop.harvests:
        return "This crop cannot be deleted because harvests are linked to it.", 400
    db.session.delete(crop)
    db.session.commit()
    return redirect(url_for("crops"))

# =========================================================
# HARVESTS
# =========================================================
@app.route("/harvests")
def harvests():
    if not logged_in():
        return redirect(url_for("login"))
    search = request.args.get("search", "").strip()
    query = scoped_model_query(Harvest).join(Crop).join(Farm).join(Farmer)
    if search:
        query = query.filter(or_(Crop.name.ilike(f"%{search}%"), Farm.name.ilike(f"%{search}%"), Farmer.fullname.ilike(f"%{search}%"), Harvest.quality_grade.ilike(f"%{search}%"), Harvest.storage_location.ilike(f"%{search}%"), Harvest.status.ilike(f"%{search}%")))
    harvests_list = query.order_by(Harvest.created_at.desc()).all()
    return render_optional_template("harvests.html", "Harvests", harvests=harvests_list, search=search)

@app.route("/harvests/add", methods=["GET", "POST"])
def add_harvest():
    if not logged_in():
        return redirect(url_for("login"))
    crops_list = scoped_model_query(Crop).order_by(Crop.name.asc()).all()
    if request.method == "POST":
        crop_id = request.form.get("crop_id", "").strip()
        harvest_date_text = request.form.get("harvest_date", "").strip()
        quantity = request.form.get("quantity", "").strip()
        unit = request.form.get("unit", "kg").strip()
        quality_grade = request.form.get("quality_grade", "").strip()
        storage_location = request.form.get("storage_location", "").strip()
        status = request.form.get("status", "Available").strip()
        notes = request.form.get("notes", "").strip()

        if not crop_id or not harvest_date_text or not quantity:
            return "Crop, harvest date and quantity are required.", 400
        try:
            crop_id_value = int(crop_id)
            harvest_date_value = parse_date(harvest_date_text)
            quantity_value = float(quantity)
        except ValueError:
            return "Please enter valid harvest information.", 400

        crop = scoped_get(Crop, crop_id_value)
        if not crop:
            return "Selected crop does not exist.", 400

        new_harvest = Harvest(crop_id=crop.id, harvest_date=harvest_date_value, quantity=quantity_value, unit=unit or "kg", quality_grade=quality_grade or None, storage_location=storage_location or None, status=status, notes=notes or None, cooperative_id=default_record_cooperative_id(crop.cooperative_id))
        db.session.add(new_harvest)
        db.session.commit()
        return redirect(url_for("harvests"))
    return render_optional_template("harvest_form.html", "Add Harvest", harvest=None, crops=crops_list)

@app.route("/harvests/edit/<int:harvest_id>", methods=["GET", "POST"])
def edit_harvest(harvest_id):
    if not logged_in():
        return redirect(url_for("login"))
    harvest = scoped_get_or_404(Harvest, harvest_id)
    crops_list = scoped_model_query(Crop).order_by(Crop.name.asc()).all()
    if request.method == "POST":
        crop_id = request.form.get("crop_id", "").strip()
        harvest_date_text = request.form.get("harvest_date", "").strip()
        quantity = request.form.get("quantity", "").strip()
        unit = request.form.get("unit", "kg").strip()
        quality_grade = request.form.get("quality_grade", "").strip()
        storage_location = request.form.get("storage_location", "").strip()
        status = request.form.get("status", "Available").strip()
        notes = request.form.get("notes", "").strip()

        if not crop_id or not harvest_date_text or not quantity:
            return "Crop, harvest date and quantity are required.", 400
        try:
            crop_id_value = int(crop_id)
            harvest.harvest_date = parse_date(harvest_date_text)
            harvest.quantity = float(quantity)
        except ValueError:
            return "Please enter valid harvest information.", 400

        crop = scoped_get(Crop, crop_id_value)
        if not crop:
            return "Selected crop does not exist.", 400

        harvest.crop_id = crop.id
        harvest.cooperative_id = default_record_cooperative_id(crop.cooperative_id)
        harvest.unit = unit or "kg"
        harvest.quality_grade = quality_grade or None
        harvest.storage_location = storage_location or None
        harvest.status = status
        harvest.notes = notes or None
        db.session.commit()
        return redirect(url_for("harvests"))
    return render_optional_template("harvest_form.html", "Edit Harvest", harvest=harvest, crops=crops_list)

@app.route("/harvests/delete/<int:harvest_id>", methods=["POST"])
def delete_harvest(harvest_id):
    if not logged_in():
        return redirect(url_for("login"))
    harvest = scoped_get_or_404(Harvest, harvest_id)
    if harvest.sales:
        return "This harvest cannot be deleted because sales are linked to it.", 400
    db.session.delete(harvest)
    db.session.commit()
    return redirect(url_for("harvests"))

# =========================================================
# SALES
# =========================================================
@app.route("/sales")
def sales():
    if not logged_in():
        return redirect(url_for("login"))
    search = request.args.get("search", "").strip()
    query = scoped_model_query(Sale).join(Harvest).join(Crop).join(Farm)
    if search:
        query = query.filter(or_(Sale.buyer_name.ilike(f"%{search}%"), Sale.buyer_phone.ilike(f"%{search}%"), Sale.status.ilike(f"%{search}%"), Crop.name.ilike(f"%{search}%"), Farm.name.ilike(f"%{search}%")))
    sales_list = query.order_by(Sale.created_at.desc()).all()
    return render_optional_template("sales.html", "Sales", sales=sales_list, search=search)

@app.route("/sales/add", methods=["GET", "POST"])
def add_sale():
    if not logged_in():
        return redirect(url_for("login"))
    harvests_list = scoped_model_query(Harvest).order_by(Harvest.harvest_date.desc()).all()
    if request.method == "POST":
        harvest_id = request.form.get("harvest_id", "").strip()
        buyer_name = request.form.get("buyer_name", "").strip()
        buyer_phone = request.form.get("buyer_phone", "").strip()
        quantity = request.form.get("quantity", "").strip()
        unit = request.form.get("unit", "kg").strip()
        price_per_unit = request.form.get("price_per_unit", "").strip()
        sale_date_text = request.form.get("sale_date", "").strip()
        status = request.form.get("status", "Pending").strip()
        notes = request.form.get("notes", "").strip()

        if not harvest_id or not buyer_name or not quantity or not price_per_unit or not sale_date_text:
            return "Harvest, buyer, quantity, price and sale date are required.", 400
        try:
            harvest_id_value = int(harvest_id)
            quantity_value = float(quantity)
            price_per_unit_value = float(price_per_unit)
            sale_date_value = parse_date(sale_date_text)
        except ValueError:
            return "Please enter valid sale information.", 400

        harvest = scoped_get(Harvest, harvest_id_value)
        if not harvest:
            return "Selected harvest does not exist.", 400

        total_amount_value = quantity_value * price_per_unit_value
        new_sale = Sale(harvest_id=harvest.id, buyer_name=buyer_name, buyer_phone=buyer_phone or None, quantity=quantity_value, unit=unit or "kg", price_per_unit=price_per_unit_value, total_amount=total_amount_value, sale_date=sale_date_value, status=status, notes=notes or None, cooperative_id=default_record_cooperative_id(harvest.cooperative_id))
        db.session.add(new_sale)
        db.session.commit()
        return redirect(url_for("sales"))
    return render_optional_template("sale_form.html", "Add Sale", sale=None, harvests=harvests_list)

@app.route("/sales/edit/<int:sale_id>", methods=["GET", "POST"])
def edit_sale(sale_id):
    if not logged_in():
        return redirect(url_for("login"))
    sale = scoped_get_or_404(Sale, sale_id)
    harvests_list = scoped_model_query(Harvest).order_by(Harvest.harvest_date.desc()).all()
    if request.method == "POST":
        harvest_id = request.form.get("harvest_id", "").strip()
        buyer_name = request.form.get("buyer_name", "").strip()
        buyer_phone = request.form.get("buyer_phone", "").strip()
        quantity = request.form.get("quantity", "").strip()
        unit = request.form.get("unit", "kg").strip()
        price_per_unit = request.form.get("price_per_unit", "").strip()
        sale_date_text = request.form.get("sale_date", "").strip()
        status = request.form.get("status", "Pending").strip()
        notes = request.form.get("notes", "").strip()

        if not harvest_id or not buyer_name or not quantity or not price_per_unit or not sale_date_text:
            return "Harvest, buyer, quantity, price and sale date are required.", 400
        try:
            harvest_id_value = int(harvest_id)
            quantity_value = float(quantity)
            price_per_unit_value = float(price_per_unit)
            sale_date_value = parse_date(sale_date_text)
        except ValueError:
            return "Please enter valid sale information.", 400

        harvest = scoped_get(Harvest, harvest_id_value)
        if not harvest:
            return "Selected harvest does not exist.", 400

        sale.harvest_id = harvest.id
        sale.cooperative_id = default_record_cooperative_id(harvest.cooperative_id)
        sale.buyer_name = buyer_name
        sale.buyer_phone = buyer_phone or None
        sale.quantity = quantity_value
        sale.unit = unit or "kg"
        sale.price_per_unit = price_per_unit_value
        sale.total_amount = quantity_value * price_per_unit_value
        sale.sale_date = sale_date_value
        sale.status = status
        sale.notes = notes or None
        db.session.commit()
        return redirect(url_for("sales"))
    return render_optional_template("sale_form.html", "Edit Sale", sale=sale, harvests=harvests_list)

@app.route("/sales/delete/<int:sale_id>", methods=["POST"])
def delete_sale(sale_id):
    if not logged_in():
        return redirect(url_for("login"))
    sale = scoped_get_or_404(Sale, sale_id)
    if sale.payments:
        return "This sale cannot be deleted because payments are linked to it.", 400
    db.session.delete(sale)
    db.session.commit()
    return redirect(url_for("sales"))

# =========================================================
# PAYMENTS
# =========================================================
@app.route("/payments")
def payments():
    if not logged_in():
        return redirect(url_for("login"))
    search = request.args.get("search", "").strip()
    query = scoped_model_query(Payment).join(Sale)
    if search:
        query = query.filter(or_(Sale.buyer_name.ilike(f"%{search}%"), Payment.method.ilike(f"%{search}%"), Payment.reference.ilike(f"%{search}%"), Payment.status.ilike(f"%{search}%")))
    payments_list = query.order_by(Payment.created_at.desc()).all()
    return render_optional_template("payments.html", "Payments", payments=payments_list, search=search)

@app.route("/payments/add", methods=["GET", "POST"])
def add_payment():
    if not logged_in():
        return redirect(url_for("login"))
    sales_list = scoped_model_query(Sale).order_by(Sale.sale_date.desc()).all()
    if request.method == "POST":
        sale_id = request.form.get("sale_id", "").strip()
        amount = request.form.get("amount", "").strip()
        payment_date_text = request.form.get("payment_date", "").strip()
        method = request.form.get("method", "").strip()
        reference = request.form.get("reference", "").strip()
        status = request.form.get("status", "Received").strip()
        notes = request.form.get("notes", "").strip()

        if not sale_id or not amount or not payment_date_text:
            return "Sale, amount and payment date are required.", 400
        try:
            sale_id_value = int(sale_id)
            amount_value = float(amount)
            payment_date_value = parse_date(payment_date_text)
        except ValueError:
            return "Please enter valid payment information.", 400

        sale = scoped_get(Sale, sale_id_value)
        if not sale:
            return "Selected sale does not exist.", 400

        new_payment = Payment(sale_id=sale.id, amount=amount_value, payment_date=payment_date_value, method=method or None, reference=reference or None, status=status, notes=notes or None, cooperative_id=default_record_cooperative_id(sale.cooperative_id))
        db.session.add(new_payment)
        db.session.commit()
        return redirect(url_for("payments"))
    return render_optional_template("payment_form.html", "Add Payment", payment=None, sales=sales_list)

@app.route("/payments/edit/<int:payment_id>", methods=["GET", "POST"])
def edit_payment(payment_id):
    if not logged_in():
        return redirect(url_for("login"))
    payment = scoped_get_or_404(Payment, payment_id)
    sales_list = scoped_model_query(Sale).order_by(Sale.sale_date.desc()).all()
    if request.method == "POST":
        sale_id = request.form.get("sale_id", "").strip()
        amount = request.form.get("amount", "").strip()
        payment_date_text = request.form.get("payment_date", "").strip()
        method = request.form.get("method", "").strip()
        reference = request.form.get("reference", "").strip()
        status = request.form.get("status", "Received").strip()
        notes = request.form.get("notes", "").strip()

        if not sale_id or not amount or not payment_date_text:
            return "Sale, amount and payment date are required.", 400
        try:
            sale_id_value = int(sale_id)
            amount_value = float(amount)
            payment_date_value = parse_date(payment_date_text)
        except ValueError:
            return "Please enter valid payment information.", 400

        sale = scoped_get(Sale, sale_id_value)
        if not sale:
            return "Selected sale does not exist.", 400

        payment.sale_id = sale.id
        payment.cooperative_id = default_record_cooperative_id(sale.cooperative_id)
        payment.amount = amount_value
        payment.payment_date = payment_date_value
        payment.method = method or None
        payment.reference = reference or None
        payment.status = status
        payment.notes = notes or None
        db.session.commit()
        return redirect(url_for("payments"))
    return render_optional_template("payment_form.html", "Edit Payment", payment=payment, sales=sales_list)

@app.route("/payments/delete/<int:payment_id>", methods=["POST"])
def delete_payment(payment_id):
    if not logged_in():
        return redirect(url_for("login"))
    payment = scoped_get_or_404(Payment, payment_id)
    db.session.delete(payment)
    db.session.commit()
    return redirect(url_for("payments"))

# =========================================================
# CUSTOMERS / BUYERS
# =========================================================
@app.route("/customers")
@login_required
def customers():
    search = request.args.get("search", "").strip()
    query = scoped_model_query(Customer)
    if search:
        query = query.filter(or_(Customer.name.ilike(f"%{search}%"), Customer.contact_person.ilike(f"%{search}%"), Customer.phone.ilike(f"%{search}%"), Customer.email.ilike(f"%{search}%"), Customer.customer_type.ilike(f"%{search}%")))
    customers_list = query.order_by(Customer.name.asc()).all()
    return render_optional_template("customers.html", "Customers / Buyers", customers=customers_list, search=search)

@app.route("/customers/add", methods=["GET", "POST"])
@login_required
def add_customer():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            return "Customer name is required.", 400
        customer = Customer(
            cooperative_id=default_record_cooperative_id(),
            name=name,
            contact_person=request.form.get("contact_person", "").strip() or None,
            phone=request.form.get("phone", "").strip() or None,
            email=request.form.get("email", "").strip() or None,
            address=request.form.get("address", "").strip() or None,
            customer_type=request.form.get("customer_type", "").strip() or None,
            status=request.form.get("status", "Active").strip(),
            notes=request.form.get("notes", "").strip() or None,
        )
        db.session.add(customer)
        db.session.flush()
        add_audit_log("CREATE", "Customer", customer.id, customer.name, cooperative_id=customer.cooperative_id)
        db.session.commit()
        return redirect(url_for("customers"))
    return render_optional_template("customer_form.html", "Add Customer", customer=None)

@app.route("/customers/edit/<int:customer_id>", methods=["GET", "POST"])
@login_required
def edit_customer(customer_id):
    customer = scoped_get_or_404(Customer, customer_id)
    if request.method == "POST":
        customer.name = request.form.get("name", "").strip()
        if not customer.name:
            return "Customer name is required.", 400
        customer.contact_person = request.form.get("contact_person", "").strip() or None
        customer.phone = request.form.get("phone", "").strip() or None
        customer.email = request.form.get("email", "").strip() or None
        customer.address = request.form.get("address", "").strip() or None
        customer.customer_type = request.form.get("customer_type", "").strip() or None
        customer.status = request.form.get("status", "Active").strip()
        customer.notes = request.form.get("notes", "").strip() or None
        add_audit_log("UPDATE", "Customer", customer.id, customer.name)
        db.session.commit()
        return redirect(url_for("customers"))
    return render_optional_template("customer_form.html", "Edit Customer", customer=customer)

@app.route("/customers/delete/<int:customer_id>", methods=["POST"])
@login_required
def delete_customer(customer_id):
    customer = scoped_get_or_404(Customer, customer_id)
    add_audit_log("DELETE", "Customer", customer.id, customer.name)
    db.session.delete(customer)
    db.session.commit()
    return redirect(url_for("customers"))

# =========================================================
# SUPPLIERS
# =========================================================
@app.route("/suppliers")
@login_required
def suppliers():
    search = request.args.get("search", "").strip()
    query = scoped_model_query(Supplier)
    if search:
        query = query.filter(or_(Supplier.name.ilike(f"%{search}%"), Supplier.contact_person.ilike(f"%{search}%"), Supplier.phone.ilike(f"%{search}%"), Supplier.email.ilike(f"%{search}%"), Supplier.supplier_type.ilike(f"%{search}%")))
    suppliers_list = query.order_by(Supplier.name.asc()).all()
    return render_optional_template("suppliers.html", "Suppliers", suppliers=suppliers_list, search=search)

@app.route("/suppliers/add", methods=["GET", "POST"])
@login_required
def add_supplier():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            return "Supplier name is required.", 400
        supplier = Supplier(
            cooperative_id=default_record_cooperative_id(),
            name=name,
            contact_person=request.form.get("contact_person", "").strip() or None,
            phone=request.form.get("phone", "").strip() or None,
            email=request.form.get("email", "").strip() or None,
            address=request.form.get("address", "").strip() or None,
            supplier_type=request.form.get("supplier_type", "").strip() or None,
            status=request.form.get("status", "Active").strip(),
            notes=request.form.get("notes", "").strip() or None,
        )
        db.session.add(supplier)
        db.session.flush()
        add_audit_log("CREATE", "Supplier", supplier.id, supplier.name, cooperative_id=supplier.cooperative_id)
        db.session.commit()
        return redirect(url_for("suppliers"))
    return render_optional_template("supplier_form.html", "Add Supplier", supplier=None)

@app.route("/suppliers/edit/<int:supplier_id>", methods=["GET", "POST"])
@login_required
def edit_supplier(supplier_id):
    supplier = scoped_get_or_404(Supplier, supplier_id)
    if request.method == "POST":
        supplier.name = request.form.get("name", "").strip()
        if not supplier.name:
            return "Supplier name is required.", 400
        supplier.contact_person = request.form.get("contact_person", "").strip() or None
        supplier.phone = request.form.get("phone", "").strip() or None
        supplier.email = request.form.get("email", "").strip() or None
        supplier.address = request.form.get("address", "").strip() or None
        supplier.supplier_type = request.form.get("supplier_type", "").strip() or None
        supplier.status = request.form.get("status", "Active").strip()
        supplier.notes = request.form.get("notes", "").strip() or None
        add_audit_log("UPDATE", "Supplier", supplier.id, supplier.name)
        db.session.commit()
        return redirect(url_for("suppliers"))
    return render_optional_template("supplier_form.html", "Edit Supplier", supplier=supplier)

@app.route("/suppliers/delete/<int:supplier_id>", methods=["POST"])
@login_required
def delete_supplier(supplier_id):
    supplier = scoped_get_or_404(Supplier, supplier_id)
    if supplier.expenses or supplier.inventory_items:
        return "This supplier cannot be deleted because linked records exist.", 400
    add_audit_log("DELETE", "Supplier", supplier.id, supplier.name)
    db.session.delete(supplier)
    db.session.commit()
    return redirect(url_for("suppliers"))

# =========================================================
# EXPENSES
# =========================================================
@app.route("/expenses")
@login_required
def expenses():
    search = request.args.get("search", "").strip()
    query = scoped_model_query(Expense).outerjoin(Farm).outerjoin(Supplier)
    if search:
        query = query.filter(or_(Expense.category.ilike(f"%{search}%"), Expense.description.ilike(f"%{search}%"), Expense.reference.ilike(f"%{search}%"), Expense.status.ilike(f"%{search}%"), Farm.name.ilike(f"%{search}%"), Supplier.name.ilike(f"%{search}%")))
    expenses_list = query.order_by(Expense.expense_date.desc()).all()
    return render_optional_template("expenses.html", "Expenses", expenses=expenses_list, search=search)

@app.route("/expenses/add", methods=["GET", "POST"])
@login_required
def add_expense():
    farms_list = scoped_model_query(Farm).order_by(Farm.name.asc()).all()
    suppliers_list = scoped_model_query(Supplier).order_by(Supplier.name.asc()).all()
    if request.method == "POST":
        category = request.form.get("category", "").strip()
        description = request.form.get("description", "").strip()
        amount = parse_float(request.form.get("amount"))
        expense_date = parse_date(request.form.get("expense_date"))

        if not category or not description:
            return "Category and description are required.", 400
        if amount is None or amount < 0:
            return "Expense amount must be valid.", 400
        if not expense_date:
            return "A valid expense date is required.", 400

        farm_id_value = parse_int(request.form.get("farm_id"))
        supplier_id_value = parse_int(request.form.get("supplier_id"))
        farm_record = scoped_get(Farm, farm_id_value) if farm_id_value else None
        supplier_record = scoped_get(Supplier, supplier_id_value) if supplier_id_value else None
        inherited_cooperative_id = farm_record.cooperative_id if farm_record else supplier_record.cooperative_id if supplier_record else None

        expense = Expense(
            cooperative_id=default_record_cooperative_id(inherited_cooperative_id),
            farm_id=farm_id_value,
            supplier_id=supplier_id_value,
            category=category,
            description=description,
            amount=amount,
            expense_date=expense_date,
            payment_method=request.form.get("payment_method", "").strip() or None,
            reference=request.form.get("reference", "").strip() or None,
            status=request.form.get("status", "Paid").strip(),
            notes=request.form.get("notes", "").strip() or None,
        )
        db.session.add(expense)
        db.session.flush()
        add_audit_log("CREATE", "Expense", expense.id, f"{category} - R{amount:.2f}", cooperative_id=expense.cooperative_id)
        db.session.commit()
        return redirect(url_for("expenses"))
    return render_optional_template("expense_form.html", "Add Expense", expense=None, farms=farms_list, suppliers=suppliers_list)

@app.route("/expenses/edit/<int:expense_id>", methods=["GET", "POST"])
@login_required
def edit_expense(expense_id):
    expense = scoped_get_or_404(Expense, expense_id)
    farms_list = scoped_model_query(Farm).order_by(Farm.name.asc()).all()
    suppliers_list = scoped_model_query(Supplier).order_by(Supplier.name.asc()).all()
    if request.method == "POST":
        category = request.form.get("category", "").strip()
        description = request.form.get("description", "").strip()
        amount = parse_float(request.form.get("amount"))
        expense_date = parse_date(request.form.get("expense_date"))

        if not category or not description:
            return "Category and description are required.", 400
        if amount is None or amount < 0:
            return "Expense amount must be valid.", 400
        if not expense_date:
            return "A valid expense date is required.", 400

        farm_id_value = parse_int(request.form.get("farm_id"))
        supplier_id_value = parse_int(request.form.get("supplier_id"))
        farm_record = scoped_get(Farm, farm_id_value) if farm_id_value else None
        supplier_record = scoped_get(Supplier, supplier_id_value) if supplier_id_value else None
        inherited_cooperative_id = farm_record.cooperative_id if farm_record else supplier_record.cooperative_id if supplier_record else expense.cooperative_id

        expense.farm_id = farm_id_value
        expense.supplier_id = supplier_id_value
        expense.cooperative_id = default_record_cooperative_id(inherited_cooperative_id)
        expense.category = category
        expense.description = description
        expense.amount = amount
        expense.expense_date = expense_date
        expense.payment_method = request.form.get("payment_method", "").strip() or None
        expense.reference = request.form.get("reference", "").strip() or None
        expense.status = request.form.get("status", "Paid").strip()
        expense.notes = request.form.get("notes", "").strip() or None
        add_audit_log("UPDATE", "Expense", expense.id, expense.description)
        db.session.commit()
        return redirect(url_for("expenses"))
    return render_optional_template("expense_form.html", "Edit Expense", expense=expense, farms=farms_list, suppliers=suppliers_list)

@app.route("/expenses/delete/<int:expense_id>", methods=["POST"])
@login_required
def delete_expense(expense_id):
    expense = scoped_get_or_404(Expense, expense_id)
    add_audit_log("DELETE", "Expense", expense.id, expense.description)
    db.session.delete(expense)
    db.session.commit()
    return redirect(url_for("expenses"))

# =========================================================
# INVENTORY
# =========================================================
@app.route("/inventory")
@login_required
def inventory():
    search = request.args.get("search", "").strip()
    query = scoped_model_query(InventoryItem).outerjoin(Supplier)
    if search:
        query = query.filter(or_(InventoryItem.name.ilike(f"%{search}%"), InventoryItem.category.ilike(f"%{search}%"), InventoryItem.storage_location.ilike(f"%{search}%"), Supplier.name.ilike(f"%{search}%")))
    items = query.order_by(InventoryItem.name.asc()).all()
    return render_optional_template("inventory.html", "Inventory", items=items, search=search)

@app.route("/inventory/add", methods=["GET", "POST"])
@login_required
def add_inventory_item():
    suppliers_list = scoped_model_query(Supplier).order_by(Supplier.name.asc()).all()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            return "Inventory item name is required.", 400
        supplier_id_value = parse_int(request.form.get("supplier_id"))
        supplier_record = scoped_get(Supplier, supplier_id_value) if supplier_id_value else None

        item = InventoryItem(
            cooperative_id=default_record_cooperative_id(supplier_record.cooperative_id if supplier_record else None),
            name=name,
            category=request.form.get("category", "").strip() or None,
            unit=request.form.get("unit", "units").strip(),
            quantity_on_hand=parse_float(request.form.get("quantity_on_hand"), 0),
            reorder_level=parse_float(request.form.get("reorder_level"), 0),
            unit_cost=parse_float(request.form.get("unit_cost"), 0),
            storage_location=request.form.get("storage_location", "").strip() or None,
            supplier_id=supplier_id_value,
            status=request.form.get("status", "Active").strip(),
            notes=request.form.get("notes", "").strip() or None,
        )
        db.session.add(item)
        db.session.flush()
        add_audit_log("CREATE", "InventoryItem", item.id, item.name, cooperative_id=item.cooperative_id)
        db.session.commit()
        return redirect(url_for("inventory"))
    return render_optional_template("inventory_form.html", "Add Inventory Item", item=None, suppliers=suppliers_list)

@app.route("/inventory/edit/<int:item_id>", methods=["GET", "POST"])
@login_required
def edit_inventory_item(item_id):
    item = scoped_get_or_404(InventoryItem, item_id)
    suppliers_list = scoped_model_query(Supplier).order_by(Supplier.name.asc()).all()
    if request.method == "POST":
        item.name = request.form.get("name", "").strip()
        if not item.name:
            return "Inventory item name is required.", 400
        item.category = request.form.get("category", "").strip() or None
        item.unit = request.form.get("unit", "units").strip()
        item.reorder_level = parse_float(request.form.get("reorder_level"), 0)
        item.unit_cost = parse_float(request.form.get("unit_cost"), 0)
        item.storage_location = request.form.get("storage_location", "").strip() or None

        supplier_id_value = parse_int(request.form.get("supplier_id"))
        supplier_record = scoped_get(Supplier, supplier_id_value) if supplier_id_value else None
        item.supplier_id = supplier_id_value
        item.cooperative_id = default_record_cooperative_id(supplier_record.cooperative_id if supplier_record else item.cooperative_id)

        item.status = request.form.get("status", "Active").strip()
        item.notes = request.form.get("notes", "").strip() or None
        add_audit_log("UPDATE", "InventoryItem", item.id, item.name)
        db.session.commit()
        return redirect(url_for("inventory"))
    return render_optional_template("inventory_form.html", "Edit Inventory Item", item=item, suppliers=suppliers_list)

@app.route("/inventory/adjust/<int:item_id>", methods=["POST"])
@login_required
def adjust_inventory(item_id):
    item = scoped_get_or_404(InventoryItem, item_id)
    transaction_type = request.form.get("transaction_type", "").strip()
    quantity = parse_float(request.form.get("quantity"))
    transaction_date = parse_date(request.form.get("transaction_date"))

    if transaction_type not in {"IN", "OUT", "ADJUSTMENT"}:
        return "Invalid inventory transaction type.", 400
    if quantity is None or quantity <= 0:
        return "Quantity must be greater than zero.", 400
    if not transaction_date:
        return "A valid transaction date is required.", 400

    if transaction_type == "IN":
        item.quantity_on_hand += quantity
    elif transaction_type == "OUT":
        if quantity > item.quantity_on_hand:
            return "Not enough inventory is available.", 400
        item.quantity_on_hand -= quantity
    else:
        item.quantity_on_hand = quantity

    transaction = InventoryTransaction(
        cooperative_id=default_record_cooperative_id(item.cooperative_id),
        inventory_item_id=item.id,
        transaction_type=transaction_type,
        quantity=quantity,
        transaction_date=transaction_date,
        reference=request.form.get("reference", "").strip() or None,
        notes=request.form.get("notes", "").strip() or None,
    )
    db.session.add(transaction)
    add_audit_log("ADJUST", "InventoryItem", item.id, f"{transaction_type} {quantity:g} {item.unit}", cooperative_id=item.cooperative_id)
    db.session.commit()
    return redirect(url_for("inventory"))

@app.route("/inventory/delete/<int:item_id>", methods=["POST"])
@login_required
def delete_inventory_item(item_id):
    item = scoped_get_or_404(InventoryItem, item_id)
    if item.transactions:
        return "This inventory item cannot be deleted because transaction history exists.", 400
    add_audit_log("DELETE", "InventoryItem", item.id, item.name)
    db.session.delete(item)
    db.session.commit()
    return redirect(url_for("inventory"))

# =========================================================
# EQUIPMENT
# =========================================================
@app.route("/equipment")
@login_required
def equipment():
    search = request.args.get("search", "").strip()
    query = scoped_model_query(Equipment).outerjoin(Farm)
    if search:
        query = query.filter(or_(Equipment.name.ilike(f"%{search}%"), Equipment.equipment_type.ilike(f"%{search}%"), Equipment.serial_number.ilike(f"%{search}%"), Equipment.status.ilike(f"%{search}%"), Farm.name.ilike(f"%{search}%")))
    equipment_list = query.order_by(Equipment.name.asc()).all()
    return render_optional_template("equipment.html", "Equipment", equipment=equipment_list, search=search)

@app.route("/equipment/add", methods=["GET", "POST"])
@login_required
def add_equipment():
    farms_list = scoped_model_query(Farm).order_by(Farm.name.asc()).all()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            return "Equipment name is required.", 400

        farm_id_value = parse_int(request.form.get("farm_id"))
        farm = scoped_get(Farm, farm_id_value) if farm_id_value else None

        equipment_item = Equipment(
            cooperative_id=default_record_cooperative_id(farm.cooperative_id if farm else None),
            name=name,
            equipment_type=request.form.get("equipment_type", "").strip() or None,
            serial_number=request.form.get("serial_number", "").strip() or None,
            farm_id=farm_id_value,
            purchase_date=parse_date(request.form.get("purchase_date")),
            purchase_cost=parse_float(request.form.get("purchase_cost")),
            last_service_date=parse_date(request.form.get("last_service_date")),
            next_service_date=parse_date(request.form.get("next_service_date")),
            status=request.form.get("status", "Available").strip(),
            notes=request.form.get("notes", "").strip() or None,
        )
        db.session.add(equipment_item)
        db.session.flush()
        add_audit_log("CREATE", "Equipment", equipment_item.id, equipment_item.name, cooperative_id=equipment_item.cooperative_id)
        db.session.commit()
        return redirect(url_for("equipment"))
    return render_optional_template("equipment_form.html", "Add Equipment", equipment_item=None, farms=farms_list)

@app.route("/equipment/edit/<int:equipment_id>", methods=["GET", "POST"])
@login_required
def edit_equipment(equipment_id):
    equipment_item = scoped_get_or_404(Equipment, equipment_id)
    farms_list = scoped_model_query(Farm).order_by(Farm.name.asc()).all()
    if request.method == "POST":
        equipment_item.name = request.form.get("name", "").strip()
        if not equipment_item.name:
            return "Equipment name is required.", 400
        equipment_item.equipment_type = request.form.get("equipment_type", "").strip() or None
        equipment_item.serial_number = request.form.get("serial_number", "").strip() or None

        farm_id_value = parse_int(request.form.get("farm_id"))
        farm = scoped_get(Farm, farm_id_value) if farm_id_value else None
        equipment_item.farm_id = farm_id_value
        equipment_item.cooperative_id = default_record_cooperative_id(farm.cooperative_id if farm else equipment_item.cooperative_id)

        equipment_item.purchase_date = parse_date(request.form.get("purchase_date"))
        equipment_item.purchase_cost = parse_float(request.form.get("purchase_cost"))
        equipment_item.last_service_date = parse_date(request.form.get("last_service_date"))
        equipment_item.next_service_date = parse_date(request.form.get("next_service_date"))
        equipment_item.status = request.form.get("status", "Available").strip()
        equipment_item.notes = request.form.get("notes", "").strip() or None
        add_audit_log("UPDATE", "Equipment", equipment_item.id, equipment_item.name)
        db.session.commit()
        return redirect(url_for("equipment"))
    return render_optional_template("equipment_form.html", "Edit Equipment", equipment_item=equipment_item, farms=farms_list)

@app.route("/equipment/delete/<int:equipment_id>", methods=["POST"])
@login_required
def delete_equipment(equipment_id):
    equipment_item = scoped_get_or_404(Equipment, equipment_id)
    add_audit_log("DELETE", "Equipment", equipment_item.id, equipment_item.name)
    db.session.delete(equipment_item)
    db.session.commit()
    return redirect(url_for("equipment"))

# =========================================================
# TASKS
# =========================================================
@app.route("/tasks")
@login_required
def tasks():
    search = request.args.get("search", "").strip()
    query = scoped_model_query(Task).outerjoin(Farm).outerjoin(User)
    if search:
        query = query.filter(or_(Task.title.ilike(f"%{search}%"), Task.description.ilike(f"%{search}%"), Task.priority.ilike(f"%{search}%"), Task.status.ilike(f"%{search}%"), Farm.name.ilike(f"%{search}%"), User.fullname.ilike(f"%{search}%")))
    task_list = query.order_by(Task.due_date.asc(), Task.created_at.desc()).all()
    return render_optional_template("tasks.html", "Tasks", tasks=task_list, search=search)

@app.route("/tasks/add", methods=["GET", "POST"])
@login_required
def add_task():
    farms_list = scoped_model_query(Farm).order_by(Farm.name.asc()).all()
    users_list = accessible_users_query().order_by(User.fullname.asc()).all()
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        if not title:
            return "Task title is required.", 400

        farm_id_value = parse_int(request.form.get("farm_id"))
        assigned_user_id_value = parse_int(request.form.get("assigned_user_id"))
        farm = scoped_get(Farm, farm_id_value) if farm_id_value else None
        assigned_user = accessible_users_query().filter(User.id == assigned_user_id_value).first() if assigned_user_id_value else None
        if assigned_user_id_value and not assigned_user:
            return "Selected user is outside your cooperative access.", 400
        assigned_access = UserAccess.query.filter_by(user_id=assigned_user.id).first() if assigned_user else None
        inherited_cooperative_id = farm.cooperative_id if farm else assigned_access.cooperative_id if assigned_access else None

        task = Task(
            cooperative_id=default_record_cooperative_id(inherited_cooperative_id),
            title=title,
            description=request.form.get("description", "").strip() or None,
            farm_id=farm_id_value,
            assigned_user_id=assigned_user_id_value,
            due_date=parse_date(request.form.get("due_date")),
            priority=request.form.get("priority", "Normal").strip(),
            status=request.form.get("status", "Open").strip(),
        )
        if task.status == "Completed":
            task.completed_at = datetime.utcnow()
        db.session.add(task)
        db.session.flush()
        add_audit_log("CREATE", "Task", task.id, task.title, cooperative_id=task.cooperative_id)
        db.session.commit()
        return redirect(url_for("tasks"))
    return render_optional_template("task_form.html", "Add Task", task=None, farms=farms_list, users=users_list)

@app.route("/tasks/edit/<int:task_id>", methods=["GET", "POST"])
@login_required
def edit_task(task_id):
    task = scoped_get_or_404(Task, task_id)
    farms_list = scoped_model_query(Farm).order_by(Farm.name.asc()).all()
    users_list = accessible_users_query().order_by(User.fullname.asc()).all()
    if request.method == "POST":
        task.title = request.form.get("title", "").strip()
        if not task.title:
            return "Task title is required.", 400
        task.description = request.form.get("description", "").strip() or None

        farm_id_value = parse_int(request.form.get("farm_id"))
        assigned_user_id_value = parse_int(request.form.get("assigned_user_id"))
        farm = scoped_get(Farm, farm_id_value) if farm_id_value else None
        assigned_user = accessible_users_query().filter(User.id == assigned_user_id_value).first() if assigned_user_id_value else None
        if assigned_user_id_value and not assigned_user:
            return "Selected user is outside your cooperative access.", 400
        assigned_access = UserAccess.query.filter_by(user_id=assigned_user.id).first() if assigned_user else None
        inherited_cooperative_id = farm.cooperative_id if farm else assigned_access.cooperative_id if assigned_access else task.cooperative_id

        task.farm_id = farm_id_value
        task.assigned_user_id = assigned_user_id_value
        task.cooperative_id = default_record_cooperative_id(inherited_cooperative_id)
        task.due_date = parse_date(request.form.get("due_date"))
        task.priority = request.form.get("priority", "Normal").strip()
        old_status = task.status
        task.status = request.form.get("status", "Open").strip()
        if task.status == "Completed" and old_status != "Completed":
            task.completed_at = datetime.utcnow()
        if task.status != "Completed":
            task.completed_at = None
        add_audit_log("UPDATE", "Task", task.id, task.title)
        db.session.commit()
        return redirect(url_for("tasks"))
    return render_optional_template("task_form.html", "Edit Task", task=task, farms=farms_list, users=users_list)

@app.route("/tasks/delete/<int:task_id>", methods=["POST"])
@login_required
def delete_task(task_id):
    task = scoped_get_or_404(Task, task_id)
    add_audit_log("DELETE", "Task", task.id, task.title)
    db.session.delete(task)
    db.session.commit()
    return redirect(url_for("tasks"))

# =========================================================
# FARMER INTERACTIONS
# =========================================================
@app.route("/interactions")
@login_required
def interactions():
    search = request.args.get("search", "").strip()
    query = scoped_model_query(FarmerInteraction).join(Farmer)
    if search:
        query = query.filter(or_(Farmer.fullname.ilike(f"%{search}%"), FarmerInteraction.interaction_type.ilike(f"%{search}%"), FarmerInteraction.subject.ilike(f"%{search}%"), FarmerInteraction.notes.ilike(f"%{search}%")))
    interaction_list = query.order_by(FarmerInteraction.interaction_date.desc()).all()
    return render_optional_template("interactions.html", "Farmer Interactions", interactions=interaction_list, search=search)

@app.route("/interactions/add", methods=["GET", "POST"])
@login_required
def add_interaction():
    farmers_list = scoped_model_query(Farmer).order_by(Farmer.fullname.asc()).all()
    if request.method == "POST":
        farmer_id = parse_int(request.form.get("farmer_id"))
        farmer = scoped_get(Farmer, farmer_id) if farmer_id else None
        interaction_date = parse_date(request.form.get("interaction_date"))
        interaction_type = request.form.get("interaction_type", "").strip()

        if not farmer:
            return "Please select a valid farmer.", 400
        if not interaction_date:
            return "A valid interaction date is required.", 400
        if not interaction_type:
            return "Interaction type is required.", 400

        interaction = FarmerInteraction(
            cooperative_id=default_record_cooperative_id(farmer.cooperative_id),
            farmer_id=farmer.id,
            interaction_date=interaction_date,
            interaction_type=interaction_type,
            subject=request.form.get("subject", "").strip() or None,
            notes=request.form.get("notes", "").strip() or None,
            follow_up_date=parse_date(request.form.get("follow_up_date")),
            created_by=session.get("user_id"),
        )
        db.session.add(interaction)
        db.session.flush()
        add_audit_log("CREATE", "FarmerInteraction", interaction.id, farmer.fullname, cooperative_id=interaction.cooperative_id)
        db.session.commit()
        return redirect(url_for("interactions"))
    return render_optional_template("interaction_form.html", "Add Farmer Interaction", interaction=None, farmers=farmers_list)

@app.route("/interactions/delete/<int:interaction_id>", methods=["POST"])
@login_required
def delete_interaction(interaction_id):
    interaction = scoped_get_or_404(FarmerInteraction, interaction_id)
    add_audit_log("DELETE", "FarmerInteraction", interaction.id, interaction.farmer.fullname)
    db.session.delete(interaction)
    db.session.commit()
    return redirect(url_for("interactions"))

# =========================================================
# MEMBERSHIPS
# =========================================================
@app.route("/memberships")
@login_required
def memberships():
    search = request.args.get("search", "").strip()
    query = scoped_model_query(Membership).join(Farmer)
    if search:
        query = query.filter(or_(Membership.member_number.ilike(f"%{search}%"), Membership.membership_type.ilike(f"%{search}%"), Membership.status.ilike(f"%{search}%"), Farmer.fullname.ilike(f"%{search}%")))
    membership_list = query.order_by(Membership.created_at.desc()).all()
    return render_optional_template("memberships.html", "Memberships", memberships=membership_list, search=search)

@app.route("/memberships/add", methods=["GET", "POST"])
@login_required
def add_membership():
    farmers_list = scoped_model_query(Farmer).order_by(Farmer.fullname.asc()).all()
    if request.method == "POST":
        farmer_id = parse_int(request.form.get("farmer_id"))
        farmer = scoped_get(Farmer, farmer_id) if farmer_id else None
        member_number = request.form.get("member_number", "").strip()

        if not farmer:
            return "Please select a valid farmer.", 400
        if not member_number:
            return "Member number is required.", 400
        if scoped_model_query(Membership).filter_by(member_number=member_number).first():
            return "This member number already exists.", 400

        membership = Membership(
            cooperative_id=default_record_cooperative_id(farmer.cooperative_id),
            farmer_id=farmer.id,
            member_number=member_number,
            membership_type=request.form.get("membership_type", "Primary").strip(),
            join_date=parse_date(request.form.get("join_date")),
            fee_amount=parse_float(request.form.get("fee_amount"), 0),
            fee_paid=parse_float(request.form.get("fee_paid"), 0),
            status=request.form.get("status", "Active").strip(),
            notes=request.form.get("notes", "").strip() or None,
        )
        db.session.add(membership)
        db.session.flush()
        add_audit_log("CREATE", "Membership", membership.id, member_number, cooperative_id=membership.cooperative_id)
        db.session.commit()
        return redirect(url_for("memberships"))
    return render_optional_template("membership_form.html", "Add Membership", membership=None, farmers=farmers_list)

@app.route("/memberships/edit/<int:membership_id>", methods=["GET", "POST"])
@login_required
def edit_membership(membership_id):
    membership = scoped_get_or_404(Membership, membership_id)
    farmers_list = scoped_model_query(Farmer).order_by(Farmer.fullname.asc()).all()
    if request.method == "POST":
        farmer_id = parse_int(request.form.get("farmer_id"))
        farmer = scoped_get(Farmer, farmer_id) if farmer_id else None
        member_number = request.form.get("member_number", "").strip()

        if not farmer:
            return "Please select a valid farmer.", 400
        if not member_number:
            return "Member number is required.", 400
        duplicate = scoped_model_query(Membership).filter(Membership.member_number == member_number, Membership.id != membership.id).first()
        if duplicate:
            return "This member number already exists.", 400

        membership.farmer_id = farmer.id
        membership.cooperative_id = default_record_cooperative_id(farmer.cooperative_id)
        membership.member_number = member_number
        membership.membership_type = request.form.get("membership_type", "Primary").strip()
        membership.join_date = parse_date(request.form.get("join_date"))
        membership.fee_amount = parse_float(request.form.get("fee_amount"), 0)
        membership.fee_paid = parse_float(request.form.get("fee_paid"), 0)
        membership.status = request.form.get("status", "Active").strip()
        membership.notes = request.form.get("notes", "").strip() or None
        add_audit_log("UPDATE", "Membership", membership.id, member_number)
        db.session.commit()
        return redirect(url_for("memberships"))
    return render_optional_template("membership_form.html", "Edit Membership", membership=membership, farmers=farmers_list)

@app.route("/memberships/delete/<int:membership_id>", methods=["POST"])
@login_required
def delete_membership(membership_id):
    membership = scoped_get_or_404(Membership, membership_id)
    add_audit_log("DELETE", "Membership", membership.id, membership.member_number)
    db.session.delete(membership)
    db.session.commit()
    return redirect(url_for("memberships"))

# =========================================================
# CONTRIBUTIONS
# =========================================================
@app.route("/contributions")
@login_required
def contributions():
    search = request.args.get("search", "").strip()
    query = scoped_model_query(Contribution).join(Farmer)
    if search:
        query = query.filter(or_(Farmer.fullname.ilike(f"%{search}%"), Contribution.category.ilike(f"%{search}%"), Contribution.reference.ilike(f"%{search}%"), Contribution.status.ilike(f"%{search}%")))
    contribution_list = query.order_by(Contribution.contribution_date.desc()).all()
    return render_optional_template("contributions.html", "Contributions", contributions=contribution_list, search=search)

@app.route("/contributions/add", methods=["GET", "POST"])
@login_required
def add_contribution():
    farmers_list = scoped_model_query(Farmer).order_by(Farmer.fullname.asc()).all()
    if request.method == "POST":
        farmer_id = parse_int(request.form.get("farmer_id"))
        farmer = scoped_get(Farmer, farmer_id) if farmer_id else None
        amount = parse_float(request.form.get("amount"))
        contribution_date = parse_date(request.form.get("contribution_date"))

        if not farmer:
            return "Please select a valid farmer.", 400
        if amount is None or amount <= 0:
            return "Contribution amount must be greater than zero.", 400
        if not contribution_date:
            return "A valid contribution date is required.", 400

        contribution = Contribution(
            cooperative_id=default_record_cooperative_id(farmer.cooperative_id),
            farmer_id=farmer.id,
            amount=amount,
            contribution_date=contribution_date,
            category=request.form.get("category", "").strip() or None,
            method=request.form.get("method", "").strip() or None,
            reference=request.form.get("reference", "").strip() or None,
            status=request.form.get("status", "Received").strip(),
            notes=request.form.get("notes", "").strip() or None,
        )
        db.session.add(contribution)
        db.session.flush()
        add_audit_log("CREATE", "Contribution", contribution.id, f"{farmer.fullname} - R{amount:.2f}", cooperative_id=contribution.cooperative_id)
        db.session.commit()
        return redirect(url_for("contributions"))
    return render_optional_template("contribution_form.html", "Add Contribution", contribution=None, farmers=farmers_list)

@app.route("/contributions/delete/<int:contribution_id>", methods=["POST"])
@login_required
def delete_contribution(contribution_id):
    contribution = scoped_get_or_404(Contribution, contribution_id)
    add_audit_log("DELETE", "Contribution", contribution.id, f"R{contribution.amount:.2f}")
    db.session.delete(contribution)
    db.session.commit()
    return redirect(url_for("contributions"))

# =========================================================
# COOPERATIVES
# =========================================================
@app.route("/cooperatives")
@roles_required("Admin", "Secondary Chairperson", "Secondary Secretary")
def cooperatives():
    search = request.args.get("search", "").strip()
    query = Cooperative.query
    if search:
        query = query.filter(or_(Cooperative.name.ilike(f"%{search}%"), Cooperative.registration_number.ilike(f"%{search}%"), Cooperative.code.ilike(f"%{search}%"), Cooperative.location.ilike(f"%{search}%")))
    cooperative_list = query.order_by(Cooperative.cooperative_type.desc(), Cooperative.name.asc()).all()
    return render_optional_template("cooperatives.html", "Cooperatives", cooperatives=cooperative_list, search=search)

@app.route("/cooperatives/add", methods=["GET", "POST"])
@roles_required("Admin", "Secondary Chairperson")
def add_cooperative():
    secondary_list = Cooperative.query.filter_by(cooperative_type="Secondary").order_by(Cooperative.name.asc()).all()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        cooperative_type = request.form.get("cooperative_type", "").strip()
        parent_id = parse_int(request.form.get("parent_id"))

        if not name:
            return "Cooperative name is required.", 400
        if cooperative_type not in {"Secondary", "Primary"}:
            return "Cooperative type must be Secondary or Primary.", 400
        if Cooperative.query.filter(func.lower(Cooperative.name) == name.lower()).first():
            return "A cooperative with this name already exists.", 400
        if cooperative_type == "Secondary":
            parent_id = None
        else:
            if not parent_id:
                return "A primary cooperative must belong to a secondary cooperative.", 400
            parent = db.session.get(Cooperative, parent_id)
            if not parent or parent.cooperative_type != "Secondary":
                return "Please select a valid secondary cooperative.", 400

        cooperative = Cooperative(
            name=name,
            cooperative_type=cooperative_type,
            parent_id=parent_id,
            registration_number=request.form.get("registration_number", "").strip() or None,
            code=request.form.get("code", "").strip() or None,
            location=request.form.get("location", "").strip() or None,
            status=request.form.get("status", "Active").strip(),
        )
        db.session.add(cooperative)
        db.session.flush()
        add_audit_log("CREATE", "Cooperative", cooperative.id, cooperative.name, cooperative_id=cooperative.id)
        db.session.commit()
        return redirect(url_for("cooperatives"))
    return render_optional_template("cooperative_form.html", "Add Cooperative", cooperative=None, secondary_cooperatives=secondary_list)

@app.route("/cooperatives/edit/<int:cooperative_id>", methods=["GET", "POST"])
@roles_required("Admin", "Secondary Chairperson")
def edit_cooperative(cooperative_id):
    cooperative = Cooperative.query.get_or_404(cooperative_id)
    secondary_list = Cooperative.query.filter(Cooperative.cooperative_type == "Secondary", Cooperative.id != cooperative.id).order_by(Cooperative.name.asc()).all()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        cooperative_type = request.form.get("cooperative_type", "").strip()
        parent_id = parse_int(request.form.get("parent_id"))

        if not name:
            return "Cooperative name is required.", 400
        if cooperative_type not in {"Secondary", "Primary"}:
            return "Cooperative type must be Secondary or Primary.", 400
        duplicate = Cooperative.query.filter(func.lower(Cooperative.name) == name.lower(), Cooperative.id != cooperative.id).first()
        if duplicate:
            return "A cooperative with this name already exists.", 400
        if cooperative_type == "Secondary":
            parent_id = None
        else:
            if not parent_id:
                return "A primary cooperative must belong to a secondary cooperative.", 400
            parent = db.session.get(Cooperative, parent_id)
            if not parent or parent.cooperative_type != "Secondary":
                return "Please select a valid secondary cooperative.", 400

        cooperative.name = name
        cooperative.cooperative_type = cooperative_type
        cooperative.parent_id = parent_id
        cooperative.registration_number = request.form.get("registration_number", "").strip() or None
        cooperative.code = request.form.get("code", "").strip() or None
        cooperative.location = request.form.get("location", "").strip() or None
        cooperative.status = request.form.get("status", "Active").strip()
        add_audit_log("UPDATE", "Cooperative", cooperative.id, cooperative.name, cooperative_id=cooperative.id)
        db.session.commit()
        return redirect(url_for("cooperatives"))
    return render_optional_template("cooperative_form.html", "Edit Cooperative", cooperative=cooperative, secondary_cooperatives=secondary_list)

# =========================================================
# REPORTS
# =========================================================
@app.route("/reports")
@login_required
def reports():
    start_date = parse_date(request.args.get("start_date"))
    end_date = parse_date(request.args.get("end_date"))

    sales_query = scoped_model_query(Sale)
    payments_query = scoped_model_query(Payment).filter(Payment.status != "Reversed")
    expenses_query = scoped_model_query(Expense).filter(Expense.status != "Cancelled")
    contributions_query = scoped_model_query(Contribution).filter(Contribution.status == "Received")

    if start_date:
        sales_query = sales_query.filter(Sale.sale_date >= start_date)
        payments_query = payments_query.filter(Payment.payment_date >= start_date)
        expenses_query = expenses_query.filter(Expense.expense_date >= start_date)
        contributions_query = contributions_query.filter(Contribution.contribution_date >= start_date)
    if end_date:
        sales_query = sales_query.filter(Sale.sale_date <= end_date)
        payments_query = payments_query.filter(Payment.payment_date <= end_date)
        expenses_query = expenses_query.filter(Expense.expense_date <= end_date)
        contributions_query = contributions_query.filter(Contribution.contribution_date <= end_date)

    total_sales_value = sales_query.with_entities(func.coalesce(func.sum(Sale.total_amount), 0)).scalar() or 0
    total_payments_value = payments_query.with_entities(func.coalesce(func.sum(Payment.amount), 0)).scalar() or 0
    total_expenses_value = expenses_query.with_entities(func.coalesce(func.sum(Expense.amount), 0)).scalar() or 0
    total_contributions_value = contributions_query.with_entities(func.coalesce(func.sum(Contribution.amount), 0)).scalar() or 0
    outstanding_balance = float(total_sales_value) - float(total_payments_value)
    net_cash_position = float(total_payments_value) - float(total_expenses_value)

    return render_optional_template("reports.html", "Reports",
        farmer_count=scoped_model_query(Farmer).count(), farm_count=scoped_model_query(Farm).count(),
        crop_count=scoped_model_query(Crop).count(), harvest_count=scoped_model_query(Harvest).count(),
        sales_count=scoped_model_query(Sale).count(), payment_count=scoped_model_query(Payment).count(),
        customer_count=scoped_model_query(Customer).count(), supplier_count=scoped_model_query(Supplier).count(),
        expense_count=scoped_model_query(Expense).count(),
        total_sales_value=total_sales_value, total_payments_value=total_payments_value,
        total_expenses_value=total_expenses_value, total_contributions_value=total_contributions_value,
        outstanding_balance=outstanding_balance, net_cash_position=net_cash_position,
        recent_sales=sales_query.order_by(Sale.sale_date.desc()).limit(10).all(),
        recent_payments=payments_query.order_by(Payment.payment_date.desc()).limit(10).all(),
        recent_expenses=expenses_query.order_by(Expense.expense_date.desc()).limit(10).all(),
        start_date=start_date, end_date=end_date,
        current_access=current_access(), current_cooperative=current_cooperative()
    )

# =========================================================
# SETTINGS / PROFILE
# =========================================================
@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    user = current_user()
    if request.method == "POST":
        fullname = request.form.get("fullname", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip().lower()
        farm_location = request.form.get("farm_location", "").strip()

        if not all([fullname, phone, email, farm_location]):
            return "Name, phone, email and location are required.", 400
        duplicate = User.query.filter(User.email == email, User.id != user.id).first()
        if duplicate:
            return "Another user already uses this email address.", 400

        user.fullname = fullname
        user.phone = phone
        user.email = email
        user.farm_location = farm_location
        session["fullname"] = user.fullname
        add_audit_log("UPDATE", "UserProfile", user.id, user.email)
        db.session.commit()
        return redirect(url_for("settings"))
    return render_optional_template("settings.html", "Settings", user=user)

@app.route("/settings/password", methods=["POST"])
@login_required
def change_password():
    user = current_user()
    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")

    if not check_password_hash(user.password, current_password):
        return "Current password is incorrect.", 400
    if len(new_password) < 8:
        return "New password must be at least 8 characters.", 400
    if new_password != confirm_password:
        return "New passwords do not match.", 400

    user.password = generate_password_hash(new_password)
    add_audit_log("PASSWORD_CHANGE", "User", user.id, user.email)
    db.session.commit()
    return redirect(url_for("settings"))

# =========================================================
# USER MANAGEMENT
# =========================================================
@app.route("/users")
@roles_required("Admin", "Secondary Chairperson")
def users():
    search = request.args.get("search", "").strip()
    query = accessible_users_query()
    if search:
        query = query.filter(or_(User.fullname.ilike(f"%{search}%"), User.email.ilike(f"%{search}%"), User.phone.ilike(f"%{search}%")))
    user_list = query.order_by(User.created_at.desc()).all()
    access_map = {r.user_id: r for r in UserAccess.query.all()}
    cooperative_list = accessible_cooperative_query().order_by(Cooperative.cooperative_type.desc(), Cooperative.name.asc()).all()
    return render_optional_template("users.html", "User Management", users=user_list, access_map=access_map, cooperatives=cooperative_list, valid_roles=sorted(VALID_ACCESS_ROLES), search=search)

@app.route("/users/access/<int:user_id>", methods=["POST"])
@roles_required("Admin", "Secondary Chairperson")
def update_user_access(user_id):
    user = User.query.get_or_404(user_id)
    access = get_user_access(user.id)
    role = request.form.get("role", access.role).strip()
    status = request.form.get("status", access.status).strip()
    cooperative_id = parse_int(request.form.get("cooperative_id"))

    if role not in VALID_ACCESS_ROLES:
        return "Invalid role.", 400
    if status not in {"Active", "Inactive"}:
        return "Invalid access status.", 400

    cooperative = None
    if cooperative_id:
        cooperative = db.session.get(Cooperative, cooperative_id)
        if not cooperative:
            return "Selected cooperative does not exist.", 400

    if role in SECONDARY_ROLES and role != "Admin":
        if not cooperative or cooperative.cooperative_type != "Secondary":
            return "A secondary role must be assigned to a secondary cooperative.", 400

    if role in PRIMARY_ROLES:
        if not cooperative or cooperative.cooperative_type != "Primary":
            return "This role must be assigned to a primary cooperative.", 400

    if role == "Admin":
        cooperative_id = cooperative.id if cooperative else None

    access.role = role
    access.status = status
    access.cooperative_id = cooperative_id
    add_audit_log("ACCESS_UPDATE", "User", user.id, f"{role} / {status} / cooperative={cooperative_id or 'ALL'}", cooperative_id=cooperative_id)
    db.session.commit()
    return redirect(url_for("users"))

# =========================================================
# AUDIT LOGS
# =========================================================
@app.route("/audit-logs")
@roles_required("Admin", "Secondary Chairperson")
def audit_logs():
    logs = scoped_model_query(AuditLog).order_by(AuditLog.created_at.desc()).limit(500).all()
    return render_optional_template("audit_logs.html", "Audit Logs", logs=logs)

# =========================================================
# CSV EXPORTS
# =========================================================
@app.route("/exports/farmers.csv")
@login_required
def export_farmers():
    rows = scoped_model_query(Farmer).order_by(Farmer.fullname.asc()).all()
    return make_csv_response("farmers.csv", ["ID", "Full Name", "Phone", "Email", "Location", "Farm Size", "Primary Crop", "Status"],
        [[r.id, r.fullname, r.phone, r.email or "", r.location, r.farm_size or "", r.primary_crop or "", r.status] for r in rows])

@app.route("/exports/farms.csv")
@login_required
def export_farms():
    rows = scoped_model_query(Farm).order_by(Farm.name.asc()).all()
    return make_csv_response("farms.csv", ["ID", "Farm Name", "Farmer", "Location", "Size", "Farming Type", "Main Crop", "Status"],
        [[r.id, r.name, r.farmer.fullname, r.location, r.size or "", r.farming_type or "", r.main_crop or "", r.status] for r in rows])

@app.route("/exports/crops.csv")
@login_required
def export_crops():
    rows = scoped_model_query(Crop).order_by(Crop.created_at.desc()).all()
    return make_csv_response("crops.csv", ["ID", "Crop", "Farm", "Farmer", "Variety", "Planting Date", "Expected Harvest", "Area Planted", "Status"],
        [[r.id, r.name, r.farm.name, r.farm.farmer.fullname, r.variety or "", r.planting_date or "", r.expected_harvest_date or "", r.area_planted or "", r.status] for r in rows])

@app.route("/exports/harvests.csv")
@login_required
def export_harvests():
    rows = scoped_model_query(Harvest).order_by(Harvest.harvest_date.desc()).all()
    return make_csv_response("harvests.csv", ["ID", "Crop", "Farm", "Harvest Date", "Quantity", "Unit", "Quality Grade", "Storage", "Status"],
        [[r.id, r.crop.name, r.crop.farm.name, r.harvest_date, r.quantity, r.unit, r.quality_grade or "", r.storage_location or "", r.status] for r in rows])

@app.route("/exports/sales.csv")
@login_required
def export_sales():
    rows = scoped_model_query(Sale).order_by(Sale.sale_date.desc()).all()
    return make_csv_response("sales.csv", ["ID", "Sale Date", "Buyer", "Phone", "Crop", "Quantity", "Unit", "Price Per Unit", "Total Amount", "Paid", "Outstanding", "Status"],
        [[r.id, r.sale_date, r.buyer_name, r.buyer_phone or "", r.harvest.crop.name, r.quantity, r.unit, r.price_per_unit, r.total_amount, sale_paid_amount(r), sale_outstanding_amount(r), r.status] for r in rows])

@app.route("/exports/payments.csv")
@login_required
def export_payments():
    rows = scoped_model_query(Payment).order_by(Payment.payment_date.desc()).all()
    return make_csv_response("payments.csv", ["ID", "Payment Date", "Buyer", "Amount", "Method", "Reference", "Status"],
        [[r.id, r.payment_date, r.sale.buyer_name, r.amount, r.method or "", r.reference or "", r.status] for r in rows])

@app.route("/exports/expenses.csv")
@login_required
def export_expenses():
    rows = scoped_model_query(Expense).order_by(Expense.expense_date.desc()).all()
    return make_csv_response("expenses.csv", ["ID", "Expense Date", "Category", "Description", "Farm", "Supplier", "Amount", "Payment Method", "Reference", "Status"],
        [[r.id, r.expense_date, r.category, r.description, r.farm.name if r.farm else "", r.supplier.name if r.supplier else "", r.amount, r.payment_method or "", r.reference or "", r.status] for r in rows])

# =========================================================
# DATABASE BACKUP
# =========================================================
@app.route("/admin/database-backup")
@roles_required("Admin", "Secondary Chairperson")
def database_backup():
    database_url = db.engine.url
    if database_url.get_backend_name() != "sqlite":
        return "Automatic file backup is currently available only for SQLite.", 400
    database_file = database_url.database
    if not database_file:
        return "Database file could not be determined.", 500
    database_path = Path(database_file).resolve()
    if not database_path.exists():
        return "Database file was not found.", 404
    backup_name = "malenge_farmers_backup_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".db"
    return send_file(database_path, as_attachment=True, download_name=backup_name)

# =========================================================
# HEALTH CHECK
# =========================================================
@app.route("/health")
def health():
    return {"status": "ok", "application": "Malenge Farmers CRM", "time": datetime.utcnow().isoformat()}

# =========================================================
# LOGOUT
# =========================================================
@app.route("/logout")
@login_required
def logout():
    session.clear()
    return redirect(url_for("login"))

# =========================================================
# ERROR HANDLERS
# =========================================================
@app.errorhandler(403)
def forbidden(_error):
    return "You do not have permission to access this page.", 403

@app.errorhandler(404)
def page_not_found(_error):
    return "The requested page was not found.", 404

@app.errorhandler(500)
def internal_error(_error):
    db.session.rollback()
    return "An internal server error occurred.", 500

# =========================================================
# RUN APPLICATION
# =========================================================
if __name__ == "__main__":
    app.run(debug=False, port=5050)