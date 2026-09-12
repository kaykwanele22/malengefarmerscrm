"""Phase 7 cooperative operations suite for Malenge Farmers CRM.

Adds role inboxes, notifications, controlled documents, finance planning and
reconciliation, richer meeting records, production costing, equipment usage,
reporting, global search and a scoped read API without weakening the Phase 6
separation-of-duties model.
"""
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path
import hashlib
import os
import secrets
import uuid

from flask import (
    Blueprint, abort, flash, g, jsonify, redirect, render_template, request,
    send_file, session, url_for,
)
from sqlalchemy import func, or_
from werkzeug.utils import secure_filename

import importlib
import sys

_CORE_NAMES = (
    "db", "User", "UserAccess", "Cooperative", "Farmer", "Farm", "Crop", "Harvest", "Sale", "Payment",
    "Expense", "Contribution", "Membership", "Meeting", "Resolution", "Task", "InventoryItem",
    "Equipment", "AuditLog", "COOPERATIVE_EXECUTIVE_ROLES", "GOVERNANCE_VIEW_ROLES", "MEETING_RECORD_ROLES",
    "FINANCE_RECORD_ROLES", "FINANCE_APPROVAL_ROLES", "FINANCE_VIEW_ROLES", "OPERATIONS_RECORD_ROLES",
    "OPERATIONS_VIEW_ROLES", "MEMBERSHIP_VIEW_ROLES", "ACCOUNTABILITY_VERIFY_ROLES",
    "CONFIRMED_EXPENSE_STATUSES", "CONFIRMED_CONTRIBUTION_STATUSES", "PAYMENT_VALUE_STATUSES",
    "current_access", "current_cooperative", "current_user", "accessible_cooperative_ids", "can_access_cooperative",
    "scoped_model_query", "scoped_get", "scoped_get_or_404", "own_cooperative_query", "own_cooperative_id",
    "require_own_cooperative", "login_required", "roles_required", "add_audit_log", "utc_now", "crm_today",
    "parse_int", "parse_float", "parse_date", "list_database_backups", "two_factor_policy_enabled",
)
_core = sys.modules.get("__main__")
if _core is None or not hasattr(_core, "db"):
    _core = importlib.import_module("app")
for _name in _CORE_NAMES:
    globals()[_name] = getattr(_core, _name)

bp = Blueprint("phase7", __name__)

DOCUMENT_UPLOAD_DIR = Path(
    os.getenv("DOCUMENT_UPLOAD_DIR", str(Path(_core.app.instance_path) / "documents"))
).expanduser().resolve()
DOCUMENT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DOCUMENT_ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "webp", "docx", "xlsx", "csv", "txt"}

DOCUMENT_TYPES = (
    "Constitution", "Cooperative Certificate", "Land Document", "Contract",
    "Quotation", "Invoice", "Receipt", "Proof of Payment", "Meeting Record",
    "Financial Document", "Membership Document", "Production Document", "Joint Operations Document", "General",
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class Notification(db.Model):
    __tablename__ = "notification"

    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    category = db.Column(db.String(50), nullable=False, index=True)
    title = db.Column(db.String(180), nullable=False)
    message = db.Column(db.String(500), nullable=False)
    severity = db.Column(db.String(20), default="Info", nullable=False)
    link = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(20), default="Unread", nullable=False, index=True)
    due_date = db.Column(db.Date, nullable=True)
    source_type = db.Column(db.String(60), nullable=True)
    source_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False, index=True)
    read_at = db.Column(db.DateTime, nullable=True)

    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id])
    user = db.relationship("User", foreign_keys=[user_id])


class CooperativeDocument(db.Model):
    __tablename__ = "cooperative_document"

    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False, index=True)
    document_type = db.Column(db.String(80), nullable=False, index=True)
    title = db.Column(db.String(180), nullable=False)
    entity_type = db.Column(db.String(60), nullable=True)
    entity_id = db.Column(db.Integer, nullable=True)
    original_name = db.Column(db.String(255), nullable=False)
    stored_name = db.Column(db.String(255), nullable=False, unique=True)
    file_sha256 = db.Column(db.String(64), nullable=False)
    uploaded_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False, index=True)

    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id])
    uploaded_by_user = db.relationship("User", foreign_keys=[uploaded_by_user_id])


class Budget(db.Model):
    __tablename__ = "budget"
    __table_args__ = (
        db.UniqueConstraint("cooperative_id", "fiscal_year", "budget_type", "category", name="uq_budget_scope"),
    )

    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False, index=True)
    fiscal_year = db.Column(db.Integer, nullable=False, index=True)
    budget_type = db.Column(db.String(30), nullable=False)  # Expense / Contribution / Sales Receipts
    category = db.Column(db.String(100), nullable=False)
    planned_amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(30), default="Pending Approval", nullable=False)
    notes = db.Column(db.Text, nullable=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    approved_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)

    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id])
    created_by = db.relationship("User", foreign_keys=[created_by_user_id])
    approved_by = db.relationship("User", foreign_keys=[approved_by_user_id])


class BankReconciliation(db.Model):
    __tablename__ = "bank_reconciliation"

    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False, index=True)
    statement_date = db.Column(db.Date, nullable=False, index=True)
    statement_balance = db.Column(db.Float, nullable=False)
    book_balance = db.Column(db.Float, nullable=False)
    difference = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(30), default="Pending Review", nullable=False)
    notes = db.Column(db.Text, nullable=True)
    prepared_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    reviewed_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)

    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id])
    prepared_by = db.relationship("User", foreign_keys=[prepared_by_user_id])
    reviewed_by = db.relationship("User", foreign_keys=[reviewed_by_user_id])


class MeetingAgendaItem(db.Model):
    __tablename__ = "meeting_agenda_item"
    __table_args__ = (
        db.UniqueConstraint("meeting_id", "item_number", name="uq_meeting_agenda_number"),
    )

    id = db.Column(db.Integer, primary_key=True)
    meeting_id = db.Column(db.Integer, db.ForeignKey("meeting.id", ondelete="CASCADE"), nullable=False, index=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False, index=True)
    item_number = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(180), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(30), default="Open", nullable=False)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)

    meeting = db.relationship("Meeting", backref=db.backref("agenda_items", cascade="all, delete-orphan", order_by="MeetingAgendaItem.item_number"))
    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id])
    created_by = db.relationship("User", foreign_keys=[created_by_user_id])


class MeetingAttendance(db.Model):
    __tablename__ = "meeting_attendance"

    id = db.Column(db.Integer, primary_key=True)
    meeting_id = db.Column(db.Integer, db.ForeignKey("meeting.id", ondelete="CASCADE"), nullable=False, index=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    attendee_name = db.Column(db.String(150), nullable=False)
    role_or_capacity = db.Column(db.String(100), nullable=True)
    attendance_status = db.Column(db.String(30), nullable=False)  # Present / Apology / Absent
    notes = db.Column(db.Text, nullable=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)

    meeting = db.relationship("Meeting", backref=db.backref("attendance_entries", cascade="all, delete-orphan", order_by="MeetingAttendance.attendee_name"))
    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id])
    user = db.relationship("User", foreign_keys=[user_id])
    created_by = db.relationship("User", foreign_keys=[created_by_user_id])


