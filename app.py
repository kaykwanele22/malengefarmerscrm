from datetime import datetime, timedelta, timezone
from pathlib import Path
from functools import wraps

import base64
import csv
import hashlib
import hmac
import html
import io
import json
import os
import platform
import re
import secrets
import shutil
import sqlite3
import struct
import sys
import threading
import time
import uuid
from collections import defaultdict, deque
from urllib.parse import quote, urlsplit

from cryptography.fernet import Fernet, InvalidToken
from dotenv import load_dotenv
import qrcode

from flask import (
    Flask,
    Response,
    abort,
    g,
    has_request_context,
    redirect,
    send_file,
    render_template,
    render_template_string,
    request,
    session,
    url_for,
)

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy import func, or_, text as sql_text
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename


# =========================================================
# ENVIRONMENT VARIABLES
# =========================================================

load_dotenv()


# =========================================================
# FLASK APPLICATION
# =========================================================

def env_bool(name, default=False):
    """Read a boolean environment variable safely."""
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    return raw.strip().lower() in {"1", "true", "yes", "on"}


IS_PRODUCTION = (
    os.getenv("APP_ENV", "").strip().lower() == "production"
    or os.getenv("FLASK_ENV", "").strip().lower() == "production"
    or env_bool("RENDER", False)
)

SECRET_KEY = os.getenv("SECRET_KEY", "").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

if IS_PRODUCTION and not SECRET_KEY:
    raise RuntimeError("SECRET_KEY must be configured in production.")

if IS_PRODUCTION and not DATABASE_URL:
    raise RuntimeError("DATABASE_URL must be configured in production; SQLite fallback is disabled.")

app = Flask(
    __name__,
    static_folder="static",
    static_url_path="/static"
)

app.config.update(
    SECRET_KEY=SECRET_KEY or "malenge-farmers-development-key",
    SQLALCHEMY_DATABASE_URI=DATABASE_URL or "sqlite:///malenge_farmers.db",
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=env_bool("SESSION_COOKIE_SECURE", IS_PRODUCTION),
    MAX_CONTENT_LENGTH=int(os.getenv("MAX_CONTENT_LENGTH", str(16 * 1024 * 1024))),
    ALLOW_BOOTSTRAP_REGISTRATION=env_bool("ALLOW_BOOTSTRAP_REGISTRATION", not IS_PRODUCTION),
    TRUST_PROXY_HEADERS=env_bool("TRUST_PROXY_HEADERS", IS_PRODUCTION),
    TWO_FACTOR_REQUIRED=env_bool("TWO_FACTOR_REQUIRED", True),
    TWO_FACTOR_ISSUER=os.getenv("TWO_FACTOR_ISSUER", "Malenge Farmers CRM").strip() or "Malenge Farmers CRM",
    TWO_FACTOR_MAX_ATTEMPTS=max(3, int(os.getenv("TWO_FACTOR_MAX_ATTEMPTS", "5"))),
)


db = SQLAlchemy(app)
migrate = Migrate(app, db)

CRM_TIMEZONE = timezone(timedelta(hours=2))  # South Africa Standard Time (SAST)

# Phase 6 evidence storage. Files are kept outside /static so every download
# passes through cooperative/role authorization.
ACCOUNTABILITY_UPLOAD_DIR = Path(
    os.getenv("ACCOUNTABILITY_UPLOAD_DIR", str(Path(app.instance_path) / "accountability_uploads"))
).expanduser().resolve()
ACCOUNTABILITY_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ACCOUNTABILITY_ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "webp"}


def utc_now():
    """Return naive UTC for database storage."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def crm_today():
    """Return the current South African calendar date for deadlines/workflows."""
    return datetime.now(CRM_TIMEZONE).date()


def format_sast(value, fmt="%d %b %Y %H:%M:%S"):
    """Format a stored UTC datetime for the South African CRM interface."""
    if not value:
        return "—"
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(CRM_TIMEZONE).strftime(fmt)


# =========================================================
# DATABASE MODELS
# =========================================================
class User(db.Model):
    """User model for authentication and system users."""
    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)
    fullname = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(30), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    farm_location = db.Column(db.String(150), nullable=False)
    password = db.Column(db.String(255), nullable=False)
    two_factor_enabled = db.Column(db.Boolean, default=False, nullable=False)
    two_factor_secret = db.Column(db.String(512), nullable=True)
    two_factor_recovery_codes = db.Column(db.Text, nullable=True)
    two_factor_confirmed_at = db.Column(db.DateTime, nullable=True)
    two_factor_last_counter = db.Column(db.BigInteger, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now)

    def __repr__(self):
        return f"<User {self.email}>"


class Cooperative(db.Model):
    """Cooperative model for secondary and primary cooperatives."""
    __tablename__ = "cooperative"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    cooperative_type = db.Column(db.String(30), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=True)
    registration_number = db.Column(db.String(120), nullable=True)
    code = db.Column(db.String(50), nullable=True)
    location = db.Column(db.String(200), nullable=True)
    status = db.Column(db.String(30), default="Active", nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now)

    parent = db.relationship(
        "Cooperative",
        remote_side=[id],
        backref=db.backref("primary_cooperatives", lazy=True)
    )

    def __repr__(self):
        return f"<Cooperative {self.name}>"


class Farmer(db.Model):
    """Farmer model for individual farmers."""
    __tablename__ = "farmer"

    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=True)
    fullname = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(150), nullable=True)
    location = db.Column(db.String(200), nullable=False)
    farm_size = db.Column(db.Float, nullable=True)  # Legacy field
    primary_crop = db.Column(db.String(100), nullable=True)  # Legacy field
    status = db.Column(db.String(50), default="Active")
    created_at = db.Column(db.DateTime, default=utc_now)

    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id], backref="cooperative_farmers")

    def __repr__(self):
        return f"<Farmer {self.fullname}>"


class Farm(db.Model):
    """Farm model for agricultural holdings."""
    __tablename__ = "farm"

    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=True)
    name = db.Column(db.String(150), nullable=False)
    farmer_id = db.Column(db.Integer, db.ForeignKey("farmer.id"), nullable=False)
    location = db.Column(db.String(200), nullable=False)
    size = db.Column(db.Float, nullable=True)
    farming_type = db.Column(db.String(100), nullable=True)
    main_crop = db.Column(db.String(100), nullable=True)  # Legacy field
    registration_date = db.Column(db.DateTime, default=utc_now)
    status = db.Column(db.String(50), default="Active")

    farmer = db.relationship("Farmer", backref="farms")
    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id], backref="cooperative_farms")

    def __repr__(self):
        return f"<Farm {self.name}>"


class Crop(db.Model):
    """Crop model for planted crops."""
    __tablename__ = "crop"

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
    created_at = db.Column(db.DateTime, default=utc_now)

    farm = db.relationship("Farm", backref="crops")
    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id], backref="cooperative_crops")

    def __repr__(self):
        return f"<Crop {self.name}>"


class Harvest(db.Model):
    """Harvest model for crop yields."""
    __tablename__ = "harvest"

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
    created_at = db.Column(db.DateTime, default=utc_now)

    crop = db.relationship("Crop", backref="harvests")
    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id], backref="cooperative_harvests")

    def __repr__(self):
        return f"<Harvest {self.id} for {self.crop.name}>"


class Sale(db.Model):
    """Sale model for harvest sales."""
    __tablename__ = "sale"

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
    created_at = db.Column(db.DateTime, default=utc_now)

    harvest = db.relationship("Harvest", backref="sales")
    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id], backref="cooperative_sales")

    def __repr__(self):
        return f"<Sale {self.id} to {self.buyer_name}>"


class Payment(db.Model):
    """Payment model for sale payments."""
    __tablename__ = "payment"

    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=True)
    sale_id = db.Column(db.Integer, db.ForeignKey("sale.id"), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    payment_date = db.Column(db.Date, nullable=False)
    method = db.Column(db.String(50), nullable=True)
    reference = db.Column(db.String(120), nullable=True)
    status = db.Column(db.String(50), default="Received")
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now)

    sale = db.relationship("Sale", backref="payments")
    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id], backref="cooperative_payments")

    def __repr__(self):
        return f"<Payment {self.id} for Sale {self.sale_id}>"


class Customer(db.Model):
    """Customer model for buyers."""
    __tablename__ = "customer"

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
    created_at = db.Column(db.DateTime, default=utc_now)

    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id], backref="cooperative_customers")

    def __repr__(self):
        return f"<Customer {self.name}>"


class Supplier(db.Model):
    """Supplier model for input suppliers."""
    __tablename__ = "supplier"

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
    created_at = db.Column(db.DateTime, default=utc_now)

    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id], backref="cooperative_suppliers")

    def __repr__(self):
        return f"<Supplier {self.name}>"


class Expense(db.Model):
    """Expense model for farm expenses."""
    __tablename__ = "expense"

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
    created_at = db.Column(db.DateTime, default=utc_now)

    farm = db.relationship("Farm", backref="expenses")
    supplier = db.relationship("Supplier", backref="expenses")
    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id], backref="cooperative_expenses")

    def __repr__(self):
        return f"<Expense {self.id} - {self.category}>"


class InventoryItem(db.Model):
    """Inventory item model for farm supplies."""
    __tablename__ = "inventory_item"

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
    created_at = db.Column(db.DateTime, default=utc_now)

    supplier = db.relationship("Supplier", backref="inventory_items")
    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id], backref="cooperative_inventory_items")

    def __repr__(self):
        return f"<InventoryItem {self.name}>"


class InventoryTransaction(db.Model):
    """Inventory transaction model for stock movements."""
    __tablename__ = "inventory_transaction"

    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=True)
    inventory_item_id = db.Column(db.Integer, db.ForeignKey("inventory_item.id"), nullable=False)
    transaction_type = db.Column(db.String(30), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    transaction_date = db.Column(db.Date, nullable=False)
    reference = db.Column(db.String(120), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now)

    inventory_item = db.relationship("InventoryItem", backref="transactions")
    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id],
                                  backref="cooperative_inventory_transactions")

    def __repr__(self):
        return f"<InventoryTransaction {self.id}>"


class Equipment(db.Model):
    """Equipment model for farm machinery and tools."""
    __tablename__ = "equipment"

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
    created_at = db.Column(db.DateTime, default=utc_now)

    farm = db.relationship("Farm", backref="equipment")
    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id], backref="cooperative_equipment")

    def __repr__(self):
        return f"<Equipment {self.name}>"


class Task(db.Model):
    """Operational/accountability task with permanent progress and verification links."""
    __tablename__ = "task"

    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=True)
    resolution_id = db.Column(db.Integer, db.ForeignKey("resolution.id"), nullable=True, index=True)
    title = db.Column(db.String(180), nullable=False)
    description = db.Column(db.Text, nullable=True)
    farm_id = db.Column(db.Integer, db.ForeignKey("farm.id"), nullable=True)
    assigned_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    assigned_role = db.Column(db.String(50), nullable=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    due_date = db.Column(db.Date, nullable=True)
    priority = db.Column(db.String(30), default="Normal")
    status = db.Column(db.String(30), default="Open")
    progress_percentage = db.Column(db.Integer, default=0, nullable=False)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    verified_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    verified_at = db.Column(db.DateTime, nullable=True)
    verification_notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now)

    farm = db.relationship("Farm", backref="tasks")
    assigned_user = db.relationship("User", foreign_keys=[assigned_user_id], backref="tasks")
    created_by_user = db.relationship("User", foreign_keys=[created_by_user_id])
    verified_by_user = db.relationship("User", foreign_keys=[verified_by_user_id])
    resolution = db.relationship("Resolution", foreign_keys=[resolution_id], backref="tasks")
    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id], backref="cooperative_tasks")

    def __repr__(self):
        return f"<Task {self.title}>"


class FarmerInteraction(db.Model):
    """Farmer interaction model for communication records."""
    __tablename__ = "farmer_interaction"

    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=True)
    farmer_id = db.Column(db.Integer, db.ForeignKey("farmer.id"), nullable=False)
    interaction_date = db.Column(db.Date, nullable=False)
    interaction_type = db.Column(db.String(80), nullable=False)
    subject = db.Column(db.String(180), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    follow_up_date = db.Column(db.Date, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now)

    farmer = db.relationship("Farmer", backref="interactions")
    user = db.relationship("User", backref="farmer_interactions")
    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id],
                                  backref="cooperative_farmer_interactions")

    def __repr__(self):
        return f"<FarmerInteraction {self.id}>"


class Membership(db.Model):
    """Individual membership of a Primary cooperative."""
    __tablename__ = "membership"

    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False)
    farmer_id = db.Column(db.Integer, db.ForeignKey("farmer.id"), nullable=False)
    member_number = db.Column(db.String(80), unique=True, nullable=False)
    membership_type = db.Column(db.String(80), default="Primary", nullable=False)
    join_date = db.Column(db.Date, nullable=True)
    fee_amount = db.Column(db.Float, default=0, nullable=False)
    fee_paid = db.Column(db.Float, default=0, nullable=False)
    status = db.Column(db.String(30), default="Active", nullable=False)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    farmer = db.relationship("Farmer", backref="memberships")
    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id], backref="cooperative_memberships")

    @property
    def fee_pending(self):
        """Membership-fee money recorded by the Treasurer but not yet confirmed."""
        return sum(
            float(contribution.amount or 0)
            for contribution in self.contributions
            if contribution.status == "Pending Confirmation"
            and (contribution.category or "").strip().casefold() in MEMBERSHIP_FEE_CATEGORY_ALIASES
        )

    @property
    def fee_confirmed_outstanding(self):
        """Balance still unconfirmed against the expected fee."""
        return max(float(self.fee_amount or 0) - float(self.fee_paid or 0), 0.0)

    @property
    def fee_outstanding(self):
        """Amount the member still needs to pay after confirmed + pending receipts."""
        return max(
            float(self.fee_amount or 0)
            - float(self.fee_paid or 0)
            - float(self.fee_pending or 0),
            0.0,
        )

    @property
    def fee_status(self):
        expected = float(self.fee_amount or 0)
        confirmed = float(self.fee_paid or 0)
        pending = float(self.fee_pending or 0)

        if expected <= 1e-9:
            return "No Fee"
        if confirmed + 1e-9 >= expected:
            return "Paid"
        if pending > 1e-9 and self.fee_outstanding <= 1e-9:
            return "Awaiting Confirmation"
        if confirmed > 1e-9 or pending > 1e-9:
            return "Partially Paid"
        return "Due"

    def __repr__(self):
        return f"<Membership {self.member_number}>"


class Contribution(db.Model):
    """Contribution model for farmer/member financial contributions."""
    __tablename__ = "contribution"

    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=True)
    farmer_id = db.Column(db.Integer, db.ForeignKey("farmer.id"), nullable=False)
    membership_id = db.Column(db.Integer, db.ForeignKey("membership.id"), nullable=True)
    amount = db.Column(db.Float, nullable=False)
    contribution_date = db.Column(db.Date, nullable=False)
    category = db.Column(db.String(100), nullable=True)
    method = db.Column(db.String(50), nullable=True)
    reference = db.Column(db.String(120), nullable=True)
    status = db.Column(db.String(30), default="Received")
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now)

    farmer = db.relationship("Farmer", backref="contributions")
    membership = db.relationship("Membership", backref="contributions")
    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id], backref="cooperative_contributions")

    def __repr__(self):
        return f"<Contribution {self.id}>"


class MembershipHistory(db.Model):
    """Permanent lifecycle history for a cooperative membership."""
    __tablename__ = "membership_history"

    id = db.Column(db.Integer, primary_key=True)
    membership_id = db.Column(db.Integer, db.ForeignKey("membership.id", ondelete="CASCADE"), nullable=False, index=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    event_type = db.Column(db.String(50), nullable=False)
    from_status = db.Column(db.String(30), nullable=True)
    to_status = db.Column(db.String(30), nullable=True)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False, index=True)

    membership = db.relationship(
        "Membership",
        backref=db.backref("history_entries", cascade="all, delete-orphan", order_by="MembershipHistory.created_at.desc()"),
    )
    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id])
    user = db.relationship("User", foreign_keys=[user_id])

    def __repr__(self):
        return f"<MembershipHistory {self.membership_id} {self.event_type}>"


class UserAccess(db.Model):
    """User access model for role-based permissions."""
    __tablename__ = "user_access"
    __table_args__ = (
        db.Index(
            "uq_active_cooperative_executive_position",
            "cooperative_id",
            "role",
            unique=True,
            sqlite_where=sql_text("status = 'Active' AND cooperative_id IS NOT NULL"),
            postgresql_where=sql_text("status = 'Active' AND cooperative_id IS NOT NULL"),
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), unique=True, nullable=False)
    role = db.Column(db.String(30), default="Unassigned", nullable=False)
    status = db.Column(db.String(30), default="Pending", nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now)

    user = db.relationship("User", backref=db.backref("access_record", uselist=False))
    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id], backref="user_access_records")

    def __repr__(self):
        return f"<UserAccess {self.user_id} - {self.role}>"


class ExecutiveAppointment(db.Model):
    """Historical executive appointment linked to the current CRM access record."""
    __tablename__ = "executive_appointment"
    __table_args__ = (
        db.Index(
            "uq_active_executive_appointment_position",
            "cooperative_id",
            "role",
            unique=True,
            sqlite_where=sql_text("status = 'Active'"),
            postgresql_where=sql_text("status = 'Active'"),
        ),
        db.Index(
            "uq_active_executive_appointment_user",
            "user_id",
            unique=True,
            sqlite_where=sql_text("status = 'Active'"),
            postgresql_where=sql_text("status = 'Active'"),
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    role = db.Column(db.String(30), nullable=False)
    start_date = db.Column(db.Date, nullable=False, default=lambda: utc_now().date())
    end_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), default="Active", nullable=False)
    appointed_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    ended_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    cooperative = db.relationship(
        "Cooperative",
        foreign_keys=[cooperative_id],
        backref=db.backref("executive_appointments", lazy=True),
    )
    user = db.relationship(
        "User",
        foreign_keys=[user_id],
        backref=db.backref("executive_appointments", lazy=True),
    )
    appointed_by = db.relationship("User", foreign_keys=[appointed_by_user_id])
    ended_by = db.relationship("User", foreign_keys=[ended_by_user_id])

    def __repr__(self):
        return f"<ExecutiveAppointment {self.cooperative_id} {self.role} user={self.user_id}>"


class AuditLog(db.Model):
    """Permanent system activity record with request/security context."""
    __tablename__ = "audit_log"

    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    action = db.Column(db.String(80), nullable=False)
    entity_type = db.Column(db.String(80), nullable=False)
    entity_id = db.Column(db.Integer, nullable=True)
    details = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(64), nullable=True)
    request_method = db.Column(db.String(12), nullable=True)
    request_path = db.Column(db.String(255), nullable=True)
    request_id = db.Column(db.String(64), nullable=True, index=True)
    user_agent = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now, index=True)

    user = db.relationship("User", backref="audit_logs")
    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id], backref="cooperative_audit_logs")

    def __repr__(self):
        return f"<AuditLog {self.id} - {self.action}>"


class Meeting(db.Model):
    """Minimal meeting index; handwritten/scanned records remain the source evidence."""
    __tablename__ = "meeting"

    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False, index=True)
    meeting_number = db.Column(db.String(80), nullable=False, unique=True, index=True)
    meeting_type = db.Column(db.String(80), nullable=False)
    title = db.Column(db.String(180), nullable=False)
    meeting_date = db.Column(db.Date, nullable=False, index=True)
    venue = db.Column(db.String(200), nullable=True)
    quorum_status = db.Column(db.String(30), default="Not Recorded", nullable=False)
    status = db.Column(db.String(30), default="Draft", nullable=False, index=True)
    notes = db.Column(db.Text, nullable=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    confirmed_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    confirmed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)

    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id], backref="meetings")
    created_by_user = db.relationship("User", foreign_keys=[created_by_user_id])
    confirmed_by_user = db.relationship("User", foreign_keys=[confirmed_by_user_id])

    def __repr__(self):
        return f"<Meeting {self.meeting_number}>"


class MeetingDocument(db.Model):
    """Immutable evidence file uploaded against a meeting."""
    __tablename__ = "meeting_document"

    id = db.Column(db.Integer, primary_key=True)
    meeting_id = db.Column(db.Integer, db.ForeignKey("meeting.id", ondelete="CASCADE"), nullable=False, index=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False, index=True)
    document_type = db.Column(db.String(60), nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    stored_name = db.Column(db.String(255), nullable=False, unique=True)
    file_sha256 = db.Column(db.String(64), nullable=False)
    uploaded_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)

    meeting = db.relationship("Meeting", backref=db.backref("documents", lazy=True, cascade="all, delete-orphan"))
    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id])
    uploaded_by_user = db.relationship("User", foreign_keys=[uploaded_by_user_id])


class Resolution(db.Model):
    """Structured accountability outcome extracted from official meeting evidence."""
    __tablename__ = "resolution"

    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False, index=True)
    meeting_id = db.Column(db.Integer, db.ForeignKey("meeting.id"), nullable=False, index=True)
    resolution_number = db.Column(db.String(80), nullable=False, unique=True, index=True)
    title = db.Column(db.String(180), nullable=False)
    resolution_text = db.Column(db.Text, nullable=False)
    responsible_role = db.Column(db.String(50), nullable=False)
    responsible_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    due_date = db.Column(db.Date, nullable=True, index=True)
    priority = db.Column(db.String(30), default="Normal", nullable=False)
    status = db.Column(db.String(30), default="Draft", nullable=False, index=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    certified_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    certified_at = db.Column(db.DateTime, nullable=True)
    closed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id], backref="resolutions")
    meeting = db.relationship("Meeting", backref="resolutions")
    responsible_user = db.relationship("User", foreign_keys=[responsible_user_id])
    created_by_user = db.relationship("User", foreign_keys=[created_by_user_id])
    certified_by_user = db.relationship("User", foreign_keys=[certified_by_user_id])

    @property
    def accountability_status(self):
        if self.status in {"Closed", "Rejected"}:
            return self.status
        today = crm_today()
        if self.status in {"Assigned", "In Progress"} and self.due_date:
            if self.due_date < today:
                return "Overdue"
            if self.due_date <= today + timedelta(days=3):
                return "At Risk"
        return self.status

    def __repr__(self):
        return f"<Resolution {self.resolution_number}>"


class TaskUpdate(db.Model):
    """Append-only progress update for an accountability task."""
    __tablename__ = "task_update"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("task.id", ondelete="CASCADE"), nullable=False, index=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    status = db.Column(db.String(30), nullable=False)
    progress_percentage = db.Column(db.Integer, nullable=False, default=0)
    comment = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False, index=True)

    task = db.relationship("Task", backref=db.backref("progress_updates", lazy=True, cascade="all, delete-orphan", order_by="TaskUpdate.created_at.desc()"))
    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id])
    user = db.relationship("User", foreign_keys=[user_id])


class TaskEvidence(db.Model):
    """Immutable supporting evidence uploaded against an accountability task."""
    __tablename__ = "task_evidence"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("task.id", ondelete="CASCADE"), nullable=False, index=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False, index=True)
    evidence_type = db.Column(db.String(60), nullable=False)
    description = db.Column(db.String(300), nullable=True)
    original_name = db.Column(db.String(255), nullable=False)
    stored_name = db.Column(db.String(255), nullable=False, unique=True)
    file_sha256 = db.Column(db.String(64), nullable=False)
    uploaded_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)

    task = db.relationship("Task", backref=db.backref("evidence_files", lazy=True, cascade="all, delete-orphan"))
    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id])
    uploaded_by_user = db.relationship("User", foreign_keys=[uploaded_by_user_id])


# =========================================================
# CONSTANTS AND CONFIGURATION
# =========================================================
SYSTEM_ROLES = {"Admin"}

SECONDARY_EXECUTIVE_ROLES = {
    "Secondary Chairperson",
    "Secondary Vice Chairperson",
    "Secondary Secretary",
    "Secondary Vice Secretary",
    "Secondary Treasurer",
}

PRIMARY_EXECUTIVE_ROLES = {
    "Primary Chairperson",
    "Primary Vice Chairperson",
    "Primary Secretary",
    "Primary Vice Secretary",
    "Primary Treasurer",
}

EXECUTIVE_POSITIONS = (
    "Chairperson",
    "Vice Chairperson",
    "Secretary",
    "Vice Secretary",
    "Treasurer",
)


def executive_role_for(cooperative_type, position):
    """Return the role string for a cooperative type and executive position."""
    if cooperative_type not in {"Secondary", "Primary"}:
        return None
    if position not in EXECUTIVE_POSITIONS:
        return None
    return f"{cooperative_type} {position}"


def executive_position_from_role(role):
    """Return the human position name from a valid executive role."""
    for prefix in ("Secondary ", "Primary "):
        if role.startswith(prefix):
            position = role[len(prefix):]
            if position in EXECUTIVE_POSITIONS:
                return position
    return None

SECONDARY_ROLES = SYSTEM_ROLES | SECONDARY_EXECUTIVE_ROLES
PRIMARY_ROLES = PRIMARY_EXECUTIVE_ROLES
VALID_ACCESS_ROLES = SYSTEM_ROLES | SECONDARY_EXECUTIVE_ROLES | PRIMARY_EXECUTIVE_ROLES

COOPERATIVE_VIEW_ROLES = {
    "Admin",
    "Secondary Chairperson",
    "Secondary Vice Chairperson",
    "Secondary Secretary",
    "Secondary Vice Secretary",
    "Secondary Treasurer",
}

COOPERATIVE_EDIT_ROLES = {
    "Admin",
}

USER_MANAGEMENT_ROLES = {
    "Admin",
}

AUDIT_LOG_ROLES = {
    "Admin",
}

# Executive responsibility rules
# Individual members belong to Primary cooperatives. Secondary Secretaries have
# network oversight, while Primary Secretary/Vice Secretary maintain the register.
MEMBERSHIP_MANAGEMENT_ROLES = {
    "Primary Secretary",
    "Primary Vice Secretary",
}

MEMBERSHIP_OVERSIGHT_ROLES = {
    "Secondary Secretary",
    "Secondary Vice Secretary",
}

FINANCE_RECORD_ROLES = {
    "Secondary Treasurer",
    "Primary Treasurer",
}

FINANCE_APPROVAL_ROLES = {
    "Secondary Chairperson",
    "Primary Chairperson",
}

# Phase 6 governance/accountability permissions. System Admin remains a technical
# administrator and is intentionally not treated as a cooperative executive.
GOVERNANCE_VIEW_ROLES = SECONDARY_EXECUTIVE_ROLES | PRIMARY_EXECUTIVE_ROLES
MEETING_RECORD_ROLES = {
    "Secondary Secretary", "Secondary Vice Secretary",
    "Primary Secretary", "Primary Vice Secretary",
}
MEETING_CONFIRM_ROLES = {"Secondary Chairperson", "Primary Chairperson"}
RESOLUTION_RECORD_ROLES = MEETING_RECORD_ROLES
ACCOUNTABILITY_VERIFY_ROLES = {
    "Secondary Chairperson", "Secondary Vice Chairperson", "Secondary Secretary",
    "Primary Chairperson", "Primary Vice Chairperson", "Primary Secretary",
}

# Route-level cooperative permissions.
COOPERATIVE_EXECUTIVE_ROLES = SECONDARY_EXECUTIVE_ROLES | PRIMARY_EXECUTIVE_ROLES

LEADERSHIP_ROLES = {
    "Secondary Chairperson",
    "Secondary Vice Chairperson",
    "Primary Chairperson",
    "Primary Vice Chairperson",
}

PRIMARY_OPERATION_RECORD_ROLES = {
    "Primary Chairperson",
    "Primary Vice Chairperson",
}

PRIMARY_LEADERSHIP_ROLES = {
    "Primary Chairperson",
    "Primary Vice Chairperson",
}

# Individual farmers, memberships and farm-production records belong to Primary
# cooperatives. Secondary executives receive aggregate network summaries only.
FARMER_VIEW_ROLES = MEMBERSHIP_MANAGEMENT_ROLES | PRIMARY_LEADERSHIP_ROLES
FARMER_RECORD_ROLES = MEMBERSHIP_MANAGEMENT_ROLES

AGRICULTURE_VIEW_ROLES = PRIMARY_LEADERSHIP_ROLES

BUSINESS_VIEW_ROLES = LEADERSHIP_ROLES | FINANCE_RECORD_ROLES
BUSINESS_RECORD_ROLES = FINANCE_RECORD_ROLES

FINANCE_VIEW_ROLES = LEADERSHIP_ROLES | FINANCE_RECORD_ROLES
MEMBERSHIP_VIEW_ROLES = PRIMARY_EXECUTIVE_ROLES
MEMBERSHIP_ALLOWED_STATUSES = {
    "Pending",
    "Active",
    "Suspended",
    "Resigned",
    "Deceased",
    "Inactive",
}
MEMBERSHIP_FEE_CATEGORY = "Membership Fee"
MEMBERSHIP_FEE_CATEGORY_ALIASES = {"membership fee", "membership"}

# Deferred/extended module permissions. Secondary leadership may view operational
# records across the network, while Primary Chair/Vice Chair mutate farm operations.
CUSTOMER_VIEW_ROLES = BUSINESS_VIEW_ROLES
CUSTOMER_RECORD_ROLES = BUSINESS_RECORD_ROLES
SUPPLIER_VIEW_ROLES = BUSINESS_VIEW_ROLES
SUPPLIER_RECORD_ROLES = BUSINESS_RECORD_ROLES
OPERATIONS_VIEW_ROLES = AGRICULTURE_VIEW_ROLES
OPERATIONS_RECORD_ROLES = PRIMARY_OPERATION_RECORD_ROLES
INTERACTION_VIEW_ROLES = FARMER_VIEW_ROLES
INTERACTION_RECORD_ROLES = FARMER_RECORD_ROLES

# Authentication throttling. This is intentionally conservative and dependency-free.
# It operates per application process; a shared Redis-backed limiter can replace it
# later if the deployment is scaled to multiple Gunicorn workers/instances.
LOGIN_FAILURE_WINDOW_SECONDS = int(os.getenv("LOGIN_FAILURE_WINDOW_SECONDS", "900"))
LOGIN_MAX_FAILURES_PER_ACCOUNT = int(os.getenv("LOGIN_MAX_FAILURES_PER_ACCOUNT", "5"))
LOGIN_MAX_FAILURES_PER_IP = int(os.getenv("LOGIN_MAX_FAILURES_PER_IP", "20"))
_LOGIN_FAILURES = defaultdict(deque)
_LOGIN_FAILURE_LOCK = threading.Lock()

# Historical confirmed statuses are retained so existing data keeps counting.
CONFIRMED_EXPENSE_STATUSES = ("Paid", "Confirmed")
CONFIRMED_CONTRIBUTION_STATUSES = ("Received", "Confirmed")

PAYMENT_VALUE_STATUSES = ("Received", "Partial")
PAYMENT_ALLOWED_STATUSES = {"Received", "Pending", "Partial", "Reversed"}

CROP_ALLOWED_STATUSES = {
    "Planted",
    "Growing",
    "Ready for Harvest",
    "Partially Harvested",
    "Harvested",
    "Failed",
}

HARVEST_ALLOWED_STATUSES = {"Available", "Reserved", "Sold", "Spoiled"}
HARVEST_ALLOWED_UNITS = {"kg", "tonnes", "bags", "crates"}

# Malenge governance structure: one Secondary Cooperative coordinates two Primaries.
MALENGE_MAX_SECONDARY_COOPERATIVES = 1
MALENGE_MAX_PRIMARY_COOPERATIVES = 2
COOPERATIVE_ALLOWED_STATUSES = {"Active", "Inactive"}


# =========================================================
# AUTHENTICATION / REQUEST SECURITY HELPERS
# =========================================================
def client_ip_address():
    """Return the best available client IP without blindly trusting proxy headers."""
    if not has_request_context():
        return None

    if app.config.get("TRUST_PROXY_HEADERS"):
        forwarded = request.headers.get("X-Forwarded-For", "").strip()
        if forwarded:
            return forwarded.split(",", 1)[0].strip()[:64]

    return (request.remote_addr or "")[:64] or None


def csrf_token():
    """Return the per-session CSRF token used by all state-changing forms."""
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def _prune_login_failures(bucket, now):
    cutoff = now - LOGIN_FAILURE_WINDOW_SECONDS
    while bucket and bucket[0] < cutoff:
        bucket.popleft()


def _login_failure_keys(email):
    email_key = (email or "").strip().lower() or "<blank>"
    ip_key = client_ip_address() or "unknown"
    return f"account:{email_key}", f"ip:{ip_key}"


def login_rate_limited(email):
    """Check account and IP failure windows before attempting authentication."""
    if app.config.get("TESTING"):
        return False

    now = time.monotonic()
    account_key, ip_key = _login_failure_keys(email)

    with _LOGIN_FAILURE_LOCK:
        account_bucket = _LOGIN_FAILURES[account_key]
        ip_bucket = _LOGIN_FAILURES[ip_key]
        _prune_login_failures(account_bucket, now)
        _prune_login_failures(ip_bucket, now)
        return (
            len(account_bucket) >= LOGIN_MAX_FAILURES_PER_ACCOUNT
            or len(ip_bucket) >= LOGIN_MAX_FAILURES_PER_IP
        )


def record_login_failure(email):
    """Record a failed authentication attempt for both account and IP limits."""
    if app.config.get("TESTING"):
        return

    now = time.monotonic()
    account_key, ip_key = _login_failure_keys(email)

    with _LOGIN_FAILURE_LOCK:
        for key in (account_key, ip_key):
            bucket = _LOGIN_FAILURES[key]
            _prune_login_failures(bucket, now)
            bucket.append(now)


def clear_login_failures(email):
    """Clear the account-specific failure bucket after a successful login."""
    if app.config.get("TESTING"):
        return

    account_key, _ = _login_failure_keys(email)
    with _LOGIN_FAILURE_LOCK:
        _LOGIN_FAILURES.pop(account_key, None)


def _two_factor_fernet():
    """Derive an authenticated-encryption key from the configured SECRET_KEY."""
    material = str(app.config["SECRET_KEY"]).encode("utf-8")
    digest = hmac.new(material, b"malenge-two-factor-secret-v1", hashlib.sha256).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_two_factor_secret(secret):
    """Encrypt a TOTP secret before storing it in the database."""
    return _two_factor_fernet().encrypt(secret.encode("ascii")).decode("ascii")


def decrypt_two_factor_secret(value):
    """Decrypt a stored TOTP secret. A changed SECRET_KEY requires 2FA reset."""
    if not value:
        return None
    try:
        return _two_factor_fernet().decrypt(value.encode("ascii")).decode("ascii")
    except (InvalidToken, ValueError, TypeError) as exc:
        raise RuntimeError(
            "This account's Google Authenticator secret cannot be decrypted. "
            "The account needs a 2FA reset before it can be used."
        ) from exc


def generate_totp_secret():
    """Generate a 160-bit Base32 secret compatible with Google Authenticator."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _decode_base32(secret):
    padding = "=" * ((8 - len(secret) % 8) % 8)
    return base64.b32decode((secret + padding).upper(), casefold=True)


def totp_code_for_counter(secret, counter, digits=6):
    """Return the RFC 6238 SHA-1 TOTP code for one counter value."""
    digest = hmac.new(
        _decode_base32(secret),
        struct.pack(">Q", int(counter)),
        hashlib.sha1,
    ).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{binary % (10 ** digits):0{digits}d}"


def verify_totp_code(secret, token, valid_window=1, at_time=None):
    """Verify a six-digit Google Authenticator code and return its counter."""
    token = "".join(ch for ch in str(token or "") if ch.isdigit())
    if len(token) != 6:
        return None

    now = int(time.time() if at_time is None else at_time)
    current_counter = now // 30
    for offset in range(-valid_window, valid_window + 1):
        counter = current_counter + offset
        if counter < 0:
            continue
        expected = totp_code_for_counter(secret, counter)
        if hmac.compare_digest(expected, token):
            return counter
    return None


