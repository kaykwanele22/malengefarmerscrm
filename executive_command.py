"""Executive command centre for cooperative leadership.

This module consolidates governance, accountability, finance and operational
signals without weakening the role/entity boundaries already enforced by the
CRM. It also upgrades the existing /dashboard endpoint for cooperative
executives while leaving the Admin dashboard unchanged.
"""

import importlib
import sys
from functools import wraps

from flask import Blueprint, abort, render_template, request, url_for


_core = sys.modules.get("app")
if _core is None or not hasattr(_core, "db"):
    _core = importlib.import_module("app")

from account_ledger import FinanceAccount, LedgerTransaction


bp = Blueprint("execdash", __name__)


def _executive_context():
    access = _core.current_access()
    cooperative = _core.current_cooperative()
    if not access or not cooperative:
        abort(403)
    if access.role not in _core.COOPERATIVE_EXECUTIVE_ROLES:
        abort(403)
    return access, cooperative


def _ledger_snapshot(cooperative_id):
    accounts = FinanceAccount.query.filter_by(cooperative_id=cooperative_id).order_by(FinanceAccount.name.asc()).all()
    confirmed_balance = sum(float(account.confirmed_balance or 0) for account in accounts)
    pending_change = sum(float(account.pending_change or 0) for account in accounts)
    pending_count = LedgerTransaction.query.filter_by(
        cooperative_id=cooperative_id,
        status="Pending Confirmation",
    ).count()
    return accounts, confirmed_balance, pending_change, pending_count


def _primary_network_rows(secondary_id):
    rows = []
    primaries = _core.Cooperative.query.filter_by(
        parent_id=secondary_id,
        cooperative_type="Primary",
        status="Active",
    ).order_by(_core.Cooperative.name.asc()).all()

    for cooperative in primaries:
        accounts, confirmed_balance, pending_change, pending_count = _ledger_snapshot(cooperative.id)
        rows.append({
            "cooperative": cooperative,
            "member_count": _core.Membership.query.filter_by(cooperative_id=cooperative.id).count(),
            "farm_count": _core.Farm.query.filter_by(cooperative_id=cooperative.id).count(),
            "crop_count": _core.Crop.query.filter_by(cooperative_id=cooperative.id).count(),
            "confirmed_balance": confirmed_balance,
            "pending_change": pending_change,
            "pending_count": pending_count,
            "account_count": len(accounts),
        })
    return rows