class ProductionInput(db.Model):
    __tablename__ = "production_input"

    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False, index=True)
    crop_id = db.Column(db.Integer, db.ForeignKey("crop.id"), nullable=False, index=True)
    inventory_item_id = db.Column(db.Integer, db.ForeignKey("inventory_item.id"), nullable=True)
    input_type = db.Column(db.String(80), nullable=False)
    description = db.Column(db.String(250), nullable=False)
    quantity = db.Column(db.Float, nullable=False, default=0)
    unit = db.Column(db.String(40), nullable=True)
    unit_cost = db.Column(db.Float, nullable=False, default=0)
    total_cost = db.Column(db.Float, nullable=False, default=0)
    activity_date = db.Column(db.Date, nullable=False, index=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)

    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id])
    crop = db.relationship("Crop", backref="production_inputs")
    inventory_item = db.relationship("InventoryItem", foreign_keys=[inventory_item_id])
    created_by = db.relationship("User", foreign_keys=[created_by_user_id])


class EquipmentUsage(db.Model):
    __tablename__ = "equipment_usage"

    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False, index=True)
    equipment_id = db.Column(db.Integer, db.ForeignKey("equipment.id"), nullable=False, index=True)
    farm_id = db.Column(db.Integer, db.ForeignKey("farm.id"), nullable=False)
    crop_id = db.Column(db.Integer, db.ForeignKey("crop.id"), nullable=True)
    responsible_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    purpose = db.Column(db.String(220), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=True)
    fuel_cost = db.Column(db.Float, nullable=False, default=0)
    notes = db.Column(db.Text, nullable=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)

    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id])
    equipment = db.relationship("Equipment", backref="usage_history")
    farm = db.relationship("Farm", foreign_keys=[farm_id])
    crop = db.relationship("Crop", foreign_keys=[crop_id])
    responsible_user = db.relationship("User", foreign_keys=[responsible_user_id])
    created_by = db.relationship("User", foreign_keys=[created_by_user_id])


class ApiAccessToken(db.Model):
    __tablename__ = "api_access_token"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    token_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    last_used_at = db.Column(db.DateTime, nullable=True)
    revoked_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)

    user = db.relationship("User", foreign_keys=[user_id])


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------
def _allowed_ids_for(user_id=None):
    return accessible_cooperative_ids(user_id=user_id)


def _cooperative_visible(cooperative_id, user_id=None):
    ids = _allowed_ids_for(user_id=user_id)
    return ids is None or cooperative_id in (ids or [])


def _year_bounds(year):
    return date(year, 1, 1), date(year + 1, 1, 1)


def _confirmed_primary_cooperative_contributions(cooperative_id, start_date=None, through_date=None):
    """Return confirmed Primary-to-Secondary contributions without using a fake farmer record."""
    try:
        from joint_operations import PrimaryContributionPayment
    except (ImportError, AttributeError):
        return 0.0
    query = db.session.query(func.coalesce(func.sum(PrimaryContributionPayment.amount), 0)).filter(
        PrimaryContributionPayment.secondary_cooperative_id == cooperative_id,
        PrimaryContributionPayment.status == "Confirmed",
    )
    if start_date:
        query = query.filter(PrimaryContributionPayment.payment_date >= start_date)
    if through_date:
        query = query.filter(PrimaryContributionPayment.payment_date <= through_date)
    return float(query.scalar() or 0)


def _confirmed_book_balance(cooperative_id, through_date=None):
    contribution_query = db.session.query(func.coalesce(func.sum(Contribution.amount), 0)).filter(
        Contribution.cooperative_id == cooperative_id,
        Contribution.status.in_(CONFIRMED_CONTRIBUTION_STATUSES),
    )
    payment_query = db.session.query(func.coalesce(func.sum(Payment.amount), 0)).filter(
        Payment.cooperative_id == cooperative_id,
        Payment.status.in_(PAYMENT_VALUE_STATUSES),
    )
    expense_query = db.session.query(func.coalesce(func.sum(Expense.amount), 0)).filter(
        Expense.cooperative_id == cooperative_id,
        Expense.status.in_(CONFIRMED_EXPENSE_STATUSES),
    )
    if through_date:
        contribution_query = contribution_query.filter(Contribution.contribution_date <= through_date)
        payment_query = payment_query.filter(Payment.payment_date <= through_date)
        expense_query = expense_query.filter(Expense.expense_date <= through_date)
    contributions = contribution_query.scalar() or 0
    payments = payment_query.scalar() or 0
    expenses = expense_query.scalar() or 0
    primary_cooperative_contributions = _confirmed_primary_cooperative_contributions(
        cooperative_id, through_date=through_date
    )
    return float(contributions) + primary_cooperative_contributions + float(payments) - float(expenses)


def budget_actual(budget):
    start, end = _year_bounds(budget.fiscal_year)
    category = (budget.category or "").strip()
    if budget.budget_type == "Expense":
        query = db.session.query(func.coalesce(func.sum(Expense.amount), 0)).filter(
            Expense.cooperative_id == budget.cooperative_id,
            Expense.status.in_(CONFIRMED_EXPENSE_STATUSES),
            Expense.expense_date >= start,
            Expense.expense_date < end,
        )
        if category and category.casefold() != "all":
            query = query.filter(func.lower(Expense.category) == category.lower())
        return float(query.scalar() or 0)
    if budget.budget_type == "Contribution":
        query = db.session.query(func.coalesce(func.sum(Contribution.amount), 0)).filter(
            Contribution.cooperative_id == budget.cooperative_id,
            Contribution.status.in_(CONFIRMED_CONTRIBUTION_STATUSES),
            Contribution.contribution_date >= start,
            Contribution.contribution_date < end,
        )
        if category and category.casefold() != "all":
            query = query.filter(func.lower(Contribution.category) == category.lower())
        legacy_total = float(query.scalar() or 0)
        joint_total = _confirmed_primary_cooperative_contributions(
            budget.cooperative_id, start_date=start, through_date=end - timedelta(days=1)
        )
        return legacy_total + joint_total
    return float(db.session.query(func.coalesce(func.sum(Payment.amount), 0)).filter(
        Payment.cooperative_id == budget.cooperative_id,
        Payment.status.in_(PAYMENT_VALUE_STATUSES),
        Payment.payment_date >= start,
        Payment.payment_date < end,
    ).scalar() or 0)


def _document_extension(filename):
    safe = secure_filename(filename or "")
    if "." not in safe:
        return None
    ext = safe.rsplit(".", 1)[1].lower()
    return ext if ext in DOCUMENT_ALLOWED_EXTENSIONS else None


def _save_document(file_storage):
    if not file_storage or not file_storage.filename:
        raise ValueError("Choose a document to upload.")
    ext = _document_extension(file_storage.filename)
    if not ext:
        raise ValueError("Allowed files: PDF, images, DOCX, XLSX, CSV and TXT.")
    original = secure_filename(file_storage.filename)[:255] or f"document.{ext}"
    stored = f"doc_{uuid.uuid4().hex}.{ext}"
    path = DOCUMENT_UPLOAD_DIR / stored
    file_storage.save(path)
    header = path.read_bytes()[:16]
    valid = True
    if ext == "pdf": valid = header.startswith(b"%PDF-")
    elif ext == "png": valid = header.startswith(b"\x89PNG\r\n\x1a\n")
    elif ext in {"jpg", "jpeg"}: valid = header.startswith(b"\xff\xd8\xff")
    elif ext == "webp": valid = header[:4] == b"RIFF" and header[8:12] == b"WEBP"
    elif ext in {"docx", "xlsx"}: valid = header.startswith(b"PK")
    if not valid:
        path.unlink(missing_ok=True)
        raise ValueError("The uploaded file content does not match its file type.")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return original, stored, digest