def google_authenticator_uri(user, secret):
    """Build the standard otpauth URI consumed by Google Authenticator."""
    issuer = app.config.get("TWO_FACTOR_ISSUER", "Malenge Farmers CRM")
    label = f"{issuer}:{user.email}"
    return (
        f"otpauth://totp/{quote(label, safe='')}?"
        f"secret={quote(secret, safe='')}&issuer={quote(issuer, safe='')}"
        "&algorithm=SHA1&digits=6&period=30"
    )


def google_authenticator_qr_data_uri(uri):
    """Render an otpauth URI as an in-memory PNG data URI."""
    image = qrcode.make(uri)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")


def _normalize_recovery_code(code):
    return "".join(ch for ch in str(code or "").upper() if ch.isalnum())


def _hash_recovery_code(code):
    normalized = _normalize_recovery_code(code)
    key = str(app.config["SECRET_KEY"]).encode("utf-8")
    return hmac.new(key, normalized.encode("ascii"), hashlib.sha256).hexdigest()


def generate_recovery_codes(count=8):
    """Generate one-time recovery codes and their keyed hashes."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    codes = []
    for _ in range(count):
        raw = "".join(secrets.choice(alphabet) for _ in range(12))
        codes.append(f"{raw[:4]}-{raw[4:8]}-{raw[8:]}")
    return codes


def set_recovery_codes(user, codes):
    user.two_factor_recovery_codes = json.dumps([_hash_recovery_code(code) for code in codes])


def recovery_code_count(user):
    try:
        values = json.loads(user.two_factor_recovery_codes or "[]")
    except (TypeError, ValueError):
        return 0
    return len(values) if isinstance(values, list) else 0


def consume_recovery_code(user, code):
    """Consume one valid recovery code and return True; recovery codes are one-use."""
    candidate = _hash_recovery_code(code)
    try:
        hashes = json.loads(user.two_factor_recovery_codes or "[]")
    except (TypeError, ValueError):
        hashes = []

    if not isinstance(hashes, list):
        return False

    for index, stored in enumerate(hashes):
        if isinstance(stored, str) and hmac.compare_digest(stored, candidate):
            del hashes[index]
            user.two_factor_recovery_codes = json.dumps(hashes)
            return True
    return False


def two_factor_policy_enabled():
    """Return the effective global 2FA policy selected by the Admin.

    TWO_FACTOR_REQUIRED remains an environment-level master switch. The
    Admin runtime setting can temporarily pause enforcement without deleting
    any user's Google Authenticator enrollment.
    """
    if not app.config.get("TWO_FACTOR_REQUIRED", True):
        return False
    return bool(load_system_settings().get("two_factor_required", True))


def two_factor_is_required():
    """Return whether this request should enforce mandatory 2FA."""
    if not two_factor_policy_enabled():
        return False
    if app.config.get("TESTING") and not app.config.get("TEST_TWO_FACTOR"):
        return False
    return True


def two_factor_session_complete():
    # A password-only session created while Admin temporarily disabled 2FA
    # must not stay trusted after Admin reactivates the policy.
    return bool(session.get("two_factor_authenticated")) and not bool(session.get("two_factor_bypassed"))


def clear_user_two_factor(user):
    """Reset a user's Google Authenticator enrollment without deleting the user."""
    user.two_factor_enabled = False
    user.two_factor_secret = None
    user.two_factor_recovery_codes = None
    user.two_factor_confirmed_at = None
    user.two_factor_last_counter = None


def logged_in():
    """Check if a user is currently logged in."""
    return "user_id" in session


def current_user():
    """Get the current logged-in user."""
    if not logged_in():
        return None
    return db.session.get(User, session.get("user_id"))


def get_user_access(user_id):
    """Get or create access record for a user."""
    access = UserAccess.query.filter_by(user_id=user_id).first()
    if access:
        return access

    first_user_id = db.session.query(func.min(User.id)).scalar()

    if user_id == first_user_id:
        access = UserAccess(
            user_id=user_id,
            role="Admin",
            status="Active",
            cooperative_id=None,
        )
    else:
        access = UserAccess(
            user_id=user_id,
            role="Unassigned",
            status="Pending",
            cooperative_id=None,
        )

    db.session.add(access)
    db.session.commit()
    return access


def current_access():
    """Get access record for the current user."""
    if not logged_in():
        return None
    return get_user_access(session["user_id"])


def current_cooperative():
    """Get the current user's cooperative."""
    access = current_access()
    if not access or not access.cooperative_id:
        return None
    return db.session.get(Cooperative, access.cooperative_id)


# =========================================================
# SCOPING HELPERS
# =========================================================
def accessible_cooperative_ids(user_id=None):
    """Get list of cooperative IDs accessible to a user."""
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

    # Every executive works only with records owned by the cooperative assigned
    # to that account. Secondary executives do not inherit raw Primary records.
    # Cross-primary visibility is intentionally exposed only through explicit
    # aggregate network summaries on the Secondary dashboard/reports.
    return [cooperative.id]


def can_access_cooperative(cooperative_id, user_id=None):
    """Check if a user can access a specific cooperative."""
    if cooperative_id is None:
        return False

    allowed_ids = accessible_cooperative_ids(user_id)

    if allowed_ids is None:
        return True

    return cooperative_id in allowed_ids


def scope_cooperative_query(query, model, user_id=None, include_unassigned_for_admin=True):
    """Scope a query to accessible cooperatives."""
    allowed_ids = accessible_cooperative_ids(user_id)

    if allowed_ids is None:
        return query

    if not allowed_ids:
        return query.filter(model.cooperative_id.in_([]))

    return query.filter(model.cooperative_id.in_(allowed_ids))


def scoped_model_query(model, user_id=None):
    """Get a scoped query for a model."""
    return scope_cooperative_query(model.query, model, user_id=user_id)


def scoped_get(model, record_id, user_id=None):
    """Get a record with cooperative scoping."""
    if record_id is None:
        return None

    return (
        scoped_model_query(model, user_id=user_id)
        .filter(model.id == record_id)
        .first()
    )


def scoped_get_or_404(model, record_id, user_id=None):
    """Get a record with cooperative scoping or abort with 404."""
    record = scoped_get(model, record_id, user_id=user_id)

    if record is None:
        abort(404)

    return record


def accessible_cooperative_query():
    """Get a query for accessible cooperatives."""
    query = Cooperative.query
    allowed_ids = accessible_cooperative_ids()

    if allowed_ids is None:
        return query

    if not allowed_ids:
        return query.filter(Cooperative.id.in_([]))

    return query.filter(Cooperative.id.in_(allowed_ids))


def accessible_users_query():
    """Get a query for accessible users."""
    query = User.query.outerjoin(
        UserAccess,
        UserAccess.user_id == User.id
    )

    access = current_access()

    if not access:
        return query.filter(User.id.in_([]))

    if access.role == "Admin":
        return query

    allowed_ids = accessible_cooperative_ids()

    if access.role == "Secondary Chairperson":
        conditions = [
            UserAccess.status == "Pending",
            UserAccess.cooperative_id.is_(None),
        ]

        if allowed_ids:
            conditions.append(UserAccess.cooperative_id.in_(allowed_ids))

        return query.filter(or_(*conditions)).distinct()

    if not allowed_ids:
        return query.filter(User.id.in_([]))

    return query.filter(
        UserAccess.cooperative_id.in_(allowed_ids)
    ).distinct()


def default_record_cooperative_id(fallback_cooperative_id=None):
    """Get the default cooperative ID for a new record."""
    if not logged_in():
        return fallback_cooperative_id

    access = get_user_access(session["user_id"])

    if access.role in PRIMARY_ROLES and access.cooperative_id:
        return access.cooperative_id

    return fallback_cooperative_id or access.cooperative_id


def own_cooperative_id():
    """Return the cooperative assigned to the current executive account."""
    access = current_access()
    return access.cooperative_id if access else None


def require_own_cooperative(cooperative_id):
    """Require a record to belong to the executive's assigned cooperative.

    Secondary executives may have oversight visibility across child primary
    cooperatives, but operational mutation and finance approval remain within
    the executive's own cooperative.
    """
    access = current_access()
    if not access or not access.cooperative_id:
        abort(403)
    if cooperative_id != access.cooperative_id:
        abort(403)
    return access


def own_cooperative_query(model):
    """Query records belonging only to the current executive's cooperative."""
    cooperative_id = own_cooperative_id()
    if not cooperative_id:
        return model.query.filter(model.id.in_([]))
    return model.query.filter(model.cooperative_id == cooperative_id)


# =========================================================
# PHASE 6 ACCOUNTABILITY HELPERS
# =========================================================
def cooperative_record_prefix(cooperative):
    """Stable short prefix for meeting/resolution references."""
    if not cooperative:
        return "COOP"
    raw = (cooperative.code or cooperative.name or "COOP").upper()
    cleaned = re.sub(r"[^A-Z0-9]", "", raw)
    return (cleaned[:12] or f"C{cooperative.id}")


def next_governance_number(model, cooperative, kind, date_value=None):
    """Generate human-readable sequential meeting/resolution references."""
    date_value = date_value or crm_today()
    year = date_value.year
    prefix = cooperative_record_prefix(cooperative)
    field = Meeting.meeting_number if model is Meeting else Resolution.resolution_number
    pattern_prefix = f"{prefix}-{kind}-{year}-"
    existing = model.query.filter(
        model.cooperative_id == cooperative.id,
        field.ilike(f"{pattern_prefix}%"),
    ).with_entities(field).all()
    highest = 0
    for (value,) in existing:
        try:
            highest = max(highest, int((value or "").rsplit("-", 1)[-1]))
        except (TypeError, ValueError):
            continue
    return f"{pattern_prefix}{highest + 1:03d}"


def active_executive_accesses(cooperative_id):
    """Return active executive access records for one cooperative."""
    return UserAccess.query.filter_by(
        cooperative_id=cooperative_id,
        status="Active",
    ).filter(UserAccess.role.in_(GOVERNANCE_VIEW_ROLES)).join(User).order_by(UserAccess.role.asc()).all()


def accountability_file_extension(filename):
    name = secure_filename(filename or "")
    if "." not in name:
        return None
    extension = name.rsplit(".", 1)[1].lower()
    return extension if extension in ACCOUNTABILITY_ALLOWED_EXTENSIONS else None


def save_accountability_upload(file_storage, category):
    """Persist an evidence upload outside static and return immutable metadata."""
    if not file_storage or not file_storage.filename:
        raise ValueError("Please choose a PDF or image to upload.")
    extension = accountability_file_extension(file_storage.filename)
    if not extension:
        raise ValueError("Only PDF, PNG, JPG, JPEG and WEBP evidence files are allowed.")

    original_name = secure_filename(file_storage.filename)[:255] or f"evidence.{extension}"
    stored_name = f"{category}_{uuid.uuid4().hex}.{extension}"
    destination = ACCOUNTABILITY_UPLOAD_DIR / stored_name
    file_storage.save(destination)

    # Do not trust a filename extension alone. A lightweight signature check keeps
    # HTML/scripts or unrelated binaries from being stored as official evidence.
    header = destination.read_bytes()[:16]
    valid_signature = (
        (extension == "pdf" and header.startswith(b"%PDF-"))
        or (extension == "png" and header.startswith(b"\x89PNG\r\n\x1a\n"))
        or (extension in {"jpg", "jpeg"} and header.startswith(b"\xff\xd8\xff"))
        or (extension == "webp" and header[:4] == b"RIFF" and header[8:12] == b"WEBP")
    )
    if not valid_signature:
        destination.unlink(missing_ok=True)
        raise ValueError("The uploaded file content does not match its PDF/image file type.")

    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    return original_name, stored_name, digest


def accountability_file_path(stored_name):
    """Resolve one stored evidence filename without accepting path traversal."""
    safe_name = Path(stored_name or "").name
    if safe_name != stored_name:
        abort(404)
    path = ACCOUNTABILITY_UPLOAD_DIR / safe_name
    if not path.is_file():
        abort(404)
    return path


def can_update_accountability_task(task, access=None):
    """Only the executive made responsible may report progress on that responsibility."""
    access = access or current_access()
    if not access or access.status != "Active" or task.cooperative_id != access.cooperative_id:
        return False
    return task.assigned_user_id == session.get("user_id")


def sync_resolution_from_task(task):
    """Keep the structured resolution status aligned with its implementation task."""
    if not task or not task.resolution:
        return
    if task.status == "Verified":
        task.resolution.status = "Closed"
        task.resolution.closed_at = task.verified_at or utc_now()
    elif task.status == "Awaiting Verification":
        task.resolution.status = "Awaiting Verification"
    elif task.status == "In Progress":
        task.resolution.status = "In Progress"
    elif task.status == "Open":
        task.resolution.status = "Assigned"


# =========================================================
# DECORATORS
# =========================================================
def login_required(view_func):
    """Decorator to require login for a view."""

    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if not logged_in():
            return redirect(url_for("login"))
        access = get_user_access(session["user_id"])
        if access.status != "Active" or access.role not in VALID_ACCESS_ROLES:
            session.clear()
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)

    return wrapped_view


def roles_required(*allowed_roles):
    """Decorator to require specific roles for a view."""

    def decorator(view_func):
        @wraps(view_func)
        def wrapped_view(*args, **kwargs):
            if not logged_in():
                return redirect(url_for("login"))

            access = get_user_access(session["user_id"])

            if (
                    access.status != "Active"
                    or access.role not in allowed_roles
            ):
                abort(403)

            return view_func(*args, **kwargs)

        return wrapped_view

    return decorator


# =========================================================
# UTILITY FUNCTIONS
# =========================================================
def parse_float(value, default=None):
    """Parse numeric form input; blank uses default, malformed input returns None."""
    if value is None:
        return default
    value = str(value).strip()
    if not value:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_int(value, default=None):
    """Parse an integer value from a string."""
    if value is None:
        return default
    value = str(value).strip()
    if not value:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_date(value):
    """Parse a date from a string."""
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def add_audit_log(
        action,
        entity_type,
        entity_id=None,
        details=None,
        cooperative_id=None,
        user_id=None,
):
    """Add a permanent audit entry with request/security metadata."""
    resolved_user_id = user_id
    request_id = None
    ip_address = None
    request_method = None
    request_path = None
    user_agent = None

    if has_request_context():
        if resolved_user_id is None:
            resolved_user_id = session.get("user_id")

        request_id = getattr(g, "request_id", None)
        ip_address = client_ip_address()
        request_method = request.method[:12] if request.method else None
        request_path = request.path[:255] if request.path else None
        user_agent = (request.headers.get("User-Agent", "") or "")[:255] or None

    if cooperative_id is None and resolved_user_id:
        access = UserAccess.query.filter_by(user_id=resolved_user_id).first()
        if access:
            cooperative_id = access.cooperative_id

    log = AuditLog(
        user_id=resolved_user_id,
        cooperative_id=cooperative_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
        ip_address=ip_address,
        request_method=request_method,
        request_path=request_path,
        request_id=request_id,
        user_agent=user_agent,
    )
    db.session.add(log)
    return log


def sale_paid_amount(sale, exclude_payment_id=None):
    """Calculate total paid amount for a sale."""
    total = 0.0
    for payment in sale.payments:
        if exclude_payment_id and payment.id == exclude_payment_id:
            continue
        if payment.status not in PAYMENT_VALUE_STATUSES:
            continue
        total += float(payment.amount or 0)
    return total


def sale_recorded_payment_amount(sale, exclude_payment_id=None):
    """Calculate total recorded payment amount for a sale (including pending)."""
    total = 0.0
    for payment in sale.payments:
        if exclude_payment_id and payment.id == exclude_payment_id:
            continue
        if payment.status == "Reversed":
            continue
        total += float(payment.amount or 0)
    return total


def sale_outstanding_amount(sale):
    """Calculate outstanding amount for a sale."""
    return max(float(sale.total_amount or 0) - float(sale_paid_amount(sale) or 0), 0)


def sale_payment_status(sale):
    """Determine the payment status of a sale."""
    if sale.status == "Cancelled":
        return "Cancelled"

    total = float(sale.total_amount or 0)
    paid = float(sale_paid_amount(sale) or 0)

    if paid <= 1e-9:
        return "Pending"
    if total > 0 and paid + 1e-9 >= total:
        return "Paid"
    return "Partially Paid"


def harvest_sold_quantity(harvest, exclude_sale_id=None):
    """Calculate total sold quantity from a harvest."""
    total = 0.0
    for sale in harvest.sales:
        if exclude_sale_id and sale.id == exclude_sale_id:
            continue
        if sale.status == "Cancelled":
            continue
        total += float(sale.quantity or 0)
    return total


def harvest_available_quantity(harvest, exclude_sale_id=None):
    """Calculate available quantity from a harvest."""
    harvested = float(harvest.quantity or 0)
    sold = harvest_sold_quantity(harvest, exclude_sale_id=exclude_sale_id)
    return max(harvested - sold, 0.0)


def crop_harvest_count(crop_id, exclude_harvest_id=None):
    """Count harvests for a crop."""
    query = Harvest.query.filter(Harvest.crop_id == crop_id)
    if exclude_harvest_id is not None:
        query = query.filter(Harvest.id != exclude_harvest_id)
    return query.count()


def sync_crop_status_after_harvest_change(crop):
    """Update crop status based on harvest records."""
    if not crop or crop.status == "Failed":
        return

    if crop_harvest_count(crop.id) > 0:
        if crop.status != "Harvested":
            crop.status = "Partially Harvested"
        return

    today = utc_now().date()
    if crop.expected_harvest_date and crop.expected_harvest_date <= today:
        crop.status = "Ready for Harvest"
    elif crop.planting_date and crop.planting_date <= today:
        crop.status = "Growing"
    else:
        crop.status = "Planted"


def normalize_membership_status(value, default="Active"):
    """Return a permitted Phase 5 membership lifecycle status."""
    status = (value or default).strip().title()
    if status not in MEMBERSHIP_ALLOWED_STATUSES:
        return None
    return status


def membership_number_prefix(cooperative):
    """Build a stable human-readable prefix for a Primary cooperative."""
    if not cooperative:
        return "MEM"
    raw = (cooperative.code or "").strip().upper()
    cleaned = re.sub(r"[^A-Z0-9]", "", raw)
    if cleaned:
        return cleaned[:12]
    return f"P{cooperative.id}"


def generate_member_number(cooperative):
    """Generate the next member number such as SIYA-0001 for a Primary cooperative."""
    prefix = membership_number_prefix(cooperative)
    pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)$", re.IGNORECASE)
    highest = 0
    existing = Membership.query.filter(Membership.member_number.ilike(f"{prefix}-%")).with_entities(
        Membership.member_number
    ).all()
    for (number,) in existing:
        match = pattern.match(number or "")
        if match:
            highest = max(highest, int(match.group(1)))
    return f"{prefix}-{highest + 1:04d}"


def record_membership_history(membership, event_type, description=None, from_status=None, to_status=None, user_id=None):
    """Append an immutable lifecycle event for a membership."""
    if not membership or not membership.id:
        raise ValueError("Membership must be flushed before history is recorded.")
    entry = MembershipHistory(
        membership_id=membership.id,
        cooperative_id=membership.cooperative_id,
        user_id=user_id if user_id is not None else session.get("user_id") if has_request_context() else None,
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        description=description,
    )
    db.session.add(entry)
    return entry


def membership_filtered_query(search="", status="", fee_status="", cooperative_id=None):
    """Build the role-scoped Phase 5 membership register query."""
    query = scoped_model_query(Membership).join(Farmer).join(
        Cooperative, Membership.cooperative_id == Cooperative.id
    ).filter(Cooperative.cooperative_type == "Primary")

    if search:
        query = query.filter(or_(
            Membership.member_number.ilike(f"%{search}%"),
            Membership.membership_type.ilike(f"%{search}%"),
            Membership.status.ilike(f"%{search}%"),
            Farmer.fullname.ilike(f"%{search}%"),
            Farmer.phone.ilike(f"%{search}%"),
        ))

    if status in MEMBERSHIP_ALLOWED_STATUSES:
        query = query.filter(Membership.status == status)

    if cooperative_id:
        query = query.filter(Membership.cooperative_id == cooperative_id)

    pending_membership_fee = (
        db.session.query(func.coalesce(func.sum(Contribution.amount), 0))
        .filter(
            Contribution.membership_id == Membership.id,
            Contribution.status == "Pending Confirmation",
            func.lower(func.trim(func.coalesce(Contribution.category, ""))).in_(MEMBERSHIP_FEE_CATEGORY_ALIASES),
        )
        .correlate(Membership)
        .scalar_subquery()
    )

    if fee_status == "paid":
        query = query.filter(Membership.fee_paid >= Membership.fee_amount)
    elif fee_status == "due":
        query = query.filter(
            (Membership.fee_paid + pending_membership_fee) < Membership.fee_amount
        )
    elif fee_status == "pending":
        query = query.filter(pending_membership_fee > 0)

    return query


def csv_safe_cell(value):
    """Prevent spreadsheet formula execution in exported user-controlled text."""
    if not isinstance(value, str):
        return value

    stripped = value.lstrip()
    if stripped.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def make_csv_response(filename, headers, rows):
    """Create a CSV response with spreadsheet-injection protection."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([csv_safe_cell(value) for value in headers])
    for row in rows:
        writer.writerow([csv_safe_cell(value) for value in row])
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


# =========================================================
# SYSTEM ADMINISTRATION HELPERS
# =========================================================
DEFAULT_SYSTEM_SETTINGS = {
    "brand_name": "Malenge",
    "product_name": "Farmers CRM",
    "organization_name": "Malenge Farmers",
    "developer_name": "KayCode Labs",
    "support_email": "",
    "default_location": "Malenge",
    "session_timeout_minutes": 480,
    "maintenance_notice": "",
    # Admin-controlled runtime policy. Disabling this does not erase any
    # user's enrolled Google Authenticator secret or recovery codes.
    "two_factor_required": True,
}


ROLE_PERMISSION_MATRIX = [
    {
        "role": "Admin",
        "scope": "System-wide",
        "allowed": "CRM users, access, executive appointments/history, cooperative structure, audit logs, security, backup/restore, system health, exports and system settings.",
        "restricted": "Does not perform Secretary, Treasurer or Chairperson cooperative duties."
    },
    {
        "role": "Secondary Chairperson",
        "scope": "Malenge Secondary Cooperative",
        "allowed": "Leadership oversight, meeting evidence confirmation, resolution certification, accountability verification and confirmation/rejection of Secondary Cooperative financial entries.",
        "restricted": "Cannot manage CRM users or change system configuration."
    },
    {
        "role": "Secondary Vice Chairperson",
        "scope": "Malenge Secondary Cooperative",
        "allowed": "Leadership/operational oversight, assigned accountability execution and independent verification when not self-verifying.",
        "restricted": "No CRM administration and no finance confirmation unless policy is changed later."
    },
    {
        "role": "Secondary Secretary",
        "scope": "Malenge Secondary Cooperative",
        "allowed": "Network-wide membership oversight; registers Secondary meeting evidence, captures resolutions and maintains accountability records.",
        "restricted": "Individual member registration belongs to each Primary Secretary/Vice Secretary; does not record or approve cooperative money."
    },
    {
        "role": "Secondary Vice Secretary",
        "scope": "Malenge Secondary Cooperative",
        "allowed": "Assists with network membership oversight, meeting evidence uploads and draft accountability/resolution records.",
        "restricted": "Cannot create or edit individual Primary membership records and does not record or approve cooperative money."
    },
    {
        "role": "Secondary Treasurer",
        "scope": "Malenge Secondary Cooperative",
        "allowed": "Records Secondary Cooperative money, views governance evidence and carries out assigned accountability tasks.",
        "restricted": "Cannot confirm own entries or transact for Primary Cooperatives."
    },
    {
        "role": "Primary Chairperson",
        "scope": "Assigned Primary Cooperative",
        "allowed": "Leadership oversight, meeting evidence confirmation, resolution certification, accountability verification and confirmation/rejection of that Primary Cooperative's financial entries.",
        "restricted": "Cannot manage CRM users or another cooperative's transactions."
    },
    {
        "role": "Primary Vice Chairperson",
        "scope": "Assigned Primary Cooperative",
        "allowed": "Leadership/operational oversight, assigned accountability execution and independent verification when not self-verifying.",
        "restricted": "No CRM administration and no finance confirmation unless policy is changed later."
    },
    {
        "role": "Primary Secretary",
        "scope": "Assigned Primary Cooperative",
        "allowed": "Registers and maintains membership records; registers meeting evidence, captures resolutions and maintains accountability records.",
        "restricted": "Does not record actual money paid."
    },
    {
        "role": "Primary Vice Secretary",
        "scope": "Assigned Primary Cooperative",
        "allowed": "Assists with membership, meeting evidence uploads and draft governance/accountability records for the assigned Primary Cooperative.",
        "restricted": "Does not record actual money paid."
    },
    {
        "role": "Primary Treasurer",
        "scope": "Assigned Primary Cooperative",
        "allowed": "Records contributions, expenses and permitted money records; views governance evidence and carries out assigned accountability tasks.",
        "restricted": "Cannot confirm own entries or transact for another cooperative."
    },
]


def system_settings_path():
    """Return the JSON file used for lightweight global CRM settings."""
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    return Path(app.instance_path) / "system_settings.json"


def load_system_settings():
    """Load safe non-secret CRM settings from JSON."""
    settings = dict(DEFAULT_SYSTEM_SETTINGS)
    path = system_settings_path()

    if path.exists():
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                for key in DEFAULT_SYSTEM_SETTINGS:
                    if key in saved:
                        settings[key] = saved[key]
        except (OSError, ValueError, TypeError):
            pass

    try:
        timeout = int(settings.get("session_timeout_minutes", 480))
    except (TypeError, ValueError):
        timeout = 480

    settings["session_timeout_minutes"] = min(max(timeout, 15), 1440)

    raw_two_factor = settings.get("two_factor_required", True)
    if isinstance(raw_two_factor, str):
        settings["two_factor_required"] = raw_two_factor.strip().lower() in {"1", "true", "yes", "on"}
    else:
        settings["two_factor_required"] = bool(raw_two_factor)

    return settings


def save_system_settings(settings):
    """Persist safe CRM settings."""
    path = system_settings_path()
    path.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def apply_session_timeout():
    """Apply configured login-session timeout."""
    settings = load_system_settings()
    app.permanent_session_lifetime = timedelta(
        minutes=settings["session_timeout_minutes"]
    )


def sqlite_database_path():
    """Resolve the current SQLite database path, if SQLite is in use."""
    database_url = db.engine.url
    if database_url.get_backend_name() != "sqlite":
        return None

    database_file = database_url.database
    if not database_file:
        return None

    path = Path(database_file)
    if not path.is_absolute():
        path = Path(app.instance_path) / path
    return path.resolve()


def backup_directory():
    """Return/create the server-side backup directory."""
    path = Path(app.instance_path) / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_database_backups():
    """Return metadata for saved SQLite backups."""
    backups = []
    for path in sorted(
        backup_directory().glob("*.db"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    ):
        stat = path.stat()
        backups.append({
            "name": path.name,
            "size_bytes": stat.st_size,
            "size_mb": round(stat.st_size / (1024 * 1024), 2),
            "created_at": datetime.fromtimestamp(stat.st_mtime),
        })
    return backups


def create_database_backup_copy(prefix="malenge_farmers_backup"):
    """Create a consistent SQLite backup using SQLite's backup API."""
    database_path = sqlite_database_path()
    if not database_path or not database_path.exists():
        raise RuntimeError("SQLite database file could not be found.")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    target = backup_directory() / f"{prefix}_{stamp}.db"

    source_connection = sqlite3.connect(str(database_path))
    backup_connection = sqlite3.connect(str(target))

    try:
        source_connection.backup(backup_connection)
    finally:
        backup_connection.close()
        source_connection.close()

    return target


def validate_sqlite_backup(path):
    """Validate integrity and minimum Malenge CRM tables."""
    if not path.exists() or path.suffix.lower() != ".db":
        return False, "Backup file does not exist or is not a .db file."

    connection = sqlite3.connect(str(path))
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            return False, "SQLite integrity check failed."

        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        required = {"user", "user_access", "cooperative", "audit_log"}
        missing = required - tables
        if missing:
            return False, "Backup is missing required CRM tables: " + ", ".join(sorted(missing))
    finally:
        connection.close()

    return True, None


def admin_export_rows(dataset):
    """Build system-wide Admin export data."""
    if dataset == "users":
        users = User.query.order_by(User.created_at.desc()).all()
        access_map = {u.id: get_user_access(u.id) for u in users}
        return (
            ["ID", "Full Name", "Phone", "Email", "Location", "Role", "Access Status", "Cooperative", "Created"],
            [[
                u.id,
                u.fullname,
                u.phone,
                u.email,
                u.farm_location,
                access_map[u.id].role if access_map.get(u.id) else "",
                access_map[u.id].status if access_map.get(u.id) else "",
                access_map[u.id].cooperative.name if access_map.get(u.id) and access_map[u.id].cooperative else "",
                u.created_at or "",
            ] for u in users]
        )

    if dataset == "cooperatives":
        rows = Cooperative.query.order_by(Cooperative.cooperative_type.desc(), Cooperative.name.asc()).all()
        return (
            ["ID", "Name", "Type", "Parent", "Registration Number", "Code", "Location", "Status", "Created"],
            [[
                r.id, r.name, r.cooperative_type,
                r.parent.name if r.parent else "",
                r.registration_number or "", r.code or "",
                r.location or "", r.status, r.created_at or ""
            ] for r in rows]
        )

    if dataset == "executive-history":
        rows = ExecutiveAppointment.query.order_by(
            ExecutiveAppointment.start_date.desc(),
            ExecutiveAppointment.created_at.desc(),
        ).all()
        return (
            [
                "ID", "Cooperative", "Type", "Position", "Role", "Executive",
                "Email", "Start Date", "End Date", "Status", "Appointed By",
                "Ended By", "Notes"
            ],
            [[
                r.id,
                r.cooperative.name if r.cooperative else "",
                r.cooperative.cooperative_type if r.cooperative else "",
                executive_position_from_role(r.role) or "",
                r.role,
                r.user.fullname if r.user else "",
                r.user.email if r.user else "",
                r.start_date or "",
                r.end_date or "",
                r.status,
                r.appointed_by.fullname if r.appointed_by else "",
                r.ended_by.fullname if r.ended_by else "",
                r.notes or "",
            ] for r in rows]
        )

    if dataset == "audit-logs":
        rows = AuditLog.query.order_by(AuditLog.created_at.desc()).all()
        return (
            [
                "ID", "Date/Time UTC", "User", "Action", "Entity", "Entity ID",
                "Cooperative", "Details", "IP Address", "Method", "Path",
                "Request ID", "User Agent"
            ],
            [[
                r.id, r.created_at or "",
                r.user.fullname if r.user else "",
                r.action, r.entity_type, r.entity_id or "",
                r.cooperative.name if r.cooperative else "",
                r.details or "", r.ip_address or "", r.request_method or "",
                r.request_path or "", r.request_id or "", r.user_agent or ""
            ] for r in rows]
        )

    if dataset == "memberships":
        rows = Membership.query.order_by(Membership.created_at.desc()).all()
        return (
            ["ID", "Member Number", "Member", "Cooperative", "Type", "Join Date", "Fee Expected", "Fee Confirmed", "Fee Pending", "Fee Outstanding", "Fee Status", "Status", "Updated"],
            [[
                r.id, r.member_number,
                r.farmer.fullname if r.farmer else "",
                r.cooperative.name if r.cooperative else "",
                r.membership_type or "", r.join_date or "",
                r.fee_amount or 0, r.fee_paid or 0, r.fee_pending, r.fee_outstanding, r.fee_status,
                r.status, r.updated_at or r.created_at or ""
            ] for r in rows]
        )

    if dataset == "farmers":
        rows = Farmer.query.order_by(Farmer.created_at.desc()).all()
        return (
            ["ID", "Full Name", "Cooperative", "Phone", "Email", "Location", "Status"],
            [[r.id, r.fullname, r.cooperative.name if r.cooperative else "", r.phone, r.email or "", r.location, r.status] for r in rows]
        )

    if dataset == "farms":
        rows = Farm.query.order_by(Farm.registration_date.desc()).all()
        return (
            ["ID", "Farm", "Cooperative", "Farmer", "Location", "Size", "Farming Type", "Status"],
            [[r.id, r.name, r.cooperative.name if r.cooperative else "", r.farmer.fullname if r.farmer else "", r.location, r.size or "", r.farming_type or "", r.status] for r in rows]
        )

    if dataset == "crops":
        rows = Crop.query.order_by(Crop.created_at.desc()).all()
        return (
            ["ID", "Crop", "Cooperative", "Farm", "Variety", "Planting Date", "Expected Harvest", "Area Planted", "Status"],
            [[r.id, r.name, r.cooperative.name if r.cooperative else "", r.farm.name if r.farm else "", r.variety or "", r.planting_date or "", r.expected_harvest_date or "", r.area_planted or "", r.status] for r in rows]
        )

    if dataset == "harvests":
        rows = Harvest.query.order_by(Harvest.harvest_date.desc()).all()
        return (
            ["ID", "Cooperative", "Crop", "Farm", "Harvest Date", "Quantity", "Unit", "Quality", "Storage", "Status"],
            [[r.id, r.cooperative.name if r.cooperative else "", r.crop.name if r.crop else "", r.crop.farm.name if r.crop and r.crop.farm else "", r.harvest_date or "", r.quantity, r.unit, r.quality_grade or "", r.storage_location or "", r.status] for r in rows]
        )

    if dataset == "sales":
        rows = Sale.query.order_by(Sale.sale_date.desc()).all()
        return (
            ["ID", "Cooperative", "Sale Date", "Buyer", "Crop", "Quantity", "Unit", "Price/Unit", "Total", "Status"],
            [[r.id, r.cooperative.name if r.cooperative else "", r.sale_date or "", r.buyer_name, r.harvest.crop.name if r.harvest and r.harvest.crop else "", r.quantity, r.unit, r.price_per_unit, r.total_amount, r.status] for r in rows]
        )

    if dataset == "payments":
        rows = Payment.query.order_by(Payment.payment_date.desc()).all()
        return (
            ["ID", "Cooperative", "Payment Date", "Buyer", "Amount", "Method", "Reference", "Status"],
            [[r.id, r.cooperative.name if r.cooperative else "", r.payment_date or "", r.sale.buyer_name if r.sale else "", r.amount, r.method or "", r.reference or "", r.status] for r in rows]
        )

    if dataset == "contributions":
        rows = Contribution.query.order_by(Contribution.contribution_date.desc()).all()
        return (
            ["ID", "Cooperative", "Date", "Member/Farmer", "Category", "Amount", "Method", "Reference", "Status"],
            [[r.id, r.cooperative.name if r.cooperative else "", r.contribution_date or "", r.farmer.fullname if r.farmer else "", r.category or "", r.amount, r.method or "", r.reference or "", r.status] for r in rows]
        )

    if dataset == "expenses":
        rows = Expense.query.order_by(Expense.expense_date.desc()).all()
        return (
            ["ID", "Cooperative", "Date", "Category", "Description", "Amount", "Method", "Reference", "Status"],
            [[r.id, r.cooperative.name if r.cooperative else "", r.expense_date or "", r.category, r.description, r.amount, r.payment_method or "", r.reference or "", r.status] for r in rows]
        )

    return None




def template_exists(template_name):
    """Check if a template exists."""
    template_path = Path(app.root_path) / (app.template_folder or "templates") / template_name
    return template_path.exists()


