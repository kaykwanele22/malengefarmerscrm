"""Idempotent Phase 7 hardening patch.

Keeps Phase 7 safe when app.py is executed directly, tightens cross-cooperative
references, and makes bank reconciliation calculate the book balance as of the
statement date.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "phase7.py"


def replace_once(text, old, new, label):
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"Could not find Phase 7 patch target: {label}")
    return text.replace(old, new, 1)


def main():
    text = PATH.read_text(encoding="utf-8")

    # Avoid importing app.py a second time when a developer launches `python app.py`.
    # Under Gunicorn/Alembic, the partially initialized `app` module is reused.
    old_import = '''from app import (
    db, User, UserAccess, Cooperative, Farmer, Farm, Crop, Harvest, Sale, Payment,
    Expense, Contribution, Membership, Meeting, Resolution, Task, InventoryItem,
    Equipment, AuditLog,
    COOPERATIVE_EXECUTIVE_ROLES, GOVERNANCE_VIEW_ROLES, MEETING_RECORD_ROLES,
    FINANCE_RECORD_ROLES, FINANCE_APPROVAL_ROLES, FINANCE_VIEW_ROLES,
    OPERATIONS_RECORD_ROLES, OPERATIONS_VIEW_ROLES, MEMBERSHIP_VIEW_ROLES,
    ACCOUNTABILITY_VERIFY_ROLES,
    CONFIRMED_EXPENSE_STATUSES, CONFIRMED_CONTRIBUTION_STATUSES,
    PAYMENT_VALUE_STATUSES,
    current_access, current_cooperative, current_user, accessible_cooperative_ids,
    can_access_cooperative, scoped_model_query, scoped_get, scoped_get_or_404,
    own_cooperative_query, own_cooperative_id, require_own_cooperative,
    login_required, roles_required, add_audit_log, utc_now, crm_today,
    parse_int, parse_float, parse_date, list_database_backups,
    two_factor_policy_enabled,
)
'''
    new_import = '''import importlib
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
'''
    text = replace_once(text, old_import, new_import, "runtime-safe core import")

    text = text.replace(
        'os.getenv("DOCUMENT_UPLOAD_DIR", str(Path("instance") / "documents"))',
        'os.getenv("DOCUMENT_UPLOAD_DIR", str(Path(_core.app.instance_path) / "documents"))',
        1,
    )

    text = text.replace(
        'order_by="MeetingAgendaItem.item_number.asc()"',
        'order_by="MeetingAgendaItem.item_number"',
    )
    text = text.replace(
        'order_by="MeetingAttendance.attendee_name.asc()"',
        'order_by="MeetingAttendance.attendee_name"',
    )

    # Reconciliation should compare the bank statement with books through that same date.
    pattern = re.compile(r"def _confirmed_book_balance\(cooperative_id\):.*?\n\ndef budget_actual", re.S)
    replacement = '''def _confirmed_book_balance(cooperative_id, through_date=None):
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
    return float(contributions) + float(payments) - float(expenses)


def budget_actual'''
    if "def _confirmed_book_balance(cooperative_id, through_date=None):" not in text:
        text, count = pattern.subn(replacement, text, count=1)
        if count != 1:
            raise RuntimeError("Could not harden reconciliation balance helper")

    text = text.replace(
        'book = _confirmed_book_balance(access.cooperative_id)\n    item = BankReconciliation(',
        'book = _confirmed_book_balance(access.cooperative_id, through_date=statement_date)\n    item = BankReconciliation(',
        1,
    )

    attendance_old = '''    if not name or attendance_status not in {"Present", "Apology", "Absent"}:
        return "Attendee name and attendance status are required.", 400
    entry = MeetingAttendance(
        meeting_id=meeting.id, cooperative_id=meeting.cooperative_id,
        user_id=parse_int(request.form.get("user_id")), attendee_name=name,
'''
    attendance_new = '''    if not name or attendance_status not in {"Present", "Apology", "Absent"}:
        return "Attendee name and attendance status are required.", 400
    linked_user_id = parse_int(request.form.get("user_id"))
    if linked_user_id:
        linked_access = UserAccess.query.filter_by(user_id=linked_user_id, status="Active").first()
        if not linked_access or linked_access.cooperative_id != meeting.cooperative_id:
            return "The linked CRM user must be an active user of this cooperative.", 400
    entry = MeetingAttendance(
        meeting_id=meeting.id, cooperative_id=meeting.cooperative_id,
        user_id=linked_user_id, attendee_name=name,
'''
    text = replace_once(text, attendance_old, attendance_new, "meeting attendance cooperative validation")

    equipment_old = '''    fuel_cost = parse_float(request.form.get("fuel_cost"), 0) or 0
    purpose = request.form.get("purpose", "").strip()
    if not purpose or fuel_cost < 0:
        return "Purpose is required and fuel cost cannot be negative.", 400
    item = EquipmentUsage(
        cooperative_id=access.cooperative_id, equipment_id=equipment.id, farm_id=farm.id,
        crop_id=crop.id if crop else None, responsible_user_id=parse_int(request.form.get("responsible_user_id")),
'''
    equipment_new = '''    fuel_cost = parse_float(request.form.get("fuel_cost"), 0) or 0
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
'''
    text = replace_once(text, equipment_old, equipment_new, "equipment responsibility cooperative validation")

    PATH.write_text(text, encoding="utf-8")
    print("Phase 7 hardening complete")


if __name__ == "__main__":
    main()