def _document_path(stored_name):
    safe = Path(stored_name or "").name
    if safe != stored_name:
        abort(404)
    path = DOCUMENT_UPLOAD_DIR / safe
    if not path.is_file():
        abort(404)
    return path


def _upsert_notification(user_id, cooperative_id, category, title, message, severity="Info", link=None,
                         due_date=None, source_type=None, source_id=None):
    query = Notification.query.filter_by(
        user_id=user_id, category=category, source_type=source_type, source_id=source_id,
    )
    item = query.first()
    if item:
        item.cooperative_id = cooperative_id
        item.title = title
        item.message = message
        item.severity = severity
        item.link = link
        item.due_date = due_date
        if item.status == "Resolved":
            item.status = "Unread"
            item.read_at = None
        return item
    item = Notification(
        user_id=user_id, cooperative_id=cooperative_id, category=category,
        title=title, message=message, severity=severity, link=link,
        due_date=due_date, source_type=source_type, source_id=source_id,
    )
    db.session.add(item)
    return item


def refresh_notifications(user_id=None):
    user_id = user_id or session.get("user_id")
    if not user_id:
        return
    access = UserAccess.query.filter_by(user_id=user_id).first()
    if not access or access.status != "Active":
        return

    active_keys = set()
    coop_id = access.cooperative_id
    today = crm_today()

    def add(category, title, message, severity="Info", link=None, due_date=None, source_type=None, source_id=None,
            notification_coop_id=coop_id):
        key = (category, source_type, source_id)
        active_keys.add(key)
        _upsert_notification(user_id, notification_coop_id, category, title, message, severity, link,
                             due_date, source_type, source_id)

    if access.role == "Admin":
        if not two_factor_policy_enabled():
            add("Security", "2FA is paused", "Google Authenticator enforcement is temporarily paused for testing.",
                "Warning", url_for("admin_security"), source_type="System", source_id=1, notification_coop_id=None)
        inactive = UserAccess.query.filter(UserAccess.status != "Active").count()
        if inactive:
            add("Access", "Accounts need attention", f"{inactive} CRM account(s) are inactive or pending.",
                "Info", url_for("users_list"), source_type="System", source_id=2, notification_coop_id=None)
        if len(list_database_backups()) == 0:
            add("Backup", "No local database backup", "No built-in SQLite backup is currently stored.",
                "Warning", url_for("admin_backup_restore"), source_type="System", source_id=3, notification_coop_id=None)
    else:
        assigned = Task.query.filter(
            Task.assigned_user_id == user_id,
            Task.cooperative_id == coop_id,
            Task.status.notin_(["Verified", "Completed", "Closed"]),
        ).all()
        for task in assigned:
            if task.due_date and task.due_date < today:
                add("Accountability", "Responsibility overdue", task.title, "Critical",
                    url_for("accountability_task_detail", task_id=task.id), task.due_date, "Task", task.id)
            elif task.due_date and task.due_date <= today + timedelta(days=3):
                add("Accountability", "Responsibility due soon", task.title, "Warning",
                    url_for("accountability_task_detail", task_id=task.id), task.due_date, "Task", task.id)

        upcoming = Meeting.query.filter(
            Meeting.cooperative_id == coop_id,
            Meeting.meeting_date >= today,
            Meeting.meeting_date <= today + timedelta(days=7),
        ).all()
        for meeting in upcoming:
            add("Meeting", "Upcoming meeting", f"{meeting.title} on {meeting.meeting_date.strftime('%d %b %Y')}",
                "Info", url_for("meeting_detail", meeting_id=meeting.id), meeting.meeting_date, "Meeting", meeting.id)

        if access.role in FINANCE_APPROVAL_ROLES:
            pending_c = Contribution.query.filter_by(cooperative_id=coop_id, status="Pending Confirmation").count()
            pending_e = Expense.query.filter_by(cooperative_id=coop_id, status="Pending Confirmation").count()
            pending_b = Budget.query.filter_by(cooperative_id=coop_id, status="Pending Approval").count()
            if pending_c:
                add("Finance", "Contributions awaiting approval", f"{pending_c} contribution(s) need your decision.",
                    "Warning", url_for("contributions_list"), source_type="FinanceQueue", source_id=1)
            if pending_e:
                add("Finance", "Expenses awaiting approval", f"{pending_e} expense(s) need your decision.",
                    "Warning", url_for("expenses_list"), source_type="FinanceQueue", source_id=2)
            if pending_b:
                add("Finance", "Budgets awaiting approval", f"{pending_b} budget line(s) need your decision.",
                    "Warning", url_for("phase7.finance_control"), source_type="FinanceQueue", source_id=4)

        if access.role in FINANCE_RECORD_ROLES:
            rejected = (
                Contribution.query.filter_by(cooperative_id=coop_id, status="Rejected").count()
                + Expense.query.filter_by(cooperative_id=coop_id, status="Rejected").count()
                + Budget.query.filter_by(cooperative_id=coop_id, status="Rejected").count()
            )
            if rejected:
                add("Finance", "Rejected finance needs correction", f"{rejected} rejected finance record(s) need correction or review.",
                    "Warning", url_for("phase7.finance_control"), source_type="FinanceQueue", source_id=3)

        if "Secretary" in access.role:
            due_count = sum(1 for m in Membership.query.filter_by(cooperative_id=coop_id, status="Active").all()
                            if m.fee_outstanding > 0)
            if due_count:
                add("Membership", "Membership fees outstanding", f"{due_count} active member(s) still have membership fees due.",
                    "Info", url_for("memberships_list"), source_type="MembershipQueue", source_id=1)

        if "Chairperson" in access.role or "Vice Chairperson" in access.role:
            low_stock = InventoryItem.query.filter(
                InventoryItem.cooperative_id == coop_id,
                InventoryItem.status == "Active",
                InventoryItem.quantity_on_hand <= InventoryItem.reorder_level,
            ).count()
            if low_stock:
                add("Operations", "Low stock items", f"{low_stock} inventory item(s) are at or below reorder level.",
                    "Warning", url_for("inventory_list"), source_type="OperationsQueue", source_id=1)
            service_due = Equipment.query.filter(
                Equipment.cooperative_id == coop_id,
                Equipment.next_service_date.isnot(None),
                Equipment.next_service_date <= today + timedelta(days=14),
            ).count()
            if service_due:
                add("Operations", "Equipment service due", f"{service_due} equipment item(s) are due for service within 14 days.",
                    "Warning", url_for("equipment_list"), source_type="OperationsQueue", source_id=2)

    generated_categories = {"Security", "Access", "Backup", "Accountability", "Meeting", "Finance", "Membership", "Operations"}
    for item in Notification.query.filter(
        Notification.user_id == user_id,
        Notification.category.in_(generated_categories),
        Notification.status != "Resolved",
    ).all():
        key = (item.category, item.source_type, item.source_id)
        if key not in active_keys:
            item.status = "Resolved"
    db.session.commit()


def _api_user():
    if session.get("user_id"):
        access = UserAccess.query.filter_by(user_id=session["user_id"]).first()
        if access and access.status == "Active" and access.role == "Admin":
            return db.session.get(User, session["user_id"])
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    raw = header[7:].strip()
    if not raw:
        return None
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    token = ApiAccessToken.query.filter_by(token_hash=digest).first()
    if not token or token.revoked_at:
        return None
    if token.expires_at and token.expires_at < utc_now():
        return None
    access = UserAccess.query.filter_by(user_id=token.user_id).first()
    if not access or access.status != "Active" or access.role != "Admin":
        return None
    token.last_used_at = utc_now()
    db.session.commit()
    g.api_token = token
    return token.user