def render_optional_template(template_name, module_title, **context):
    """Render a template if it exists, otherwise show a placeholder."""
    if template_exists(template_name):
        return render_template(template_name, **context)

    return render_template_string("""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{{ module_title }} | Malenge Farmers CRM</title>
            <style>
                body{margin:0;font-family:Arial,Helvetica,sans-serif;background:#f4f7f5;color:#1f2937}
                .placeholder{max-width:720px;margin:80px auto;padding:40px;background:#fff;border-radius:14px;box-shadow:0 3px 15px rgba(0,0,0,0.06)}
                h1{margin-top:0;color:#173b2b}
                a{display:inline-block;margin-top:20px;padding:11px 18px;background:#2e7d4f;color:#fff;text-decoration:none;border-radius:8px}
            </style>
        </head>
        <body>
            <div class="placeholder">
                <h1>{{ module_title }}</h1>
                <p>The backend for this module is ready.</p>
                <p>The template <strong>{{ template_name }}</strong> has not been created yet.</p>
                <a href="{{ dashboard_url }}">Back to Dashboard</a>
            </div>
        </body>
        </html>
    """,
                                  module_title=module_title,
                                  template_name=template_name,
                                  dashboard_url=url_for("dashboard")
                                  )


# =========================================================
# FORM FEEDBACK FUNCTIONS
# =========================================================
SENSITIVE_FORM_FIELDS = {
    "password",
    "confirm_password",
    "current_password",
    "new_password",
    "code",
    "two_factor_code",
    "recovery_code",
}


def _form_snapshot():
    """Create a snapshot of form data for validation feedback."""
    snapshot = {}
    total_chars = 0

    for index, (field_name, values) in enumerate(request.form.lists()):
        if index >= 40:
            break

        if field_name.lower() in SENSITIVE_FORM_FIELDS or "password" in field_name.lower():
            continue

        clean_values = []
        for value in values:
            clean_value = str(value)[:400]
            if total_chars + len(clean_value) > 1800:
                break
            clean_values.append(clean_value)
            total_chars += len(clean_value)

        if not clean_values:
            continue

        snapshot[field_name] = (
            clean_values[0]
            if len(clean_values) == 1
            else clean_values
        )

        if total_chars >= 1800:
            break

    return snapshot


def _plain_error_message(response):
    """Extract plain error message from response."""
    if response.mimetype not in {"text/html", "text/plain"}:
        return None

    try:
        message = response.get_data(as_text=True).strip()
    except Exception:
        return None

    if not message or len(message) > 1200:
        return None

    lowered = message.lower()
    if "<html" in lowered or "<!doctype" in lowered or "<body" in lowered:
        return None

    return message


def _safe_feedback_target():
    """Determine safe redirect target for form feedback."""
    referrer = request.referrer

    if referrer:
        parsed = urlsplit(referrer)
        if not parsed.netloc or parsed.netloc == request.host:
            return referrer

    if logged_in():
        return url_for("dashboard")

    return url_for("login")


def _render_branded_error(status_code, title, message):
    """Render a branded error page."""
    destination = url_for("dashboard") if logged_in() else url_for("home")
    destination_label = "Back to Dashboard" if logged_in() else "Back to Home"

    return render_template_string(
        """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{{ status_code }} | Malenge Farmers CRM</title>
            <style>
                * { box-sizing: border-box; }
                body {
                    margin: 0;
                    min-height: 100vh;
                    display: grid;
                    place-items: center;
                    padding: 24px;
                    font-family: Arial, Helvetica, sans-serif;
                    background: #f3f7f4;
                    color: #173b2b;
                }
                .error-card {
                    width: min(620px, 100%);
                    padding: 38px;
                    background: #ffffff;
                    border: 1px solid #dfe8e2;
                    border-radius: 18px;
                    box-shadow: 0 18px 45px rgba(18, 63, 41, 0.08);
                }
                .error-code {
                    display: inline-flex;
                    margin-bottom: 18px;
                    padding: 7px 12px;
                    border-radius: 999px;
                    background: #fde7e7;
                    color: #a02d2d;
                    font-size: 12px;
                    font-weight: 800;
                    letter-spacing: .7px;
                }
                h1 { margin: 0 0 12px; font-size: 30px; }
                p { margin: 0; color: #5f6f65; line-height: 1.65; }
                .actions { margin-top: 26px; display: flex; gap: 12px; flex-wrap: wrap; }
                a, button {
                    min-height: 44px;
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    padding: 0 18px;
                    border-radius: 9px;
                    font-size: 14px;
                    font-weight: 700;
                    text-decoration: none;
                    cursor: pointer;
                }
                a { background: #2e8251; color: #fff; }
                button { 
                    background: #f3f7f4; 
                    color: #315441; 
                    border: 1px solid #d7e3db;
                    font-family: inherit;
                }
            </style>
        </head>
        <body>
            <section class="error-card">
                <div class="error-code">ERROR {{ status_code }}</div>
                <h1>{{ title }}</h1>
                <p>{{ message }}</p>
                <div class="actions">
                    <button type="button" onclick="history.back()">Go Back</button>
                    <a href="{{ destination }}">{{ destination_label }}</a>
                </div>
            </section>
        </body>
        </html>
        """,
        status_code=status_code,
        title=title,
        message=message,
        destination=destination,
        destination_label=destination_label,
    )


# =========================================================
# APPLICATION CONTEXT PROCESSORS AND REQUEST HANDLERS
# =========================================================
@app.context_processor
def inject_security_context():
    """Expose only safe request-security helpers to Jinja templates."""
    return {
        "csrf_token": csrf_token,
        "format_sast": format_sast,
        "recovery_code_count": recovery_code_count,
        "two_factor_policy_enabled": two_factor_policy_enabled,
    }


@app.before_request
def assign_request_context():
    """Attach a stable request ID used by responses and audit records."""
    incoming = request.headers.get("X-Request-ID", "").strip()
    g.request_id = (incoming[:64] if incoming else uuid.uuid4().hex)


@app.before_request
def protect_csrf():
    """Reject forged state-changing requests with a session-bound token."""
    if app.config.get("TESTING"):
        return None

    if request.method in {"GET", "HEAD", "OPTIONS", "TRACE"}:
        return None

    expected = session.get("_csrf_token")
    provided = (
        request.form.get("csrf_token")
        or request.headers.get("X-CSRFToken")
        or request.headers.get("X-CSRF-Token")
    )

    if not expected or not provided or not hmac.compare_digest(str(expected), str(provided)):
        abort(400, description="Your security token is missing or expired. Refresh the page and try again.")

    return None


@app.after_request
def add_security_headers(response):
    """Apply baseline browser security headers to every response."""
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        "img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; "
        "font-src 'self' data:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'; "
        "form-action 'self'"
    )

    if request.is_secure:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")

    if getattr(g, "request_id", None):
        response.headers.setdefault("X-Request-ID", g.request_id)

    if logged_in() and request.endpoint != "static":
        response.headers.setdefault("Cache-Control", "no-store")

    return response


@app.context_processor
def inject_access_context():
    """Inject access-related variables into templates."""
    if not logged_in():
        return {
            "current_access": None,
            "current_cooperative": None,
            "can_view_cooperatives": False,
            "can_edit_cooperatives": False,
            "can_manage_users": False,
            "can_view_audit_logs": False,
            "can_manage_memberships": False,
            "can_record_finance": False,
            "can_approve_finance": False,
            "can_view_farmers": False,
            "can_manage_farmers": False,
            "can_view_agriculture": False,
            "can_manage_agriculture": False,
            "can_view_business": False,
            "can_manage_business": False,
            "can_view_finance": False,
            "can_view_governance": False,
            "can_record_meetings": False,
            "can_confirm_meetings": False,
            "can_record_resolutions": False,
            "can_verify_accountability": False,
            "system_settings": load_system_settings(),
            "sale_paid_amount": sale_paid_amount,
            "sale_outstanding_amount": sale_outstanding_amount,
            "sale_payment_status": sale_payment_status,
        }

    access = current_access()
    cooperative = current_cooperative()

    active = (
            access is not None
            and access.status == "Active"
            and access.role in VALID_ACCESS_ROLES
    )

    return {
        "current_access": access,
        "current_cooperative": cooperative,
        "can_view_cooperatives": active and access.role in COOPERATIVE_VIEW_ROLES,
        "can_edit_cooperatives": active and access.role in COOPERATIVE_EDIT_ROLES,
        "can_manage_users": active and access.role in USER_MANAGEMENT_ROLES,
        "can_view_audit_logs": active and access.role in AUDIT_LOG_ROLES,
        "can_manage_memberships": active and access.role in MEMBERSHIP_MANAGEMENT_ROLES,
        "can_record_finance": active and access.role in FINANCE_RECORD_ROLES,
        "can_approve_finance": active and access.role in FINANCE_APPROVAL_ROLES,
        "can_view_farmers": active and access.role in FARMER_VIEW_ROLES,
        "can_manage_farmers": active and access.role in FARMER_RECORD_ROLES,
        "can_view_agriculture": active and access.role in AGRICULTURE_VIEW_ROLES,
        "can_manage_agriculture": active and access.role in PRIMARY_OPERATION_RECORD_ROLES,
        "can_view_business": active and access.role in BUSINESS_VIEW_ROLES,
        "can_manage_business": active and access.role in BUSINESS_RECORD_ROLES,
        "can_view_finance": active and access.role in FINANCE_VIEW_ROLES,
        "can_view_governance": active and access.role in GOVERNANCE_VIEW_ROLES,
        "can_record_meetings": active and access.role in MEETING_RECORD_ROLES,
        "can_confirm_meetings": active and access.role in MEETING_CONFIRM_ROLES,
        "can_record_resolutions": active and access.role in RESOLUTION_RECORD_ROLES,
        "can_verify_accountability": active and access.role in ACCOUNTABILITY_VERIFY_ROLES,
        "system_settings": load_system_settings(),
        "sale_paid_amount": sale_paid_amount,
        "sale_outstanding_amount": sale_outstanding_amount,
        "sale_payment_status": sale_payment_status,
    }


@app.before_request
def enforce_active_access():
    """Enforce active access for all protected endpoints."""
    public_endpoints = {
        "home",
        "login",
        "register",
        "health",
        "static",
    }

    if request.endpoint in public_endpoints:
        return None

    if not logged_in():
        return None

    access = get_user_access(session["user_id"])

    if (
            access.status != "Active"
            or access.role not in VALID_ACCESS_ROLES
    ):
        session.clear()
        return redirect(url_for("login"))

    return None


@app.before_request
def enforce_two_factor():
    """Keep password-only sessions away from protected CRM routes."""
    if not two_factor_is_required() or not logged_in():
        return None

    exempt_endpoints = {
        "home",
        "login",
        "register",
        "health",
        "static",
        "logout",
        "two_factor_setup",
        "two_factor_verify",
    }
    if request.endpoint in exempt_endpoints:
        return None

    user = current_user()
    if not user:
        session.clear()
        return redirect(url_for("login"))

    if two_factor_session_complete():
        return None

    if user.two_factor_enabled:
        return redirect(url_for("two_factor_verify"))

    return redirect(url_for("two_factor_setup"))


@app.before_request
def load_form_feedback():
    """Load form feedback from session."""
    g.malenge_form_error = session.pop("_malenge_form_error", None)
    g.malenge_form_values = session.pop("_malenge_form_values", None)
    g.malenge_form_action = session.pop("_malenge_form_action", None)


@app.after_request
def improve_error_experience(response):
    """Enhance error responses with better user experience."""
    # Turn simple POST validation errors into a redirect back to the form
    if request.method == "POST" and response.status_code in {400, 401}:
        message = _plain_error_message(response)

        if message:
            session["_malenge_form_error"] = message
            snapshot = _form_snapshot()
            if snapshot:
                session["_malenge_form_values"] = snapshot
            session["_malenge_form_action"] = request.path
            return redirect(_safe_feedback_target(), code=303)

    # Replace simple non-form HTTP errors with a branded page
    if response.status_code in {400, 401, 403, 404, 413, 429, 500}:
        message = _plain_error_message(response)

        if message:
            titles = {
                400: "Please check the information",
                401: "Sign-in required",
                403: "Access denied",
                404: "Page not found",
                413: "Request too large",
                429: "Too many attempts",
                500: "Something went wrong",
            }
            html_response = _render_branded_error(
                response.status_code,
                titles.get(response.status_code, "Request could not be completed"),
                message,
            )
            branded = app.make_response(html_response)
            branded.status_code = response.status_code
            return branded

    # Inject a reusable validation banner into any HTML page after a failed form
    form_error = getattr(g, "malenge_form_error", None)
    form_values = getattr(g, "malenge_form_values", None) or {}
    form_action = getattr(g, "malenge_form_action", None) or ""

    if (
            request.method in {"GET", "HEAD"}
            and form_error
            and response.status_code < 400
            and response.mimetype == "text/html"
    ):
        try:
            page = response.get_data(as_text=True)
        except Exception:
            return response

        safe_message = html.escape(str(form_error))
        snapshot_json = json.dumps(form_values).replace("</", "<\\/")
        action_json = json.dumps(form_action).replace("</", "<\\/")

        feedback_markup = f"""
        <style>
            #malenge-validation-alert {{
                position: fixed;
                top: 22px;
                right: 24px;
                z-index: 99999;
                width: min(520px, calc(100vw - 48px));
                display: flex;
                align-items: flex-start;
                gap: 12px;
                padding: 16px 18px;
                background: #fff7f7;
                border: 1px solid #efb7b7;
                border-left: 5px solid #c83f3f;
                border-radius: 12px;
                box-shadow: 0 16px 36px rgba(91, 28, 28, 0.14);
                color: #732727;
                font-family: Arial, Helvetica, sans-serif;
            }}
            #malenge-validation-alert .malenge-alert-icon {{
                flex: 0 0 auto;
                font-size: 18px;
                line-height: 1.4;
            }}
            #malenge-validation-alert .malenge-alert-copy {{
                flex: 1;
                min-width: 0;
            }}
            #malenge-validation-alert strong {{
                display: block;
                margin-bottom: 3px;
                font-size: 14px;
            }}
            #malenge-validation-alert p {{
                margin: 0;
                color: #7b3535;
                font-size: 13px;
                line-height: 1.5;
            }}
            #malenge-validation-alert button {{
                flex: 0 0 auto;
                padding: 0;
                border: 0;
                background: transparent;
                color: #8a4444;
                cursor: pointer;
                font-size: 20px;
                line-height: 1;
            }}
            @media (max-width: 700px) {{
                #malenge-validation-alert {{
                    top: 12px;
                    right: 12px;
                    width: calc(100vw - 24px);
                }}
            }}
        </style>

        <div id="malenge-validation-alert" role="alert" aria-live="assertive">
            <div class="malenge-alert-icon">⚠️</div>
            <div class="malenge-alert-copy">
                <strong>Please check this form</strong>
                <p>{safe_message}</p>
            </div>
            <button type="button" aria-label="Close error message" onclick="this.parentElement.remove()">×</button>
        </div>

        <script id="malenge-form-values" type="application/json">{snapshot_json}</script>
        <script>
            (function () {{
                const dataNode = document.getElementById("malenge-form-values");
                if (!dataNode) return;

                let values = {{}};
                try {{
                    values = JSON.parse(dataNode.textContent || "{{}}");
                }} catch (error) {{
                    return;
                }}

                const failedAction = {action_json};
                const allForms = Array.from(document.forms);
                const matchingForms = allForms.filter(function (form) {{
                    try {{
                        const actionUrl = new URL(form.action || window.location.href, window.location.href);
                        return failedAction && actionUrl.pathname === failedAction;
                    }} catch (error) {{
                        return false;
                    }}
                }});
                const targetForms = matchingForms.length ? matchingForms : allForms;

                Object.keys(values).forEach(function (name) {{
                    const saved = Array.isArray(values[name]) ? values[name] : [values[name]];

                    targetForms.forEach(function (form) {{
                        const controls = Array.from(form.elements).filter(function (control) {{
                            return control.name === name;
                        }});

                        controls.forEach(function (control) {{
                            const type = (control.type || "").toLowerCase();

                            if (type === "password" || type === "file" || type === "submit" || type === "button") {{
                                return;
                            }}

                            if (type === "checkbox" || type === "radio") {{
                                control.checked = saved.includes(control.value);
                                return;
                            }}

                            if (control.tagName === "SELECT" && control.multiple) {{
                                Array.from(control.options).forEach(function (option) {{
                                    option.selected = saved.includes(option.value);
                                }});
                                return;
                            }}

                            if (saved.length) {{
                                control.value = saved[0];
                                control.dispatchEvent(new Event("change", {{ bubbles: true }}));
                            }}
                        }});
                    }});
                }});

                const focusRoot = targetForms.length ? targetForms[0] : document;
                const firstInvalidCandidate = focusRoot.querySelector(
                    "input:not([type='hidden']):not([type='password']), select, textarea"
                );
                if (firstInvalidCandidate) {{
                    firstInvalidCandidate.focus({{ preventScroll: true }});
                }}
            }})();
        </script>
        """

        if "</body>" in page.lower():
            lower_page = page.lower()
            body_index = lower_page.rfind("</body>")
            page = page[:body_index] + feedback_markup + page[body_index:]
        else:
            page += feedback_markup

        response.set_data(page)
        response.headers["Content-Length"] = str(len(response.get_data()))

    return response


# =========================================================
# ROUTES - PUBLIC
# =========================================================
@app.route("/")
def home():
    """Landing page."""
    return render_template("landing.html")


@app.route("/health")
def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "application": "Malenge Farmers CRM",
        "time": utc_now().isoformat()
    }