def _dashboard_data():
    access, cooperative = _executive_context()
    role = access.role
    cooperative_id = cooperative.id
    today = _core.crm_today()

    resolutions = _core.Resolution.query.filter_by(cooperative_id=cooperative_id)
    open_statuses = ("Assigned", "In Progress", "Awaiting Verification")
    open_responsibilities = resolutions.filter(_core.Resolution.status.in_(open_statuses)).count()
    overdue_responsibilities = resolutions.filter(
        _core.Resolution.status.in_(("Assigned", "In Progress")),
        _core.Resolution.due_date.isnot(None),
        _core.Resolution.due_date < today,
    ).count()
    awaiting_verification = resolutions.filter_by(status="Awaiting Verification").count()
    recent_resolutions = resolutions.order_by(_core.Resolution.created_at.desc()).limit(5).all()

    upcoming_meetings = _core.Meeting.query.filter(
        _core.Meeting.cooperative_id == cooperative_id,
        _core.Meeting.meeting_date >= today,
    ).order_by(_core.Meeting.meeting_date.asc()).limit(5).all()

    active_executives = _core.ExecutiveAppointment.query.filter_by(
        cooperative_id=cooperative_id,
        status="Active",
    ).order_by(_core.ExecutiveAppointment.role.asc()).all()
    positions_filled = len(active_executives)
    positions_vacant = max(0, 5 - positions_filled)

    can_view_finance = role in _core.FINANCE_VIEW_ROLES
    accounts = []
    confirmed_balance = 0.0
    pending_change = 0.0
    pending_finance = 0
    if can_view_finance:
        accounts, confirmed_balance, pending_change, pending_finance = _ledger_snapshot(cooperative_id)

    primary_stats = None
    network_rows = []
    if cooperative.cooperative_type == "Primary":
        memberships = _core.Membership.query.filter_by(cooperative_id=cooperative_id).all()
        primary_stats = {
            "member_count": len(memberships),
            "active_member_count": sum(1 for membership in memberships if membership.status == "Active"),
            "membership_fee_due": sum(max(0.0, float(getattr(membership, "fee_outstanding", 0) or 0)) for membership in memberships),
            "farmer_count": _core.Farmer.query.filter_by(cooperative_id=cooperative_id).count(),
            "farm_count": _core.Farm.query.filter_by(cooperative_id=cooperative_id).count(),
            "crop_count": _core.Crop.query.filter_by(cooperative_id=cooperative_id).count(),
            "harvest_count": _core.Harvest.query.filter_by(cooperative_id=cooperative_id).count(),
        }
    elif cooperative.cooperative_type == "Secondary":
        network_rows = _primary_network_rows(cooperative_id)

    alerts = []
    if pending_finance:
        alerts.append({
            "severity": "attention",
            "title": "Finance awaiting confirmation",
            "value": str(pending_finance),
            "detail": "Ledger transactions are waiting for an independent finance decision.",
            "href": url_for("ledger.dashboard", status="Pending Confirmation"),
        })
    if overdue_responsibilities:
        alerts.append({
            "severity": "danger",
            "title": "Overdue responsibilities",
            "value": str(overdue_responsibilities),
            "detail": "Resolution-linked work is past its recorded due date.",
            "href": url_for("accountability_register", status="Overdue"),
        })
    if awaiting_verification:
        alerts.append({
            "severity": "attention",
            "title": "Awaiting verification",
            "value": str(awaiting_verification),
            "detail": "Completed accountability work still needs independent verification.",
            "href": url_for("accountability_register", status="Awaiting Verification"),
        })
    if positions_vacant:
        alerts.append({
            "severity": "muted",
            "title": "Vacant executive offices",
            "value": str(positions_vacant),
            "detail": "The cooperative has fewer than five active executive appointments.",
            "href": None,
        })
    if primary_stats and primary_stats["membership_fee_due"] > 0 and role in {
        "Primary Secretary", "Primary Vice Secretary", "Primary Chairperson", "Primary Treasurer"
    }:
        alerts.append({
            "severity": "attention",
            "title": "Membership fees outstanding",
            "value": f"R {primary_stats['membership_fee_due']:,.2f}",
            "detail": "Membership records show confirmed amounts still outstanding.",
            "href": url_for("memberships_list", fee="due"),
        })

    return {
        "current_access": access,
        "current_cooperative": cooperative,
        "role": role,
        "is_secondary": cooperative.cooperative_type == "Secondary",
        "is_primary": cooperative.cooperative_type == "Primary",
        "can_view_finance": can_view_finance,
        "accounts": accounts,
        "confirmed_balance": confirmed_balance,
        "pending_change": pending_change,
        "pending_finance": pending_finance,
        "open_responsibilities": open_responsibilities,
        "overdue_responsibilities": overdue_responsibilities,
        "awaiting_verification": awaiting_verification,
        "recent_resolutions": recent_resolutions,
        "upcoming_meetings": upcoming_meetings,
        "active_executives": active_executives,
        "positions_filled": positions_filled,
        "positions_vacant": positions_vacant,
        "primary_stats": primary_stats,
        "network_rows": network_rows,
        "alerts": alerts,
    }


@bp.route("/executive-command-centre")
@_core.login_required
def command_centre():
    """Single operational command centre for cooperative executives."""
    return render_template("executive_command.html", **_dashboard_data())


def register_executive_command(app):
    """Register the command centre and make it the executive /dashboard view."""
    if "execdash" not in app.blueprints:
        app.register_blueprint(bp)

    # Document access is a cross-cutting executive concern. Install it only
    # after Phase 7 has registered its endpoint names so existing links keep
    # working while the view functions receive role/context enforcement.
    from document_access import install_document_access_controls
    install_document_access_controls(app)

    original_dashboard = app.view_functions.get("dashboard")
    if not original_dashboard or getattr(original_dashboard, "_executive_command_router", False):
        return

    @wraps(original_dashboard)
    def dashboard_router(*args, **kwargs):
        access = _core.current_access()
        if access and access.role in _core.COOPERATIVE_EXECUTIVE_ROLES:
            return command_centre()
        return original_dashboard(*args, **kwargs)

    dashboard_router._executive_command_router = True
    app.view_functions["dashboard"] = dashboard_router