def api_auth_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = _api_user()
        if not user:
            return jsonify({"error": "Authentication required"}), 401
        g.api_user = user
        return view(*args, **kwargs)
    return wrapped


def _api_query(model):
    return scoped_model_query(model, user_id=g.api_user.id)


# ---------------------------------------------------------------------------
# My Work + Notifications
# ---------------------------------------------------------------------------
@bp.route("/work")
@login_required
def my_work():
    refresh_notifications()
    access = current_access()
    user_id = session["user_id"]
    coop_id = access.cooperative_id
    today = crm_today()

    tasks = Task.query.filter(
        Task.assigned_user_id == user_id,
        Task.status.notin_(["Verified", "Completed", "Closed"]),
    )
    if coop_id:
        tasks = tasks.filter(Task.cooperative_id == coop_id)
    tasks = tasks.order_by(Task.due_date.asc().nullslast(), Task.created_at.desc()).all()

    pending_contributions = []
    pending_expenses = []
    verification = []
    memberships_due = []
    if coop_id:
        if access.role in FINANCE_APPROVAL_ROLES:
            pending_contributions = Contribution.query.filter_by(cooperative_id=coop_id, status="Pending Confirmation").order_by(Contribution.contribution_date.asc()).all()
            pending_expenses = Expense.query.filter_by(cooperative_id=coop_id, status="Pending Confirmation").order_by(Expense.expense_date.asc()).all()
        if access.role in ACCOUNTABILITY_VERIFY_ROLES:
            verification = Task.query.filter(
                Task.cooperative_id == coop_id,
                Task.status == "Awaiting Verification",
                Task.assigned_user_id != user_id,
            ).order_by(Task.updated_at.asc()).all()
        if "Secretary" in access.role:
            memberships_due = [m for m in Membership.query.filter_by(cooperative_id=coop_id, status="Active").all() if m.fee_outstanding > 0]

    upcoming_meetings = [] if not coop_id else Meeting.query.filter(
        Meeting.cooperative_id == coop_id,
        Meeting.meeting_date >= today,
        Meeting.meeting_date <= today + timedelta(days=30),
    ).order_by(Meeting.meeting_date.asc()).all()

    unread = Notification.query.filter_by(user_id=user_id, status="Unread").order_by(Notification.created_at.desc()).limit(8).all()
    return render_template(
        "phase7/my_work.html", tasks=tasks, pending_contributions=pending_contributions,
        pending_expenses=pending_expenses, verification=verification, memberships_due=memberships_due,
        upcoming_meetings=upcoming_meetings, unread_notifications=unread, today=today,
    )


@bp.route("/notifications")
@login_required
def notifications():
    refresh_notifications()
    status = request.args.get("status", "Unread").strip()
    query = Notification.query.filter_by(user_id=session["user_id"])
    if status in {"Unread", "Read", "Resolved"}:
        query = query.filter(Notification.status == status)
    items = query.order_by(Notification.created_at.desc()).limit(200).all()
    unread_count = Notification.query.filter_by(user_id=session["user_id"], status="Unread").count()
    return render_template("phase7/notifications.html", items=items, status=status, unread_count=unread_count)


@bp.route("/notifications/<int:notification_id>/read", methods=["POST"])
@login_required
def notification_read(notification_id):
    item = Notification.query.filter_by(id=notification_id, user_id=session["user_id"]).first_or_404()
    item.status = "Read"
    item.read_at = utc_now()
    db.session.commit()
    if item.link:
        return redirect(item.link)
    return redirect(url_for("phase7.notifications"))


@bp.route("/notifications/read-all", methods=["POST"])
@login_required
def notification_read_all():
    Notification.query.filter_by(user_id=session["user_id"], status="Unread").update(
        {"status": "Read", "read_at": utc_now()}, synchronize_session=False
    )
    db.session.commit()
    return redirect(url_for("phase7.notifications", status="Read"))


# ---------------------------------------------------------------------------
# Controlled document register
# ---------------------------------------------------------------------------
@bp.route("/documents")
@roles_required("Admin", *COOPERATIVE_EXECUTIVE_ROLES)
def documents():
    search = request.args.get("search", "").strip()
    doc_type = request.args.get("type", "").strip()
    query = scoped_model_query(CooperativeDocument)
    if search:
        query = query.filter(or_(
            CooperativeDocument.title.ilike(f"%{search}%"),
            CooperativeDocument.original_name.ilike(f"%{search}%"),
            CooperativeDocument.notes.ilike(f"%{search}%"),
        ))
    if doc_type:
        query = query.filter(CooperativeDocument.document_type == doc_type)
    items = query.order_by(CooperativeDocument.created_at.desc()).all()
    return render_template("phase7/documents.html", documents=items, search=search, doc_type=doc_type,
                           document_types=DOCUMENT_TYPES)


@bp.route("/documents/upload", methods=["GET", "POST"])
@roles_required(*COOPERATIVE_EXECUTIVE_ROLES)
def document_upload():
    access = current_access()
    coop_id = access.cooperative_id
    if not coop_id:
        abort(403)
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        document_type = request.form.get("document_type", "").strip()
        if not title or document_type not in DOCUMENT_TYPES:
            return "Title and valid document type are required.", 400
        try:
            original, stored, digest = _save_document(request.files.get("file"))
        except ValueError as exc:
            return str(exc), 400
        item = CooperativeDocument(
            cooperative_id=coop_id,
            document_type=document_type,
            title=title,
            entity_type=request.form.get("entity_type", "").strip() or None,
            entity_id=parse_int(request.form.get("entity_id")),
            original_name=original,
            stored_name=stored,
            file_sha256=digest,
            uploaded_by_user_id=session["user_id"],
            notes=request.form.get("notes", "").strip() or None,
        )
        db.session.add(item)
        db.session.flush()
        add_audit_log("DOCUMENT_UPLOADED", "CooperativeDocument", item.id,
                      f"{item.document_type}: {item.title} sha256={digest}", cooperative_id=coop_id)
        db.session.commit()
        return redirect(url_for("phase7.documents"))
    return render_template("phase7/document_form.html", document_types=DOCUMENT_TYPES)


@bp.route("/documents/<int:document_id>/download")
@roles_required("Admin", *COOPERATIVE_EXECUTIVE_ROLES)
def document_download(document_id):
    item = scoped_get_or_404(CooperativeDocument, document_id)
    return send_file(_document_path(item.stored_name), as_attachment=True, download_name=item.original_name)