@app.route("/login", methods=["GET", "POST"])
def login():
    """User login with throttling and security auditing."""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if login_rate_limited(email):
            add_audit_log(
                "LOGIN_RATE_LIMITED",
                "User",
                details=f"Login temporarily blocked after repeated failures for {email or 'blank email'}.",
            )
            db.session.commit()
            return "Too many failed login attempts. Please wait before trying again.", 429

        user = User.query.filter_by(email=email).first()

        if not user or not check_password_hash(user.password, password):
            record_login_failure(email)
            add_audit_log(
                "LOGIN_FAILED",
                "User",
                user.id if user else None,
                f"Failed login attempt for {email or 'blank email'}",
                user_id=user.id if user else None,
            )
            db.session.commit()
            return "Invalid email or password.", 401

        access = get_user_access(user.id)

        if access.status == "Pending":
            add_audit_log(
                "LOGIN_DENIED",
                "User",
                user.id,
                "Login denied because account is Pending.",
                cooperative_id=access.cooperative_id,
                user_id=user.id,
            )
            db.session.commit()
            return (
                "Your CRM account is awaiting authorization "
                "and cooperative assignment.",
                403,
            )

        if access.status != "Active":
            add_audit_log(
                "LOGIN_DENIED",
                "User",
                user.id,
                f"Login denied because account status is {access.status}.",
                cooperative_id=access.cooperative_id,
                user_id=user.id,
            )
            db.session.commit()
            return "Your CRM account is currently inactive.", 403

        if access.role not in VALID_ACCESS_ROLES:
            add_audit_log(
                "LOGIN_DENIED",
                "User",
                user.id,
                f"Login denied because role is {access.role}.",
                cooperative_id=access.cooperative_id,
                user_id=user.id,
            )
            db.session.commit()
            return (
                "Your CRM account requires an updated role assignment.",
                403,
            )

        clear_login_failures(email)
        apply_session_timeout()
        session.clear()
        session.permanent = True
        session["user_id"] = user.id
        session["fullname"] = user.fullname
        session["two_factor_authenticated"] = False
        session["two_factor_bypassed"] = False
        session["two_factor_failures"] = 0
        # Rotate the CSRF token when the authentication state changes.
        session["_csrf_token"] = secrets.token_urlsafe(32)

        if two_factor_is_required():
            if user.two_factor_enabled:
                add_audit_log(
                    "TWO_FACTOR_CHALLENGE",
                    "User",
                    user.id,
                    "Password accepted; Google Authenticator verification required.",
                    cooperative_id=access.cooperative_id,
                )
                db.session.commit()
                return redirect(url_for("two_factor_verify"))

            add_audit_log(
                "TWO_FACTOR_ENROLLMENT_REQUIRED",
                "User",
                user.id,
                "Password accepted; mandatory Google Authenticator enrollment required.",
                cooperative_id=access.cooperative_id,
            )
            db.session.commit()
            return redirect(url_for("two_factor_setup"))

        session["two_factor_authenticated"] = True
        session["two_factor_bypassed"] = True
        add_audit_log(
            "LOGIN_SUCCESS",
            "User",
            user.id,
            f"Successful login as {access.role}.",
            cooperative_id=access.cooperative_id,
        )
        db.session.commit()
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Bootstrap the first Admin account only when explicitly allowed."""
    if User.query.count() > 0:
        return redirect(url_for("login"))

    if not app.config.get("ALLOW_BOOTSTRAP_REGISTRATION"):
        abort(403, description="Bootstrap registration is disabled. Create the first Admin from a trusted environment.")

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

        existing_user = User.query.filter(func.lower(User.email) == email.lower()).first()
        if existing_user:
            return "An account with this email already exists.", 400

        new_user = User(
            fullname=fullname,
            phone=phone,
            email=email,
            farm_location=farm_location,
            password=generate_password_hash(password),
        )
        db.session.add(new_user)
        db.session.flush()

        access = UserAccess(
            user_id=new_user.id,
            role="Admin",
            status="Active",
            cooperative_id=None,
        )
        db.session.add(access)
        add_audit_log(
            "BOOTSTRAP_ADMIN_CREATE",
            "User",
            new_user.id,
            "Initial CRM Admin account created through bootstrap registration.",
            user_id=new_user.id,
        )
        db.session.commit()
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/logout")
@login_required
def logout():
    """User logout with security auditing."""
    user = current_user()
    access = current_access()

    if user:
        add_audit_log(
            "LOGOUT",
            "User",
            user.id,
            f"User logged out from role {access.role if access else 'Unknown'}.",
            cooperative_id=access.cooperative_id if access else None,
        )
        db.session.commit()

    session.clear()
    return redirect(url_for("login"))


# =========================================================
# ROUTES - DASHBOARD
# =========================================================
@app.route("/dashboard")
@login_required
def dashboard():
    """Role-aware dashboard for Admin, Secondary and Primary executives."""
    access_now = current_access()
    cooperative_now = current_cooperative()
    role_now = access_now.role if access_now else ""
    own_cooperative_id = access_now.cooperative_id if access_now else None

    is_admin_dashboard = role_now == "Admin"
    is_secondary_dashboard = role_now in SECONDARY_EXECUTIVE_ROLES
    is_primary_dashboard = role_now in PRIMARY_EXECUTIVE_ROLES

    # -----------------------------------------------------
    # Direct cooperative record totals (never inherited child records)
    # -----------------------------------------------------
    farmer_count = scoped_model_query(Farmer).count()
    farm_count = scoped_model_query(Farm).count()
    crop_count = scoped_model_query(Crop).count()
    harvest_count = scoped_model_query(Harvest).count()

    active_sales_query = scoped_model_query(Sale).filter(Sale.status != "Cancelled")
    sales_count = active_sales_query.count()
    payment_count = scoped_model_query(Payment).count()

    total_sales_value = active_sales_query.with_entities(
        func.coalesce(func.sum(Sale.total_amount), 0)
    ).scalar() or 0

    total_payments_value = scoped_model_query(Payment).filter(
        Payment.status.in_(PAYMENT_VALUE_STATUSES)
    ).with_entities(
        func.coalesce(func.sum(Payment.amount), 0)
    ).scalar() or 0

    total_expenses_value = scoped_model_query(Expense).filter(
        Expense.status.in_(CONFIRMED_EXPENSE_STATUSES)
    ).with_entities(
        func.coalesce(func.sum(Expense.amount), 0)
    ).scalar() or 0

    total_contributions_value = scoped_model_query(Contribution).filter(
        Contribution.status.in_(CONFIRMED_CONTRIBUTION_STATUSES)
    ).with_entities(
        func.coalesce(func.sum(Contribution.amount), 0)
    ).scalar() or 0

    outstanding_balance = max(float(total_sales_value) - float(total_payments_value), 0.0)
    net_cash_position = (
        float(total_payments_value)
        + float(total_contributions_value)
        - float(total_expenses_value)
    )

    membership_count = scoped_model_query(Membership).count()
    active_membership_count = scoped_model_query(Membership).filter(
        Membership.status == "Active"
    ).count()

    visible_active_memberships = scoped_model_query(Membership).filter(
        Membership.status == "Active"
    ).all()
    membership_fee_due_value = sum(
        m.fee_outstanding
        for m in visible_active_memberships
    )

    customer_count = scoped_model_query(Customer).count()
    supplier_count = scoped_model_query(Supplier).count()
    expense_count = scoped_model_query(Expense).count()
    inventory_count = scoped_model_query(InventoryItem).count()
    equipment_count = scoped_model_query(Equipment).count()
    open_task_count = scoped_model_query(Task).filter(Task.status.notin_(["Completed", "Cancelled", "Verified"])).count()

    recent_farmers = scoped_model_query(Farmer).order_by(Farmer.created_at.desc()).limit(5).all()
    recent_sales = active_sales_query.order_by(Sale.created_at.desc()).limit(5).all()
    recent_payments = scoped_model_query(Payment).order_by(Payment.created_at.desc()).limit(5).all()

    # -----------------------------------------------------
    # Cooperative structure / primary performance
    # -----------------------------------------------------
    secondary_cooperatives = accessible_cooperative_query().filter_by(
        cooperative_type="Secondary", status="Active"
    ).order_by(Cooperative.name.asc()).all()

    if is_secondary_dashboard and cooperative_now and cooperative_now.cooperative_type == "Secondary":
        # Secondary dashboards may compare the two Primaries as aggregate units,
        # without granting access to their individual records.
        primary_cooperatives = Cooperative.query.filter_by(
            parent_id=cooperative_now.id, cooperative_type="Primary", status="Active"
        ).order_by(Cooperative.name.asc()).all()
    else:
        primary_cooperatives = accessible_cooperative_query().filter_by(
            cooperative_type="Primary", status="Active"
        ).order_by(Cooperative.name.asc()).all()

    primary_performance = []
    for cooperative in primary_cooperatives:
        coop_sales = db.session.query(
            func.coalesce(func.sum(Sale.total_amount), 0)
        ).filter(
            Sale.cooperative_id == cooperative.id,
            Sale.status != "Cancelled",
        ).scalar() or 0

        coop_payments = db.session.query(
            func.coalesce(func.sum(Payment.amount), 0)
        ).filter(
            Payment.cooperative_id == cooperative.id,
            Payment.status.in_(PAYMENT_VALUE_STATUSES),
        ).scalar() or 0

        coop_expenses = db.session.query(
            func.coalesce(func.sum(Expense.amount), 0)
        ).filter(
            Expense.cooperative_id == cooperative.id,
            Expense.status.in_(CONFIRMED_EXPENSE_STATUSES),
        ).scalar() or 0

        coop_contributions = db.session.query(
            func.coalesce(func.sum(Contribution.amount), 0)
        ).filter(
            Contribution.cooperative_id == cooperative.id,
            Contribution.status.in_(CONFIRMED_CONTRIBUTION_STATUSES),
        ).scalar() or 0

        coop_members = Membership.query.filter_by(cooperative_id=cooperative.id).count()
        coop_active_memberships = Membership.query.filter_by(
            cooperative_id=cooperative.id,
            status="Active",
        ).all()
        coop_fee_due = sum(
            m.fee_outstanding
            for m in coop_active_memberships
        )

        pending_finance = (
            Contribution.query.filter_by(
                cooperative_id=cooperative.id,
                status="Pending Confirmation",
            ).count()
            + Expense.query.filter_by(
                cooperative_id=cooperative.id,
                status="Pending Confirmation",
            ).count()
        )

        primary_performance.append({
            "cooperative": cooperative,
            "farmer_count": Farmer.query.filter_by(cooperative_id=cooperative.id).count(),
            "member_count": coop_members,
            "farm_count": Farm.query.filter_by(cooperative_id=cooperative.id).count(),
            "crop_count": Crop.query.filter_by(cooperative_id=cooperative.id).count(),
            "harvest_count": Harvest.query.filter_by(cooperative_id=cooperative.id).count(),
            "sales_value": float(coop_sales),
            "payments_value": float(coop_payments),
            "contributions_value": float(coop_contributions),
            "expenses_value": float(coop_expenses),
            "outstanding_balance": max(float(coop_sales) - float(coop_payments), 0.0),
            "cash_position": float(coop_payments) + float(coop_contributions) - float(coop_expenses),
            "membership_fee_due": float(coop_fee_due),
            "pending_finance": pending_finance,
            "open_tasks": Task.query.filter(
                Task.cooperative_id == cooperative.id,
                Task.status.notin_(["Completed", "Cancelled", "Verified"]),
            ).count(),
            "low_stock_items": InventoryItem.query.filter(
                InventoryItem.cooperative_id == cooperative.id,
                InventoryItem.status == "Active",
                InventoryItem.quantity_on_hand <= InventoryItem.reorder_level,
            ).count(),
        })

    # -----------------------------------------------------
    # Alerts in the user's visibility scope
    # -----------------------------------------------------
    today = crm_today()

    overdue_task_count = scoped_model_query(Task).filter(
        Task.status.notin_(["Completed", "Cancelled", "Verified"]),
        Task.due_date.isnot(None),
        Task.due_date < today,
    ).count()

    low_stock_count = scoped_model_query(InventoryItem).filter(
        InventoryItem.status == "Active",
        InventoryItem.quantity_on_hand <= InventoryItem.reorder_level,
    ).count()

    service_due_count = scoped_model_query(Equipment).filter(
        Equipment.next_service_date.isnot(None),
        Equipment.next_service_date <= today,
        Equipment.status != "Retired",
    ).count()

    unpaid_membership_count = sum(
        1
        for membership in scoped_model_query(Membership).filter(
            Membership.status == "Active"
        ).all()
        if membership.fee_outstanding > 1e-9
    )

    recent_cooperative_activity = scoped_model_query(AuditLog).filter(
        AuditLog.cooperative_id.isnot(None)
    ).order_by(AuditLog.created_at.desc()).limit(12).all()

    # -----------------------------------------------------
    # The executive's OWN cooperative. Important for Secondary
    # executives: oversight visibility must not be confused with
    # authority to mutate/approve Primary Cooperative records.
    # -----------------------------------------------------
    own_farmer_count = 0
    own_farm_count = 0
    own_crop_count = 0
    own_harvest_count = 0
    own_member_count = 0
    own_active_member_count = 0
    own_membership_fee_due = 0.0
    own_sales_value = 0.0
    own_payments_value = 0.0
    own_contributions_value = 0.0
    own_expenses_value = 0.0
    own_outstanding_balance = 0.0
    own_cash_position = 0.0
    own_pending_contributions = 0
    own_pending_expenses = 0
    own_pending_finance = 0
    own_recent_memberships = []
    own_recent_contributions = []
    own_recent_expenses = []
    own_recent_farmers = []
    own_executives = []
    own_positions_filled = 0
    own_positions_vacant = 0

    if own_cooperative_id:
        own_farmer_count = Farmer.query.filter_by(cooperative_id=own_cooperative_id).count()
        own_farm_count = Farm.query.filter_by(cooperative_id=own_cooperative_id).count()
        own_crop_count = Crop.query.filter_by(cooperative_id=own_cooperative_id).count()
        own_harvest_count = Harvest.query.filter_by(cooperative_id=own_cooperative_id).count()
        own_member_count = Membership.query.filter_by(cooperative_id=own_cooperative_id).count()
        own_active_member_count = Membership.query.filter_by(
            cooperative_id=own_cooperative_id,
            status="Active",
        ).count()

        own_memberships_for_due = Membership.query.filter_by(
            cooperative_id=own_cooperative_id,
            status="Active",
        ).all()
        own_membership_fee_due = sum(
            m.fee_outstanding
            for m in own_memberships_for_due
        )

        own_sales_value = db.session.query(
            func.coalesce(func.sum(Sale.total_amount), 0)
        ).filter(
            Sale.cooperative_id == own_cooperative_id,
            Sale.status != "Cancelled",
        ).scalar() or 0

        own_payments_value = db.session.query(
            func.coalesce(func.sum(Payment.amount), 0)
        ).filter(
            Payment.cooperative_id == own_cooperative_id,
            Payment.status.in_(PAYMENT_VALUE_STATUSES),
        ).scalar() or 0

        own_contributions_value = db.session.query(
            func.coalesce(func.sum(Contribution.amount), 0)
        ).filter(
            Contribution.cooperative_id == own_cooperative_id,
            Contribution.status.in_(CONFIRMED_CONTRIBUTION_STATUSES),
        ).scalar() or 0

        own_expenses_value = db.session.query(
            func.coalesce(func.sum(Expense.amount), 0)
        ).filter(
            Expense.cooperative_id == own_cooperative_id,
            Expense.status.in_(CONFIRMED_EXPENSE_STATUSES),
        ).scalar() or 0

        own_outstanding_balance = max(float(own_sales_value) - float(own_payments_value), 0.0)
        own_cash_position = (
            float(own_payments_value)
            + float(own_contributions_value)
            - float(own_expenses_value)
        )

        own_pending_contributions = Contribution.query.filter_by(
            cooperative_id=own_cooperative_id,
            status="Pending Confirmation",
        ).count()
        own_pending_expenses = Expense.query.filter_by(
            cooperative_id=own_cooperative_id,
            status="Pending Confirmation",
        ).count()
        own_pending_finance = own_pending_contributions + own_pending_expenses

        own_recent_memberships = Membership.query.filter_by(
            cooperative_id=own_cooperative_id
        ).order_by(Membership.created_at.desc()).limit(6).all()

        own_recent_contributions = Contribution.query.filter_by(
            cooperative_id=own_cooperative_id
        ).order_by(Contribution.created_at.desc()).limit(6).all()

        own_recent_expenses = Expense.query.filter_by(
            cooperative_id=own_cooperative_id
        ).order_by(Expense.created_at.desc()).limit(6).all()

        own_recent_farmers = Farmer.query.filter_by(
            cooperative_id=own_cooperative_id
        ).order_by(Farmer.created_at.desc()).limit(6).all()

        own_executives = UserAccess.query.filter_by(
            cooperative_id=own_cooperative_id,
            status="Active",
        ).join(User).order_by(UserAccess.role.asc()).all()

        if cooperative_now and cooperative_now.cooperative_type == "Secondary":
            expected_roles = SECONDARY_EXECUTIVE_ROLES
        else:
            expected_roles = PRIMARY_EXECUTIVE_ROLES

        filled_roles = {
            executive.role for executive in own_executives
            if executive.role in expected_roles
        }
        own_positions_filled = len(filled_roles)
        own_positions_vacant = max(5 - own_positions_filled, 0)

    # -----------------------------------------------------
    # Phase 6 accountability command-centre metrics
    # -----------------------------------------------------
    accountability_open_count = 0
    accountability_overdue_count = 0
    accountability_awaiting_verification_count = 0
    my_accountability_task_count = 0
    my_overdue_accountability_count = 0
    recent_resolutions = []
    upcoming_meetings = []

    if own_cooperative_id and not is_admin_dashboard:
        own_resolutions = Resolution.query.filter_by(cooperative_id=own_cooperative_id)
        accountability_open_count = own_resolutions.filter(
            Resolution.status.in_(["Assigned", "In Progress", "Awaiting Verification"])
        ).count()
        accountability_overdue_count = own_resolutions.filter(
            Resolution.status.in_(["Assigned", "In Progress"]),
            Resolution.due_date.isnot(None),
            Resolution.due_date < today,
        ).count()
        accountability_awaiting_verification_count = own_resolutions.filter_by(
            status="Awaiting Verification"
        ).count()
        recent_resolutions = own_resolutions.order_by(Resolution.created_at.desc()).limit(5).all()
        upcoming_meetings = Meeting.query.filter(
            Meeting.cooperative_id == own_cooperative_id,
            Meeting.meeting_date >= today,
        ).order_by(Meeting.meeting_date.asc()).limit(4).all()

        my_tasks = Task.query.filter(
            Task.cooperative_id == own_cooperative_id,
            Task.resolution_id.isnot(None),
            Task.assigned_user_id == session.get("user_id"),
            Task.status.in_(["Open", "In Progress", "Awaiting Verification"]),
        )
        my_accountability_task_count = my_tasks.count()
        my_overdue_accountability_count = my_tasks.filter(
            Task.due_date.isnot(None),
            Task.due_date < today,
            Task.status.in_(["Open", "In Progress"]),
        ).count()

    # -----------------------------------------------------
    # Admin-only dashboard variables
    # -----------------------------------------------------
    admin_user_count = User.query.count() if is_admin_dashboard else 0
    admin_active_access_count = UserAccess.query.filter_by(status="Active").count() if is_admin_dashboard else 0
    admin_inactive_access_count = UserAccess.query.filter_by(status="Inactive").count() if is_admin_dashboard else 0
    admin_cooperative_count = Cooperative.query.count() if is_admin_dashboard else 0
    admin_audit_count = AuditLog.query.count() if is_admin_dashboard else 0
    admin_recent_activity = (
        AuditLog.query.order_by(AuditLog.created_at.desc()).limit(12).all()
        if is_admin_dashboard else []
    )
    admin_backup_count = len(list_database_backups()) if is_admin_dashboard else 0
    admin_database_backend = db.engine.url.get_backend_name() if is_admin_dashboard else ""

    return render_template(
        "dashboard.html",
        # Role / cooperative context
        current_access=access_now,
        current_cooperative=cooperative_now,
        role_now=role_now,
        is_admin_dashboard=is_admin_dashboard,
        is_secondary_dashboard=is_secondary_dashboard,
        is_primary_dashboard=is_primary_dashboard,

        # Visible scope totals
        farmer_count=farmer_count,
        farm_count=farm_count,
        crop_count=crop_count,
        harvest_count=harvest_count,
        membership_count=membership_count,
        active_membership_count=active_membership_count,
        membership_fee_due_value=membership_fee_due_value,
        sales_count=sales_count,
        payment_count=payment_count,
        total_sales_value=total_sales_value,
        total_payments_value=total_payments_value,
        total_contributions_value=total_contributions_value,
        total_expenses_value=total_expenses_value,
        outstanding_balance=outstanding_balance,
        net_cash_position=net_cash_position,
        customer_count=customer_count,
        supplier_count=supplier_count,
        expense_count=expense_count,
        inventory_count=inventory_count,
        equipment_count=equipment_count,
        open_task_count=open_task_count,
        recent_farmers=recent_farmers,
        recent_sales=recent_sales,
        recent_payments=recent_payments,
        recent_cooperative_activity=recent_cooperative_activity,
        secondary_cooperatives=secondary_cooperatives,
        primary_cooperatives=primary_cooperatives,
        primary_performance=primary_performance,
        overdue_task_count=overdue_task_count,
        low_stock_count=low_stock_count,
        service_due_count=service_due_count,
        unpaid_membership_count=unpaid_membership_count,
        today=today,

        # Own cooperative totals / workflow
        own_farmer_count=own_farmer_count,
        own_farm_count=own_farm_count,
        own_crop_count=own_crop_count,
        own_harvest_count=own_harvest_count,
        own_member_count=own_member_count,
        own_active_member_count=own_active_member_count,
        own_membership_fee_due=own_membership_fee_due,
        own_sales_value=own_sales_value,
        own_payments_value=own_payments_value,
        own_contributions_value=own_contributions_value,
        own_expenses_value=own_expenses_value,
        own_outstanding_balance=own_outstanding_balance,
        own_cash_position=own_cash_position,
        own_pending_contributions=own_pending_contributions,
        own_pending_expenses=own_pending_expenses,
        own_pending_finance=own_pending_finance,
        own_recent_memberships=own_recent_memberships,
        own_recent_contributions=own_recent_contributions,
        own_recent_expenses=own_recent_expenses,
        own_recent_farmers=own_recent_farmers,
        own_executives=own_executives,
        own_positions_filled=own_positions_filled,
        own_positions_vacant=own_positions_vacant,

        # Phase 6 accountability
        accountability_open_count=accountability_open_count,
        accountability_overdue_count=accountability_overdue_count,
        accountability_awaiting_verification_count=accountability_awaiting_verification_count,
        my_accountability_task_count=my_accountability_task_count,
        my_overdue_accountability_count=my_overdue_accountability_count,
        recent_resolutions=recent_resolutions,
        upcoming_meetings=upcoming_meetings,

        # Admin totals
        admin_user_count=admin_user_count,
        admin_active_access_count=admin_active_access_count,
        admin_inactive_access_count=admin_inactive_access_count,
        admin_cooperative_count=admin_cooperative_count,
        admin_audit_count=admin_audit_count,
        admin_recent_activity=admin_recent_activity,
        admin_backup_count=admin_backup_count,
        admin_database_backend=admin_database_backend,
    )


# =========================================================
# ROUTES - FARMERS
# =========================================================
@app.route("/farmers")
@roles_required(*FARMER_VIEW_ROLES)
def farmers_list():
    """List farmers."""
    search = request.args.get("search", "").strip()
    if search:
        farmers = scoped_model_query(Farmer).filter(or_(
            Farmer.fullname.ilike(f"%{search}%"),
            Farmer.phone.ilike(f"%{search}%"),
            Farmer.email.ilike(f"%{search}%"),
            Farmer.location.ilike(f"%{search}%"),
        )).order_by(Farmer.created_at.desc()).all()
    else:
        farmers = scoped_model_query(Farmer).order_by(
            Farmer.created_at.desc()
        ).all()
    return render_template("farmers.html", farmers=farmers, search=search)


@app.route("/farmers/add", methods=["GET", "POST"])
@roles_required(*FARMER_RECORD_ROLES)
def add_farmer():
    """Add a farmer."""
    if request.method == "POST":
        fullname = request.form.get("fullname", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        location = request.form.get("location", "").strip()
        status = request.form.get("status", "Active").strip()

        if not fullname or not phone or not location:
            return "Name, phone number and location are required.", 400

        cooperative_id = own_cooperative_id()
        if not cooperative_id:
            abort(403)

        new_farmer = Farmer(
            fullname=fullname,
            phone=phone,
            email=email or None,
            location=location,
            status=status,
            cooperative_id=cooperative_id,
        )
        db.session.add(new_farmer)
        db.session.flush()
        add_audit_log("CREATE", "Farmer", new_farmer.id, new_farmer.fullname, cooperative_id=new_farmer.cooperative_id)
        db.session.commit()
        return redirect(url_for("farmers_list"))
    return render_template("farmer_form.html", farmer=None)


@app.route("/farmers/edit/<int:farmer_id>", methods=["GET", "POST"])
@roles_required(*FARMER_RECORD_ROLES)
def edit_farmer(farmer_id):
    """Edit a farmer."""
    farmer = scoped_get_or_404(Farmer, farmer_id)
    require_own_cooperative(farmer.cooperative_id)

    if request.method == "POST":
        farmer.fullname = request.form.get("fullname", "").strip()
        farmer.phone = request.form.get("phone", "").strip()
        farmer.email = request.form.get("email", "").strip() or None
        farmer.location = request.form.get("location", "").strip()
        farmer.status = request.form.get("status", "Active").strip()

        if not farmer.fullname or not farmer.phone or not farmer.location:
            return "Name, phone number and location are required.", 400

        add_audit_log("UPDATE", "Farmer", farmer.id, farmer.fullname, cooperative_id=farmer.cooperative_id)
        db.session.commit()
        return redirect(url_for("farmers_list"))
    return render_template("farmer_form.html", farmer=farmer)


@app.route("/farmers/delete/<int:farmer_id>", methods=["POST"])
@roles_required(*FARMER_RECORD_ROLES)
def delete_farmer(farmer_id):
    """Delete a farmer."""
    farmer = scoped_get_or_404(Farmer, farmer_id)
    require_own_cooperative(farmer.cooperative_id)

    if farmer.memberships:
        return "This farmer cannot be deleted because membership records are linked to the farmer.", 400
    if farmer.contributions:
        return "This farmer cannot be deleted because contribution records are linked to the farmer.", 400
    if farmer.interactions:
        return "This farmer cannot be deleted because interaction records are linked to the farmer.", 400
    if farmer.farms:
        return "This farmer cannot be deleted because farms are linked to the farmer.", 400
    add_audit_log("DELETE", "Farmer", farmer.id, farmer.fullname, cooperative_id=farmer.cooperative_id)
    db.session.delete(farmer)
    db.session.commit()
    return redirect(url_for("farmers_list"))


# =========================================================
# ROUTES - FARMS
# =========================================================
@app.route("/farms")
@roles_required(*AGRICULTURE_VIEW_ROLES)
def farms_list():
    """List farms."""
    search = request.args.get("search", "").strip()
    if search:
        farms = scoped_model_query(Farm).join(Farmer).filter(or_(
            Farm.name.ilike(f"%{search}%"),
            Farm.location.ilike(f"%{search}%"),
            Farm.farming_type.ilike(f"%{search}%"),
            Farmer.fullname.ilike(f"%{search}%"),
        )).order_by(Farm.registration_date.desc()).all()
    else:
        farms = scoped_model_query(Farm).order_by(
            Farm.registration_date.desc()
        ).all()
    return render_template("farms.html", farms=farms, search=search)


@app.route("/farms/add", methods=["GET", "POST"])
@roles_required(*PRIMARY_OPERATION_RECORD_ROLES)
def add_farm():
    """Add a farm."""
    farmers = own_cooperative_query(Farmer).order_by(Farmer.fullname.asc()).all()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        farmer_id = request.form.get("farmer_id", "").strip()
        location = request.form.get("location", "").strip()
        size = request.form.get("size", "").strip()
        farming_type = request.form.get("farming_type", "").strip()
        status = request.form.get("status", "Active").strip()

        if not name or not farmer_id or not location:
            return "Farm name, farmer and location are required.", 400

        try:
            farmer_id_value = int(farmer_id)
            size_value = float(size) if size else None
        except ValueError:
            return "Invalid farmer or farm size.", 400

        if size_value is not None and size_value < 0:
            return "Farm size cannot be negative.", 400

        farmer = db.session.get(Farmer, farmer_id_value)
        if not farmer or farmer.cooperative_id != own_cooperative_id():
            return "Please select a farmer from your own cooperative.", 400

        new_farm = Farm(
            name=name,
            farmer_id=farmer.id,
            location=location,
            size=size_value,
            farming_type=farming_type or None,
            status=status,
            cooperative_id=own_cooperative_id(),
        )
        db.session.add(new_farm)
        db.session.flush()
        add_audit_log("CREATE", "Farm", new_farm.id, new_farm.name, cooperative_id=new_farm.cooperative_id)
        db.session.commit()
        return redirect(url_for("farms_list"))
    return render_template("farm_form.html", farm=None, farmers=farmers)


@app.route("/farms/edit/<int:farm_id>", methods=["GET", "POST"])
@roles_required(*PRIMARY_OPERATION_RECORD_ROLES)
def edit_farm(farm_id):
    """Edit a farm."""
    farm = scoped_get_or_404(Farm, farm_id)
    require_own_cooperative(farm.cooperative_id)
    farmers = own_cooperative_query(Farmer).order_by(Farmer.fullname.asc()).all()

    if request.method == "POST":
        farm.name = request.form.get("name", "").strip()
        farmer_id = request.form.get("farmer_id", "").strip()
        farm.location = request.form.get("location", "").strip()
        size = request.form.get("size", "").strip()
        farm.farming_type = request.form.get("farming_type", "").strip() or None
        farm.status = request.form.get("status", "Active").strip()

        if not farm.name or not farmer_id or not farm.location:
            return "Farm name, farmer and location are required.", 400

        try:
            farmer_id_value = int(farmer_id)
            farm.size = float(size) if size else None
        except ValueError:
            return "Invalid farmer or farm size.", 400

        if farm.size is not None and farm.size < 0:
            return "Farm size cannot be negative.", 400

        farmer = db.session.get(Farmer, farmer_id_value)
        if not farmer or farmer.cooperative_id != own_cooperative_id():
            return "Please select a farmer from your own cooperative.", 400

        farm.farmer_id = farmer.id
        farm.cooperative_id = own_cooperative_id()
        add_audit_log("UPDATE", "Farm", farm.id, farm.name, cooperative_id=farm.cooperative_id)
        db.session.commit()
        return redirect(url_for("farms_list"))

    return render_template("farm_form.html", farm=farm, farmers=farmers)


@app.route("/farms/delete/<int:farm_id>", methods=["POST"])
@roles_required(*PRIMARY_OPERATION_RECORD_ROLES)
def delete_farm(farm_id):
    """Delete a farm."""
    farm = scoped_get_or_404(Farm, farm_id)
    require_own_cooperative(farm.cooperative_id)

    if farm.crops:
        return "This farm cannot be deleted because crops are linked to it.", 400
    add_audit_log("DELETE", "Farm", farm.id, farm.name, cooperative_id=farm.cooperative_id)
    db.session.delete(farm)
    db.session.commit()
    return redirect(url_for("farms_list"))


# =========================================================
# ROUTES - CROPS
# =========================================================
@app.route("/crops")
@roles_required(*AGRICULTURE_VIEW_ROLES)
def crops_list():
    """List crops."""
    search = request.args.get("search", "").strip()
    query = scoped_model_query(Crop).join(Farm).join(Farmer)

    if search:
        query = query.filter(or_(
            Crop.name.ilike(f"%{search}%"),
            Crop.variety.ilike(f"%{search}%"),
            Crop.status.ilike(f"%{search}%"),
            Farm.name.ilike(f"%{search}%"),
            Farmer.fullname.ilike(f"%{search}%")
        ))

    crops = query.order_by(Crop.created_at.desc()).all()
    return render_template("crops.html", crops=crops, search=search)


@app.route("/crops/add", methods=["GET", "POST"])
@roles_required(*PRIMARY_OPERATION_RECORD_ROLES)
def add_crop():
    """Add a crop."""
    farms = own_cooperative_query(Farm).order_by(Farm.name.asc()).all()

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

        if status not in CROP_ALLOWED_STATUSES:
            return "Please select a valid crop status.", 400

        if status in {"Partially Harvested", "Harvested"}:
            return "A new crop cannot be marked harvested before a harvest record exists.", 400

        try:
            farm_id_value = int(farm_id)
            area_planted_value = float(area_planted) if area_planted else None
            planting_date_value = parse_date(planting_date_text)
            expected_harvest_date_value = parse_date(expected_harvest_date_text)
        except ValueError:
            return "Please enter valid crop information.", 400

        if area_planted_value is not None and area_planted_value <= 0:
            return "Area planted must be greater than zero.", 400

        if planting_date_value and expected_harvest_date_value and expected_harvest_date_value < planting_date_value:
            return "Expected harvest date cannot be earlier than the planting date.", 400

        farm = db.session.get(Farm, farm_id_value)
        if not farm or farm.cooperative_id != own_cooperative_id():
            return "Please select a farm from your own cooperative.", 400

        new_crop = Crop(
            name=name,
            farm_id=farm.id,
            variety=variety or None,
            planting_date=planting_date_value,
            expected_harvest_date=expected_harvest_date_value,
            area_planted=area_planted_value,
            status=status,
            notes=notes or None,
            cooperative_id=own_cooperative_id(),
        )
        db.session.add(new_crop)
        db.session.flush()
        add_audit_log("CREATE", "Crop", new_crop.id, new_crop.name, cooperative_id=new_crop.cooperative_id)
        db.session.commit()
        return redirect(url_for("crops_list"))

    return render_template("crop_form.html", crop=None, farms=farms)


@app.route("/crops/edit/<int:crop_id>", methods=["GET", "POST"])
@roles_required(*PRIMARY_OPERATION_RECORD_ROLES)
def edit_crop(crop_id):
    """Edit a crop."""
    crop = scoped_get_or_404(Crop, crop_id)
    require_own_cooperative(crop.cooperative_id)
    farms = own_cooperative_query(Farm).order_by(Farm.name.asc()).all()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        farm_id = request.form.get("farm_id", "").strip()
        variety = request.form.get("variety", "").strip()
        planting_date_text = request.form.get("planting_date", "").strip()
        expected_harvest_date_text = request.form.get("expected_harvest_date", "").strip()
        area_planted = request.form.get("area_planted", "").strip()
        requested_status = request.form.get("status", crop.status or "Planted").strip()
        notes = request.form.get("notes", "").strip()

        if not name or not farm_id:
            return "Crop name and farm are required.", 400

        if requested_status not in CROP_ALLOWED_STATUSES:
            return "Please select a valid crop status.", 400

        try:
            farm_id_value = int(farm_id)
            area_planted_value = float(area_planted) if area_planted else None
            planting_date_value = parse_date(planting_date_text)
            expected_harvest_date_value = parse_date(expected_harvest_date_text)
        except ValueError:
            return "Please enter valid crop information.", 400

        if area_planted_value is not None and area_planted_value <= 0:
            return "Area planted must be greater than zero.", 400

        if planting_date_value and expected_harvest_date_value and expected_harvest_date_value < planting_date_value:
            return "Expected harvest date cannot be earlier than the planting date.", 400

        farm = db.session.get(Farm, farm_id_value)
        if not farm or farm.cooperative_id != own_cooperative_id():
            return "Please select a farm from your own cooperative.", 400

        harvest_count = crop_harvest_count(crop.id)
        if harvest_count == 0 and requested_status in {"Partially Harvested", "Harvested"}:
            return "This crop has no harvest records yet, so it cannot be marked harvested.", 400

        if harvest_count > 0 and requested_status in {"Planted", "Growing", "Ready for Harvest"}:
            return "This crop already has harvest records. Use Partially Harvested, Harvested, or Failed.", 400

        crop.name = name
        crop.farm_id = farm.id
        crop.cooperative_id = own_cooperative_id()
        crop.variety = variety or None
        crop.planting_date = planting_date_value
        crop.expected_harvest_date = expected_harvest_date_value
        crop.area_planted = area_planted_value
        crop.status = requested_status
        crop.notes = notes or None
        add_audit_log("UPDATE", "Crop", crop.id, crop.name, cooperative_id=crop.cooperative_id)
        db.session.commit()
        return redirect(url_for("crops_list"))

    return render_template("crop_form.html", crop=crop, farms=farms)


@app.route("/crops/delete/<int:crop_id>", methods=["POST"])
@roles_required(*PRIMARY_OPERATION_RECORD_ROLES)
def delete_crop(crop_id):
    """Delete a crop."""
    crop = scoped_get_or_404(Crop, crop_id)
    require_own_cooperative(crop.cooperative_id)

    if crop.harvests:
        return "This crop cannot be deleted because harvests are linked to it.", 400

    add_audit_log("DELETE", "Crop", crop.id, crop.name, cooperative_id=crop.cooperative_id)
    db.session.delete(crop)
    db.session.commit()
    return redirect(url_for("crops_list"))


# =========================================================
# ROUTES - HARVESTS
# =========================================================
@app.route("/harvests")
@roles_required(*AGRICULTURE_VIEW_ROLES)
def harvests_list():
    """List harvests."""
    search = request.args.get("search", "").strip()
    query = scoped_model_query(Harvest).join(Crop).join(Farm).join(Farmer)

    if search:
        query = query.filter(or_(
            Crop.name.ilike(f"%{search}%"),
            Farm.name.ilike(f"%{search}%"),
            Farmer.fullname.ilike(f"%{search}%"),
            Harvest.quality_grade.ilike(f"%{search}%"),
            Harvest.storage_location.ilike(f"%{search}%"),
            Harvest.status.ilike(f"%{search}%")
        ))

    harvests = query.order_by(Harvest.created_at.desc()).all()
    return render_optional_template("harvests.html", "Harvests", harvests=harvests, search=search)


@app.route("/harvests/add", methods=["GET", "POST"])
@roles_required(*PRIMARY_OPERATION_RECORD_ROLES)
def add_harvest():
    """Add a harvest."""
    crops = own_cooperative_query(Crop).order_by(Crop.name.asc()).all()

    if request.method == "POST":
        crop_id = request.form.get("crop_id", "").strip()
        harvest_date_text = request.form.get("harvest_date", "").strip()
        quantity = request.form.get("quantity", "").strip()
        unit = request.form.get("unit", "kg").strip() or "kg"
        quality_grade = request.form.get("quality_grade", "").strip()
        storage_location = request.form.get("storage_location", "").strip()
        status = request.form.get("status", "Available").strip()
        notes = request.form.get("notes", "").strip()
        final_harvest = request.form.get("final_harvest") == "1"

        if not crop_id or not harvest_date_text or not quantity:
            return "Crop, harvest date and quantity are required.", 400

        if unit not in HARVEST_ALLOWED_UNITS:
            return "Please select a valid harvest unit.", 400

        if status not in HARVEST_ALLOWED_STATUSES:
            return "Please select a valid harvest status.", 400

        try:
            crop_id_value = int(crop_id)
            harvest_date_value = parse_date(harvest_date_text)
            quantity_value = float(quantity)
        except ValueError:
            return "Please enter valid harvest information.", 400

        if quantity_value <= 0:
            return "Harvest quantity must be greater than zero.", 400

        crop = db.session.get(Crop, crop_id_value)
        if not crop or crop.cooperative_id != own_cooperative_id():
            return "Please select a crop from your own cooperative.", 400

        if crop.status == "Failed":
            return "A failed crop cannot receive a harvest record. Update the crop status first if harvesting is possible.", 400

        if crop.planting_date and harvest_date_value < crop.planting_date:
            return "Harvest date cannot be earlier than the crop planting date.", 400

        new_harvest = Harvest(
            crop_id=crop.id,
            harvest_date=harvest_date_value,
            quantity=quantity_value,
            unit=unit,
            quality_grade=quality_grade or None,
            storage_location=storage_location or None,
            status=status,
            notes=notes or None,
            cooperative_id=own_cooperative_id(),
        )
        db.session.add(new_harvest)
        db.session.flush()

        crop.status = "Harvested" if final_harvest else "Partially Harvested"
        add_audit_log("CREATE", "Harvest", new_harvest.id, f"{crop.name} - {quantity_value:g} {unit}",
                      cooperative_id=new_harvest.cooperative_id)
        db.session.commit()
        return redirect(url_for("harvests_list"))

    return render_optional_template("harvest_form.html", "Add Harvest", harvest=None, crops=crops)


@app.route("/harvests/edit/<int:harvest_id>", methods=["GET", "POST"])
@roles_required(*PRIMARY_OPERATION_RECORD_ROLES)
def edit_harvest(harvest_id):
    """Edit a harvest."""
    harvest = scoped_get_or_404(Harvest, harvest_id)
    require_own_cooperative(harvest.cooperative_id)
    crops = own_cooperative_query(Crop).order_by(Crop.name.asc()).all()

    if request.method == "POST":
        crop_id = request.form.get("crop_id", "").strip()
        harvest_date_text = request.form.get("harvest_date", "").strip()
        quantity = request.form.get("quantity", "").strip()
        unit = request.form.get("unit", "kg").strip() or "kg"
        quality_grade = request.form.get("quality_grade", "").strip()
        storage_location = request.form.get("storage_location", "").strip()
        status = request.form.get("status", "Available").strip()
        notes = request.form.get("notes", "").strip()
        final_harvest = request.form.get("final_harvest") == "1"

        if not crop_id or not harvest_date_text or not quantity:
            return "Crop, harvest date and quantity are required.", 400

        if unit not in HARVEST_ALLOWED_UNITS:
            return "Please select a valid harvest unit.", 400

        if status not in HARVEST_ALLOWED_STATUSES:
            return "Please select a valid harvest status.", 400

        try:
            crop_id_value = int(crop_id)
            harvest_date_value = parse_date(harvest_date_text)
            quantity_value = float(quantity)
        except ValueError:
            return "Please enter valid harvest information.", 400

        if quantity_value <= 0:
            return "Harvest quantity must be greater than zero.", 400

        crop = db.session.get(Crop, crop_id_value)
        if not crop or crop.cooperative_id != own_cooperative_id():
            return "Please select a crop from your own cooperative.", 400

        if crop.status == "Failed":
            return "A failed crop cannot receive a harvest record. Update the crop status first if harvesting is possible.", 400

        if crop.planting_date and harvest_date_value < crop.planting_date:
            return "Harvest date cannot be earlier than the crop planting date.", 400

        sold_quantity = harvest_sold_quantity(harvest)
        if quantity_value + 1e-9 < sold_quantity:
            return f"Harvest quantity cannot be reduced below the {sold_quantity:.2f} {harvest.unit} already sold.", 400

        if sold_quantity > 0 and unit != harvest.unit:
            return "Harvest unit cannot be changed after sales have been recorded.", 400

        if crop.id != harvest.crop_id and harvest.sales:
            return "This harvest cannot be moved to another crop because sales are linked to it.", 400

        sale_dates = [sale.sale_date for sale in harvest.sales if sale.status != "Cancelled" and sale.sale_date]
        if sale_dates and harvest_date_value > min(sale_dates):
            return "Harvest date cannot be later than a sale already recorded for this harvest.", 400

        old_crop = harvest.crop
        old_crop_id = harvest.crop_id

        harvest.crop_id = crop.id
        harvest.cooperative_id = own_cooperative_id()
        harvest.harvest_date = harvest_date_value
        harvest.quantity = quantity_value
        harvest.unit = unit
        harvest.quality_grade = quality_grade or None
        harvest.storage_location = storage_location or None
        harvest.status = status
        harvest.notes = notes or None
        db.session.flush()

        crop.status = "Harvested" if final_harvest else "Partially Harvested"
        if old_crop_id != crop.id:
            sync_crop_status_after_harvest_change(old_crop)

        add_audit_log("UPDATE", "Harvest", harvest.id, f"{crop.name} - {quantity_value:g} {unit}",
                      cooperative_id=harvest.cooperative_id)
        db.session.commit()
        return redirect(url_for("harvests_list"))

    return render_optional_template("harvest_form.html", "Edit Harvest", harvest=harvest, crops=crops)


@app.route("/harvests/delete/<int:harvest_id>", methods=["POST"])
@roles_required(*PRIMARY_OPERATION_RECORD_ROLES)
def delete_harvest(harvest_id):
    """Delete a harvest."""
    harvest = scoped_get_or_404(Harvest, harvest_id)
    require_own_cooperative(harvest.cooperative_id)

    if harvest.sales:
        return "This harvest cannot be deleted because sales are linked to it.", 400

    crop = harvest.crop
    harvest_description = f"{crop.name} - {float(harvest.quantity or 0):g} {harvest.unit}"
    cooperative_id = harvest.cooperative_id
    db.session.delete(harvest)
    db.session.flush()
    sync_crop_status_after_harvest_change(crop)
    add_audit_log("DELETE", "Harvest", harvest_id, harvest_description, cooperative_id=cooperative_id)
    db.session.commit()
    return redirect(url_for("harvests_list"))


# =========================================================
# ROUTES - SALES
# =========================================================
@app.route("/sales")
@roles_required(*BUSINESS_VIEW_ROLES)
def sales_list():
    """List sales."""
    search = request.args.get("search", "").strip()
    query = scoped_model_query(Sale).join(Harvest).join(Crop).join(Farm)

    if search:
        query = query.filter(or_(
            Sale.buyer_name.ilike(f"%{search}%"),
            Sale.buyer_phone.ilike(f"%{search}%"),
            Sale.status.ilike(f"%{search}%"),
            Crop.name.ilike(f"%{search}%"),
            Farm.name.ilike(f"%{search}%")
        ))

    sales = query.order_by(Sale.created_at.desc()).all()
    return render_optional_template("sales.html", "Sales", sales=sales, search=search)


@app.route("/sales/add", methods=["GET", "POST"])
@roles_required(*BUSINESS_RECORD_ROLES)
def add_sale():
    """Add a sale."""
    harvests = own_cooperative_query(Harvest).order_by(Harvest.harvest_date.desc()).all()

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

        harvest = db.session.get(Harvest, harvest_id_value)
        if not harvest or harvest.cooperative_id != own_cooperative_id():
            return "Please select a harvest from your own cooperative.", 400

        if quantity_value <= 0:
            return "Sale quantity must be greater than zero.", 400

        if price_per_unit_value <= 0:
            return "Price per unit must be greater than zero.", 400

        if not sale_date_value:
            return "A valid sale date is required.", 400

        if sale_date_value < harvest.harvest_date:
            return "Sale date cannot be earlier than the harvest date.", 400

        sale_unit = (unit or harvest.unit or "kg").strip()
        harvest_unit = (harvest.unit or "kg").strip()
        if sale_unit.lower() != harvest_unit.lower():
            return f"Sale unit must match the harvest unit ({harvest_unit}).", 400

        available_quantity = harvest_available_quantity(harvest)
        if quantity_value > available_quantity + 1e-9:
            return (
                f"Sale quantity exceeds the available harvest. "
                f"Available: {available_quantity:.2f} {harvest_unit}.",
                400,
            )

        total_amount_value = quantity_value * price_per_unit_value
        new_sale = Sale(
            harvest_id=harvest.id,
            buyer_name=buyer_name,
            buyer_phone=buyer_phone or None,
            quantity=quantity_value,
            unit=sale_unit,
            price_per_unit=price_per_unit_value,
            total_amount=total_amount_value,
            sale_date=sale_date_value,
            status=status,
            notes=notes or None,
            cooperative_id=own_cooperative_id(),
        )
        db.session.add(new_sale)
        db.session.flush()
        add_audit_log("CREATE", "Sale", new_sale.id, new_sale.buyer_name, cooperative_id=new_sale.cooperative_id)
        db.session.commit()
        return redirect(url_for("sales_list"))

    return render_optional_template("sale_form.html", "Add Sale", sale=None, harvests=harvests)


@app.route("/sales/edit/<int:sale_id>", methods=["GET", "POST"])
@roles_required(*BUSINESS_RECORD_ROLES)
def edit_sale(sale_id):
    """Edit a sale."""
    sale = scoped_get_or_404(Sale, sale_id)
    require_own_cooperative(sale.cooperative_id)
    harvests = own_cooperative_query(Harvest).order_by(Harvest.harvest_date.desc()).all()

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

        harvest = db.session.get(Harvest, harvest_id_value)
        if not harvest or harvest.cooperative_id != own_cooperative_id():
            return "Please select a harvest from your own cooperative.", 400

        if quantity_value <= 0:
            return "Sale quantity must be greater than zero.", 400

        if price_per_unit_value <= 0:
            return "Price per unit must be greater than zero.", 400

        if not sale_date_value:
            return "A valid sale date is required.", 400

        if sale_date_value < harvest.harvest_date:
            return "Sale date cannot be earlier than the harvest date.", 400

        sale_unit = (unit or harvest.unit or "kg").strip()
        harvest_unit = (harvest.unit or "kg").strip()
        if sale_unit.lower() != harvest_unit.lower():
            return f"Sale unit must match the harvest unit ({harvest_unit}).", 400

        available_quantity = harvest_available_quantity(
            harvest,
            exclude_sale_id=sale.id,
        )
        if quantity_value > available_quantity + 1e-9:
            return (
                f"Sale quantity exceeds the available harvest. "
                f"Available: {available_quantity:.2f} {harvest_unit}.",
                400,
            )

        new_total_amount = quantity_value * price_per_unit_value
        recorded_payments = sale_recorded_payment_amount(sale)
        if recorded_payments > new_total_amount + 1e-9:
            return (
                f"Sale total cannot be reduced below payments already recorded. "
                f"Recorded payments: R {recorded_payments:.2f}.",
                400,
            )

        payment_dates = [p.payment_date for p in sale.payments if p.status != "Reversed" and p.payment_date]
        if payment_dates and sale_date_value > min(payment_dates):
            return "Sale date cannot be later than an existing payment date.", 400

        if status == "Cancelled" and sale_paid_amount(sale) > 1e-9:
            return "Reverse received payments before cancelling this sale.", 400

        sale.harvest_id = harvest.id
        sale.cooperative_id = own_cooperative_id()
        sale.buyer_name = buyer_name
        sale.buyer_phone = buyer_phone or None
        sale.quantity = quantity_value
        sale.unit = sale_unit
        sale.price_per_unit = price_per_unit_value
        sale.total_amount = new_total_amount
        sale.sale_date = sale_date_value
        sale.status = status
        sale.notes = notes or None
        add_audit_log("UPDATE", "Sale", sale.id, sale.buyer_name, cooperative_id=sale.cooperative_id)
        db.session.commit()
        return redirect(url_for("sales_list"))

    return render_optional_template("sale_form.html", "Edit Sale", sale=sale, harvests=harvests)


@app.route("/sales/delete/<int:sale_id>", methods=["POST"])
@roles_required(*BUSINESS_RECORD_ROLES)
def delete_sale(sale_id):
    """Delete a sale."""
    sale = scoped_get_or_404(Sale, sale_id)
    require_own_cooperative(sale.cooperative_id)

    if sale.payments:
        return "This sale cannot be deleted because payments are linked to it.", 400
    add_audit_log("DELETE", "Sale", sale.id, sale.buyer_name, cooperative_id=sale.cooperative_id)
    db.session.delete(sale)
    db.session.commit()
    return redirect(url_for("sales_list"))


# =========================================================
# ROUTES - PAYMENTS
# =========================================================
@app.route("/payments")
@roles_required(*BUSINESS_VIEW_ROLES)
def payments_list():
    """List payments."""
    search = request.args.get("search", "").strip()
    query = scoped_model_query(Payment).join(Sale)

    if search:
        query = query.filter(or_(
            Sale.buyer_name.ilike(f"%{search}%"),
            Payment.method.ilike(f"%{search}%"),
            Payment.reference.ilike(f"%{search}%"),
            Payment.status.ilike(f"%{search}%")
        ))

    payments = query.order_by(Payment.created_at.desc()).all()
    return render_optional_template("payments.html", "Payments", payments=payments, search=search)


@app.route("/payments/add", methods=["GET", "POST"])
@roles_required(*BUSINESS_RECORD_ROLES)
def add_payment():
    """Add a payment."""
    sales = own_cooperative_query(Sale).order_by(Sale.sale_date.desc()).all()

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

        sale = db.session.get(Sale, sale_id_value)
        if not sale or sale.cooperative_id != own_cooperative_id():
            return "Please select a sale from your own cooperative.", 400

        if sale.status == "Cancelled":
            return "Payments cannot be recorded against a cancelled sale.", 400

        if amount_value <= 0:
            return "Payment amount must be greater than zero.", 400

        if not payment_date_value:
            return "A valid payment date is required.", 400

        if payment_date_value < sale.sale_date:
            return "Payment date cannot be earlier than the sale date.", 400

        if status not in PAYMENT_ALLOWED_STATUSES:
            return "Invalid payment status.", 400

        already_recorded = sale_recorded_payment_amount(sale)
        if status != "Reversed" and already_recorded + amount_value > float(sale.total_amount or 0) + 1e-9:
            remaining = max(float(sale.total_amount or 0) - already_recorded, 0.0)
            return (
                f"Payment exceeds the remaining sale balance. "
                f"Maximum additional payment: R {remaining:.2f}.",
                400,
            )

        new_payment = Payment(
            sale_id=sale.id,
            amount=amount_value,
            payment_date=payment_date_value,
            method=method or None,
            reference=reference or None,
            status=status,
            notes=notes or None,
            cooperative_id=own_cooperative_id(),
        )
        db.session.add(new_payment)
        db.session.flush()
        add_audit_log("CREATE", "Payment", new_payment.id, f'R{float(new_payment.amount or 0):.2f}', cooperative_id=new_payment.cooperative_id)
        db.session.commit()
        return redirect(url_for("payments_list"))

    return render_optional_template(
        "payment_form.html",
        "Add Payment",
        payment=None,
        sales=sales,
    )


@app.route("/payments/edit/<int:payment_id>", methods=["GET", "POST"])
@roles_required(*BUSINESS_RECORD_ROLES)
def edit_payment(payment_id):
    """Edit a payment."""
    payment = scoped_get_or_404(Payment, payment_id)
    require_own_cooperative(payment.cooperative_id)
    sales = own_cooperative_query(Sale).order_by(Sale.sale_date.desc()).all()

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

        sale = db.session.get(Sale, sale_id_value)
        if not sale or sale.cooperative_id != own_cooperative_id():
            return "Please select a sale from your own cooperative.", 400

        if sale.status == "Cancelled":
            return "Payments cannot be assigned to a cancelled sale.", 400

        if amount_value <= 0:
            return "Payment amount must be greater than zero.", 400

        if not payment_date_value:
            return "A valid payment date is required.", 400

        if payment_date_value < sale.sale_date:
            return "Payment date cannot be earlier than the sale date.", 400

        if status not in PAYMENT_ALLOWED_STATUSES:
            return "Invalid payment status.", 400

        already_recorded = sale_recorded_payment_amount(
            sale,
            exclude_payment_id=payment.id,
        )
        if status != "Reversed" and already_recorded + amount_value > float(sale.total_amount or 0) + 1e-9:
            remaining = max(float(sale.total_amount or 0) - already_recorded, 0.0)
            return (
                f"Payment exceeds the remaining sale balance. "
                f"Maximum payment for this record: R {remaining:.2f}.",
                400,
            )

        payment.sale_id = sale.id
        payment.cooperative_id = own_cooperative_id()
        payment.amount = amount_value
        payment.payment_date = payment_date_value
        payment.method = method or None
        payment.reference = reference or None
        payment.status = status
        payment.notes = notes or None
        add_audit_log("UPDATE", "Payment", payment.id, f"R{float(payment.amount or 0):.2f}", cooperative_id=payment.cooperative_id)
        db.session.commit()
        return redirect(url_for("payments_list"))

    return render_optional_template(
        "payment_form.html",
        "Edit Payment",
        payment=payment,
        sales=sales,
    )


@app.route("/payments/delete/<int:payment_id>", methods=["POST"])
@roles_required(*BUSINESS_RECORD_ROLES)
def delete_payment(payment_id):
    """Delete a payment."""
    payment = scoped_get_or_404(Payment, payment_id)
    require_own_cooperative(payment.cooperative_id)

    if payment.status not in {"Pending", "Reversed"}:
        return "Received financial records cannot be deleted. Reverse the payment instead.", 400

    add_audit_log("DELETE", "Payment", payment.id, f"R{float(payment.amount or 0):.2f}", cooperative_id=payment.cooperative_id)
    db.session.delete(payment)
    db.session.commit()
    return redirect(url_for("payments_list"))


# =========================================================
# ROUTES - CUSTOMERS
# =========================================================
@app.route("/customers")
@roles_required(*CUSTOMER_VIEW_ROLES)
def customers_list():
    """List customers."""
    search = request.args.get("search", "").strip()
    query = scoped_model_query(Customer)

    if search:
        query = query.filter(or_(
            Customer.name.ilike(f"%{search}%"),
            Customer.contact_person.ilike(f"%{search}%"),
            Customer.phone.ilike(f"%{search}%"),
            Customer.email.ilike(f"%{search}%"),
            Customer.customer_type.ilike(f"%{search}%")
        ))

    customers = query.order_by(Customer.name.asc()).all()
    return render_optional_template("customers.html", "Customers / Buyers", customers=customers, search=search)


@app.route("/customers/add", methods=["GET", "POST"])
@roles_required(*CUSTOMER_RECORD_ROLES)
def add_customer():
    """Add a customer."""
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            return "Customer name is required.", 400

        cooperative_id = own_cooperative_id()
        if not cooperative_id:
            abort(403)

        customer = Customer(
            cooperative_id=cooperative_id,
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
        return redirect(url_for("customers_list"))

    return render_optional_template("customer_form.html", "Add Customer", customer=None)


@app.route("/customers/edit/<int:customer_id>", methods=["GET", "POST"])
@roles_required(*CUSTOMER_RECORD_ROLES)
def edit_customer(customer_id):
    """Edit a customer."""
    customer = scoped_get_or_404(Customer, customer_id)
    require_own_cooperative(customer.cooperative_id)

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
        return redirect(url_for("customers_list"))

    return render_optional_template("customer_form.html", "Edit Customer", customer=customer)


@app.route("/customers/delete/<int:customer_id>", methods=["POST"])
@roles_required(*CUSTOMER_RECORD_ROLES)
def delete_customer(customer_id):
    """Delete a customer."""
    customer = scoped_get_or_404(Customer, customer_id)
    require_own_cooperative(customer.cooperative_id)
    add_audit_log("DELETE", "Customer", customer.id, customer.name, cooperative_id=customer.cooperative_id)
    db.session.delete(customer)
    db.session.commit()
    return redirect(url_for("customers_list"))


# =========================================================
# ROUTES - SUPPLIERS
# =========================================================
@app.route("/suppliers")
@roles_required(*SUPPLIER_VIEW_ROLES)
def suppliers_list():
    """List suppliers."""
    search = request.args.get("search", "").strip()
    query = scoped_model_query(Supplier)

    if search:
        query = query.filter(or_(
            Supplier.name.ilike(f"%{search}%"),
            Supplier.contact_person.ilike(f"%{search}%"),
            Supplier.phone.ilike(f"%{search}%"),
            Supplier.email.ilike(f"%{search}%"),
            Supplier.supplier_type.ilike(f"%{search}%")
        ))

    suppliers = query.order_by(Supplier.name.asc()).all()
    return render_optional_template("suppliers.html", "Suppliers", suppliers=suppliers, search=search)


@app.route("/suppliers/add", methods=["GET", "POST"])
@roles_required(*SUPPLIER_RECORD_ROLES)
def add_supplier():
    """Add a supplier."""
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            return "Supplier name is required.", 400

        cooperative_id = own_cooperative_id()
        if not cooperative_id:
            abort(403)

        supplier = Supplier(
            cooperative_id=cooperative_id,
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
        return redirect(url_for("suppliers_list"))

    return render_optional_template("supplier_form.html", "Add Supplier", supplier=None)


@app.route("/suppliers/edit/<int:supplier_id>", methods=["GET", "POST"])
@roles_required(*SUPPLIER_RECORD_ROLES)
def edit_supplier(supplier_id):
    """Edit a supplier."""
    supplier = scoped_get_or_404(Supplier, supplier_id)
    require_own_cooperative(supplier.cooperative_id)

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
        return redirect(url_for("suppliers_list"))

    return render_optional_template("supplier_form.html", "Edit Supplier", supplier=supplier)


@app.route("/suppliers/delete/<int:supplier_id>", methods=["POST"])
@roles_required(*SUPPLIER_RECORD_ROLES)
def delete_supplier(supplier_id):
    """Delete a supplier."""
    supplier = scoped_get_or_404(Supplier, supplier_id)
    require_own_cooperative(supplier.cooperative_id)
    if supplier.expenses or supplier.inventory_items:
        return "This supplier cannot be deleted because linked records exist.", 400
    add_audit_log("DELETE", "Supplier", supplier.id, supplier.name)
    db.session.delete(supplier)
    db.session.commit()
    return redirect(url_for("suppliers_list"))


# =========================================================
# ROUTES - EXPENSES
# =========================================================
@app.route("/expenses")
@roles_required(*FINANCE_VIEW_ROLES)
def expenses_list():
    """List expenses within the user's visibility scope."""
    search = request.args.get("search", "").strip()
    query = scoped_model_query(Expense).outerjoin(Farm).outerjoin(Supplier)

    if search:
        query = query.filter(or_(
            Expense.category.ilike(f"%{search}%"),
            Expense.description.ilike(f"%{search}%"),
            Expense.reference.ilike(f"%{search}%"),
            Expense.status.ilike(f"%{search}%"),
            Farm.name.ilike(f"%{search}%"),
            Supplier.name.ilike(f"%{search}%")
        ))

    expenses = query.order_by(Expense.expense_date.desc()).all()
    return render_optional_template(
        "expenses.html",
        "Expenses",
        expenses=expenses,
        search=search,
    )


