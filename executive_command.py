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
from joint_operations import PrimaryContributionAccount, JointProjectAllocation
from phase7 import BankReconciliation, Budget, CooperativeDocument


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
    """Secondary oversight without exposing a Primary cooperative's internal finances."""
    rows = []
    today = _core.crm_today()
    primaries = _core.Cooperative.query.filter_by(
        parent_id=secondary_id,
        cooperative_type="Primary",
        status="Active",
    ).order_by(_core.Cooperative.name.asc()).all()

    for cooperative in primaries:
        contribution_accounts = PrimaryContributionAccount.query.filter_by(
            secondary_cooperative_id=secondary_id,
            primary_cooperative_id=cooperative.id,
            fiscal_year=today.year,
        ).all()
        expected_contribution = sum(float(item.expected_amount or 0) for item in contribution_accounts)
        confirmed_contribution = sum(float(item.confirmed_paid or 0) for item in contribution_accounts)
        pending_contribution = sum(float(item.pending_paid or 0) for item in contribution_accounts)
        outstanding_contribution = max(expected_contribution - confirmed_contribution, 0.0)

        allocated_amount = float(
            _core.db.session.query(_core.func.coalesce(_core.func.sum(JointProjectAllocation.allocated_amount), 0))
            .filter(
                JointProjectAllocation.secondary_cooperative_id == secondary_id,
                JointProjectAllocation.primary_cooperative_id == cooperative.id,
            )
            .scalar() or 0
        )

        latest_reconciliation = BankReconciliation.query.filter_by(
            cooperative_id=cooperative.id,
        ).order_by(BankReconciliation.statement_date.desc()).first()

        open_actions = _core.Task.query.filter(
            _core.Task.cooperative_id == cooperative.id,
            _core.Task.resolution_id.isnot(None),
            _core.Task.status.notin_(["Verified", "Completed", "Closed"]),
        ).count()

        rows.append({
            "cooperative": cooperative,
            "member_count": _core.Membership.query.filter_by(cooperative_id=cooperative.id).count(),
            "farm_count": _core.Farm.query.filter_by(cooperative_id=cooperative.id).count(),
            "crop_count": _core.Crop.query.filter_by(cooperative_id=cooperative.id).count(),
            "financial_reporting_status": "Submitted" if latest_reconciliation else "Outstanding",
            "financial_reporting_date": latest_reconciliation.statement_date if latest_reconciliation else None,
            "expected_contribution": expected_contribution,
            "confirmed_contribution": confirmed_contribution,
            "pending_contribution": pending_contribution,
            "outstanding_contribution": outstanding_contribution,
            "joint_allocated_amount": allocated_amount,
            "open_actions": open_actions,
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
    chairperson_decisions = None
    finance_composition = None
    treasurer_work = None
    secretary_work = None
    role_focus = None
    network_rows = []
    if cooperative.cooperative_type == "Primary":
        memberships = _core.Membership.query.filter_by(cooperative_id=cooperative_id).all()
        valid_fee_memberships = [
            membership
            for membership in memberships
            if 0 <= float(getattr(membership, "fee_amount", 0) or 0) <= _core.MAX_PRIMARY_MEMBERSHIP_FEE
        ]
        membership_fee_anomaly_count = len(memberships) - len(valid_fee_memberships)
        primary_stats = {
            "member_count": len(memberships),
            "active_member_count": sum(1 for membership in memberships if membership.status == "Active"),
            "membership_fee_due": sum(
                max(0.0, float(getattr(membership, "fee_outstanding", 0) or 0))
                for membership in valid_fee_memberships
            ),
            "membership_fee_anomaly_count": membership_fee_anomaly_count,
            "farmer_count": _core.Farmer.query.filter_by(cooperative_id=cooperative_id).count(),
            "farm_count": _core.Farm.query.filter_by(cooperative_id=cooperative_id).count(),
            "crop_count": _core.Crop.query.filter_by(cooperative_id=cooperative_id).count(),
            "harvest_count": _core.Harvest.query.filter_by(cooperative_id=cooperative_id).count(),
        }

        active_crop_rows = _core.Crop.query.filter(
            _core.Crop.cooperative_id == cooperative_id,
            _core.Crop.status.in_(("Planted", "Growing", "Ready for Harvest", "Partially Harvested")),
        ).all()
        active_crop_count = len(active_crop_rows)
        active_area_hectares = sum(float(row.area_planted or 0) for row in active_crop_rows)
        expected_harvest_count = sum(
            1 for row in active_crop_rows
            if row.expected_harvest_date and row.expected_harvest_date >= today
        )

        if role == "Primary Chairperson":
            pending_ledger_rows = LedgerTransaction.query.filter_by(
                cooperative_id=cooperative_id,
                status="Pending Confirmation",
            ).all()
            pending_budgets = Budget.query.filter_by(
                cooperative_id=cooperative_id,
                status="Pending Approval",
            ).all()
            pending_reconciliations = BankReconciliation.query.filter_by(
                cooperative_id=cooperative_id,
                status="Pending Review",
            ).all()
            chairperson_decisions = {
                "finance_count": len(pending_ledger_rows),
                "finance_value": sum(float(row.amount or 0) for row in pending_ledger_rows),
                "budget_count": len(pending_budgets),
                "budget_value": sum(float(row.planned_amount or 0) for row in pending_budgets),
                "reconciliation_count": len(pending_reconciliations),
                "verification_count": awaiting_verification,
            }

            confirmed_rows = LedgerTransaction.query.filter_by(
                cooperative_id=cooperative_id,
                status="Confirmed",
            ).all()
            finance_composition = {
                "cash_bank": confirmed_balance,
                "sales_income": sum(
                    float(row.amount or 0)
                    for row in confirmed_rows
                    if row.category in {"Product Sale", "Bulk Sale"} and not row.reversal_of_transaction_id
                ),
                "grants_loans": sum(
                    float(row.amount or 0)
                    for row in confirmed_rows
                    if row.category in {"Grant", "Loan"} and not row.reversal_of_transaction_id
                ),
                "expenses": sum(
                    float(row.amount or 0)
                    for row in confirmed_rows
                    if row.transaction_type == "Expense" and not row.reversal_of_transaction_id
                ),
                "pending_value": sum(float(row.amount or 0) for row in pending_ledger_rows),
            }

        if role == "Primary Treasurer":
            pending_rows = LedgerTransaction.query.filter_by(
                cooperative_id=cooperative_id,
                status="Pending Confirmation",
            ).all()
            rejected_rows = LedgerTransaction.query.filter_by(
                cooperative_id=cooperative_id,
                status="Rejected",
            ).all()
            pending_budgets = Budget.query.filter_by(
                cooperative_id=cooperative_id,
                status="Pending Approval",
            ).all()
            pending_reconciliations = BankReconciliation.query.filter_by(
                cooperative_id=cooperative_id,
                status="Pending Review",
            ).all()

            evidence_rows = LedgerTransaction.query.filter(
                LedgerTransaction.cooperative_id == cooperative_id,
                LedgerTransaction.status.in_(("Pending Confirmation", "Confirmed")),
                LedgerTransaction.reversal_of_transaction_id.is_(None),
            ).all()
            evidence_transaction_ids = {
                row[0]
                for row in _core.db.session.query(CooperativeDocument.entity_id)
                .filter(
                    CooperativeDocument.cooperative_id == cooperative_id,
                    CooperativeDocument.entity_type == "LedgerTransaction",
                    CooperativeDocument.entity_id.isnot(None),
                )
                .all()
            }
            missing_evidence_count = sum(
                1 for row in evidence_rows if row.id not in evidence_transaction_ids
            )

            latest_reconciliation = BankReconciliation.query.filter_by(
                cooperative_id=cooperative_id,
            ).order_by(BankReconciliation.statement_date.desc()).first()

            confirmed_cashflow_rows = LedgerTransaction.query.filter_by(
                cooperative_id=cooperative_id,
                status="Confirmed",
            ).all()
            money_in = sum(
                float(row.amount or 0)
                for row in confirmed_cashflow_rows
                if row.transaction_type == "Income" and not row.reversal_of_transaction_id
            )
            money_out = sum(
                float(row.amount or 0)
                for row in confirmed_cashflow_rows
                if row.transaction_type == "Expense" and not row.reversal_of_transaction_id
            )

            treasurer_work = {
                "money_in": money_in,
                "money_out": money_out,
                "current_position": confirmed_balance,
                "pending_count": len(pending_rows),
                "pending_value": sum(float(row.amount or 0) for row in pending_rows),
                "rejected_count": len(rejected_rows),
                "rejected_value": sum(float(row.amount or 0) for row in rejected_rows),
                "budget_count": len(pending_budgets),
                "budget_value": sum(float(row.planned_amount or 0) for row in pending_budgets),
                "reconciliation_count": len(pending_reconciliations),
                "latest_reconciliation_difference": (
                    float(latest_reconciliation.difference or 0)
                    if latest_reconciliation else None
                ),
                "missing_evidence_count": missing_evidence_count,
            }

        if role in {"Primary Secretary", "Primary Vice Secretary"}:
            membership_attention_count = sum(
                1
                for membership in memberships
                if membership.status in {"Pending", "Suspended"}
                or not membership.join_date
            )
            membership_fee_followup_count = sum(
                1
                for membership in valid_fee_memberships
                if membership.status == "Active" and float(membership.fee_outstanding or 0) > 1e-9
            )

            draft_meetings = _core.Meeting.query.filter(
                _core.Meeting.cooperative_id == cooperative_id,
                _core.Meeting.status != "Confirmed",
            ).order_by(_core.Meeting.meeting_date.asc()).all()
            meetings_without_evidence = sum(1 for meeting in draft_meetings if not meeting.documents)
            draft_resolutions = _core.Resolution.query.filter_by(
                cooperative_id=cooperative_id,
                status="Draft",
            ).count()
            upcoming_30_count = _core.Meeting.query.filter(
                _core.Meeting.cooperative_id == cooperative_id,
                _core.Meeting.meeting_date >= today,
                _core.Meeting.meeting_date <= today + _core.timedelta(days=30),
            ).count()

            secretary_work = {
                "membership_attention_count": membership_attention_count,
                "membership_fee_followup_count": membership_fee_followup_count,
                "draft_meeting_count": len(draft_meetings),
                "meetings_without_evidence": meetings_without_evidence,
                "draft_resolution_count": draft_resolutions,
                "upcoming_30_count": upcoming_30_count,
            }

        if role == "Primary Chairperson":
            decision_total = (
                (chairperson_decisions or {}).get("finance_count", 0)
                + (chairperson_decisions or {}).get("budget_count", 0)
                + (chairperson_decisions or {}).get("reconciliation_count", 0)
                + (chairperson_decisions or {}).get("verification_count", 0)
            )
            role_focus = {
                "metric_1_label": "Current Financial Position",
                "metric_1_value": f"R {confirmed_balance:,.2f}",
                "metric_1_detail": "Confirmed bank, cash and controlled-account position",
                "metric_2_label": "Production Position",
                "metric_2_value": f"{active_crop_count} active crops",
                "metric_2_detail": f"{active_area_hectares:,.2f} ha under active cultivation",
                "queue_label": "Awaiting My Approval",
                "queue_value": decision_total,
                "queue_detail": "Transactions, budgets, reconciliations and verification items",
                "queue_href": url_for("ledger.dashboard", status="Pending Confirmation"),
            }
        elif role == "Primary Vice Chairperson":
            role_focus = {
                "metric_1_label": "Active Cultivation",
                "metric_1_value": f"{active_crop_count} crops",
                "metric_1_detail": f"{active_area_hectares:,.2f} ha currently active",
                "metric_2_label": "Expected Harvests",
                "metric_2_value": expected_harvest_count,
                "metric_2_detail": "Active crops with an upcoming expected harvest date",
                "queue_label": "Overdue Operations",
                "queue_value": overdue_responsibilities,
                "queue_detail": "Operational responsibilities past their deadline",
                "queue_href": url_for("accountability_register"),
            }
        elif role in {"Primary Secretary", "Primary Vice Secretary"}:
            secretary_attention = 0
            if secretary_work:
                secretary_attention = (
                    secretary_work.get("membership_attention_count", 0)
                    + secretary_work.get("draft_meeting_count", 0)
                    + secretary_work.get("draft_resolution_count", 0)
                )
            role_focus = {
                "metric_1_label": "Institutional Registry",
                "metric_1_value": primary_stats["member_count"],
                "metric_1_detail": f'{primary_stats["active_member_count"]} active members',
                "metric_2_label": "Active Mandates",
                "metric_2_value": open_responsibilities,
                "metric_2_detail": "Assigned, in-progress or awaiting-verification resolutions",
                "queue_label": "Records Needing Attention",
                "queue_value": secretary_attention,
                "queue_detail": "Membership, meeting-evidence and draft-resolution follow-up",
                "queue_href": url_for("accountability_register"),
            }
        elif role == "Primary Treasurer":
            approved_expense_budgets = Budget.query.filter_by(
                cooperative_id=cooperative_id,
                fiscal_year=today.year,
                budget_type="Expense",
                status="Approved",
            ).all()
            planned_expense_budget = sum(float(row.planned_amount or 0) for row in approved_expense_budgets)
            confirmed_expense_spend = sum(
                float(row.amount or 0)
                for row in LedgerTransaction.query.filter_by(
                    cooperative_id=cooperative_id,
                    status="Confirmed",
                    transaction_type="Expense",
                ).all()
                if not row.reversal_of_transaction_id
            )
            burn_percent = (
                (confirmed_expense_spend / planned_expense_budget) * 100
                if planned_expense_budget > 0 else 0.0
            )
            reconciliation_state = "Not started"
            reconciliation_detail = "No bank reconciliation recorded yet"
            if treasurer_work and treasurer_work.get("latest_reconciliation_difference") is not None:
                difference = float(treasurer_work["latest_reconciliation_difference"] or 0)
                reconciliation_state = "Balanced" if abs(difference) < 0.005 else "Attention"
                reconciliation_detail = f"Latest statement difference: R {difference:,.2f}"
            action_count = (
                (treasurer_work or {}).get("rejected_count", 0)
                + (treasurer_work or {}).get("missing_evidence_count", 0)
                + (treasurer_work or {}).get("pending_count", 0)
            )
            role_focus = {
                "metric_1_label": "Seasonal Budget Burn",
                "metric_1_value": f"{burn_percent:,.1f}%",
                "metric_1_detail": f"R {confirmed_expense_spend:,.2f} of R {planned_expense_budget:,.2f} approved expense budget",
                "metric_2_label": "Reconciliation Integrity",
                "metric_2_value": reconciliation_state,
                "metric_2_detail": reconciliation_detail,
                "queue_label": "Transactions Needing Action",
                "queue_value": action_count,
                "queue_detail": "Pending, rejected or evidence-incomplete transaction work",
                "queue_href": url_for("ledger.dashboard"),
            }

    elif cooperative.cooperative_type == "Secondary":
        network_rows = _primary_network_rows(cooperative_id)
        if role == "Secondary Chairperson":
            role_focus = {
                "metric_1_label": "Network Reporting",
                "metric_1_value": sum(1 for row in network_rows if row["financial_reporting_status"] == "Submitted"),
                "metric_1_detail": f"{len(network_rows)} Primary cooperatives in the network",
                "metric_2_label": "Open Shared Actions",
                "metric_2_value": sum(row["open_actions"] for row in network_rows),
                "metric_2_detail": "Aggregate shared accountability only; no Primary raw records",
                "queue_label": "Awaiting My Approval",
                "queue_value": pending_finance + awaiting_verification,
                "queue_detail": "Secondary-level financial and accountability decisions",
                "queue_href": url_for("ledger.dashboard", status="Pending Confirmation"),
            }
        elif role == "Secondary Vice Chairperson":
            role_focus = {
                "metric_1_label": "Joint Operations",
                "metric_1_value": len(network_rows),
                "metric_1_detail": "Active Primary cooperatives participating in the network",
                "metric_2_label": "Open Shared Actions",
                "metric_2_value": sum(row["open_actions"] for row in network_rows),
                "metric_2_detail": "Aggregate operations requiring follow-up",
                "queue_label": "Overdue Operations",
                "queue_value": overdue_responsibilities,
                "queue_detail": "Secondary responsibilities past their deadline",
                "queue_href": url_for("accountability_register"),
            }
        elif role in {"Secondary Secretary", "Secondary Vice Secretary"}:
            role_focus = {
                "metric_1_label": "Primary Cooperatives",
                "metric_1_value": len(network_rows),
                "metric_1_detail": "Aggregate institutional registry only",
                "metric_2_label": "Active Mandates",
                "metric_2_value": open_responsibilities,
                "metric_2_detail": "Secondary resolutions still active",
                "queue_label": "Records Needing Attention",
                "queue_value": awaiting_verification + overdue_responsibilities,
                "queue_detail": "Secondary governance records requiring follow-up",
                "queue_href": url_for("accountability_register"),
            }
        elif role == "Secondary Treasurer":
            role_focus = {
                "metric_1_label": "Secondary Financial Position",
                "metric_1_value": f"R {confirmed_balance:,.2f}",
                "metric_1_detail": "Secondary accounts only; Primary internal accounts remain private",
                "metric_2_label": "Primary Contributions",
                "metric_2_value": f"R {sum(row['confirmed_contribution'] for row in network_rows):,.2f}",
                "metric_2_detail": "Confirmed Primary-to-Secondary contributions",
                "queue_label": "Transactions Needing Action",
                "queue_value": pending_finance,
                "queue_detail": "Secondary ledger transactions awaiting decision",
                "queue_href": url_for("ledger.dashboard"),
            }

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
    if primary_stats and primary_stats.get("membership_fee_anomaly_count", 0) > 0 and role in {
        "Primary Secretary", "Primary Vice Secretary", "Primary Chairperson", "Primary Treasurer"
    }:
        alerts.append({
            "severity": "danger",
            "title": "Membership fee data needs review",
            "value": str(primary_stats["membership_fee_anomaly_count"]),
            "detail": (
                "One or more membership fee amounts exceed the allowed membership-fee range and are excluded "
                "from fee receivables until corrected."
            ),
            "href": url_for("memberships_list"),
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
        "chairperson_decisions": chairperson_decisions,
        "finance_composition": finance_composition,
        "treasurer_work": treasurer_work,
        "secretary_work": secretary_work,
        "role_focus": role_focus,
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