# ---------------------------------------------------------------------------
# Finance control: budgets, reconciliation and supporting documents
# ---------------------------------------------------------------------------
@bp.route("/finance-control")
@roles_required(*FINANCE_VIEW_ROLES)
def finance_control():
    access = current_access()
    coop_id = access.cooperative_id
    year = parse_int(request.args.get("year")) or crm_today().year
    budgets = Budget.query.filter_by(cooperative_id=coop_id, fiscal_year=year).order_by(Budget.budget_type, Budget.category).all()
    budget_rows = [{"budget": item, "actual": budget_actual(item)} for item in budgets]
    reconciliations = BankReconciliation.query.filter_by(cooperative_id=coop_id).order_by(BankReconciliation.statement_date.desc()).limit(12).all()
    finance_docs = CooperativeDocument.query.filter(
        CooperativeDocument.cooperative_id == coop_id,
        CooperativeDocument.document_type.in_(["Quotation", "Invoice", "Receipt", "Proof of Payment", "Financial Document"]),
    ).order_by(CooperativeDocument.created_at.desc()).limit(10).all()
    return render_template(
        "phase7/finance_control.html", budget_rows=budget_rows, reconciliations=reconciliations,
        finance_docs=finance_docs, year=year, book_balance=_confirmed_book_balance(coop_id),
        can_record=access.role in FINANCE_RECORD_ROLES, can_approve=access.role in FINANCE_APPROVAL_ROLES,
    )


@bp.route("/finance-control/budgets", methods=["POST"])
@roles_required(*FINANCE_RECORD_ROLES)
def budget_create():
    access = current_access()
    year = parse_int(request.form.get("fiscal_year"))
    planned = parse_float(request.form.get("planned_amount"))
    budget_type = request.form.get("budget_type", "").strip()
    category = request.form.get("category", "").strip() or "All"
    if not year or year < 2020 or year > 2100 or planned is None or planned < 0:
        return "Enter a valid fiscal year and non-negative planned amount.", 400
    if budget_type not in {"Expense", "Contribution", "Sales Receipts"}:
        return "Invalid budget type.", 400
    existing = Budget.query.filter_by(
        cooperative_id=access.cooperative_id, fiscal_year=year, budget_type=budget_type, category=category
    ).first()
    if existing:
        return "That budget line already exists for this year.", 400
    item = Budget(
        cooperative_id=access.cooperative_id, fiscal_year=year, budget_type=budget_type,
        category=category, planned_amount=planned, status="Pending Approval",
        notes=request.form.get("notes", "").strip() or None, created_by_user_id=session["user_id"],
    )
    db.session.add(item)
    db.session.flush()
    add_audit_log("BUDGET_SUBMITTED", "Budget", item.id,
                  f"{year} {budget_type} {category} R{planned:.2f}", cooperative_id=access.cooperative_id)
    db.session.commit()
    return redirect(url_for("phase7.finance_control", year=year))


@bp.route("/finance-control/budgets/<int:budget_id>/decision", methods=["POST"])
@roles_required(*FINANCE_APPROVAL_ROLES)
def budget_decision(budget_id):
    item = Budget.query.get_or_404(budget_id)
    require_own_cooperative(item.cooperative_id)
    if item.status != "Pending Approval":
        return "Only pending budgets can be decided.", 400
    decision = request.form.get("decision", "").strip().lower()
    if decision not in {"approve", "reject"}:
        return "Choose approve or reject.", 400
    item.status = "Approved" if decision == "approve" else "Rejected"
    item.approved_by_user_id = session["user_id"]
    item.approved_at = utc_now()
    add_audit_log("BUDGET_APPROVED" if decision == "approve" else "BUDGET_REJECTED", "Budget", item.id,
                  f"{item.fiscal_year} {item.budget_type} {item.category}", cooperative_id=item.cooperative_id)
    db.session.commit()
    return redirect(url_for("phase7.finance_control", year=item.fiscal_year))


@bp.route("/finance-control/budgets/<int:budget_id>/resubmit", methods=["POST"])
@roles_required(*FINANCE_RECORD_ROLES)
def budget_resubmit(budget_id):
    item = Budget.query.get_or_404(budget_id)
    require_own_cooperative(item.cooperative_id)
    if item.status != "Rejected":
        return "Only rejected budget lines can be corrected and resubmitted.", 400

    year = parse_int(request.form.get("fiscal_year"))
    planned = parse_float(request.form.get("planned_amount"))
    budget_type = request.form.get("budget_type", "").strip()
    category = request.form.get("category", "").strip() or "All"
    notes = request.form.get("notes", "").strip() or None

    if not year or year < 2020 or year > 2100 or planned is None or planned < 0:
        return "Enter a valid fiscal year and non-negative planned amount.", 400
    if budget_type not in {"Expense", "Contribution", "Sales Receipts"}:
        return "Invalid budget type.", 400

    duplicate = Budget.query.filter(
        Budget.cooperative_id == item.cooperative_id,
        Budget.fiscal_year == year,
        Budget.budget_type == budget_type,
        Budget.category == category,
        Budget.id != item.id,
    ).first()
    if duplicate:
        return "Another budget line already uses that year, type and category.", 400

    before = f"{item.fiscal_year} {item.budget_type} {item.category} R{float(item.planned_amount or 0):.2f}"
    item.fiscal_year = year
    item.budget_type = budget_type
    item.category = category
    item.planned_amount = planned
    item.notes = notes
    item.status = "Pending Approval"
    item.approved_by_user_id = None
    item.approved_at = None

    add_audit_log(
        "BUDGET_RESUBMITTED", "Budget", item.id,
        f"Corrected from [{before}] to [{year} {budget_type} {category} R{planned:.2f}] and resubmitted for approval.",
        cooperative_id=item.cooperative_id,
    )
    db.session.commit()
    flash("Budget line corrected and resubmitted for Chairperson approval.", "success")
    return redirect(url_for("phase7.finance_control", year=year))


@bp.route("/finance-control/reconciliation", methods=["POST"])
@roles_required(*FINANCE_RECORD_ROLES)
def reconciliation_create():
    access = current_access()
    try:
        statement_date = parse_date(request.form.get("statement_date"))
    except ValueError:
        return "Enter a valid statement date.", 400
    statement_balance = parse_float(request.form.get("statement_balance"))
    if not statement_date or statement_balance is None:
        return "Statement date and balance are required.", 400
    book = _confirmed_book_balance(access.cooperative_id, through_date=statement_date)
    item = BankReconciliation(
        cooperative_id=access.cooperative_id, statement_date=statement_date,
        statement_balance=statement_balance, book_balance=book,
        difference=statement_balance - book, status="Pending Review",
        notes=request.form.get("notes", "").strip() or None,
        prepared_by_user_id=session["user_id"],
    )
    db.session.add(item)
    db.session.flush()
    add_audit_log("BANK_RECONCILIATION_RECORDED", "BankReconciliation", item.id,
                  f"Statement R{statement_balance:.2f}; book R{book:.2f}; difference R{item.difference:.2f}",
                  cooperative_id=access.cooperative_id)
    db.session.commit()
    return redirect(url_for("phase7.finance_control"))


@bp.route("/finance-control/reconciliation/<int:reconciliation_id>/review", methods=["POST"])
@roles_required(*FINANCE_APPROVAL_ROLES)
def reconciliation_review(reconciliation_id):
    item = BankReconciliation.query.get_or_404(reconciliation_id)
    require_own_cooperative(item.cooperative_id)
    item.status = "Reviewed"
    item.reviewed_by_user_id = session["user_id"]
    item.reviewed_at = utc_now()
    add_audit_log("BANK_RECONCILIATION_REVIEWED", "BankReconciliation", item.id,
                  f"Difference R{item.difference:.2f}", cooperative_id=item.cooperative_id)
    db.session.commit()
    return redirect(url_for("phase7.finance_control"))