@app.route("/expenses/add", methods=["GET", "POST"])
@roles_required(*FINANCE_RECORD_ROLES)
def add_expense():
    """Treasurer records an expense; Chairperson confirms it."""
    access = current_access()
    farms = own_cooperative_query(Farm).order_by(Farm.name.asc()).all()
    suppliers = own_cooperative_query(Supplier).order_by(Supplier.name.asc()).all()

    if request.method == "POST":
        category = request.form.get("category", "").strip()
        description = request.form.get("description", "").strip()
        amount = parse_float(request.form.get("amount"))

        try:
            expense_date = parse_date(request.form.get("expense_date"))
        except ValueError:
            return "A valid expense date is required.", 400

        if not category or not description:
            return "Category and description are required.", 400
        if amount is None or amount <= 0:
            return "Expense amount must be greater than zero.", 400
        if not expense_date:
            return "A valid expense date is required.", 400

        farm_id_value = parse_int(request.form.get("farm_id"))
        supplier_id_value = parse_int(request.form.get("supplier_id"))
        farm_record = db.session.get(Farm, farm_id_value) if farm_id_value else None
        supplier_record = db.session.get(Supplier, supplier_id_value) if supplier_id_value else None

        if farm_id_value and not farm_record:
            return "Selected farm does not exist.", 400
        if supplier_id_value and not supplier_record:
            return "Selected supplier does not exist.", 400
        if farm_record and farm_record.cooperative_id != access.cooperative_id:
            abort(403)
        if supplier_record and supplier_record.cooperative_id != access.cooperative_id:
            abort(403)

        expense = Expense(
            cooperative_id=access.cooperative_id,
            farm_id=farm_record.id if farm_record else None,
            supplier_id=supplier_record.id if supplier_record else None,
            category=category,
            description=description,
            amount=amount,
            expense_date=expense_date,
            payment_method=request.form.get("payment_method", "").strip() or None,
            reference=request.form.get("reference", "").strip() or None,
            status="Pending Confirmation",
            notes=request.form.get("notes", "").strip() or None,
        )
        db.session.add(expense)
        db.session.flush()
        add_audit_log(
            "FINANCE_RECORDED",
            "Expense",
            expense.id,
            f"{category} - R{amount:.2f} - pending Chairperson confirmation",
            cooperative_id=expense.cooperative_id,
        )
        db.session.commit()
        return redirect(url_for("expenses_list"))

    return render_optional_template(
        "expense_form.html",
        "Add Expense",
        expense=None,
        farms=farms,
        suppliers=suppliers,
    )


@app.route("/expenses/edit/<int:expense_id>", methods=["GET", "POST"])
@roles_required(*FINANCE_RECORD_ROLES)
def edit_expense(expense_id):
    """Treasurer may correct an unconfirmed/rejected expense and resubmit it."""
    expense = scoped_get_or_404(Expense, expense_id)
    access = require_own_cooperative(expense.cooperative_id)

    if expense.status not in {"Pending Confirmation", "Rejected"}:
        return "Confirmed financial records cannot be edited.", 400

    farms = own_cooperative_query(Farm).order_by(Farm.name.asc()).all()
    suppliers = own_cooperative_query(Supplier).order_by(Supplier.name.asc()).all()

    if request.method == "POST":
        category = request.form.get("category", "").strip()
        description = request.form.get("description", "").strip()
        amount = parse_float(request.form.get("amount"))

        try:
            expense_date = parse_date(request.form.get("expense_date"))
        except ValueError:
            return "A valid expense date is required.", 400

        if not category or not description:
            return "Category and description are required.", 400
        if amount is None or amount <= 0:
            return "Expense amount must be greater than zero.", 400
        if not expense_date:
            return "A valid expense date is required.", 400

        farm_id_value = parse_int(request.form.get("farm_id"))
        supplier_id_value = parse_int(request.form.get("supplier_id"))
        farm_record = db.session.get(Farm, farm_id_value) if farm_id_value else None
        supplier_record = db.session.get(Supplier, supplier_id_value) if supplier_id_value else None

        if farm_id_value and not farm_record:
            return "Selected farm does not exist.", 400
        if supplier_id_value and not supplier_record:
            return "Selected supplier does not exist.", 400
        if farm_record and farm_record.cooperative_id != access.cooperative_id:
            abort(403)
        if supplier_record and supplier_record.cooperative_id != access.cooperative_id:
            abort(403)

        expense.farm_id = farm_record.id if farm_record else None
        expense.supplier_id = supplier_record.id if supplier_record else None
        expense.category = category
        expense.description = description
        expense.amount = amount
        expense.expense_date = expense_date
        expense.payment_method = request.form.get("payment_method", "").strip() or None
        expense.reference = request.form.get("reference", "").strip() or None
        expense.status = "Pending Confirmation"
        expense.notes = request.form.get("notes", "").strip() or None
        add_audit_log(
            "FINANCE_RESUBMITTED",
            "Expense",
            expense.id,
            f"{expense.description} - R{float(expense.amount or 0):.2f}",
            cooperative_id=expense.cooperative_id,
        )
        db.session.commit()
        return redirect(url_for("expenses_list"))

    return render_optional_template(
        "expense_form.html",
        "Edit Expense",
        expense=expense,
        farms=farms,
        suppliers=suppliers,
    )


@app.route("/expenses/<int:expense_id>/decision", methods=["POST"])
@roles_required(*FINANCE_APPROVAL_ROLES)
def decide_expense(expense_id):
    """Chairperson confirms or rejects a Treasurer-recorded expense."""
    expense = scoped_get_or_404(Expense, expense_id)
    require_own_cooperative(expense.cooperative_id)

    if expense.status != "Pending Confirmation":
        return "Only expenses awaiting confirmation can be approved or rejected.", 400

    decision = request.form.get("decision", "").strip().lower()
    if decision == "approve":
        expense.status = "Confirmed"
        action = "FINANCE_CONFIRMED"
        details = f"Expense R{float(expense.amount or 0):.2f} confirmed by Chairperson"
    elif decision == "reject":
        expense.status = "Rejected"
        action = "FINANCE_REJECTED"
        details = f"Expense R{float(expense.amount or 0):.2f} rejected by Chairperson"
    else:
        return "Please choose approve or reject.", 400

    add_audit_log(
        action,
        "Expense",
        expense.id,
        details,
        cooperative_id=expense.cooperative_id,
    )
    db.session.commit()
    return redirect(url_for("expenses_list"))


@app.route("/expenses/delete/<int:expense_id>", methods=["POST"])
@roles_required(*FINANCE_RECORD_ROLES)
def delete_expense(expense_id):
    """Treasurer may delete only an unconfirmed/rejected mistaken expense."""
    expense = scoped_get_or_404(Expense, expense_id)
    require_own_cooperative(expense.cooperative_id)

    if expense.status not in {"Pending Confirmation", "Rejected"}:
        return "Confirmed financial records cannot be deleted.", 400

    add_audit_log(
        "DELETE",
        "Expense",
        expense.id,
        expense.description,
        cooperative_id=expense.cooperative_id,
    )
    db.session.delete(expense)
    db.session.commit()
    return redirect(url_for("expenses_list"))


# =========================================================
# ROUTES - INVENTORY
# =========================================================
@app.route("/inventory")
@roles_required(*OPERATIONS_VIEW_ROLES)
def inventory_list():
    """List inventory items."""
    search = request.args.get("search", "").strip()
    query = scoped_model_query(InventoryItem).outerjoin(Supplier)

    if search:
        query = query.filter(or_(
            InventoryItem.name.ilike(f"%{search}%"),
            InventoryItem.category.ilike(f"%{search}%"),
            InventoryItem.storage_location.ilike(f"%{search}%"),
            Supplier.name.ilike(f"%{search}%")
        ))

    items = query.order_by(InventoryItem.name.asc()).all()
    return render_optional_template("inventory.html", "Inventory", items=items, search=search)


@app.route("/inventory/add", methods=["GET", "POST"])
@roles_required(*OPERATIONS_RECORD_ROLES)
def add_inventory_item():
    """Add an inventory item."""
    suppliers = scoped_model_query(Supplier).order_by(Supplier.name.asc()).all()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            return "Inventory item name is required.", 400

        cooperative_id = own_cooperative_id()
        if not cooperative_id:
            abort(403)

        supplier_id_value = parse_int(request.form.get("supplier_id"))
        supplier_record = scoped_get(Supplier, supplier_id_value) if supplier_id_value else None
        if supplier_id_value and (not supplier_record or supplier_record.cooperative_id != cooperative_id):
            return "Please select a supplier from your own cooperative.", 400

        quantity_on_hand = parse_float(request.form.get("quantity_on_hand"), 0)
        reorder_level = parse_float(request.form.get("reorder_level"), 0)
        unit_cost = parse_float(request.form.get("unit_cost"), 0)
        if quantity_on_hand is None or reorder_level is None or unit_cost is None:
            return "Inventory quantities and unit cost must be valid numbers.", 400
        if quantity_on_hand < 0 or reorder_level < 0 or unit_cost < 0:
            return "Inventory quantities and unit cost cannot be negative.", 400

        unit = request.form.get("unit", "units").strip() or "units"
        item = InventoryItem(
            cooperative_id=cooperative_id,
            name=name,
            category=request.form.get("category", "").strip() or None,
            unit=unit,
            quantity_on_hand=quantity_on_hand,
            reorder_level=reorder_level,
            unit_cost=unit_cost,
            storage_location=request.form.get("storage_location", "").strip() or None,
            supplier_id=supplier_id_value,
            status=request.form.get("status", "Active").strip(),
            notes=request.form.get("notes", "").strip() or None,
        )
        db.session.add(item)
        db.session.flush()
        add_audit_log("CREATE", "InventoryItem", item.id, item.name, cooperative_id=item.cooperative_id)
        db.session.commit()
        return redirect(url_for("inventory_list"))

    return render_optional_template("inventory_form.html", "Add Inventory Item", item=None, suppliers=suppliers)


@app.route("/inventory/edit/<int:item_id>", methods=["GET", "POST"])
@roles_required(*OPERATIONS_RECORD_ROLES)
def edit_inventory_item(item_id):
    """Edit an inventory item."""
    item = scoped_get_or_404(InventoryItem, item_id)
    require_own_cooperative(item.cooperative_id)
    suppliers = own_cooperative_query(Supplier).order_by(Supplier.name.asc()).all()

    if request.method == "POST":
        item.name = request.form.get("name", "").strip()
        if not item.name:
            return "Inventory item name is required.", 400

        reorder_level = parse_float(request.form.get("reorder_level"), 0)
        unit_cost = parse_float(request.form.get("unit_cost"), 0)
        if reorder_level is None or unit_cost is None:
            return "Reorder level and unit cost must be valid numbers.", 400
        if reorder_level < 0 or unit_cost < 0:
            return "Reorder level and unit cost cannot be negative.", 400

        item.category = request.form.get("category", "").strip() or None
        item.unit = request.form.get("unit", "units").strip() or "units"
        item.reorder_level = reorder_level
        item.unit_cost = unit_cost
        item.storage_location = request.form.get("storage_location", "").strip() or None

        supplier_id_value = parse_int(request.form.get("supplier_id"))
        supplier_record = scoped_get(Supplier, supplier_id_value) if supplier_id_value else None
        if supplier_id_value and (not supplier_record or supplier_record.cooperative_id != item.cooperative_id):
            return "Please select a supplier from your own cooperative.", 400
        item.supplier_id = supplier_id_value

        item.status = request.form.get("status", "Active").strip()
        item.notes = request.form.get("notes", "").strip() or None
        add_audit_log("UPDATE", "InventoryItem", item.id, item.name)
        db.session.commit()
        return redirect(url_for("inventory_list"))

    return render_optional_template("inventory_form.html", "Edit Inventory Item", item=item, suppliers=suppliers)


@app.route("/inventory/adjust/<int:item_id>", methods=["POST"])
@roles_required(*OPERATIONS_RECORD_ROLES)
def adjust_inventory(item_id):
    """Adjust inventory quantity."""
    item = scoped_get_or_404(InventoryItem, item_id)
    require_own_cooperative(item.cooperative_id)
    transaction_type = request.form.get("transaction_type", "").strip()
    quantity = parse_float(request.form.get("quantity"))
    try:
        transaction_date = parse_date(request.form.get("transaction_date"))
    except ValueError:
        return "Please enter a valid inventory transaction date.", 400

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
    add_audit_log("ADJUST", "InventoryItem", item.id, f"{transaction_type} {quantity:g} {item.unit}",
                  cooperative_id=item.cooperative_id)
    db.session.commit()
    return redirect(url_for("inventory_list"))


@app.route("/inventory/delete/<int:item_id>", methods=["POST"])
@roles_required(*OPERATIONS_RECORD_ROLES)
def delete_inventory_item(item_id):
    """Delete an inventory item."""
    item = scoped_get_or_404(InventoryItem, item_id)
    require_own_cooperative(item.cooperative_id)
    if item.transactions:
        return "This inventory item cannot be deleted because transaction history exists.", 400
    add_audit_log("DELETE", "InventoryItem", item.id, item.name)
    db.session.delete(item)
    db.session.commit()
    return redirect(url_for("inventory_list"))


# =========================================================
# ROUTES - EQUIPMENT
# =========================================================
@app.route("/equipment")
@roles_required(*OPERATIONS_VIEW_ROLES)
def equipment_list():
    """List equipment."""
    search = request.args.get("search", "").strip()
    query = scoped_model_query(Equipment).outerjoin(Farm)

    if search:
        query = query.filter(or_(
            Equipment.name.ilike(f"%{search}%"),
            Equipment.equipment_type.ilike(f"%{search}%"),
            Equipment.serial_number.ilike(f"%{search}%"),
            Equipment.status.ilike(f"%{search}%"),
            Farm.name.ilike(f"%{search}%")
        ))

    equipment_items = query.order_by(Equipment.name.asc()).all()
    return render_optional_template("equipment.html", "Equipment", equipment=equipment_items, search=search)


@app.route("/equipment/add", methods=["GET", "POST"])
@roles_required(*OPERATIONS_RECORD_ROLES)
def add_equipment():
    """Add equipment."""
    farms = scoped_model_query(Farm).order_by(Farm.name.asc()).all()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            return "Equipment name is required.", 400

        cooperative_id = own_cooperative_id()
        if not cooperative_id:
            abort(403)

        farm_id_value = parse_int(request.form.get("farm_id"))
        farm = scoped_get(Farm, farm_id_value) if farm_id_value else None
        if farm_id_value and (not farm or farm.cooperative_id != cooperative_id):
            return "Please select a farm from your own cooperative.", 400

        try:
            purchase_date = parse_date(request.form.get("purchase_date"))
            last_service_date = parse_date(request.form.get("last_service_date"))
            next_service_date = parse_date(request.form.get("next_service_date"))
        except ValueError:
            return "Please enter valid equipment dates.", 400

        purchase_cost_raw = request.form.get("purchase_cost")
        purchase_cost = parse_float(purchase_cost_raw)
        if purchase_cost_raw and str(purchase_cost_raw).strip() and purchase_cost is None:
            return "Purchase cost must be a valid number.", 400
        if purchase_cost is not None and purchase_cost < 0:
            return "Purchase cost cannot be negative.", 400
        if last_service_date and next_service_date and next_service_date < last_service_date:
            return "Next service date cannot be earlier than the last service date.", 400

        equipment_item = Equipment(
            cooperative_id=cooperative_id,
            name=name,
            equipment_type=request.form.get("equipment_type", "").strip() or None,
            serial_number=request.form.get("serial_number", "").strip() or None,
            farm_id=farm_id_value,
            purchase_date=purchase_date,
            purchase_cost=purchase_cost,
            last_service_date=last_service_date,
            next_service_date=next_service_date,
            status=request.form.get("status", "Available").strip(),
            notes=request.form.get("notes", "").strip() or None,
        )
        db.session.add(equipment_item)
        db.session.flush()
        add_audit_log("CREATE", "Equipment", equipment_item.id, equipment_item.name,
                      cooperative_id=equipment_item.cooperative_id)
        db.session.commit()
        return redirect(url_for("equipment_list"))

    return render_optional_template("equipment_form.html", "Add Equipment", equipment_item=None, farms=farms)


@app.route("/equipment/edit/<int:equipment_id>", methods=["GET", "POST"])
@roles_required(*OPERATIONS_RECORD_ROLES)
def edit_equipment(equipment_id):
    """Edit equipment."""
    equipment_item = scoped_get_or_404(Equipment, equipment_id)
    require_own_cooperative(equipment_item.cooperative_id)
    farms = own_cooperative_query(Farm).order_by(Farm.name.asc()).all()

    if request.method == "POST":
        equipment_item.name = request.form.get("name", "").strip()
        if not equipment_item.name:
            return "Equipment name is required.", 400

        equipment_item.equipment_type = request.form.get("equipment_type", "").strip() or None
        equipment_item.serial_number = request.form.get("serial_number", "").strip() or None

        farm_id_value = parse_int(request.form.get("farm_id"))
        farm = scoped_get(Farm, farm_id_value) if farm_id_value else None
        if farm_id_value and (not farm or farm.cooperative_id != equipment_item.cooperative_id):
            return "Please select a farm from your own cooperative.", 400
        equipment_item.farm_id = farm_id_value

        try:
            purchase_date = parse_date(request.form.get("purchase_date"))
            last_service_date = parse_date(request.form.get("last_service_date"))
            next_service_date = parse_date(request.form.get("next_service_date"))
        except ValueError:
            return "Please enter valid equipment dates.", 400

        purchase_cost_raw = request.form.get("purchase_cost")
        purchase_cost = parse_float(purchase_cost_raw)
        if purchase_cost_raw and str(purchase_cost_raw).strip() and purchase_cost is None:
            return "Purchase cost must be a valid number.", 400
        if purchase_cost is not None and purchase_cost < 0:
            return "Purchase cost cannot be negative.", 400
        if last_service_date and next_service_date and next_service_date < last_service_date:
            return "Next service date cannot be earlier than the last service date.", 400

        equipment_item.purchase_date = purchase_date
        equipment_item.purchase_cost = purchase_cost
        equipment_item.last_service_date = last_service_date
        equipment_item.next_service_date = next_service_date
        equipment_item.status = request.form.get("status", "Available").strip()
        equipment_item.notes = request.form.get("notes", "").strip() or None
        add_audit_log("UPDATE", "Equipment", equipment_item.id, equipment_item.name)
        db.session.commit()
        return redirect(url_for("equipment_list"))

    return render_optional_template("equipment_form.html", "Edit Equipment", equipment_item=equipment_item, farms=farms)


@app.route("/equipment/delete/<int:equipment_id>", methods=["POST"])
@roles_required(*OPERATIONS_RECORD_ROLES)
def delete_equipment(equipment_id):
    """Delete equipment."""
    equipment_item = scoped_get_or_404(Equipment, equipment_id)
    require_own_cooperative(equipment_item.cooperative_id)
    add_audit_log("DELETE", "Equipment", equipment_item.id, equipment_item.name, cooperative_id=equipment_item.cooperative_id)
    db.session.delete(equipment_item)
    db.session.commit()
    return redirect(url_for("equipment_list"))


# =========================================================
# ROUTES - TASKS
# =========================================================
@app.route("/tasks")
@roles_required(*OPERATIONS_VIEW_ROLES)
def tasks_list():
    """List tasks."""
    search = request.args.get("search", "").strip()
    # Resolution-linked accountability tasks are deliberately managed only through
    # the Accountability Register so the legacy task editor cannot bypass proof/verification controls.
    query = scoped_model_query(Task).filter(Task.resolution_id.is_(None)).outerjoin(Farm).outerjoin(User, Task.assigned_user_id == User.id)

    if search:
        query = query.filter(or_(
            Task.title.ilike(f"%{search}%"),
            Task.description.ilike(f"%{search}%"),
            Task.priority.ilike(f"%{search}%"),
            Task.status.ilike(f"%{search}%"),
            Farm.name.ilike(f"%{search}%"),
            User.fullname.ilike(f"%{search}%")
        ))

    tasks = query.order_by(Task.due_date.asc(), Task.created_at.desc()).all()
    return render_optional_template("tasks.html", "Tasks", tasks=tasks, search=search)


@app.route("/tasks/add", methods=["GET", "POST"])
@roles_required(*OPERATIONS_RECORD_ROLES)
def add_task():
    """Add a task."""
    farms = scoped_model_query(Farm).order_by(Farm.name.asc()).all()
    users = accessible_users_query().order_by(User.fullname.asc()).all()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        if not title:
            return "Task title is required.", 400

        cooperative_id = own_cooperative_id()
        if not cooperative_id:
            abort(403)

        farm_id_value = parse_int(request.form.get("farm_id"))
        assigned_user_id_value = parse_int(request.form.get("assigned_user_id"))
        farm = scoped_get(Farm, farm_id_value) if farm_id_value else None
        if farm_id_value and (not farm or farm.cooperative_id != cooperative_id):
            return "Please select a farm from your own cooperative.", 400

        assigned_user = accessible_users_query().filter(
            User.id == assigned_user_id_value).first() if assigned_user_id_value else None
        if assigned_user_id_value and not assigned_user:
            return "Selected user is outside your cooperative access.", 400
        assigned_access = UserAccess.query.filter_by(user_id=assigned_user.id).first() if assigned_user else None
        if assigned_access and assigned_access.cooperative_id != cooperative_id:
            return "Tasks can only be assigned within your own cooperative.", 400

        try:
            due_date = parse_date(request.form.get("due_date"))
        except ValueError:
            return "Please enter a valid task due date.", 400

        task = Task(
            cooperative_id=cooperative_id,
            title=title,
            description=request.form.get("description", "").strip() or None,
            farm_id=farm_id_value,
            assigned_user_id=assigned_user_id_value,
            due_date=due_date,
            priority=request.form.get("priority", "Normal").strip(),
            status=request.form.get("status", "Open").strip(),
        )

        if task.status == "Completed":
            task.completed_at = utc_now()

        db.session.add(task)
        db.session.flush()
        add_audit_log("CREATE", "Task", task.id, task.title, cooperative_id=task.cooperative_id)
        db.session.commit()
        return redirect(url_for("tasks_list"))

    return render_optional_template("task_form.html", "Add Task", task=None, farms=farms, users=users)


@app.route("/tasks/edit/<int:task_id>", methods=["GET", "POST"])
@roles_required(*OPERATIONS_RECORD_ROLES)
def edit_task(task_id):
    """Edit a legacy operational task; accountability tasks use their protected workflow."""
    task = scoped_get_or_404(Task, task_id)
    require_own_cooperative(task.cooperative_id)
    if task.resolution_id:
        return "Resolution-linked accountability tasks cannot be edited here. Use the Accountability Register.", 400
    farms = own_cooperative_query(Farm).order_by(Farm.name.asc()).all()
    users = accessible_users_query().filter(UserAccess.cooperative_id == task.cooperative_id).order_by(User.fullname.asc()).all()

    if request.method == "POST":
        task.title = request.form.get("title", "").strip()
        if not task.title:
            return "Task title is required.", 400

        task.description = request.form.get("description", "").strip() or None

        farm_id_value = parse_int(request.form.get("farm_id"))
        assigned_user_id_value = parse_int(request.form.get("assigned_user_id"))
        farm = scoped_get(Farm, farm_id_value) if farm_id_value else None
        if farm_id_value and (not farm or farm.cooperative_id != task.cooperative_id):
            return "Please select a farm from your own cooperative.", 400

        assigned_user = accessible_users_query().filter(
            User.id == assigned_user_id_value).first() if assigned_user_id_value else None
        if assigned_user_id_value and not assigned_user:
            return "Selected user is outside your cooperative access.", 400

        assigned_access = UserAccess.query.filter_by(user_id=assigned_user.id).first() if assigned_user else None
        if assigned_access and assigned_access.cooperative_id != task.cooperative_id:
            return "Tasks can only be assigned within your own cooperative.", 400

        try:
            due_date = parse_date(request.form.get("due_date"))
        except ValueError:
            return "Please enter a valid task due date.", 400

        task.farm_id = farm_id_value
        task.assigned_user_id = assigned_user_id_value
        task.due_date = due_date
        task.priority = request.form.get("priority", "Normal").strip()
        old_status = task.status
        task.status = request.form.get("status", "Open").strip()

        if task.status == "Completed" and old_status != "Completed":
            task.completed_at = utc_now()
        if task.status != "Completed":
            task.completed_at = None

        add_audit_log("UPDATE", "Task", task.id, task.title)
        db.session.commit()
        return redirect(url_for("tasks_list"))

    return render_optional_template("task_form.html", "Edit Task", task=task, farms=farms, users=users)


@app.route("/tasks/delete/<int:task_id>", methods=["POST"])
@roles_required(*OPERATIONS_RECORD_ROLES)
def delete_task(task_id):
    """Delete a legacy operational task; official accountability history cannot be deleted here."""
    task = scoped_get_or_404(Task, task_id)
    require_own_cooperative(task.cooperative_id)
    if task.resolution_id:
        return "Resolution-linked accountability tasks cannot be deleted. They form part of the governance record.", 400
    add_audit_log("DELETE", "Task", task.id, task.title, cooperative_id=task.cooperative_id)
    db.session.delete(task)
    db.session.commit()
    return redirect(url_for("tasks_list"))


# =========================================================
# ROUTES - FARMER INTERACTIONS
# =========================================================
@app.route("/interactions")
@roles_required(*INTERACTION_VIEW_ROLES)
def interactions_list():
    """List farmer interactions."""
    search = request.args.get("search", "").strip()
    query = scoped_model_query(FarmerInteraction).join(Farmer)

    if search:
        query = query.filter(or_(
            Farmer.fullname.ilike(f"%{search}%"),
            FarmerInteraction.interaction_type.ilike(f"%{search}%"),
            FarmerInteraction.subject.ilike(f"%{search}%"),
            FarmerInteraction.notes.ilike(f"%{search}%")
        ))

    interactions = query.order_by(FarmerInteraction.interaction_date.desc()).all()
    return render_optional_template("interactions.html", "Farmer Interactions", interactions=interactions,
                                    search=search)


@app.route("/interactions/add", methods=["GET", "POST"])
@roles_required(*INTERACTION_RECORD_ROLES)
def add_interaction():
    """Add a farmer interaction."""
    farmers = scoped_model_query(Farmer).order_by(Farmer.fullname.asc()).all()

    if request.method == "POST":
        farmer_id = parse_int(request.form.get("farmer_id"))
        farmer = scoped_get(Farmer, farmer_id) if farmer_id else None
        try:
            interaction_date = parse_date(request.form.get("interaction_date"))
            follow_up_date = parse_date(request.form.get("follow_up_date"))
        except ValueError:
            return "Please enter valid interaction dates.", 400
        interaction_type = request.form.get("interaction_type", "").strip()

        if not farmer or farmer.cooperative_id != own_cooperative_id():
            return "Please select a farmer from your own cooperative.", 400

        if not interaction_date:
            return "A valid interaction date is required.", 400

        if not interaction_type:
            return "Interaction type is required.", 400
        if follow_up_date and follow_up_date < interaction_date:
            return "Follow-up date cannot be earlier than the interaction date.", 400

        interaction = FarmerInteraction(
            cooperative_id=default_record_cooperative_id(farmer.cooperative_id),
            farmer_id=farmer.id,
            interaction_date=interaction_date,
            interaction_type=interaction_type,
            subject=request.form.get("subject", "").strip() or None,
            notes=request.form.get("notes", "").strip() or None,
            follow_up_date=follow_up_date,
            created_by=session.get("user_id"),
        )
        db.session.add(interaction)
        db.session.flush()
        add_audit_log("CREATE", "FarmerInteraction", interaction.id, farmer.fullname,
                      cooperative_id=interaction.cooperative_id)
        db.session.commit()
        return redirect(url_for("interactions_list"))

    return render_optional_template("interaction_form.html", "Add Farmer Interaction", interaction=None,
                                    farmers=farmers)


@app.route("/interactions/delete/<int:interaction_id>", methods=["POST"])
@roles_required(*INTERACTION_RECORD_ROLES)
def delete_interaction(interaction_id):
    """Delete a farmer interaction."""
    interaction = scoped_get_or_404(FarmerInteraction, interaction_id)
    require_own_cooperative(interaction.cooperative_id)
    add_audit_log(
        "DELETE",
        "FarmerInteraction",
        interaction.id,
        interaction.farmer.fullname,
        cooperative_id=interaction.cooperative_id,
    )
    db.session.delete(interaction)
    db.session.commit()
    return redirect(url_for("interactions_list"))


# =========================================================
# ROUTES - MEMBERSHIPS
# =========================================================
@app.route("/memberships")
@roles_required(*MEMBERSHIP_VIEW_ROLES)
def memberships_list():
    """Phase 5 membership register with role-scoped filters and fee summary."""
    search = request.args.get("search", "").strip()
    status_filter = request.args.get("status", "").strip().title()
    fee_filter = request.args.get("fee", "").strip().lower()
    cooperative_filter = parse_int(request.args.get("cooperative_id"))

    visible_primary_cooperatives = accessible_cooperative_query().filter(
        Cooperative.cooperative_type == "Primary",
        Cooperative.status == "Active",
    ).order_by(Cooperative.name.asc()).all()
    visible_ids = {coop.id for coop in visible_primary_cooperatives}
    if cooperative_filter and cooperative_filter not in visible_ids:
        abort(403)

    query = membership_filtered_query(
        search=search,
        status=status_filter,
        fee_status=fee_filter,
        cooperative_id=cooperative_filter,
    )
    memberships = query.order_by(Membership.member_number.asc()).all()

    base_query = membership_filtered_query(cooperative_id=cooperative_filter)
    total_members = base_query.count()
    active_members = base_query.filter(Membership.status == "Active").count()
    attention_members = base_query.filter(Membership.status.in_(("Pending", "Suspended"))).count()
    fee_memberships = base_query.all()
    total_expected = sum(float(m.fee_amount or 0) for m in fee_memberships)
    total_paid = sum(float(m.fee_paid or 0) for m in fee_memberships)
    total_pending = sum(float(m.fee_pending or 0) for m in fee_memberships)
    total_outstanding = sum(float(m.fee_outstanding or 0) for m in fee_memberships)

    return render_template(
        "memberships.html",
        memberships=memberships,
        search=search,
        status_filter=status_filter if status_filter in MEMBERSHIP_ALLOWED_STATUSES else "",
        fee_filter=fee_filter if fee_filter in {"paid", "due", "pending"} else "",
        cooperative_filter=cooperative_filter,
        primary_cooperatives=visible_primary_cooperatives,
        membership_statuses=sorted(MEMBERSHIP_ALLOWED_STATUSES),
        total_members=total_members,
        active_members=active_members,
        attention_members=attention_members,
        total_expected=total_expected,
        total_paid=total_paid,
        total_pending=total_pending,
        total_outstanding=total_outstanding,
    )


@app.route("/memberships/add", methods=["GET", "POST"])
@roles_required(*MEMBERSHIP_MANAGEMENT_ROLES)
def add_membership():
    """Primary Secretary/Vice Secretary registers an individual member."""
    access = current_access()
    cooperative = current_cooperative()
    if not cooperative or cooperative.cooperative_type != "Primary":
        abort(403)

    farmers = own_cooperative_query(Farmer).order_by(Farmer.fullname.asc()).all()

    if request.method == "POST":
        farmer_id = parse_int(request.form.get("farmer_id"))
        farmer = db.session.get(Farmer, farmer_id) if farmer_id else None

        if not farmer or farmer.cooperative_id != access.cooperative_id:
            return "Please select a valid person from your Primary cooperative.", 400

        existing = Membership.query.filter_by(
            cooperative_id=access.cooperative_id,
            farmer_id=farmer.id,
        ).first()
        if existing:
            return "This person already has a membership record in your cooperative.", 400

        requested_number = request.form.get("member_number", "").strip()
        member_number = requested_number or generate_member_number(cooperative)
        if Membership.query.filter_by(member_number=member_number).first():
            return "This member number already exists. Please try again.", 400

        fee_amount = parse_float(request.form.get("fee_amount"), 300.0)
        if fee_amount is None or fee_amount < 0:
            return "Membership fee cannot be negative.", 400

        try:
            join_date = parse_date(request.form.get("join_date"))
        except ValueError:
            return "Please enter a valid join date.", 400

        status = normalize_membership_status(request.form.get("status"), "Active")
        if not status:
            return "Please choose a valid membership status.", 400

        membership = Membership(
            cooperative_id=access.cooperative_id,
            farmer_id=farmer.id,
            member_number=member_number,
            membership_type="Primary",
            join_date=join_date,
            fee_amount=fee_amount,
            fee_paid=0,
            status=status,
            notes=request.form.get("notes", "").strip() or None,
        )
        db.session.add(membership)
        db.session.flush()
        record_membership_history(
            membership,
            "REGISTERED",
            description=f"Membership {member_number} registered for {farmer.fullname}.",
            to_status=status,
        )
        add_audit_log(
            "MEMBER_REGISTERED",
            "Membership",
            membership.id,
            f"{member_number} - {farmer.fullname} - {status}",
            cooperative_id=membership.cooperative_id,
        )
        db.session.commit()
        return redirect(url_for("memberships_list"))

    return render_template(
        "membership_form.html",
        membership=None,
        farmers=farmers,
        generated_member_number=generate_member_number(cooperative),
        membership_statuses=sorted(MEMBERSHIP_ALLOWED_STATUSES),
    )


@app.route("/memberships/edit/<int:membership_id>", methods=["GET", "POST"])
@roles_required(*MEMBERSHIP_MANAGEMENT_ROLES)
def edit_membership(membership_id):
    """Primary Secretary/Vice Secretary maintains membership administration fields."""
    membership = scoped_get_or_404(Membership, membership_id)
    access = require_own_cooperative(membership.cooperative_id)
    cooperative = current_cooperative()
    if not cooperative or cooperative.cooperative_type != "Primary":
        abort(403)

    farmers = own_cooperative_query(Farmer).order_by(Farmer.fullname.asc()).all()

    if request.method == "POST":
        farmer_id = parse_int(request.form.get("farmer_id"))
        farmer = db.session.get(Farmer, farmer_id) if farmer_id else None

        if not farmer or farmer.cooperative_id != access.cooperative_id:
            return "Please select a valid person from your Primary cooperative.", 400

        duplicate_person = Membership.query.filter(
            Membership.cooperative_id == access.cooperative_id,
            Membership.farmer_id == farmer.id,
            Membership.id != membership.id,
        ).first()
        if duplicate_person:
            return "This person already has another membership record in your cooperative.", 400

        submitted_number = request.form.get("member_number", membership.member_number).strip()
        if submitted_number and submitted_number != membership.member_number:
            return "Member numbers are permanent and cannot be changed after registration.", 400

        fee_amount = parse_float(request.form.get("fee_amount"), membership.fee_amount or 0)
        if fee_amount is None or fee_amount < 0:
            return "Membership fee cannot be negative.", 400
        recorded_fee_total = float(membership.fee_paid or 0) + float(membership.fee_pending or 0)
        if recorded_fee_total > fee_amount + 1e-9:
            return "Membership fee cannot be set below the amount already recorded as paid or pending confirmation.", 400

        try:
            join_date = parse_date(request.form.get("join_date"))
        except ValueError:
            return "Please enter a valid join date.", 400

        new_status = normalize_membership_status(request.form.get("status"), membership.status)
        if not new_status:
            return "Please choose a valid membership status.", 400

        old_status = membership.status
        status_reason = request.form.get("status_reason", "").strip()
        if new_status != old_status and new_status in {"Suspended", "Resigned", "Deceased", "Inactive"} and not status_reason:
            return f"Please record a reason when changing membership status to {new_status}.", 400

        changes = []
        if membership.farmer_id != farmer.id:
            changes.append(f"member changed to {farmer.fullname}")
        if membership.join_date != join_date:
            changes.append("join date updated")
        if abs(float(membership.fee_amount or 0) - float(fee_amount or 0)) > 1e-9:
            changes.append(f"expected fee changed to R{float(fee_amount or 0):.2f}")
        if membership.notes != (request.form.get("notes", "").strip() or None):
            changes.append("notes updated")

        membership.farmer_id = farmer.id
        membership.membership_type = "Primary"
        membership.join_date = join_date
        membership.fee_amount = fee_amount
        membership.status = new_status
        membership.notes = request.form.get("notes", "").strip() or None
        membership.updated_at = utc_now()

        if new_status != old_status:
            record_membership_history(
                membership,
                "STATUS_CHANGED",
                description=status_reason or f"Status changed from {old_status} to {new_status}.",
                from_status=old_status,
                to_status=new_status,
            )
            add_audit_log(
                "MEMBERSHIP_STATUS_CHANGED",
                "Membership",
                membership.id,
                f"{membership.member_number}: {old_status} -> {new_status}; {status_reason or 'no additional reason'}",
                cooperative_id=membership.cooperative_id,
            )
        elif changes:
            record_membership_history(
                membership,
                "DETAILS_UPDATED",
                description="; ".join(changes),
                from_status=old_status,
                to_status=new_status,
            )
            add_audit_log(
                "MEMBERSHIP_UPDATED",
                "Membership",
                membership.id,
                f"{membership.member_number}: {'; '.join(changes)}",
                cooperative_id=membership.cooperative_id,
            )

        db.session.commit()
        return redirect(url_for("memberships_list"))

    return render_template(
        "membership_form.html",
        membership=membership,
        farmers=farmers,
        generated_member_number=membership.member_number,
        membership_statuses=sorted(MEMBERSHIP_ALLOWED_STATUSES),
    )


@app.route("/memberships/<int:membership_id>/history")
@roles_required(*MEMBERSHIP_VIEW_ROLES)
def membership_history(membership_id):
    """Show the lifecycle and finance history of one visible membership."""
    membership = scoped_get_or_404(Membership, membership_id)
    if not membership.cooperative or membership.cooperative.cooperative_type != "Primary":
        abort(404)
    history = MembershipHistory.query.filter_by(membership_id=membership.id).order_by(
        MembershipHistory.created_at.desc(), MembershipHistory.id.desc()
    ).all()
    fee_contributions = Contribution.query.filter_by(membership_id=membership.id).order_by(
        Contribution.contribution_date.desc(), Contribution.id.desc()
    ).all()
    return render_template(
        "membership_history.html",
        membership=membership,
        history=history,
        fee_contributions=fee_contributions,
    )


@app.route("/memberships/delete/<int:membership_id>", methods=["POST"])
@roles_required(*MEMBERSHIP_MANAGEMENT_ROLES)
def delete_membership(membership_id):
    """Delete only a mistaken membership with no financial transaction history."""
    membership = scoped_get_or_404(Membership, membership_id)
    require_own_cooperative(membership.cooperative_id)

    if float(membership.fee_paid or 0) > 1e-9:
        return "A membership with confirmed payments cannot be deleted. Change its status instead.", 400

    has_contributions = Contribution.query.filter_by(
        cooperative_id=membership.cooperative_id,
        farmer_id=membership.farmer_id,
    ).first()
    if has_contributions:
        return "A membership linked to contribution records cannot be deleted. Change its status instead.", 400

    add_audit_log(
        "MEMBERSHIP_DELETED",
        "Membership",
        membership.id,
        f"Deleted mistaken membership {membership.member_number} for {membership.farmer.fullname}.",
        cooperative_id=membership.cooperative_id,
    )
    db.session.delete(membership)
    db.session.commit()
    return redirect(url_for("memberships_list"))


@app.route("/exports/memberships.csv")
@roles_required(*MEMBERSHIP_VIEW_ROLES)
def export_memberships():
    """Export the currently visible membership register."""
    search = request.args.get("search", "").strip()
    status_filter = request.args.get("status", "").strip().title()
    fee_filter = request.args.get("fee", "").strip().lower()
    cooperative_filter = parse_int(request.args.get("cooperative_id"))

    visible_ids = {
        coop.id for coop in accessible_cooperative_query().filter(
            Cooperative.cooperative_type == "Primary"
        ).all()
    }
    if cooperative_filter and cooperative_filter not in visible_ids:
        abort(403)

    rows = membership_filtered_query(
        search=search,
        status=status_filter,
        fee_status=fee_filter,
        cooperative_id=cooperative_filter,
    ).order_by(Membership.member_number.asc()).all()

    add_audit_log(
        "DATA_EXPORT",
        "Membership",
        details=f"Exported {len(rows)} visible membership records.",
        cooperative_id=current_access().cooperative_id if current_access() else None,
    )
    db.session.commit()

    return make_csv_response(
        f"malenge_memberships_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        [
            "Member Number", "Full Name", "Phone", "Primary Cooperative", "Join Date",
            "Status", "Fee Expected", "Fee Confirmed", "Fee Pending", "Fee Outstanding", "Fee Status", "Notes",
        ],
        [[
            membership.member_number,
            membership.farmer.fullname,
            membership.farmer.phone,
            membership.cooperative.name if membership.cooperative else "",
            membership.join_date or "",
            membership.status,
            membership.fee_amount or 0,
            membership.fee_paid or 0,
            membership.fee_pending,
            membership.fee_outstanding,
            membership.fee_status,
            membership.notes or "",
        ] for membership in rows],
    )


# =========================================================
# ROUTES - CONTRIBUTIONS
# =========================================================
@app.route("/contributions")
@roles_required(*FINANCE_VIEW_ROLES)
def contributions_list():
    """List contributions within the user's visibility scope."""
    search = request.args.get("search", "").strip()
    query = scoped_model_query(Contribution).join(Farmer)

    if search:
        query = query.filter(or_(
            Farmer.fullname.ilike(f"%{search}%"),
            Contribution.category.ilike(f"%{search}%"),
            Contribution.reference.ilike(f"%{search}%"),
            Contribution.status.ilike(f"%{search}%")
        ))

    contributions = query.order_by(Contribution.contribution_date.desc()).all()
    return render_optional_template(
        "contributions.html",
        "Contributions",
        contributions=contributions,
        search=search,
    )


@app.route("/contributions/add", methods=["GET", "POST"])
@roles_required(*FINANCE_RECORD_ROLES)
def add_contribution():
    """Treasurer records money; membership-fee money is linked to the exact member record."""
    access = current_access()
    farmers = own_cooperative_query(Farmer).order_by(Farmer.fullname.asc()).all()
    selected_membership = None

    requested_membership_id = parse_int(request.args.get("membership_id"))
    if requested_membership_id:
        candidate = scoped_get(Membership, requested_membership_id)
        if candidate and candidate.cooperative_id == access.cooperative_id:
            selected_membership = candidate

    if request.method == "POST":
        farmer_id = parse_int(request.form.get("farmer_id"))
        farmer = db.session.get(Farmer, farmer_id) if farmer_id else None
        amount = parse_float(request.form.get("amount"))
        category = request.form.get("category", "").strip() or None
        membership_id = parse_int(request.form.get("membership_id"))

        try:
            contribution_date = parse_date(request.form.get("contribution_date"))
        except ValueError:
            return "A valid contribution date is required.", 400

        if not farmer or farmer.cooperative_id != access.cooperative_id:
            return "Please select a valid member/farmer from your cooperative.", 400
        if amount is None or amount <= 0:
            return "Contribution amount must be greater than zero.", 400
        if not contribution_date:
            return "A valid contribution date is required.", 400

        linked_membership = None
        if category and category.strip().casefold() in MEMBERSHIP_FEE_CATEGORY_ALIASES:
            category = MEMBERSHIP_FEE_CATEGORY
            if current_cooperative() and current_cooperative().cooperative_type != "Primary":
                return "Individual membership fees are recorded by the Treasurer of the member's Primary cooperative.", 400

            if membership_id:
                linked_membership = db.session.get(Membership, membership_id)
                if (
                    not linked_membership
                    or linked_membership.cooperative_id != access.cooperative_id
                    or linked_membership.farmer_id != farmer.id
                ):
                    return "Please select a valid membership from your own Primary cooperative.", 400
            else:
                linked_membership = Membership.query.filter_by(
                    cooperative_id=access.cooperative_id,
                    farmer_id=farmer.id,
                ).first()

            if not linked_membership:
                return "This person does not have a membership record for a membership-fee payment.", 400
            if linked_membership.status in {"Resigned", "Deceased", "Inactive"}:
                return f"Membership-fee payments cannot be recorded while the membership is {linked_membership.status}.", 400

            available = linked_membership.fee_outstanding
            if amount > available + 1e-9:
                return f"Membership-fee contribution exceeds the amount still due. Maximum: R {available:.2f}.", 400

        contribution = Contribution(
            cooperative_id=access.cooperative_id,
            farmer_id=farmer.id,
            membership_id=linked_membership.id if linked_membership else None,
            amount=amount,
            contribution_date=contribution_date,
            category=category,
            method=request.form.get("method", "").strip() or None,
            reference=request.form.get("reference", "").strip() or None,
            status="Pending Confirmation",
            notes=request.form.get("notes", "").strip() or None,
        )
        db.session.add(contribution)
        db.session.flush()
        if linked_membership:
            record_membership_history(
                linked_membership,
                "FEE_RECORDED",
                description=f"Treasurer recorded R{amount:.2f} membership fee; pending Chairperson confirmation.",
                from_status=linked_membership.status,
                to_status=linked_membership.status,
            )
        add_audit_log(
            "FINANCE_RECORDED",
            "Contribution",
            contribution.id,
            f"{farmer.fullname} - R{amount:.2f} - {category or 'Contribution'} - pending Chairperson confirmation",
            cooperative_id=contribution.cooperative_id,
        )
        db.session.commit()
        return redirect(url_for("contributions_list"))

    return render_template(
        "contribution_form.html",
        contribution=None,
        farmers=farmers,
        selected_membership=selected_membership,
    )


@app.route("/contributions/<int:contribution_id>/decision", methods=["POST"])
@roles_required(*FINANCE_APPROVAL_ROLES)
def decide_contribution(contribution_id):
    """Chairperson confirms or rejects a Treasurer-recorded contribution."""
    contribution = scoped_get_or_404(Contribution, contribution_id)
    require_own_cooperative(contribution.cooperative_id)

    if contribution.status != "Pending Confirmation":
        return "Only contributions awaiting confirmation can be approved or rejected.", 400

    decision = request.form.get("decision", "").strip().lower()
    if decision not in {"approve", "reject"}:
        return "Please choose approve or reject.", 400

    linked_membership = contribution.membership
    if not linked_membership and (contribution.category or "").strip().casefold() in MEMBERSHIP_FEE_CATEGORY_ALIASES:
        # Compatibility with membership-fee contributions created before Phase 5.
        linked_membership = Membership.query.filter_by(
            cooperative_id=contribution.cooperative_id,
            farmer_id=contribution.farmer_id,
        ).first()
        if linked_membership:
            contribution.membership_id = linked_membership.id

    if decision == "approve":
        contribution.status = "Confirmed"

        if (contribution.category or "").strip().casefold() in MEMBERSHIP_FEE_CATEGORY_ALIASES:
            if not linked_membership:
                return "Membership record was not found for this membership-fee contribution.", 400

            new_paid = float(linked_membership.fee_paid or 0) + float(contribution.amount or 0)
            if new_paid > float(linked_membership.fee_amount or 0) + 1e-9:
                return "Approving this payment would exceed the member's recorded membership fee.", 400
            linked_membership.fee_paid = new_paid
            linked_membership.updated_at = utc_now()
            record_membership_history(
                linked_membership,
                "FEE_CONFIRMED",
                description=(
                    f"Chairperson confirmed R{float(contribution.amount or 0):.2f} membership fee. "
                    f"Total confirmed: R{new_paid:.2f}; outstanding: R{linked_membership.fee_outstanding:.2f}."
                ),
                from_status=linked_membership.status,
                to_status=linked_membership.status,
            )

        action = "FINANCE_CONFIRMED"
        details = f"Contribution R{float(contribution.amount or 0):.2f} confirmed by Chairperson"
    else:
        contribution.status = "Rejected"
        if linked_membership:
            record_membership_history(
                linked_membership,
                "FEE_REJECTED",
                description=f"Chairperson rejected R{float(contribution.amount or 0):.2f} membership-fee record.",
                from_status=linked_membership.status,
                to_status=linked_membership.status,
            )
        action = "FINANCE_REJECTED"
        details = f"Contribution R{float(contribution.amount or 0):.2f} rejected by Chairperson"

    add_audit_log(
        action,
        "Contribution",
        contribution.id,
        details,
        cooperative_id=contribution.cooperative_id,
    )
    db.session.commit()
    return redirect(url_for("contributions_list"))


@app.route("/contributions/delete/<int:contribution_id>", methods=["POST"])
@roles_required(*FINANCE_RECORD_ROLES)
def delete_contribution(contribution_id):
    """Treasurer may remove only an unconfirmed/rejected mistaken record."""
    contribution = scoped_get_or_404(Contribution, contribution_id)
    require_own_cooperative(contribution.cooperative_id)

    if contribution.status not in {"Pending Confirmation", "Rejected"}:
        return "Confirmed financial records cannot be deleted.", 400

    linked_membership = contribution.membership
    if linked_membership:
        record_membership_history(
            linked_membership,
            "FEE_RECORD_REMOVED",
            description=f"Treasurer removed unconfirmed/rejected R{float(contribution.amount or 0):.2f} membership-fee record.",
            from_status=linked_membership.status,
            to_status=linked_membership.status,
        )

    add_audit_log(
        "DELETE",
        "Contribution",
        contribution.id,
        f"R{float(contribution.amount or 0):.2f}",
        cooperative_id=contribution.cooperative_id,
    )
    db.session.delete(contribution)
    db.session.commit()
    return redirect(url_for("contributions_list"))

# =========================================================
# ROUTES - COOPERATIVES
# =========================================================
def validate_cooperative_configuration(cooperative_type, parent_id, status, exclude_id=None):
    """Enforce Malenge's one-Secondary/two-Primary governance structure."""
    if cooperative_type not in {"Secondary", "Primary"}:
        return None, "Cooperative type must be Secondary or Primary."

    if status not in COOPERATIVE_ALLOWED_STATUSES:
        return None, "Cooperative status must be Active or Inactive."

    count_query = Cooperative.query.filter(Cooperative.cooperative_type == cooperative_type)
    if exclude_id is not None:
        count_query = count_query.filter(Cooperative.id != exclude_id)

    limit = (
        MALENGE_MAX_SECONDARY_COOPERATIVES
        if cooperative_type == "Secondary"
        else MALENGE_MAX_PRIMARY_COOPERATIVES
    )
    if count_query.count() >= limit:
        label = "Secondary Cooperative" if cooperative_type == "Secondary" else "Primary Cooperatives"
        return None, f"Malenge is configured for only {limit} {label}."

    if cooperative_type == "Secondary":
        return None, None

    if not parent_id:
        return None, "A Primary Cooperative must belong to the Secondary Cooperative."

    if exclude_id is not None and parent_id == exclude_id:
        return None, "A cooperative cannot be its own parent."

    parent = db.session.get(Cooperative, parent_id)
    if not parent or parent.cooperative_type != "Secondary":
        return None, "Please select the valid Secondary Cooperative."

    if status == "Active" and parent.status != "Active":
        return None, "An active Primary Cooperative must belong to an active Secondary Cooperative."

    return parent, None


@app.route("/cooperatives")
@roles_required(
    "Admin",
    "Secondary Chairperson",
    "Secondary Vice Chairperson",
    "Secondary Secretary",
    "Secondary Vice Secretary",
    "Secondary Treasurer",
)
def cooperatives_list():
    """List cooperatives."""
    search = request.args.get("search", "").strip()
    query = accessible_cooperative_query()

    if search:
        query = query.filter(or_(
            Cooperative.name.ilike(f"%{search}%"),
            Cooperative.registration_number.ilike(f"%{search}%"),
            Cooperative.code.ilike(f"%{search}%"),
            Cooperative.location.ilike(f"%{search}%")
        ))

    cooperatives = query.order_by(
        Cooperative.cooperative_type.desc(),
        Cooperative.name.asc()
    ).all()

    return render_optional_template("cooperatives.html", "Cooperatives", cooperatives=cooperatives, search=search)


@app.route("/cooperatives/add", methods=["GET", "POST"])
@roles_required("Admin")
def add_cooperative():
    """Add a cooperative."""
    secondary_cooperatives = Cooperative.query.filter_by(
        cooperative_type="Secondary"
    ).order_by(Cooperative.name.asc()).all()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        cooperative_type = request.form.get("cooperative_type", "").strip()
        parent_id = parse_int(request.form.get("parent_id"))
        status = request.form.get("status", "Active").strip()

        if not name:
            return "Cooperative name is required.", 400

        if Cooperative.query.filter(func.lower(Cooperative.name) == name.lower()).first():
            return "A cooperative with this name already exists.", 400

        parent, structure_error = validate_cooperative_configuration(
            cooperative_type,
            parent_id,
            status,
        )
        if structure_error:
            return structure_error, 400

        if cooperative_type == "Secondary":
            parent_id = None
        else:
            parent_id = parent.id

        cooperative = Cooperative(
            name=name,
            cooperative_type=cooperative_type,
            parent_id=parent_id,
            registration_number=request.form.get("registration_number", "").strip() or None,
            code=request.form.get("code", "").strip() or None,
            location=request.form.get("location", "").strip() or None,
            status=status,
        )
        db.session.add(cooperative)
        db.session.flush()
        add_audit_log("CREATE", "Cooperative", cooperative.id, cooperative.name, cooperative_id=cooperative.id)
        db.session.commit()
        return redirect(url_for("cooperatives_list"))

    return render_optional_template("cooperative_form.html", "Add Cooperative", cooperative=None,
                                    secondary_cooperatives=secondary_cooperatives)


@app.route("/cooperatives/edit/<int:cooperative_id>", methods=["GET", "POST"])
@roles_required("Admin")
def edit_cooperative(cooperative_id):
    """Edit a cooperative."""
    cooperative = Cooperative.query.get_or_404(cooperative_id)
    secondary_cooperatives = Cooperative.query.filter(
        Cooperative.cooperative_type == "Secondary",
        Cooperative.id != cooperative.id
    ).order_by(Cooperative.name.asc()).all()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        cooperative_type = request.form.get("cooperative_type", "").strip()
        parent_id = parse_int(request.form.get("parent_id"))
        status = request.form.get("status", "Active").strip()

        if not name:
            return "Cooperative name is required.", 400

        duplicate = Cooperative.query.filter(
            func.lower(Cooperative.name) == name.lower(),
            Cooperative.id != cooperative.id
        ).first()

        if duplicate:
            return "A cooperative with this name already exists.", 400

        if cooperative.cooperative_type == "Secondary" and cooperative_type != "Secondary":
            if cooperative.primary_cooperatives:
                return "The Secondary Cooperative cannot be changed to Primary while Primary Cooperatives belong to it.", 400

        if cooperative.cooperative_type == "Secondary" and status == "Inactive":
            if any(child.status == "Active" for child in cooperative.primary_cooperatives):
                return "Deactivate the Primary Cooperatives before deactivating the Secondary Cooperative.", 400

        parent, structure_error = validate_cooperative_configuration(
            cooperative_type,
            parent_id,
            status,
            exclude_id=cooperative.id,
        )
        if structure_error:
            return structure_error, 400

        if cooperative_type == "Secondary":
            parent_id = None
        else:
            parent_id = parent.id

        cooperative.name = name
        cooperative.cooperative_type = cooperative_type
        cooperative.parent_id = parent_id
        cooperative.registration_number = request.form.get("registration_number", "").strip() or None
        cooperative.code = request.form.get("code", "").strip() or None
        cooperative.location = request.form.get("location", "").strip() or None
        cooperative.status = status
        add_audit_log("UPDATE", "Cooperative", cooperative.id, cooperative.name, cooperative_id=cooperative.id)
        db.session.commit()
        return redirect(url_for("cooperatives_list"))

    return render_optional_template("cooperative_form.html", "Edit Cooperative", cooperative=cooperative,
                                    secondary_cooperatives=secondary_cooperatives)


# =========================================================
# ROUTES - PHASE 6 ACCOUNTABILITY & GOVERNANCE
# =========================================================
@app.route("/accountability")
@roles_required(*GOVERNANCE_VIEW_ROLES)
def accountability_register():
    """Central register: what was decided, who owns it, due date, status and proof."""
    access = current_access()
    status_filter = request.args.get("status", "").strip()
    search = request.args.get("search", "").strip()

    query = own_cooperative_query(Resolution).join(Meeting)
    if status_filter:
        if status_filter == "Overdue":
            query = query.filter(
                Resolution.status.in_(["Assigned", "In Progress"]),
                Resolution.due_date.isnot(None),
                Resolution.due_date < crm_today(),
            )
        elif status_filter == "At Risk":
            today = crm_today()
            query = query.filter(
                Resolution.status.in_(["Assigned", "In Progress"]),
                Resolution.due_date.isnot(None),
                Resolution.due_date >= today,
                Resolution.due_date <= today + timedelta(days=3),
            )
        else:
            query = query.filter(Resolution.status == status_filter)
    if search:
        query = query.filter(or_(
            Resolution.resolution_number.ilike(f"%{search}%"),
            Resolution.title.ilike(f"%{search}%"),
            Resolution.resolution_text.ilike(f"%{search}%"),
            Meeting.title.ilike(f"%{search}%"),
        ))

    resolutions = query.order_by(
        Resolution.due_date.is_(None),
        Resolution.due_date.asc(),
        Resolution.created_at.desc(),
    ).all()

    today = crm_today()
    all_own = own_cooperative_query(Resolution)
    counts = {
        "open": all_own.filter(Resolution.status.in_(["Assigned", "In Progress", "Awaiting Verification"])).count(),
        "overdue": all_own.filter(
            Resolution.status.in_(["Assigned", "In Progress"]),
            Resolution.due_date.isnot(None),
            Resolution.due_date < today,
        ).count(),
        "verification": all_own.filter_by(status="Awaiting Verification").count(),
        "closed": all_own.filter_by(status="Closed").count(),
    }

    return render_template(
        "accountability_register.html",
        resolutions=resolutions,
        counts=counts,
        status_filter=status_filter,
        search=search,
        today=today,
        current_access=access,
    )


@app.route("/meetings")
@roles_required(*GOVERNANCE_VIEW_ROLES)
def meetings_list():
    search = request.args.get("search", "").strip()
    query = own_cooperative_query(Meeting)
    if search:
        query = query.filter(or_(
            Meeting.meeting_number.ilike(f"%{search}%"),
            Meeting.title.ilike(f"%{search}%"),
            Meeting.meeting_type.ilike(f"%{search}%"),
            Meeting.venue.ilike(f"%{search}%"),
        ))
    meetings = query.order_by(Meeting.meeting_date.desc(), Meeting.created_at.desc()).all()
    return render_template("meetings.html", meetings=meetings, search=search)


@app.route("/meetings/add", methods=["GET", "POST"])
@roles_required(*MEETING_RECORD_ROLES)
def add_meeting():
    access = current_access()
    cooperative = current_cooperative()
    if not cooperative or not access.cooperative_id:
        abort(403)

    if request.method == "POST":
        meeting_type = request.form.get("meeting_type", "").strip()
        title = request.form.get("title", "").strip()
        venue = request.form.get("venue", "").strip() or None
        quorum_status = request.form.get("quorum_status", "Not Recorded").strip()
        notes = request.form.get("notes", "").strip() or None
        try:
            meeting_date = parse_date(request.form.get("meeting_date"))
        except ValueError:
            meeting_date = None

        if not meeting_type or not title or not meeting_date:
            return "Meeting type, title and date are required.", 400
        if quorum_status not in {"Met", "Not Met", "Not Recorded"}:
            return "Please choose a valid quorum status.", 400

        meeting = Meeting(
            cooperative_id=access.cooperative_id,
            meeting_number=next_governance_number(Meeting, cooperative, "MTG", meeting_date),
            meeting_type=meeting_type[:80],
            title=title[:180],
            meeting_date=meeting_date,
            venue=venue[:200] if venue else None,
            quorum_status=quorum_status,
            status="Draft",
            notes=notes,
            created_by_user_id=session["user_id"],
        )
        db.session.add(meeting)
        db.session.flush()
        add_audit_log(
            "MEETING_CREATED", "Meeting", meeting.id,
            f"{meeting.meeting_number} - {meeting.title}", cooperative_id=meeting.cooperative_id,
        )
        db.session.commit()
        return redirect(url_for("meeting_detail", meeting_id=meeting.id))

    return render_template("meeting_form.html")


@app.route("/meetings/<int:meeting_id>/edit", methods=["GET", "POST"])
@roles_required(*MEETING_RECORD_ROLES)
def edit_meeting(meeting_id):
    meeting = scoped_get_or_404(Meeting, meeting_id)
    require_own_cooperative(meeting.cooperative_id)
    if meeting.status != "Draft":
        return "Confirmed meeting records are locked. Historical evidence must not be silently edited.", 400

    if request.method == "POST":
        meeting_type = request.form.get("meeting_type", "").strip()
        title = request.form.get("title", "").strip()
        venue = request.form.get("venue", "").strip() or None
        quorum_status = request.form.get("quorum_status", "Not Recorded").strip()
        notes = request.form.get("notes", "").strip() or None
        try:
            meeting_date = parse_date(request.form.get("meeting_date"))
        except ValueError:
            meeting_date = None
        if not meeting_type or not title or not meeting_date:
            return "Meeting type, title and date are required.", 400
        if quorum_status not in {"Met", "Not Met", "Not Recorded"}:
            return "Please choose a valid quorum status.", 400

        old_summary = f"{meeting.meeting_date} / {meeting.title}"
        meeting.meeting_type = meeting_type[:80]
        meeting.title = title[:180]
        meeting.meeting_date = meeting_date
        meeting.venue = venue[:200] if venue else None
        meeting.quorum_status = quorum_status
        meeting.notes = notes
        add_audit_log(
            "MEETING_DRAFT_UPDATED", "Meeting", meeting.id,
            f"Draft meeting metadata updated from {old_summary} to {meeting.meeting_date} / {meeting.title}.",
            cooperative_id=meeting.cooperative_id,
        )
        db.session.commit()
        return redirect(url_for("meeting_detail", meeting_id=meeting.id))

    return render_template("meeting_form.html", meeting=meeting)


@app.route("/meetings/<int:meeting_id>")
@roles_required(*GOVERNANCE_VIEW_ROLES)
def meeting_detail(meeting_id):
    meeting = scoped_get_or_404(Meeting, meeting_id)
    require_own_cooperative(meeting.cooperative_id)
    return render_template("meeting_detail.html", meeting=meeting)


@app.route("/meetings/<int:meeting_id>/upload", methods=["POST"])
@roles_required(*MEETING_RECORD_ROLES)
def upload_meeting_document(meeting_id):
    meeting = scoped_get_or_404(Meeting, meeting_id)
    require_own_cooperative(meeting.cooperative_id)
    if meeting.status == "Confirmed":
        return "Confirmed meeting evidence is locked. Create an amendment record rather than replacing it.", 400

    document_type = request.form.get("document_type", "Meeting Minutes").strip() or "Meeting Minutes"
    try:
        original_name, stored_name, digest = save_accountability_upload(request.files.get("document"), "meeting")
    except ValueError as exc:
        return str(exc), 400

    document = MeetingDocument(
        meeting_id=meeting.id,
        cooperative_id=meeting.cooperative_id,
        document_type=document_type[:60],
        original_name=original_name,
        stored_name=stored_name,
        file_sha256=digest,
        uploaded_by_user_id=session["user_id"],
    )
    db.session.add(document)
    db.session.flush()
    add_audit_log(
        "MEETING_EVIDENCE_UPLOADED", "MeetingDocument", document.id,
        f"{meeting.meeting_number}: {document.document_type} ({document.original_name}); SHA256 {digest}",
        cooperative_id=meeting.cooperative_id,
    )
    db.session.commit()
    return redirect(url_for("meeting_detail", meeting_id=meeting.id))


@app.route("/meeting-documents/<int:document_id>/download")
@roles_required(*GOVERNANCE_VIEW_ROLES)
def download_meeting_document(document_id):
    document = scoped_get_or_404(MeetingDocument, document_id)
    require_own_cooperative(document.cooperative_id)
    path = accountability_file_path(document.stored_name)
    current_digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if not hmac.compare_digest(current_digest, document.file_sha256):
        abort(500, description="Stored evidence failed its integrity check.")
    return send_file(path, as_attachment=False, download_name=document.original_name)