# ---------------------------------------------------------------------------
# Meeting management upgrade
# ---------------------------------------------------------------------------
@bp.route("/meetings/<int:meeting_id>/manage")
@roles_required(*GOVERNANCE_VIEW_ROLES)
def meeting_manage(meeting_id):
    meeting = scoped_get_or_404(Meeting, meeting_id)
    access = current_access()
    return render_template(
        "phase7/meeting_manage.html", meeting=meeting,
        can_record=access.role in MEETING_RECORD_ROLES and access.cooperative_id == meeting.cooperative_id,
    )


@bp.route("/meetings/<int:meeting_id>/agenda", methods=["POST"])
@roles_required(*MEETING_RECORD_ROLES)
def meeting_agenda_add(meeting_id):
    meeting = scoped_get_or_404(Meeting, meeting_id)
    require_own_cooperative(meeting.cooperative_id)
    if meeting.status == "Confirmed":
        return "Confirmed meeting records are locked.", 400
    title = request.form.get("title", "").strip()
    item_number = parse_int(request.form.get("item_number"))
    if not title or not item_number or item_number < 1:
        return "Agenda item number and title are required.", 400
    if MeetingAgendaItem.query.filter_by(meeting_id=meeting.id, item_number=item_number).first():
        return "That agenda item number already exists.", 400
    item = MeetingAgendaItem(
        meeting_id=meeting.id, cooperative_id=meeting.cooperative_id, item_number=item_number,
        title=title, notes=request.form.get("notes", "").strip() or None,
        status=request.form.get("status", "Open").strip() or "Open", created_by_user_id=session["user_id"],
    )
    db.session.add(item)
    add_audit_log("MEETING_AGENDA_ADDED", "Meeting", meeting.id, f"Item {item_number}: {title}",
                  cooperative_id=meeting.cooperative_id)
    db.session.commit()
    return redirect(url_for("phase7.meeting_manage", meeting_id=meeting.id))


@bp.route("/meetings/<int:meeting_id>/attendance", methods=["POST"])
@roles_required(*MEETING_RECORD_ROLES)
def meeting_attendance_add(meeting_id):
    meeting = scoped_get_or_404(Meeting, meeting_id)
    require_own_cooperative(meeting.cooperative_id)
    if meeting.status == "Confirmed":
        return "Confirmed meeting records are locked.", 400
    name = request.form.get("attendee_name", "").strip()
    attendance_status = request.form.get("attendance_status", "").strip()
    if not name or attendance_status not in {"Present", "Apology", "Absent"}:
        return "Attendee name and attendance status are required.", 400
    linked_user_id = parse_int(request.form.get("user_id"))
    if linked_user_id:
        linked_access = UserAccess.query.filter_by(user_id=linked_user_id, status="Active").first()
        if not linked_access or linked_access.cooperative_id != meeting.cooperative_id:
            return "The linked CRM user must be an active user of this cooperative.", 400
    entry = MeetingAttendance(
        meeting_id=meeting.id, cooperative_id=meeting.cooperative_id,
        user_id=linked_user_id, attendee_name=name,
        role_or_capacity=request.form.get("role_or_capacity", "").strip() or None,
        attendance_status=attendance_status, notes=request.form.get("notes", "").strip() or None,
        created_by_user_id=session["user_id"],
    )
    db.session.add(entry)
    add_audit_log("MEETING_ATTENDANCE_ADDED", "Meeting", meeting.id, f"{name}: {attendance_status}",
                  cooperative_id=meeting.cooperative_id)
    db.session.commit()
    return redirect(url_for("phase7.meeting_manage", meeting_id=meeting.id))


# ---------------------------------------------------------------------------
# Member certificate + linked documents
# ---------------------------------------------------------------------------
@bp.route("/memberships/<int:membership_id>/certificate")
@roles_required(*MEMBERSHIP_VIEW_ROLES)
def membership_certificate(membership_id):
    membership = scoped_get_or_404(Membership, membership_id)
    return render_template("phase7/membership_certificate.html", membership=membership, generated_on=crm_today())


# ---------------------------------------------------------------------------
# Production costing + equipment usage
# ---------------------------------------------------------------------------
@bp.route("/production-control")
@roles_required(*OPERATIONS_VIEW_ROLES)
def production_control():
    access = current_access()
    crops = scoped_model_query(Crop).order_by(Crop.planting_date.desc().nullslast(), Crop.created_at.desc()).all()
    rows = []
    for crop in crops:
        cost = sum(float(x.total_cost or 0) for x in crop.production_inputs)
        yield_kg = 0.0
        for harvest in crop.harvests:
            if harvest.unit == "kg":
                yield_kg += float(harvest.quantity or 0)
            elif harvest.unit == "tonnes":
                yield_kg += float(harvest.quantity or 0) * 1000
        hectares = float(crop.area_planted or 0)
        rows.append({
            "crop": crop, "cost": cost, "yield_kg": yield_kg,
            "yield_per_ha": (yield_kg / hectares) if hectares > 0 else None,
            "cost_per_ha": (cost / hectares) if hectares > 0 else None,
        })
    equipment_usage = scoped_model_query(EquipmentUsage).order_by(EquipmentUsage.start_date.desc()).limit(20).all()
    own_crops = own_cooperative_query(Crop).order_by(Crop.name.asc()).all()
    own_inventory = own_cooperative_query(InventoryItem).order_by(InventoryItem.name.asc()).all()
    own_equipment = own_cooperative_query(Equipment).order_by(Equipment.name.asc()).all()
    own_farms = own_cooperative_query(Farm).order_by(Farm.name.asc()).all()
    own_users = User.query.join(UserAccess, UserAccess.user_id == User.id).filter(
        UserAccess.cooperative_id == access.cooperative_id, UserAccess.status == "Active"
    ).order_by(User.fullname.asc()).all()
    return render_template(
        "phase7/production_control.html", rows=rows, equipment_usage=equipment_usage,
        own_crops=own_crops, own_inventory=own_inventory, own_equipment=own_equipment,
        own_farms=own_farms, own_users=own_users, can_record=access.role in OPERATIONS_RECORD_ROLES,
    )


@bp.route("/production-control/input", methods=["POST"])
@roles_required(*OPERATIONS_RECORD_ROLES)
def production_input_add():
    access = current_access()
    crop_id = parse_int(request.form.get("crop_id"))
    crop = own_cooperative_query(Crop).filter(Crop.id == crop_id).first()
    if not crop:
        return "Choose a crop from your cooperative.", 400
    quantity = parse_float(request.form.get("quantity"), 0) or 0
    unit_cost = parse_float(request.form.get("unit_cost"), 0) or 0
    if quantity < 0 or unit_cost < 0:
        return "Quantity and unit cost cannot be negative.", 400
    try:
        activity_date = parse_date(request.form.get("activity_date"))
    except ValueError:
        return "Enter a valid activity date.", 400
    if not activity_date:
        return "Activity date is required.", 400
    input_type = request.form.get("input_type", "").strip()
    description = request.form.get("description", "").strip()
    if not input_type or not description:
        return "Input type and description are required.", 400
    inventory_id = parse_int(request.form.get("inventory_item_id"))
    if inventory_id and not own_cooperative_query(InventoryItem).filter(InventoryItem.id == inventory_id).first():
        return "Selected inventory item is outside your cooperative.", 400
    item = ProductionInput(
        cooperative_id=access.cooperative_id, crop_id=crop.id, inventory_item_id=inventory_id,
        input_type=input_type, description=description, quantity=quantity,
        unit=request.form.get("unit", "").strip() or None, unit_cost=unit_cost,
        total_cost=quantity * unit_cost, activity_date=activity_date,
        created_by_user_id=session["user_id"],
    )
    db.session.add(item)
    db.session.flush()
    add_audit_log("PRODUCTION_INPUT_RECORDED", "ProductionInput", item.id,
                  f"{crop.name}: {description} R{item.total_cost:.2f}", cooperative_id=access.cooperative_id)
    db.session.commit()
    return redirect(url_for("phase7.production_control"))