@app.route("/meetings/<int:meeting_id>/confirm", methods=["POST"])
@roles_required(*MEETING_CONFIRM_ROLES)
def confirm_meeting(meeting_id):
    meeting = scoped_get_or_404(Meeting, meeting_id)
    require_own_cooperative(meeting.cooperative_id)
    if meeting.status == "Confirmed":
        return redirect(url_for("meeting_detail", meeting_id=meeting.id))
    if not meeting.documents:
        return "Upload the handwritten/signed meeting evidence before confirming the record.", 400

    meeting.status = "Confirmed"
    meeting.confirmed_by_user_id = session["user_id"]
    meeting.confirmed_at = utc_now()
    add_audit_log(
        "MEETING_CONFIRMED", "Meeting", meeting.id,
        f"{meeting.meeting_number} evidence confirmed and locked by Chairperson.",
        cooperative_id=meeting.cooperative_id,
    )
    db.session.commit()
    return redirect(url_for("meeting_detail", meeting_id=meeting.id))


@app.route("/resolutions/add", methods=["GET", "POST"])
@roles_required(*RESOLUTION_RECORD_ROLES)
def add_resolution():
    access = current_access()
    cooperative = current_cooperative()
    meetings = own_cooperative_query(Meeting).filter(
        Meeting.status == "Confirmed",
        Meeting.quorum_status != "Not Met",
    ).order_by(Meeting.meeting_date.desc()).all()
    executives = active_executive_accesses(access.cooperative_id)
    selected_meeting_id = parse_int(request.args.get("meeting_id"))

    if request.method == "POST":
        meeting_id = parse_int(request.form.get("meeting_id"))
        responsible_user_id = parse_int(request.form.get("responsible_user_id"))
        title = request.form.get("title", "").strip()
        resolution_text = request.form.get("resolution_text", "").strip()
        priority = request.form.get("priority", "Normal").strip()
        meeting = db.session.get(Meeting, meeting_id) if meeting_id else None
        responsible_access = UserAccess.query.filter_by(
            cooperative_id=access.cooperative_id,
            user_id=responsible_user_id,
            status="Active",
        ).first() if responsible_user_id else None
        try:
            due_date = parse_date(request.form.get("due_date"))
        except ValueError:
            due_date = None

        if not meeting or meeting.cooperative_id != access.cooperative_id or meeting.status != "Confirmed":
            return "Choose a confirmed meeting from your cooperative.", 400
        if meeting.quorum_status == "Not Met":
            return "This meeting is recorded as not having quorum, so action resolutions cannot be created from it.", 400
        if not responsible_access or responsible_access.role not in GOVERNANCE_VIEW_ROLES:
            return "Choose an active executive from your cooperative.", 400
        if not title or not resolution_text:
            return "Resolution title and decision text are required.", 400
        if priority not in {"Low", "Normal", "High", "Urgent"}:
            return "Choose a valid priority.", 400

        resolution = Resolution(
            cooperative_id=access.cooperative_id,
            meeting_id=meeting.id,
            resolution_number=next_governance_number(Resolution, cooperative, "RES", meeting.meeting_date),
            title=title[:180],
            resolution_text=resolution_text,
            responsible_role=responsible_access.role,
            responsible_user_id=responsible_access.user_id,
            due_date=due_date,
            priority=priority,
            status="Draft",
            created_by_user_id=session["user_id"],
        )
        db.session.add(resolution)
        db.session.flush()
        add_audit_log(
            "RESOLUTION_DRAFTED", "Resolution", resolution.id,
            f"{resolution.resolution_number} - {resolution.title}; responsible: {resolution.responsible_role}",
            cooperative_id=resolution.cooperative_id,
        )
        db.session.commit()
        return redirect(url_for("resolution_detail", resolution_id=resolution.id))

    return render_template(
        "resolution_form.html",
        meetings=meetings,
        executives=executives,
        selected_meeting_id=selected_meeting_id,
    )


@app.route("/resolutions/<int:resolution_id>/edit", methods=["GET", "POST"])
@roles_required(*RESOLUTION_RECORD_ROLES)
def edit_resolution(resolution_id):
    resolution = scoped_get_or_404(Resolution, resolution_id)
    access = require_own_cooperative(resolution.cooperative_id)
    if resolution.status != "Draft":
        return "Certified resolutions are locked into the accountability workflow.", 400

    meetings = own_cooperative_query(Meeting).filter(
        Meeting.status == "Confirmed",
        Meeting.quorum_status != "Not Met",
    ).order_by(Meeting.meeting_date.desc()).all()
    executives = active_executive_accesses(access.cooperative_id)

    if request.method == "POST":
        meeting_id = parse_int(request.form.get("meeting_id"))
        responsible_user_id = parse_int(request.form.get("responsible_user_id"))
        title = request.form.get("title", "").strip()
        resolution_text = request.form.get("resolution_text", "").strip()
        priority = request.form.get("priority", "Normal").strip()
        meeting = db.session.get(Meeting, meeting_id) if meeting_id else None
        responsible_access = UserAccess.query.filter_by(
            cooperative_id=access.cooperative_id, user_id=responsible_user_id, status="Active"
        ).first() if responsible_user_id else None
        try:
            due_date = parse_date(request.form.get("due_date"))
        except ValueError:
            due_date = None

        if not meeting or meeting.cooperative_id != access.cooperative_id or meeting.status != "Confirmed" or meeting.quorum_status == "Not Met":
            return "Choose a confirmed meeting with quorum from your cooperative.", 400
        if not responsible_access or responsible_access.role not in GOVERNANCE_VIEW_ROLES:
            return "Choose an active executive from your cooperative.", 400
        if not title or not resolution_text:
            return "Resolution title and decision text are required.", 400
        if priority not in {"Low", "Normal", "High", "Urgent"}:
            return "Choose a valid priority.", 400

        resolution.meeting_id = meeting.id
        resolution.title = title[:180]
        resolution.resolution_text = resolution_text
        resolution.responsible_role = responsible_access.role
        resolution.responsible_user_id = responsible_access.user_id
        resolution.due_date = due_date
        resolution.priority = priority
        add_audit_log(
            "RESOLUTION_DRAFT_UPDATED", "Resolution", resolution.id,
            f"{resolution.resolution_number} draft updated before certification.",
            cooperative_id=resolution.cooperative_id,
        )
        db.session.commit()
        return redirect(url_for("resolution_detail", resolution_id=resolution.id))

    return render_template(
        "resolution_form.html", meetings=meetings, executives=executives,
        selected_meeting_id=resolution.meeting_id, resolution=resolution,
    )


@app.route("/resolutions/<int:resolution_id>")
@roles_required(*GOVERNANCE_VIEW_ROLES)
def resolution_detail(resolution_id):
    resolution = scoped_get_or_404(Resolution, resolution_id)
    require_own_cooperative(resolution.cooperative_id)
    task = Task.query.filter_by(resolution_id=resolution.id).first()
    return render_template("resolution_detail.html", resolution=resolution, task=task)


@app.route("/resolutions/<int:resolution_id>/certify", methods=["POST"])
@roles_required(*MEETING_CONFIRM_ROLES)
def certify_resolution(resolution_id):
    resolution = scoped_get_or_404(Resolution, resolution_id)
    require_own_cooperative(resolution.cooperative_id)
    if resolution.status != "Draft":
        return "Only draft resolutions can be certified.", 400
    if resolution.meeting.status != "Confirmed":
        return "The source meeting must be confirmed first.", 400
    if resolution.meeting.quorum_status == "Not Met":
        return "A resolution cannot be certified from a meeting recorded as not having quorum.", 400

    resolution.status = "Assigned"
    resolution.certified_by_user_id = session["user_id"]
    resolution.certified_at = utc_now()

    task = Task(
        cooperative_id=resolution.cooperative_id,
        resolution_id=resolution.id,
        title=resolution.title,
        description=resolution.resolution_text,
        assigned_user_id=resolution.responsible_user_id,
        assigned_role=resolution.responsible_role,
        created_by_user_id=session["user_id"],
        due_date=resolution.due_date,
        priority=resolution.priority,
        status="Open",
        progress_percentage=0,
    )
    db.session.add(task)
    db.session.flush()
    db.session.add(TaskUpdate(
        task_id=task.id,
        cooperative_id=task.cooperative_id,
        user_id=session["user_id"],
        status="Open",
        progress_percentage=0,
        comment="Resolution certified and accountability task created.",
    ))
    add_audit_log(
        "RESOLUTION_CERTIFIED", "Resolution", resolution.id,
        f"{resolution.resolution_number} certified; task #{task.id} assigned to {resolution.responsible_role}.",
        cooperative_id=resolution.cooperative_id,
    )
    db.session.commit()
    return redirect(url_for("accountability_task_detail", task_id=task.id))


@app.route("/accountability/tasks/<int:task_id>")
@roles_required(*GOVERNANCE_VIEW_ROLES)
def accountability_task_detail(task_id):
    task = scoped_get_or_404(Task, task_id)
    require_own_cooperative(task.cooperative_id)
    if not task.resolution_id:
        abort(404)
    return render_template(
        "accountability_task_detail.html",
        task=task,
        can_update_task=can_update_accountability_task(task),
        can_verify_task=(
            current_access().role in ACCOUNTABILITY_VERIFY_ROLES
            and task.assigned_user_id != session.get("user_id")
        ),
        today=crm_today(),
    )


@app.route("/accountability/tasks/<int:task_id>/update", methods=["POST"])
@roles_required(*GOVERNANCE_VIEW_ROLES)
def update_accountability_task(task_id):
    task = scoped_get_or_404(Task, task_id)
    require_own_cooperative(task.cooperative_id)
    if not task.resolution_id or not can_update_accountability_task(task):
        abort(403)
    if task.status == "Verified":
        return "Verified accountability work is closed and cannot be edited.", 400

    requested_status = request.form.get("status", "In Progress").strip()
    comment = request.form.get("comment", "").strip() or None
    progress = parse_int(request.form.get("progress_percentage"), task.progress_percentage or 0)
    progress = max(0, min(100, progress if progress is not None else 0))
    if requested_status not in {"Open", "In Progress", "Completed"}:
        return "Choose Open, In Progress or Completed.", 400

    if requested_status == "Completed":
        task.status = "Awaiting Verification"
        task.progress_percentage = 100
        task.completed_at = utc_now()
        log_status = "Awaiting Verification"
    else:
        task.status = requested_status
        task.progress_percentage = progress
        task.completed_at = None
        if requested_status == "In Progress" and not task.started_at:
            task.started_at = utc_now()
        log_status = requested_status

    db.session.add(TaskUpdate(
        task_id=task.id,
        cooperative_id=task.cooperative_id,
        user_id=session["user_id"],
        status=log_status,
        progress_percentage=task.progress_percentage,
        comment=comment,
    ))
    sync_resolution_from_task(task)
    add_audit_log(
        "ACCOUNTABILITY_PROGRESS", "Task", task.id,
        f"{task.title}: {log_status} ({task.progress_percentage}%). {comment or ''}".strip(),
        cooperative_id=task.cooperative_id,
    )
    db.session.commit()
    return redirect(url_for("accountability_task_detail", task_id=task.id))


@app.route("/accountability/tasks/<int:task_id>/evidence", methods=["POST"])
@roles_required(*GOVERNANCE_VIEW_ROLES)
def upload_task_evidence(task_id):
    task = scoped_get_or_404(Task, task_id)
    require_own_cooperative(task.cooperative_id)
    if not task.resolution_id or not can_update_accountability_task(task):
        abort(403)
    if task.status == "Verified":
        return "Verified accountability work is closed.", 400

    evidence_type = request.form.get("evidence_type", "Supporting Evidence").strip() or "Supporting Evidence"
    description = request.form.get("description", "").strip() or None
    try:
        original_name, stored_name, digest = save_accountability_upload(request.files.get("evidence"), "task")
    except ValueError as exc:
        return str(exc), 400

    evidence = TaskEvidence(
        task_id=task.id,
        cooperative_id=task.cooperative_id,
        evidence_type=evidence_type[:60],
        description=description[:300] if description else None,
        original_name=original_name,
        stored_name=stored_name,
        file_sha256=digest,
        uploaded_by_user_id=session["user_id"],
    )
    db.session.add(evidence)
    db.session.flush()
    add_audit_log(
        "ACCOUNTABILITY_EVIDENCE_UPLOADED", "TaskEvidence", evidence.id,
        f"Task #{task.id}: {evidence.evidence_type} ({evidence.original_name}); SHA256 {digest}",
        cooperative_id=task.cooperative_id,
    )
    db.session.commit()
    return redirect(url_for("accountability_task_detail", task_id=task.id))


@app.route("/task-evidence/<int:evidence_id>/download")
@roles_required(*GOVERNANCE_VIEW_ROLES)
def download_task_evidence(evidence_id):
    evidence = scoped_get_or_404(TaskEvidence, evidence_id)
    require_own_cooperative(evidence.cooperative_id)
    path = accountability_file_path(evidence.stored_name)
    current_digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if not hmac.compare_digest(current_digest, evidence.file_sha256):
        abort(500, description="Stored evidence failed its integrity check.")
    return send_file(path, as_attachment=False, download_name=evidence.original_name)


@app.route("/accountability/tasks/<int:task_id>/verify", methods=["POST"])
@roles_required(*ACCOUNTABILITY_VERIFY_ROLES)
def verify_accountability_task(task_id):
    task = scoped_get_or_404(Task, task_id)
    require_own_cooperative(task.cooperative_id)
    if not task.resolution_id:
        abort(404)
    if task.assigned_user_id == session.get("user_id"):
        return "The person responsible for the task cannot verify their own work.", 403
    if task.status != "Awaiting Verification":
        return "Only completed work awaiting verification can be reviewed.", 400

    decision = request.form.get("decision", "").strip().lower()
    notes = request.form.get("verification_notes", "").strip() or None
    if not notes:
        return "Add a short verification note describing what you checked or what must be corrected.", 400
    if decision == "approve":
        if not task.evidence_files:
            return "At least one supporting evidence file is required before verification.", 400
        task.status = "Verified"
        task.verified_by_user_id = session["user_id"]
        task.verified_at = utc_now()
        task.verification_notes = notes
        update_status = "Verified"
        action = "ACCOUNTABILITY_VERIFIED"
    elif decision == "return":
        task.status = "In Progress"
        task.verified_by_user_id = None
        task.verified_at = None
        task.verification_notes = notes
        task.completed_at = None
        task.progress_percentage = min(task.progress_percentage or 100, 95)
        update_status = "Returned"
        action = "ACCOUNTABILITY_RETURNED"
    else:
        return "Choose approve or return for more work.", 400

    db.session.add(TaskUpdate(
        task_id=task.id,
        cooperative_id=task.cooperative_id,
        user_id=session["user_id"],
        status=update_status,
        progress_percentage=task.progress_percentage,
        comment=notes,
    ))
    sync_resolution_from_task(task)
    add_audit_log(
        action, "Task", task.id,
        f"{task.title}: {update_status}. {notes or ''}".strip(),
        cooperative_id=task.cooperative_id,
    )
    db.session.commit()
    return redirect(url_for("accountability_task_detail", task_id=task.id))


# =========================================================
# ROUTES - REPORTS
# =========================================================
@app.route("/reports")
@roles_required(*COOPERATIVE_EXECUTIVE_ROLES)
def reports():
    """Generate reports."""
    try:
        start_date = parse_date(request.args.get("start_date"))
        end_date = parse_date(request.args.get("end_date"))
    except ValueError:
        return "Please enter valid report dates.", 400

    if start_date and end_date and end_date < start_date:
        return "Report end date cannot be earlier than the start date.", 400

    sales_query = scoped_model_query(Sale).filter(Sale.status != "Cancelled")
    payments_query = scoped_model_query(Payment).filter(Payment.status.in_(PAYMENT_VALUE_STATUSES))
    expenses_query = scoped_model_query(Expense).filter(Expense.status.in_(CONFIRMED_EXPENSE_STATUSES))
    contributions_query = scoped_model_query(Contribution).filter(Contribution.status.in_(CONFIRMED_CONTRIBUTION_STATUSES))

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

    total_sales_value = sales_query.with_entities(
        func.coalesce(func.sum(Sale.total_amount), 0)
    ).scalar() or 0

    total_payments_value = payments_query.with_entities(
        func.coalesce(func.sum(Payment.amount), 0)
    ).scalar() or 0

    total_expenses_value = expenses_query.with_entities(
        func.coalesce(func.sum(Expense.amount), 0)
    ).scalar() or 0

    total_contributions_value = contributions_query.with_entities(
        func.coalesce(func.sum(Contribution.amount), 0)
    ).scalar() or 0

    outstanding_balance = max(float(total_sales_value) - float(total_payments_value), 0.0)
    net_cash_position = float(total_payments_value) + float(total_contributions_value) - float(total_expenses_value)

    membership_query = membership_filtered_query()
    membership_fee_records = membership_query.all()
    membership_fees_expected = sum(float(m.fee_amount or 0) for m in membership_fee_records)
    membership_fees_paid = sum(float(m.fee_paid or 0) for m in membership_fee_records)
    membership_fees_pending = sum(float(m.fee_pending or 0) for m in membership_fee_records)
    membership_fees_outstanding = sum(float(m.fee_outstanding or 0) for m in membership_fee_records)

    return render_optional_template("reports.html", "Reports",
                                    farmer_count=scoped_model_query(Farmer).count(),
                                    farm_count=scoped_model_query(Farm).count(),
                                    crop_count=scoped_model_query(Crop).count(),
                                    harvest_count=scoped_model_query(Harvest).count(),
                                    sales_count=scoped_model_query(Sale).count(),
                                    payment_count=scoped_model_query(Payment).count(),
                                    customer_count=scoped_model_query(Customer).count(),
                                    supplier_count=scoped_model_query(Supplier).count(),
                                    expense_count=scoped_model_query(Expense).count(),
                                    membership_count=membership_query.count(),
                                    active_membership_count=membership_query.filter(Membership.status == "Active").count(),
                                    membership_fees_expected=membership_fees_expected,
                                    membership_fees_paid=membership_fees_paid,
                                    membership_fees_pending=membership_fees_pending,
                                    membership_fees_outstanding=membership_fees_outstanding,
                                    total_sales_value=total_sales_value,
                                    total_payments_value=total_payments_value,
                                    total_expenses_value=total_expenses_value,
                                    total_contributions_value=total_contributions_value,
                                    outstanding_balance=outstanding_balance,
                                    net_cash_position=net_cash_position,
                                    recent_sales=sales_query.order_by(Sale.sale_date.desc()).limit(10).all(),
                                    recent_payments=payments_query.order_by(Payment.payment_date.desc()).limit(
                                        10).all(),
                                    recent_expenses=expenses_query.order_by(Expense.expense_date.desc()).limit(
                                        10).all(),
                                    start_date=start_date,
                                    end_date=end_date,
                                    current_access=current_access(),
                                    current_cooperative=current_cooperative()
                                    )


# =========================================================
# ROUTES - GOOGLE AUTHENTICATOR / TWO-FACTOR AUTHENTICATION
# =========================================================
@app.route("/2fa/setup", methods=["GET", "POST"])
@login_required
def two_factor_setup():
    """Enroll the signed-in account in Google Authenticator."""
    user = current_user()
    access = current_access()

    if user.two_factor_enabled:
        if not two_factor_session_complete():
            return redirect(url_for("two_factor_verify"))
        return redirect(url_for("settings"))

    secret = None
    if user.two_factor_secret:
        try:
            secret = decrypt_two_factor_secret(user.two_factor_secret)
        except RuntimeError:
            clear_user_two_factor(user)
            db.session.commit()

    if not secret:
        secret = generate_totp_secret()
        user.two_factor_secret = encrypt_two_factor_secret(secret)
        db.session.commit()

    if request.method == "POST":
        code = request.form.get("code", "").strip()
        matched_counter = verify_totp_code(secret, code)

        if matched_counter is None:
            add_audit_log(
                "TWO_FACTOR_SETUP_FAILED",
                "User",
                user.id,
                "Google Authenticator enrollment code was invalid.",
                cooperative_id=access.cooperative_id if access else None,
            )
            db.session.commit()
            return "The verification code is invalid. Check Google Authenticator and try again.", 400

        recovery_codes = generate_recovery_codes()
        set_recovery_codes(user, recovery_codes)
        user.two_factor_enabled = True
        user.two_factor_confirmed_at = utc_now()
        # The enrollment code is considered used and cannot be replayed for login.
        user.two_factor_last_counter = matched_counter
        session["two_factor_authenticated"] = True
        session["two_factor_bypassed"] = False
        session["two_factor_failures"] = 0

        add_audit_log(
            "TWO_FACTOR_ENABLED",
            "User",
            user.id,
            "Google Authenticator two-factor authentication enabled.",
            cooperative_id=access.cooperative_id if access else None,
        )
        add_audit_log(
            "LOGIN_SUCCESS",
            "User",
            user.id,
            f"Successful login as {access.role if access else 'Unknown'} after Google Authenticator enrollment.",
            cooperative_id=access.cooperative_id if access else None,
        )
        db.session.commit()

        return render_template(
            "two_factor_setup.html",
            user=user,
            setup_complete=True,
            recovery_codes=recovery_codes,
            secret=None,
            qr_data_uri=None,
        )

    uri = google_authenticator_uri(user, secret)
    return render_template(
        "two_factor_setup.html",
        user=user,
        setup_complete=False,
        recovery_codes=None,
        secret=secret,
        qr_data_uri=google_authenticator_qr_data_uri(uri),
    )


@app.route("/2fa/verify", methods=["GET", "POST"])
@login_required
def two_factor_verify():
    """Verify Google Authenticator or a one-time recovery code after password login."""
    user = current_user()
    access = current_access()

    if not user.two_factor_enabled:
        return redirect(url_for("two_factor_setup"))

    if two_factor_session_complete():
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        code = request.form.get("code", "").strip()
        valid = False
        used_recovery = False

        try:
            secret = decrypt_two_factor_secret(user.two_factor_secret)
        except RuntimeError as exc:
            return str(exc), 500

        matched_counter = verify_totp_code(secret, code)
        if matched_counter is not None:
            if user.two_factor_last_counter is None or matched_counter > user.two_factor_last_counter:
                valid = True
                user.two_factor_last_counter = matched_counter
        elif consume_recovery_code(user, code):
            valid = True
            used_recovery = True

        if valid:
            session["two_factor_authenticated"] = True
            session["two_factor_bypassed"] = False
            session["two_factor_failures"] = 0
            action = "TWO_FACTOR_RECOVERY_USED" if used_recovery else "TWO_FACTOR_SUCCESS"
            details = (
                f"One-time recovery code accepted; {recovery_code_count(user)} recovery codes remain."
                if used_recovery
                else "Google Authenticator verification succeeded."
            )
            add_audit_log(
                action,
                "User",
                user.id,
                details,
                cooperative_id=access.cooperative_id if access else None,
            )
            add_audit_log(
                "LOGIN_SUCCESS",
                "User",
                user.id,
                f"Successful login as {access.role if access else 'Unknown'} with two-factor authentication.",
                cooperative_id=access.cooperative_id if access else None,
            )
            db.session.commit()
            return redirect(url_for("dashboard"))

        failures = int(session.get("two_factor_failures", 0)) + 1
        session["two_factor_failures"] = failures
        add_audit_log(
            "TWO_FACTOR_FAILED",
            "User",
            user.id,
            f"Invalid Google Authenticator/recovery code attempt {failures}.",
            cooperative_id=access.cooperative_id if access else None,
        )

        if failures >= int(app.config.get("TWO_FACTOR_MAX_ATTEMPTS", 5)):
            add_audit_log(
                "TWO_FACTOR_RATE_LIMITED",
                "User",
                user.id,
                "Too many invalid two-factor codes; password sign-in is required again.",
                cooperative_id=access.cooperative_id if access else None,
            )
            db.session.commit()
            session.clear()
            return "Too many two-factor verification attempts. Sign in again.", 429

        db.session.commit()
        return "Invalid verification code or recovery code.", 401

    return render_template(
        "two_factor_verify.html",
        user=user,
        remaining_recovery_codes=recovery_code_count(user),
    )


@app.route("/2fa/recovery-codes", methods=["GET", "POST"])
@login_required
def two_factor_recovery_codes():
    """Regenerate recovery codes after re-confirming password and Google Authenticator."""
    user = current_user()
    access = current_access()

    if not user.two_factor_enabled or not two_factor_session_complete():
        return redirect(url_for("two_factor_setup"))

    if request.method == "POST":
        password = request.form.get("current_password", "")
        code = request.form.get("code", "").strip()

        if not check_password_hash(user.password, password):
            return "Current password is incorrect.", 400

        try:
            secret = decrypt_two_factor_secret(user.two_factor_secret)
        except RuntimeError as exc:
            return str(exc), 500

        counter = verify_totp_code(secret, code)
        if counter is None:
            return "The Google Authenticator code is invalid.", 400

        recovery_codes = generate_recovery_codes()
        set_recovery_codes(user, recovery_codes)
        add_audit_log(
            "TWO_FACTOR_RECOVERY_REGENERATED",
            "User",
            user.id,
            "User regenerated Google Authenticator recovery codes.",
            cooperative_id=access.cooperative_id if access else None,
        )
        db.session.commit()
        return render_template(
            "two_factor_recovery_codes.html",
            user=user,
            recovery_codes=recovery_codes,
            generated=True,
        )

    return render_template(
        "two_factor_recovery_codes.html",
        user=user,
        recovery_codes=None,
        generated=False,
    )


# =========================================================
# ROUTES - SETTINGS / PROFILE
# =========================================================
@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    """User settings."""
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

    return render_optional_template(
        "settings.html",
        "Settings",
        user=user,
        current_access=current_access(),
        current_cooperative=current_cooperative(),
    )


@app.route("/settings/password", methods=["POST"])
@login_required
def change_password():
    """Change user password."""
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
# EXECUTIVE APPOINTMENT HELPERS
# =========================================================
def active_executive_appointment_for_slot(cooperative_id, role):
    """Return the current active holder of one cooperative executive position."""
    return ExecutiveAppointment.query.filter_by(
        cooperative_id=cooperative_id,
        role=role,
        status="Active",
    ).first()


def active_executive_appointment_for_user(user_id):
    """Return a user's active executive appointment, if any."""
    return ExecutiveAppointment.query.filter_by(
        user_id=user_id,
        status="Active",
    ).first()


def close_executive_appointment(appointment, end_date=None, ended_by_user_id=None):
    """Close an active appointment without deleting its history."""
    if not appointment or appointment.status != "Active":
        return appointment

    end_date = end_date or utc_now().date()
    if end_date < appointment.start_date:
        raise ValueError("Executive end date cannot be earlier than the appointment start date.")

    appointment.status = "Inactive"
    appointment.end_date = end_date
    appointment.ended_by_user_id = ended_by_user_id
    appointment.updated_at = utc_now()
    return appointment


def create_executive_appointment(
        user,
        cooperative,
        role,
        start_date=None,
        appointed_by_user_id=None,
        notes=None,
):
    """Create one active appointment after business-rule validation."""
    start_date = start_date or utc_now().date()

    if role not in COOPERATIVE_EXECUTIVE_ROLES:
        raise ValueError("Please select a cooperative executive role.")

    if cooperative.cooperative_type == "Secondary" and role not in SECONDARY_EXECUTIVE_ROLES:
        raise ValueError("The selected role does not belong to a Secondary Cooperative.")

    if cooperative.cooperative_type == "Primary" and role not in PRIMARY_EXECUTIVE_ROLES:
        raise ValueError("The selected role does not belong to a Primary Cooperative.")

    occupied = active_executive_appointment_for_slot(cooperative.id, role)
    if occupied:
        holder = occupied.user.fullname if occupied.user else "another executive"
        raise ValueError(f"{role} is already actively held by {holder} for {cooperative.name}.")

    current_for_user = active_executive_appointment_for_user(user.id)
    if current_for_user:
        raise ValueError(
            f"{user.fullname} already has an active executive appointment: "
            f"{current_for_user.role} at {current_for_user.cooperative.name}. "
            "Deactivate or replace that appointment first."
        )

    appointment = ExecutiveAppointment(
        cooperative_id=cooperative.id,
        user_id=user.id,
        role=role,
        start_date=start_date,
        status="Active",
        appointed_by_user_id=appointed_by_user_id,
        notes=notes or None,
    )
    db.session.add(appointment)
    return appointment


def sync_access_to_executive_history(
        user,
        access,
        old_role,
        old_status,
        old_cooperative_id,
        new_role,
        new_status,
        new_cooperative_id,
        effective_date=None,
):
    """Keep UserAccess and executive appointment history aligned after Admin changes."""
    effective_date = effective_date or utc_now().date()
    actor_id = session.get("user_id") if has_request_context() else None

    old_active_exec = (
        old_status == "Active"
        and old_role in COOPERATIVE_EXECUTIVE_ROLES
        and old_cooperative_id is not None
    )
    new_active_exec = (
        new_status == "Active"
        and new_role in COOPERATIVE_EXECUTIVE_ROLES
        and new_cooperative_id is not None
    )
    same_assignment = (
        old_active_exec
        and new_active_exec
        and old_role == new_role
        and old_cooperative_id == new_cooperative_id
    )

    if old_active_exec and not same_assignment:
        old_appointment = ExecutiveAppointment.query.filter_by(
            user_id=user.id,
            cooperative_id=old_cooperative_id,
            role=old_role,
            status="Active",
        ).first()
        if old_appointment:
            close_executive_appointment(old_appointment, effective_date, actor_id)

    if new_active_exec and not same_assignment:
        cooperative = db.session.get(Cooperative, new_cooperative_id)
        create_executive_appointment(
            user,
            cooperative,
            new_role,
            start_date=effective_date,
            appointed_by_user_id=actor_id,
            notes="Created from Users & Access assignment.",
        )


# =========================================================
# ROUTES - USER MANAGEMENT
# =========================================================
def validate_admin_user_assignment(role, status, cooperative_id, exclude_user_id=None):
    """Validate an Admin-selected role and protect active executive positions."""
    if role not in VALID_ACCESS_ROLES:
        return None, "Please select a valid CRM role."

    if status not in {"Active", "Inactive"}:
        return None, "Invalid access status."

    if role == "Admin":
        return None, None

    if not cooperative_id:
        return None, "Please assign this executive to a cooperative."

    cooperative = db.session.get(Cooperative, cooperative_id)
    if not cooperative:
        return None, "Selected cooperative does not exist."

    if cooperative.status != "Active" and status == "Active":
        return None, "An active executive cannot be assigned to an inactive cooperative."

    if role in SECONDARY_EXECUTIVE_ROLES and cooperative.cooperative_type != "Secondary":
        return None, "A Secondary executive role must be assigned to the Secondary Cooperative."

    if role in PRIMARY_EXECUTIVE_ROLES and cooperative.cooperative_type != "Primary":
        return None, "A Primary executive role must be assigned to a Primary Cooperative."

    if status == "Active":
        duplicate_query = UserAccess.query.filter_by(
            cooperative_id=cooperative.id,
            role=role,
            status="Active",
        )
        if exclude_user_id is not None:
            duplicate_query = duplicate_query.filter(UserAccess.user_id != exclude_user_id)

        duplicate = duplicate_query.first()
        if duplicate:
            holder = duplicate.user.fullname if duplicate.user else "another CRM user"
            return (
                None,
                f"{role} is already actively assigned to {holder} for {cooperative.name}. "
                "Deactivate or reassign that executive before assigning this position.",
            )

        appointment_query = ExecutiveAppointment.query.filter_by(
            cooperative_id=cooperative.id,
            role=role,
            status="Active",
        )
        if exclude_user_id is not None:
            appointment_query = appointment_query.filter(ExecutiveAppointment.user_id != exclude_user_id)

        appointment = appointment_query.first()
        if appointment:
            holder = appointment.user.fullname if appointment.user else "another executive"
            return (
                None,
                f"{role} already has an active appointment for {holder} at {cooperative.name}. "
                "Use Executive Management to replace or deactivate the current holder.",
            )

    return cooperative, None


# =========================================================
# ROUTES - EXECUTIVE MANAGEMENT
# =========================================================
@app.route("/executives")
@roles_required("Admin")
def executives_list():
    """Admin dashboard for the 15 cooperative executive positions."""
    cooperatives = Cooperative.query.order_by(
        Cooperative.cooperative_type.desc(),
        Cooperative.name.asc(),
    ).all()

    active_appointments = ExecutiveAppointment.query.filter_by(status="Active").all()
    appointment_map = {
        (appointment.cooperative_id, appointment.role): appointment
        for appointment in active_appointments
    }

    cooperative_rows = []
    total_positions = 0
    filled_positions = 0
    for cooperative in cooperatives:
        slots = []
        for position in EXECUTIVE_POSITIONS:
            role = executive_role_for(cooperative.cooperative_type, position)
            if not role:
                continue
            appointment = appointment_map.get((cooperative.id, role))
            total_positions += 1
            if appointment:
                filled_positions += 1
            slots.append({
                "position": position,
                "role": role,
                "appointment": appointment,
            })
        cooperative_rows.append({
            "cooperative": cooperative,
            "slots": slots,
        })

    return render_optional_template(
        "executives.html",
        "Executives",
        cooperative_rows=cooperative_rows,
        total_positions=total_positions,
        filled_positions=filled_positions,
        vacant_positions=max(total_positions - filled_positions, 0),
        today=crm_today(),
    )


@app.route("/executives/assign", methods=["GET", "POST"])
@roles_required("Admin")
def assign_executive():
    """Assign an existing CRM user to a vacant cooperative executive position."""
    cooperatives = Cooperative.query.order_by(
        Cooperative.cooperative_type.desc(),
        Cooperative.name.asc(),
    ).all()
    users = User.query.order_by(User.fullname.asc()).all()

    selected_cooperative_id = parse_int(request.values.get("cooperative_id"))
    selected_role = request.values.get("role", "").strip()

    if request.method == "POST":
        user_id = parse_int(request.form.get("user_id"))
        cooperative_id = parse_int(request.form.get("cooperative_id"))
        role = request.form.get("role", "").strip()
        start_date_raw = request.form.get("start_date", "").strip()
        notes = request.form.get("notes", "").strip()

        try:
            start_date = parse_date(start_date_raw) if start_date_raw else utc_now().date()
        except ValueError:
            return "Please enter a valid appointment start date.", 400

        user = db.session.get(User, user_id) if user_id else None
        if not user:
            return "Please select a CRM user.", 400

        access = get_user_access(user.id)
        if access.role == "Admin" and access.status == "Active":
            return "The System Admin account cannot also hold a cooperative executive position.", 400

        cooperative, assignment_error = validate_admin_user_assignment(
            role,
            "Active",
            cooperative_id,
            exclude_user_id=user.id,
        )
        if assignment_error:
            return assignment_error, 400

        active_for_user = active_executive_appointment_for_user(user.id)
        if active_for_user:
            return (
                f"{user.fullname} already holds {active_for_user.role} at "
                f"{active_for_user.cooperative.name}. Deactivate or replace that appointment first.",
                400,
            )

        if access.status == "Active" and access.role in COOPERATIVE_EXECUTIVE_ROLES:
            return (
                f"{user.fullname} already has active CRM executive access as {access.role}. "
                "Use Executive Management to change the existing appointment.",
                400,
            )

        try:
            appointment = create_executive_appointment(
                user,
                cooperative,
                role,
                start_date=start_date,
                appointed_by_user_id=session.get("user_id"),
                notes=notes,
            )
        except ValueError as exc:
            return str(exc), 400

        access.role = role
        access.status = "Active"
        access.cooperative_id = cooperative.id
        db.session.flush()

        add_audit_log(
            "EXECUTIVE_ASSIGNED",
            "ExecutiveAppointment",
            appointment.id,
            f"{user.fullname} appointed as {role} for {cooperative.name} from {start_date.isoformat()}.",
            cooperative_id=cooperative.id,
        )
        add_audit_log(
            "ACCESS_UPDATE",
            "User",
            user.id,
            f"Executive access activated: {role} / {cooperative.name}.",
            cooperative_id=cooperative.id,
        )
        db.session.commit()
        return redirect(url_for("executives_list"))

    return render_optional_template(
        "executive_assignment_form.html",
        "Assign Executive",
        cooperatives=cooperatives,
        users=users,
        selected_cooperative_id=selected_cooperative_id,
        selected_role=selected_role,
        executive_positions=EXECUTIVE_POSITIONS,
        today=crm_today(),
    )