@bp.route("/production-control/equipment-usage", methods=["POST"])
@roles_required(*OPERATIONS_RECORD_ROLES)
def equipment_usage_add():
    access = current_access()
    equipment_id = parse_int(request.form.get("equipment_id"))
    farm_id = parse_int(request.form.get("farm_id"))
    crop_id = parse_int(request.form.get("crop_id"))
    equipment = own_cooperative_query(Equipment).filter(Equipment.id == equipment_id).first()
    farm = own_cooperative_query(Farm).filter(Farm.id == farm_id).first()
    crop = own_cooperative_query(Crop).filter(Crop.id == crop_id).first() if crop_id else None
    if not equipment or not farm or (crop_id and not crop):
        return "Equipment, farm and crop selections must belong to your cooperative.", 400
    try:
        start_date = parse_date(request.form.get("start_date"))
        end_date = parse_date(request.form.get("end_date"))
    except ValueError:
        return "Enter valid equipment usage dates.", 400
    if not start_date or (end_date and end_date < start_date):
        return "Enter a valid start/end date range.", 400
    fuel_cost = parse_float(request.form.get("fuel_cost"), 0) or 0
    purpose = request.form.get("purpose", "").strip()
    if not purpose or fuel_cost < 0:
        return "Purpose is required and fuel cost cannot be negative.", 400
    responsible_user_id = parse_int(request.form.get("responsible_user_id"))
    if responsible_user_id:
        responsible_access = UserAccess.query.filter_by(user_id=responsible_user_id, status="Active").first()
        if not responsible_access or responsible_access.cooperative_id != access.cooperative_id:
            return "The responsible CRM user must belong to your cooperative.", 400
    item = EquipmentUsage(
        cooperative_id=access.cooperative_id, equipment_id=equipment.id, farm_id=farm.id,
        crop_id=crop.id if crop else None, responsible_user_id=responsible_user_id,
        purpose=purpose, start_date=start_date, end_date=end_date, fuel_cost=fuel_cost,
        notes=request.form.get("notes", "").strip() or None, created_by_user_id=session["user_id"],
    )
    db.session.add(item)
    db.session.flush()
    add_audit_log("EQUIPMENT_USAGE_RECORDED", "EquipmentUsage", item.id,
                  f"{equipment.name}: {purpose}", cooperative_id=access.cooperative_id)
    db.session.commit()
    return redirect(url_for("phase7.production_control"))


# ---------------------------------------------------------------------------
# Reports command centre
# ---------------------------------------------------------------------------
@bp.route("/reports/command-centre")
@roles_required("Admin", *COOPERATIVE_EXECUTIVE_ROLES)
def reports_command_centre():
    access = current_access()
    if access.role == "Admin":
        summary = {
            "users": User.query.count(), "cooperatives": Cooperative.query.count(),
            "members": Membership.query.count(), "farms": Farm.query.count(),
            "crops": Crop.query.count(), "open_accountability": Task.query.filter(Task.resolution_id.isnot(None), Task.status != "Verified").count(),
            "documents": CooperativeDocument.query.count(), "audit": AuditLog.query.count(),
        }
        return render_template("phase7/reports_command.html", admin_mode=True, summary=summary, network=[])

    coop_id = access.cooperative_id
    today = crm_today()
    month_start = today.replace(day=1)
    summary = {
        "members": Membership.query.filter_by(cooperative_id=coop_id).count(),
        "active_members": Membership.query.filter_by(cooperative_id=coop_id, status="Active").count(),
        "farms": Farm.query.filter_by(cooperative_id=coop_id).count(),
        "crops": Crop.query.filter_by(cooperative_id=coop_id).count(),
        "harvests": Harvest.query.filter_by(cooperative_id=coop_id).count(),
        "open_accountability": Task.query.filter(Task.cooperative_id == coop_id, Task.resolution_id.isnot(None), Task.status != "Verified").count(),
        "documents": CooperativeDocument.query.filter_by(cooperative_id=coop_id).count(),
        "month_expenses": float(db.session.query(func.coalesce(func.sum(Expense.amount), 0)).filter(
            Expense.cooperative_id == coop_id, Expense.expense_date >= month_start,
            Expense.status.in_(CONFIRMED_EXPENSE_STATUSES)).scalar() or 0),
        "month_contributions": (
            float(db.session.query(func.coalesce(func.sum(Contribution.amount), 0)).filter(
                Contribution.cooperative_id == coop_id, Contribution.contribution_date >= month_start,
                Contribution.status.in_(CONFIRMED_CONTRIBUTION_STATUSES)).scalar() or 0)
            + _confirmed_primary_cooperative_contributions(coop_id, start_date=month_start)
        ),
    }
    network = []
    if access.role.startswith("Secondary"):
        coop = current_cooperative()
        for child in coop.primary_cooperatives if coop else []:
            network.append({
                "cooperative": child,
                "members": Membership.query.filter_by(cooperative_id=child.id).count(),
                "farms": Farm.query.filter_by(cooperative_id=child.id).count(),
                "crops": Crop.query.filter_by(cooperative_id=child.id).count(),
                "open_accountability": Task.query.filter(Task.cooperative_id == child.id, Task.resolution_id.isnot(None), Task.status != "Verified").count(),
            })
    return render_template("phase7/reports_command.html", admin_mode=False, summary=summary, network=network)