@app.route("/executives/replace/<int:appointment_id>", methods=["GET", "POST"])
@roles_required("Admin")
def replace_executive(appointment_id):
    """End one appointment and appoint a replacement while preserving history."""
    appointment = db.session.get(ExecutiveAppointment, appointment_id)
    if not appointment:
        abort(404)
    if appointment.status != "Active":
        return "Only an active executive appointment can be replaced.", 400

    users = User.query.order_by(User.fullname.asc()).all()

    if request.method == "POST":
        new_user_id = parse_int(request.form.get("user_id"))
        effective_raw = request.form.get("effective_date", "").strip()
        notes = request.form.get("notes", "").strip()

        try:
            effective_date = parse_date(effective_raw) if effective_raw else utc_now().date()
        except ValueError:
            return "Please enter a valid replacement date.", 400

        if effective_date < appointment.start_date:
            return "Replacement date cannot be earlier than the current appointment start date.", 400

        new_user = db.session.get(User, new_user_id) if new_user_id else None
        if not new_user:
            return "Please select the replacement CRM user.", 400
        if new_user.id == appointment.user_id:
            return "Please select a different user as the replacement.", 400

        new_access = get_user_access(new_user.id)
        if new_access.role == "Admin" and new_access.status == "Active":
            return "The System Admin account cannot also hold a cooperative executive position.", 400

        existing_new_appointment = active_executive_appointment_for_user(new_user.id)
        if existing_new_appointment:
            return (
                f"{new_user.fullname} already holds {existing_new_appointment.role} at "
                f"{existing_new_appointment.cooperative.name}.",
                400,
            )

        if new_access.status == "Active" and new_access.role in COOPERATIVE_EXECUTIVE_ROLES:
            return f"{new_user.fullname} already has active executive access as {new_access.role}.", 400

        old_user = appointment.user
        old_access = get_user_access(old_user.id)

        close_executive_appointment(
            appointment,
            end_date=effective_date,
            ended_by_user_id=session.get("user_id"),
        )
        if (
            old_access.role == appointment.role
            and old_access.cooperative_id == appointment.cooperative_id
        ):
            old_access.status = "Inactive"

        replacement = create_executive_appointment(
            new_user,
            appointment.cooperative,
            appointment.role,
            start_date=effective_date,
            appointed_by_user_id=session.get("user_id"),
            notes=notes or f"Replaced {old_user.fullname}.",
        )
        new_access.role = appointment.role
        new_access.status = "Active"
        new_access.cooperative_id = appointment.cooperative_id
        db.session.flush()

        add_audit_log(
            "EXECUTIVE_REPLACED",
            "ExecutiveAppointment",
            replacement.id,
            f"{old_user.fullname} replaced by {new_user.fullname} as {appointment.role}; effective {effective_date.isoformat()}.",
            cooperative_id=appointment.cooperative_id,
        )
        db.session.commit()
        return redirect(url_for("executives_list"))

    return render_optional_template(
        "executive_replace_form.html",
        "Replace Executive",
        appointment=appointment,
        users=users,
        today=crm_today(),
    )


@app.route("/executives/deactivate/<int:appointment_id>", methods=["POST"])
@roles_required("Admin")
def deactivate_executive(appointment_id):
    """Deactivate an executive appointment and retain it as historical evidence."""
    appointment = db.session.get(ExecutiveAppointment, appointment_id)
    if not appointment:
        abort(404)
    if appointment.status != "Active":
        return "This executive appointment is already inactive.", 400

    end_raw = request.form.get("end_date", "").strip()
    try:
        end_date = parse_date(end_raw) if end_raw else utc_now().date()
    except ValueError:
        return "Please enter a valid executive end date.", 400

    try:
        close_executive_appointment(
            appointment,
            end_date=end_date,
            ended_by_user_id=session.get("user_id"),
        )
    except ValueError as exc:
        return str(exc), 400

    access = get_user_access(appointment.user_id)
    if access.role == appointment.role and access.cooperative_id == appointment.cooperative_id:
        access.status = "Inactive"

    add_audit_log(
        "EXECUTIVE_DEACTIVATED",
        "ExecutiveAppointment",
        appointment.id,
        f"{appointment.user.fullname} ended service as {appointment.role} on {end_date.isoformat()}.",
        cooperative_id=appointment.cooperative_id,
    )
    db.session.commit()
    return redirect(url_for("executives_list"))


@app.route("/executives/history")
@roles_required("Admin")
def executive_history():
    """View the appointment history without overwriting former office holders."""
    cooperative_id = parse_int(request.args.get("cooperative_id"))
    role = request.args.get("role", "").strip()
    user_id = parse_int(request.args.get("user_id"))

    query = ExecutiveAppointment.query
    if cooperative_id:
        query = query.filter(ExecutiveAppointment.cooperative_id == cooperative_id)
    if role in COOPERATIVE_EXECUTIVE_ROLES:
        query = query.filter(ExecutiveAppointment.role == role)
    if user_id:
        query = query.filter(ExecutiveAppointment.user_id == user_id)

    appointments = query.order_by(
        ExecutiveAppointment.start_date.desc(),
        ExecutiveAppointment.created_at.desc(),
    ).all()

    cooperatives = Cooperative.query.order_by(Cooperative.name.asc()).all()
    users = User.query.order_by(User.fullname.asc()).all()

    return render_optional_template(
        "executive_history.html",
        "Executive History",
        appointments=appointments,
        cooperatives=cooperatives,
        users=users,
        valid_roles=sorted(COOPERATIVE_EXECUTIVE_ROLES),
        selected_cooperative_id=cooperative_id,
        selected_role=role,
        selected_user_id=user_id,
    )


@app.route("/users")
@roles_required("Admin")
def users_list():
    """Admin-only CRM user and access management."""
    search = request.args.get("search", "").strip()

    query = accessible_users_query()

    if search:
        query = query.filter(
            or_(
                User.fullname.ilike(f"%{search}%"),
                User.email.ilike(f"%{search}%"),
                User.phone.ilike(f"%{search}%"),
            )
        )

    users = query.order_by(User.created_at.desc()).all()

    access_map = {
        user.id: get_user_access(user.id)
        for user in users
    }

    cooperatives = (
        Cooperative.query
        .order_by(
            Cooperative.cooperative_type.desc(),
            Cooperative.name.asc(),
        )
        .all()
    )

    return render_optional_template(
        "users.html",
        "User Management",
        users=users,
        access_map=access_map,
        cooperatives=cooperatives,
        valid_roles=sorted(VALID_ACCESS_ROLES),
        search=search,
    )


@app.route("/users/add", methods=["GET", "POST"])
@roles_required("Admin")
def add_user():
    """Admin creates a CRM login and assigns its role/access."""
    cooperatives = Cooperative.query.order_by(
        Cooperative.cooperative_type.desc(),
        Cooperative.name.asc(),
    ).all()

    if request.method == "POST":
        fullname = request.form.get("fullname", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip().lower()
        farm_location = request.form.get("farm_location", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        role = request.form.get("role", "").strip()
        status = request.form.get("status", "Active").strip()
        cooperative_id = parse_int(request.form.get("cooperative_id"))

        if not all([fullname, phone, email, farm_location, password, confirm_password]):
            return "Please complete all required user fields.", 400

        if len(password) < 8:
            return "Temporary password must be at least 8 characters.", 400

        if password != confirm_password:
            return "Passwords do not match.", 400

        if User.query.filter(func.lower(User.email) == email.lower()).first():
            return "An account with this email already exists.", 400

        cooperative, assignment_error = validate_admin_user_assignment(
            role,
            status,
            cooperative_id,
        )
        if assignment_error:
            return assignment_error, 400

        if role == "Admin":
            cooperative_id = None
        else:
            cooperative_id = cooperative.id

        user = User(
            fullname=fullname,
            phone=phone,
            email=email,
            farm_location=farm_location,
            password=generate_password_hash(password),
        )
        db.session.add(user)
        db.session.flush()

        access = UserAccess(
            user_id=user.id,
            role=role,
            status=status,
            cooperative_id=cooperative_id,
        )
        db.session.add(access)

        if role in COOPERATIVE_EXECUTIVE_ROLES and status == "Active":
            appointment = create_executive_appointment(
                user,
                cooperative,
                role,
                start_date=utc_now().date(),
                appointed_by_user_id=session.get("user_id"),
                notes="Initial executive appointment created with CRM user.",
            )
            db.session.flush()
            add_audit_log(
                "EXECUTIVE_ASSIGNED",
                "ExecutiveAppointment",
                appointment.id,
                f"{user.fullname} appointed as {role} for {cooperative.name}.",
                cooperative_id=cooperative.id,
            )

        add_audit_log(
            "CREATE",
            "User",
            user.id,
            f"Admin created CRM user {email} / {role} / {status}",
            cooperative_id=cooperative_id,
        )

        db.session.commit()
        return redirect(url_for("users_list"))

    return render_optional_template(
        "user_form.html",
        "Add CRM User",
        user=None,
        access=None,
        cooperatives=cooperatives,
        valid_roles=sorted(VALID_ACCESS_ROLES),
    )


@app.route("/users/edit/<int:user_id>", methods=["GET", "POST"])
@roles_required("Admin")
def edit_user(user_id):
    """Admin edits a CRM user's identity/contact details."""
    user = db.session.get(User, user_id)
    if not user:
        abort(404)

    access = get_user_access(user.id)

    if request.method == "POST":
        fullname = request.form.get("fullname", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip().lower()
        farm_location = request.form.get("farm_location", "").strip()

        if not all([fullname, phone, email, farm_location]):
            return "Name, phone, email and location are required.", 400

        duplicate = User.query.filter(
            func.lower(User.email) == email.lower(),
            User.id != user.id,
        ).first()

        if duplicate:
            return "Another CRM user already uses this email address.", 400

        user.fullname = fullname
        user.phone = phone
        user.email = email
        user.farm_location = farm_location

        if user.id == session.get("user_id"):
            session["fullname"] = user.fullname

        add_audit_log(
            "UPDATE",
            "User",
            user.id,
            f"Admin updated CRM user details: {user.email}",
            cooperative_id=access.cooperative_id if access else None,
        )
        db.session.commit()
        return redirect(url_for("users_list"))

    return render_optional_template(
        "user_form.html",
        "Edit CRM User",
        user=user,
        access=access,
        cooperatives=[],
        valid_roles=[],
    )


@app.route("/users/reset-password/<int:user_id>", methods=["GET", "POST"])
@roles_required("Admin")
def reset_user_password(user_id):
    """Admin resets a CRM user's password."""
    user = db.session.get(User, user_id)
    if not user:
        abort(404)

    access = get_user_access(user.id)

    if request.method == "POST":
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if len(new_password) < 8:
            return "New password must be at least 8 characters.", 400

        if new_password != confirm_password:
            return "Passwords do not match.", 400

        user.password = generate_password_hash(new_password)

        add_audit_log(
            "ADMIN_PASSWORD_RESET",
            "User",
            user.id,
            f"Admin reset password for {user.email}",
            cooperative_id=access.cooperative_id if access else None,
        )
        db.session.commit()
        return redirect(url_for("users_list"))

    return render_optional_template(
        "user_password_form.html",
        "Reset User Password",
        user=user,
        access=access,
    )


@app.route("/users/reset-2fa/<int:user_id>", methods=["POST"])
@roles_required("Admin")
def reset_user_two_factor(user_id):
    """Admin resets another user's Google Authenticator enrollment."""
    user = db.session.get(User, user_id)
    if not user:
        abort(404)

    if user.id == session.get("user_id"):
        return (
            "You cannot reset your own Google Authenticator enrollment from the Admin page. "
            "Use your recovery codes, or use the trusted reset_user_2fa.py maintenance script if both are lost.",
            400,
        )

    access = get_user_access(user.id)
    clear_user_two_factor(user)
    add_audit_log(
        "TWO_FACTOR_ADMIN_RESET",
        "User",
        user.id,
        f"Admin reset Google Authenticator enrollment for {user.email}.",
        cooperative_id=access.cooperative_id if access else None,
    )
    db.session.commit()
    return redirect(url_for("users_list"))


@app.route("/users/access/<int:user_id>", methods=["POST"])
@roles_required("Admin")
def update_user_access(user_id):
    """Admin updates a CRM user's role, cooperative and account status."""
    user = db.session.get(User, user_id)
    if not user:
        abort(404)

    # Protect the currently signed-in Admin from accidentally locking
    # themselves out of the CRM.
    if user.id == session.get("user_id"):
        return (
            "You cannot change your own Admin access assignment while signed in. "
            "Use another Admin account if this assignment must be changed.",
            400,
        )

    access = get_user_access(user.id)

    role = request.form.get("role", "").strip()
    status = request.form.get("status", "Active").strip()
    cooperative_id = parse_int(request.form.get("cooperative_id"))

    cooperative, assignment_error = validate_admin_user_assignment(
        role,
        status,
        cooperative_id,
        exclude_user_id=user.id,
    )
    if assignment_error:
        return assignment_error, 400

    if role == "Admin":
        cooperative_id = None
    else:
        cooperative_id = cooperative.id

    old_role = access.role
    old_status = access.status
    old_cooperative_id = access.cooperative_id

    sync_access_to_executive_history(
        user,
        access,
        old_role,
        old_status,
        old_cooperative_id,
        role,
        status,
        cooperative_id,
    )

    access.role = role
    access.status = status
    access.cooperative_id = cooperative_id

    if (old_role, old_status, old_cooperative_id) != (role, status, cooperative_id):
        if old_role in COOPERATIVE_EXECUTIVE_ROLES and role in COOPERATIVE_EXECUTIVE_ROLES:
            executive_action = "EXECUTIVE_ROLE_CHANGED"
        elif old_role in COOPERATIVE_EXECUTIVE_ROLES and status != "Active":
            executive_action = "EXECUTIVE_DEACTIVATED"
        elif role in COOPERATIVE_EXECUTIVE_ROLES and status == "Active":
            executive_action = "EXECUTIVE_ASSIGNED"
        else:
            executive_action = None

        if executive_action:
            add_audit_log(
                executive_action,
                "User",
                user.id,
                f"{user.fullname}: {old_role}/{old_status} -> {role}/{status}.",
                cooperative_id=cooperative_id or old_cooperative_id,
            )

    add_audit_log(
        "ACCESS_UPDATE",
        "User",
        user.id,
        f"{role} / {status} / cooperative={cooperative_id or 'SYSTEM'}",
        cooperative_id=cooperative_id,
    )

    db.session.commit()
    return redirect(url_for("users_list"))


# =========================================================
# ROUTES - AUDIT LOGS
# =========================================================
@app.route("/audit-logs")
@roles_required("Admin")
def audit_logs():
    """View audit logs."""
    logs = scoped_model_query(AuditLog).order_by(
        AuditLog.created_at.desc()
    ).limit(500).all()

    return render_optional_template("audit_logs.html", "Audit Logs", logs=logs)


# =========================================================
# ROUTES - CSV EXPORTS
# =========================================================
@app.route("/exports/farmers.csv")
@roles_required(*FARMER_VIEW_ROLES)
def export_farmers():
    """Export farmers to CSV."""
    rows = scoped_model_query(Farmer).order_by(Farmer.fullname.asc()).all()
    return make_csv_response(
        "farmers.csv",
        ["ID", "Full Name", "Cooperative", "Phone", "Email", "Location", "Registered Farms", "Status"],
        [[
            r.id,
            r.fullname,
            r.cooperative.name if r.cooperative else "",
            r.phone,
            r.email or "",
            r.location,
            len(r.farms),
            r.status,
        ] for r in rows],
    )


@app.route("/exports/farms.csv")
@roles_required(*AGRICULTURE_VIEW_ROLES)
def export_farms():
    """Export farms to CSV."""
    rows = scoped_model_query(Farm).order_by(Farm.name.asc()).all()
    return make_csv_response(
        "farms.csv",
        ["ID", "Farm Name", "Cooperative", "Farmer", "Location", "Size", "Farming Type", "Crop Records", "Status"],
        [[
            r.id,
            r.name,
            r.cooperative.name if r.cooperative else "",
            r.farmer.fullname,
            r.location,
            r.size or "",
            r.farming_type or "",
            len(r.crops),
            r.status,
        ] for r in rows],
    )


@app.route("/exports/crops.csv")
@roles_required(*AGRICULTURE_VIEW_ROLES)
def export_crops():
    """Export crops to CSV."""
    rows = scoped_model_query(Crop).order_by(Crop.created_at.desc()).all()
    return make_csv_response(
        "crops.csv",
        ["ID", "Crop", "Farm", "Farmer", "Variety", "Planting Date", "Expected Harvest", "Area Planted", "Status"],
        [[
            r.id,
            r.name,
            r.farm.name,
            r.farm.farmer.fullname,
            r.variety or "",
            r.planting_date or "",
            r.expected_harvest_date or "",
            r.area_planted or "",
            r.status
        ] for r in rows]
    )


@app.route("/exports/harvests.csv")
@roles_required(*AGRICULTURE_VIEW_ROLES)
def export_harvests():
    """Export harvests to CSV."""
    rows = scoped_model_query(Harvest).order_by(Harvest.harvest_date.desc()).all()
    return make_csv_response(
        "harvests.csv",
        ["ID", "Crop", "Farm", "Harvest Date", "Quantity", "Unit", "Quality Grade", "Storage", "Status"],
        [[
            r.id,
            r.crop.name,
            r.crop.farm.name,
            r.harvest_date,
            r.quantity,
            r.unit,
            r.quality_grade or "",
            r.storage_location or "",
            r.status
        ] for r in rows]
    )


@app.route("/exports/sales.csv")
@roles_required(*BUSINESS_VIEW_ROLES)
def export_sales():
    """Export sales to CSV."""
    rows = scoped_model_query(Sale).order_by(Sale.sale_date.desc()).all()
    return make_csv_response(
        "sales.csv",
        ["ID", "Sale Date", "Buyer", "Phone", "Crop", "Quantity", "Unit", "Price Per Unit", "Total Amount", "Paid",
         "Outstanding", "Status"],
        [[
            r.id,
            r.sale_date,
            r.buyer_name,
            r.buyer_phone or "",
            r.harvest.crop.name,
            r.quantity,
            r.unit,
            r.price_per_unit,
            r.total_amount,
            sale_paid_amount(r),
            sale_outstanding_amount(r),
            r.status
        ] for r in rows]
    )


@app.route("/exports/payments.csv")
@roles_required(*BUSINESS_VIEW_ROLES)
def export_payments():
    """Export payments to CSV."""
    rows = scoped_model_query(Payment).order_by(Payment.payment_date.desc()).all()
    return make_csv_response(
        "payments.csv",
        ["ID", "Payment Date", "Buyer", "Amount", "Method", "Reference", "Status"],
        [[
            r.id,
            r.payment_date,
            r.sale.buyer_name,
            r.amount,
            r.method or "",
            r.reference or "",
            r.status
        ] for r in rows]
    )


@app.route("/exports/expenses.csv")
@roles_required(*FINANCE_VIEW_ROLES)
def export_expenses():
    """Export expenses to CSV."""
    rows = scoped_model_query(Expense).order_by(Expense.expense_date.desc()).all()
    return make_csv_response(
        "expenses.csv",
        ["ID", "Expense Date", "Category", "Description", "Farm", "Supplier", "Amount", "Payment Method", "Reference",
         "Status"],
        [[
            r.id,
            r.expense_date,
            r.category,
            r.description,
            r.farm.name if r.farm else "",
            r.supplier.name if r.supplier else "",
            r.amount,
            r.payment_method or "",
            r.reference or "",
            r.status
        ] for r in rows]
    )


# =========================================================
# ROUTES - SYSTEM ADMINISTRATION
# =========================================================
@app.route("/admin/security/2fa-policy", methods=["POST"])
@roles_required("Admin")
def admin_two_factor_policy():
    """Temporarily disable or reactivate mandatory 2FA for all CRM accounts."""
    action = request.form.get("action", "").strip().lower()
    if action not in {"enable", "disable"}:
        return "Choose whether to enable or disable two-factor authentication.", 400

    settings_data = load_system_settings()
    previous = bool(settings_data.get("two_factor_required", True))
    enabled = action == "enable"

    # The environment switch is still the top-level safety control. If it is
    # disabled, the web UI cannot claim that 2FA has been reactivated.
    if enabled and not app.config.get("TWO_FACTOR_REQUIRED", True):
        return (
            "Two-factor authentication is disabled by the TWO_FACTOR_REQUIRED environment setting. "
            "Set TWO_FACTOR_REQUIRED=true and restart the CRM before enabling it here.",
            400,
        )

    settings_data["two_factor_required"] = enabled
    save_system_settings(settings_data)

    if enabled:
        # Ensure the Admin who reactivates 2FA is challenged again on the next
        # protected request unless this session already completed real 2FA.
        if session.get("two_factor_bypassed"):
            session["two_factor_authenticated"] = False
    else:
        # Do not clear anyone's enrollment. This flag only pauses enforcement.
        session["two_factor_bypassed"] = True

    if previous != enabled:
        action_name = "TWO_FACTOR_GLOBAL_ENABLED" if enabled else "TWO_FACTOR_GLOBAL_DISABLED"
        detail = (
            "Admin reactivated mandatory Google Authenticator 2FA for all CRM accounts."
            if enabled
            else "Admin temporarily disabled mandatory Google Authenticator 2FA for all CRM accounts for testing."
        )
        add_audit_log(action_name, "SystemSecurity", details=detail)
        db.session.commit()

    return redirect(url_for("admin_security"))


@app.route("/admin/security")
@roles_required("Admin")
def admin_security():
    """Admin-only security and account activity dashboard."""
    security_actions = (
        "LOGIN_SUCCESS",
        "LOGIN_FAILED",
        "LOGIN_DENIED",
        "LOGIN_RATE_LIMITED",
        "TWO_FACTOR_CHALLENGE",
        "TWO_FACTOR_ENROLLMENT_REQUIRED",
        "TWO_FACTOR_ENABLED",
        "TWO_FACTOR_SETUP_FAILED",
        "TWO_FACTOR_SUCCESS",
        "TWO_FACTOR_FAILED",
        "TWO_FACTOR_RATE_LIMITED",
        "TWO_FACTOR_RECOVERY_USED",
        "TWO_FACTOR_RECOVERY_REGENERATED",
        "TWO_FACTOR_ADMIN_RESET",
        "TWO_FACTOR_TRUSTED_RESET",
        "TWO_FACTOR_GLOBAL_DISABLED",
        "TWO_FACTOR_GLOBAL_ENABLED",
        "LOGOUT",
        "PASSWORD_CHANGE",
        "ADMIN_PASSWORD_RESET",
        "ACCESS_UPDATE",
    )

    security_logs = AuditLog.query.filter(
        AuditLog.action.in_(security_actions)
    ).order_by(AuditLog.created_at.desc()).limit(150).all()

    return render_optional_template(
        "admin_security.html",
        "Security",
        security_logs=security_logs,
        active_users=UserAccess.query.filter_by(status="Active").count(),
        inactive_users=UserAccess.query.filter_by(status="Inactive").count(),
        admin_users=UserAccess.query.filter_by(role="Admin", status="Active").count(),
        failed_logins=AuditLog.query.filter_by(action="LOGIN_FAILED").count(),
        denied_logins=AuditLog.query.filter_by(action="LOGIN_DENIED").count(),
        rate_limited_logins=AuditLog.query.filter_by(action="LOGIN_RATE_LIMITED").count(),
        two_factor_enabled_users=User.query.join(UserAccess, UserAccess.user_id == User.id).filter(
            UserAccess.status == "Active", User.two_factor_enabled.is_(True)
        ).count(),
        two_factor_pending_users=User.query.join(UserAccess, UserAccess.user_id == User.id).filter(
            UserAccess.status == "Active", User.two_factor_enabled.is_(False)
        ).count(),
        two_factor_failures=AuditLog.query.filter(
            AuditLog.action.in_(("TWO_FACTOR_FAILED", "TWO_FACTOR_RATE_LIMITED"))
        ).count(),
        two_factor_policy_enabled=two_factor_policy_enabled(),
        two_factor_environment_enabled=bool(app.config.get("TWO_FACTOR_REQUIRED", True)),
    )


@app.route("/admin/backup-restore")
@roles_required("Admin")
def admin_backup_restore():
    """Admin-only Backup & Restore page."""
    database_backend = db.engine.url.get_backend_name()
    return render_optional_template(
        "admin_backup_restore.html",
        "Backup & Restore",
        database_backend=database_backend,
        backups=list_database_backups() if database_backend == "sqlite" else [],
    )


@app.route("/admin/backup-create", methods=["POST"])
@roles_required("Admin")
def admin_backup_create():
    """Create a saved SQLite backup."""
    if db.engine.url.get_backend_name() != "sqlite":
        return "Built-in backup creation is currently available only for SQLite.", 400

    try:
        backup_path = create_database_backup_copy()
    except Exception as exc:
        return f"Backup could not be created: {exc}", 500

    add_audit_log(
        "BACKUP_CREATE",
        "System",
        details=f"Created database backup {backup_path.name}.",
    )
    db.session.commit()
    return redirect(url_for("admin_backup_restore"))


@app.route("/admin/backup-download/<path:backup_name>")
@roles_required("Admin")
def admin_backup_download(backup_name):
    """Download a saved backup."""
    safe_name = Path(backup_name).name
    backup_path = backup_directory() / safe_name

    if not backup_path.exists() or backup_path.parent != backup_directory():
        abort(404)

    return send_file(
        backup_path,
        as_attachment=True,
        download_name=safe_name,
    )


@app.route("/admin/backup-delete/<path:backup_name>", methods=["POST"])
@roles_required("Admin")
def admin_backup_delete(backup_name):
    """Delete a stored backup file."""
    safe_name = Path(backup_name).name
    backup_path = backup_directory() / safe_name

    if not backup_path.exists() or backup_path.parent != backup_directory():
        abort(404)

    add_audit_log(
        "BACKUP_DELETE",
        "System",
        details=f"Deleted stored backup {safe_name}.",
    )
    db.session.commit()
    backup_path.unlink()
    return redirect(url_for("admin_backup_restore"))


@app.route("/admin/backup-restore/<path:backup_name>", methods=["POST"])
@roles_required("Admin")
def admin_backup_restore_file(backup_name):
    """Restore the local SQLite database from a stored verified backup."""
    if db.engine.url.get_backend_name() != "sqlite":
        return "Built-in restore is currently available only for SQLite.", 400

    confirmation = request.form.get("confirmation", "").strip()
    if confirmation != "RESTORE":
        return 'Type RESTORE exactly to confirm the database restore.', 400

    safe_name = Path(backup_name).name
    backup_path = backup_directory() / safe_name

    if not backup_path.exists() or backup_path.parent != backup_directory():
        abort(404)

    valid, validation_error = validate_sqlite_backup(backup_path)
    if not valid:
        return validation_error or "Backup validation failed.", 400

    database_path = sqlite_database_path()
    if not database_path:
        return "Current SQLite database file could not be resolved.", 500

    # Always create a safety copy immediately before restoring.
    try:
        create_database_backup_copy(prefix="pre_restore_backup")
    except Exception as exc:
        return f"Restore stopped because the safety backup failed: {exc}", 500

    temporary_restore = database_path.with_suffix(".restore.tmp")

    try:
        db.session.remove()
        db.engine.dispose()
        shutil.copy2(backup_path, temporary_restore)
        os.replace(temporary_restore, database_path)
    except Exception as exc:
        if temporary_restore.exists():
            temporary_restore.unlink(missing_ok=True)
        return f"Database restore failed: {exc}", 500

    # Current session may no longer exist in the restored snapshot.
    session.clear()
    return redirect(url_for("login"))


@app.route("/admin/system-health")
@roles_required("Admin")
def admin_system_health():
    """Admin-only application/database health overview."""
    database_ok = True
    database_error = None

    try:
        db.session.execute(sql_text("SELECT 1"))
    except Exception as exc:
        database_ok = False
        database_error = str(exc)

    backend = db.engine.url.get_backend_name()
    database_path = sqlite_database_path()
    database_size_mb = None

    if database_path and database_path.exists():
        database_size_mb = round(database_path.stat().st_size / (1024 * 1024), 2)

    checks = [
        {
            "name": "Database Connection",
            "status": "Healthy" if database_ok else "Problem",
            "details": database_error or f"{backend} connection responded successfully."
        },
        {
            "name": "Admin Account",
            "status": "Healthy" if UserAccess.query.filter_by(role="Admin", status="Active").count() > 0 else "Problem",
            "details": "At least one active system Admin is required."
        },
        {
            "name": "Secret Key",
            "status": "Warning" if app.config["SECRET_KEY"] == "malenge-farmers-development-key" else "Healthy",
            "details": "Set SECRET_KEY in the production environment." if app.config["SECRET_KEY"] == "malenge-farmers-development-key" else "Custom SECRET_KEY is configured."
        },
        {
            "name": "Database Mode",
            "status": "Warning" if backend == "sqlite" else "Healthy",
            "details": "SQLite is suitable for local V1. PostgreSQL is recommended for production." if backend == "sqlite" else "Production database backend detected."
        },
    ]

    return render_optional_template(
        "admin_system_health.html",
        "System Health",
        checks=checks,
        database_backend=backend,
        database_size_mb=database_size_mb,
        python_version=platform.python_version(),
        operating_system=platform.platform(),
        user_count=User.query.count(),
        cooperative_count=Cooperative.query.count(),
        audit_count=AuditLog.query.count(),
        backup_count=len(list_database_backups()),
        generated_at=datetime.now(),
    )


@app.route("/admin/data-exports")
@roles_required("Admin")
def admin_data_exports():
    """Admin-only system-wide data export centre."""
    datasets = [
        ("users", "Users & Access", "CRM login holders, roles, status and cooperative assignments."),
        ("cooperatives", "Cooperative Structure", "Secondary and Primary cooperative structure."),
        ("executive-history", "Executive History", "Current and former executive appointments across all cooperatives."),
        ("audit-logs", "Audit Logs", "Complete recorded CRM activity."),
        ("memberships", "Memberships", "System-wide membership register."),
        ("farmers", "Farmers", "All farmer records."),
        ("farms", "Farms", "All registered farms."),
        ("crops", "Crops", "All crop records."),
        ("harvests", "Harvests", "All harvest records."),
        ("sales", "Sales", "All sale records."),
        ("payments", "Payments", "All sale payment records."),
        ("contributions", "Contributions", "All contribution records."),
        ("expenses", "Expenses", "All expense records."),
    ]
    return render_optional_template(
        "admin_data_exports.html",
        "Data Exports",
        datasets=datasets,
    )


@app.route("/admin/export/<dataset>.csv")
@roles_required("Admin")
def admin_export_dataset(dataset):
    """Download one system-wide Admin dataset as CSV."""
    export_data = admin_export_rows(dataset)

    if export_data is None:
        abort(404)

    headers, rows = export_data
    add_audit_log(
        "DATA_EXPORT",
        "System",
        details=f"Exported system-wide dataset: {dataset}.",
    )
    db.session.commit()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return make_csv_response(
        f"malenge_{dataset}_{timestamp}.csv",
        headers,
        rows,
    )


@app.route("/admin/role-permissions")
@roles_required("Admin")
def admin_role_permissions():
    """Admin-only role responsibility overview."""
    return render_optional_template(
        "admin_role_permissions.html",
        "Role Permissions",
        permission_matrix=ROLE_PERMISSION_MATRIX,
    )


@app.route("/admin/system-settings", methods=["GET", "POST"])
@roles_required("Admin")
def admin_system_settings():
    """Admin-only safe global CRM settings."""
    settings_data = load_system_settings()

    if request.method == "POST":
        brand_name = request.form.get("brand_name", "").strip()
        product_name = request.form.get("product_name", "").strip()
        organization_name = request.form.get("organization_name", "").strip()
        developer_name = request.form.get("developer_name", "").strip()
        support_email = request.form.get("support_email", "").strip()
        default_location = request.form.get("default_location", "").strip()
        maintenance_notice = request.form.get("maintenance_notice", "").strip()
        timeout = parse_int(request.form.get("session_timeout_minutes"))

        if not all([brand_name, product_name, organization_name, developer_name]):
            return "Brand, product, organization and developer names are required.", 400

        if timeout is None or timeout < 15 or timeout > 1440:
            return "Session timeout must be between 15 and 1440 minutes.", 400

        settings_data = {
            "brand_name": brand_name[:80],
            "product_name": product_name[:100],
            "organization_name": organization_name[:120],
            "developer_name": developer_name[:120],
            "support_email": support_email[:150],
            "default_location": default_location[:150],
            "session_timeout_minutes": timeout,
            "maintenance_notice": maintenance_notice[:500],
            "two_factor_required": bool(settings_data.get("two_factor_required", True)),
        }

        save_system_settings(settings_data)
        apply_session_timeout()

        add_audit_log(
            "SYSTEM_SETTINGS_UPDATE",
            "System",
            details="Admin updated non-secret CRM system settings.",
        )
        db.session.commit()
        return redirect(url_for("admin_system_settings"))

    return render_optional_template(
        "admin_system_settings.html",
        "System Settings",
        settings_data=settings_data,
    )


# Backward-compatible direct backup URL.
@app.route("/admin/database-backup")
@roles_required("Admin")
def database_backup():
    """Create and immediately download a SQLite database backup."""
    if db.engine.url.get_backend_name() != "sqlite":
        return "Automatic file backup is currently available only for SQLite.", 400

    try:
        backup_path = create_database_backup_copy()
    except Exception as exc:
        return f"Backup could not be created: {exc}", 500

    add_audit_log(
        "BACKUP_CREATE",
        "System",
        details=f"Created and downloaded database backup {backup_path.name}.",
    )
    db.session.commit()

    return send_file(
        backup_path,
        as_attachment=True,
        download_name=backup_path.name,
    )


# =========================================================
# ERROR HANDLERS
# =========================================================
@app.errorhandler(400)
def bad_request(error):
    """Handle bad requests, including CSRF validation failures."""
    message = getattr(error, "description", None) or "The request could not be completed because some information is invalid."
    return _render_branded_error(400, "Please check the information", message), 400


@app.errorhandler(401)
def unauthorized(error):
    """Handle unauthenticated requests."""
    message = getattr(error, "description", None) or "Please sign in with an authorized Malenge Farmers CRM account."
    return _render_branded_error(401, "Sign-in required", message), 401


@app.errorhandler(403)
def forbidden(error):
    """Handle permission failures."""
    message = getattr(error, "description", None) or "You do not have permission to access this page."
    return _render_branded_error(403, "Access denied", message), 403


@app.errorhandler(404)
def page_not_found(_error):
    """Handle unknown routes."""
    return _render_branded_error(404, "Page not found", "The requested page was not found."), 404


@app.errorhandler(413)
def request_too_large(_error):
    """Handle requests larger than the configured application limit."""
    return _render_branded_error(
        413,
        "Request too large",
        "The submitted request is larger than the CRM allows.",
    ), 413


@app.errorhandler(429)
def too_many_requests(error):
    """Handle authentication throttling and other rate limits."""
    message = getattr(error, "description", None) or "Too many requests were received. Please wait and try again."
    return _render_branded_error(429, "Too many attempts", message), 429


@app.errorhandler(500)
def internal_error(_error):
    """Handle unexpected server failures without exposing internals."""
    db.session.rollback()
    return _render_branded_error(
        500,
        "Something went wrong",
        "An internal server error occurred. Please try again.",
    ), 500


# =========================================================
# PHASE 7 COOPERATIVE OPERATIONS SUITE
# =========================================================
# Imported after the core models/helpers/routes are defined so Phase 7 can
# extend the CRM without creating circular initialization problems.
from phase7 import register_phase7
register_phase7(app)


# =========================================================
# RUN APPLICATION
# =========================================================
if __name__ == "__main__":
    app.run(debug=False, port=5050)