# ---------------------------------------------------------------------------
# Global search
# ---------------------------------------------------------------------------
@bp.route("/search")
@login_required
def global_search():
    q = request.args.get("q", "").strip()
    results = []
    if len(q) >= 2:
        farmers = scoped_model_query(Farmer).filter(or_(Farmer.fullname.ilike(f"%{q}%"), Farmer.phone.ilike(f"%{q}%"), Farmer.location.ilike(f"%{q}%"))).limit(15).all()
        for item in farmers:
            results.append({"type": "Farmer", "title": item.fullname, "detail": f"{item.phone} · {item.location}", "url": url_for("farmers_list", search=item.fullname)})
        farms = scoped_model_query(Farm).filter(or_(Farm.name.ilike(f"%{q}%"), Farm.location.ilike(f"%{q}%"))).limit(15).all()
        for item in farms:
            results.append({"type": "Farm", "title": item.name, "detail": item.location, "url": url_for("farms_list", search=item.name)})
        crops = scoped_model_query(Crop).filter(or_(Crop.name.ilike(f"%{q}%"), Crop.variety.ilike(f"%{q}%"))).limit(15).all()
        for item in crops:
            results.append({"type": "Crop", "title": item.name, "detail": item.variety or item.status, "url": url_for("crops_list", search=item.name)})
        meetings = scoped_model_query(Meeting).filter(or_(Meeting.meeting_number.ilike(f"%{q}%"), Meeting.title.ilike(f"%{q}%"))).limit(15).all()
        for item in meetings:
            results.append({"type": "Meeting", "title": item.title, "detail": item.meeting_number, "url": url_for("meeting_detail", meeting_id=item.id)})
        resolutions = scoped_model_query(Resolution).filter(or_(Resolution.resolution_number.ilike(f"%{q}%"), Resolution.title.ilike(f"%{q}%"), Resolution.resolution_text.ilike(f"%{q}%"))).limit(15).all()
        for item in resolutions:
            results.append({"type": "Resolution", "title": item.title, "detail": item.resolution_number, "url": url_for("resolution_detail", resolution_id=item.id)})
        docs = scoped_model_query(CooperativeDocument).filter(or_(CooperativeDocument.title.ilike(f"%{q}%"), CooperativeDocument.original_name.ilike(f"%{q}%"))).limit(15).all()
        for item in docs:
            results.append({"type": "Document", "title": item.title, "detail": item.document_type, "url": url_for("phase7.document_download", document_id=item.id)})
        memberships = scoped_model_query(Membership).join(Farmer, Membership.farmer_id == Farmer.id).filter(or_(Membership.member_number.ilike(f"%{q}%"), Farmer.fullname.ilike(f"%{q}%"))).limit(15).all()
        for item in memberships:
            results.append({"type": "Member", "title": item.farmer.fullname if item.farmer else item.member_number, "detail": item.member_number, "url": url_for("memberships_list", search=item.member_number)})
        contributions = scoped_model_query(Contribution).filter(or_(Contribution.reference.ilike(f"%{q}%"), Contribution.category.ilike(f"%{q}%"))).limit(15).all()
        for item in contributions:
            results.append({"type": "Contribution", "title": item.reference or item.category or f"Contribution #{item.id}", "detail": f"R {float(item.amount or 0):,.2f} · {item.status}", "url": url_for("contributions_list")})
        expenses = scoped_model_query(Expense).filter(or_(Expense.reference.ilike(f"%{q}%"), Expense.category.ilike(f"%{q}%"), Expense.description.ilike(f"%{q}%"))).limit(15).all()
        for item in expenses:
            results.append({"type": "Expense", "title": item.reference or item.description, "detail": f"R {float(item.amount or 0):,.2f} · {item.status}", "url": url_for("expenses_list")})
        payments = scoped_model_query(Payment).filter(or_(Payment.reference.ilike(f"%{q}%"), Payment.method.ilike(f"%{q}%"))).limit(15).all()
        for item in payments:
            results.append({"type": "Sale Payment", "title": item.reference or f"Payment #{item.id}", "detail": f"R {float(item.amount or 0):,.2f} · {item.status}", "url": url_for("payments_list")})
        sales = scoped_model_query(Sale).filter(or_(Sale.buyer_name.ilike(f"%{q}%"), Sale.buyer_phone.ilike(f"%{q}%"))).limit(15).all()
        for item in sales:
            results.append({"type": "Sale", "title": item.buyer_name, "detail": f"R {float(item.total_amount or 0):,.2f} · {item.status}", "url": url_for("sales_list")})
    return render_template("phase7/global_search.html", q=q, results=results)


# ---------------------------------------------------------------------------
# API access tokens and scoped read API
# ---------------------------------------------------------------------------
@bp.route("/api/tokens", methods=["GET", "POST"])
@roles_required("Admin")
def api_tokens():
    created_token = None
    if request.method == "POST":
        name = request.form.get("name", "").strip() or "Integration"
        days = parse_int(request.form.get("expires_days")) or 90
        days = max(1, min(days, 365))
        raw = "mfg_" + secrets.token_urlsafe(32)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        item = ApiAccessToken(
            user_id=session["user_id"], name=name[:120], token_hash=digest,
            expires_at=utc_now() + timedelta(days=days),
        )
        db.session.add(item)
        db.session.flush()
        add_audit_log("API_TOKEN_CREATED", "ApiAccessToken", item.id, f"Token {name} expires in {days} days.")
        db.session.commit()
        created_token = raw
    items = ApiAccessToken.query.filter_by(user_id=session["user_id"]).order_by(ApiAccessToken.created_at.desc()).all()
    return render_template("phase7/api_tokens.html", tokens=items, created_token=created_token)


@bp.route("/api/tokens/<int:token_id>/revoke", methods=["POST"])
@roles_required("Admin")
def api_token_revoke(token_id):
    item = ApiAccessToken.query.filter_by(id=token_id, user_id=session["user_id"]).first_or_404()
    item.revoked_at = utc_now()
    add_audit_log("API_TOKEN_REVOKED", "ApiAccessToken", item.id, item.name)
    db.session.commit()
    return redirect(url_for("phase7.api_tokens"))


def _serialize_farmer(item):
    return {"id": item.id, "cooperative_id": item.cooperative_id, "fullname": item.fullname,
            "phone": item.phone, "email": item.email, "location": item.location, "status": item.status}


def _serialize_farm(item):
    return {"id": item.id, "cooperative_id": item.cooperative_id, "name": item.name,
            "farmer_id": item.farmer_id, "location": item.location, "size": item.size,
            "farming_type": item.farming_type, "status": item.status}


@bp.route("/api/v1/me")
@api_auth_required
def api_me():
    access = UserAccess.query.filter_by(user_id=g.api_user.id).first()
    return jsonify({"id": g.api_user.id, "fullname": g.api_user.fullname, "email": g.api_user.email,
                    "role": access.role if access else None, "cooperative_id": access.cooperative_id if access else None})


@bp.route("/api/v1/farmers")
@api_auth_required
def api_farmers():
    return jsonify([_serialize_farmer(x) for x in _api_query(Farmer).order_by(Farmer.fullname.asc()).limit(500).all()])


@bp.route("/api/v1/farms")
@api_auth_required
def api_farms():
    return jsonify([_serialize_farm(x) for x in _api_query(Farm).order_by(Farm.name.asc()).limit(500).all()])


@bp.route("/api/v1/crops")
@api_auth_required
def api_crops():
    rows = _api_query(Crop).order_by(Crop.created_at.desc()).limit(500).all()
    return jsonify([{"id": x.id, "cooperative_id": x.cooperative_id, "farm_id": x.farm_id,
                     "name": x.name, "variety": x.variety, "planting_date": x.planting_date.isoformat() if x.planting_date else None,
                     "expected_harvest_date": x.expected_harvest_date.isoformat() if x.expected_harvest_date else None,
                     "area_planted": x.area_planted, "status": x.status} for x in rows])


@bp.route("/api/v1/memberships")
@api_auth_required
def api_memberships():
    rows = _api_query(Membership).order_by(Membership.created_at.desc()).limit(500).all()
    return jsonify([{"id": x.id, "cooperative_id": x.cooperative_id, "farmer_id": x.farmer_id,
                     "member_number": x.member_number, "join_date": x.join_date.isoformat() if x.join_date else None,
                     "fee_amount": x.fee_amount, "fee_paid": x.fee_paid, "fee_outstanding": x.fee_outstanding,
                     "status": x.status} for x in rows])


@bp.route("/api/v1/accountability")
@api_auth_required
def api_accountability():
    rows = _api_query(Resolution).order_by(Resolution.created_at.desc()).limit(500).all()
    return jsonify([{"id": x.id, "cooperative_id": x.cooperative_id, "resolution_number": x.resolution_number,
                     "title": x.title, "responsible_role": x.responsible_role,
                     "responsible_user_id": x.responsible_user_id,
                     "due_date": x.due_date.isoformat() if x.due_date else None,
                     "priority": x.priority, "status": x.accountability_status} for x in rows])


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
def register_phase7(app):
    """Register Phase 7 routes once the main app and Phase 6 models exist."""
    if "phase7" not in app.blueprints:
        app.register_blueprint(bp)
