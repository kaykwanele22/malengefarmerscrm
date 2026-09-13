"""MFPSU / Secondary cooperative joint operations for Malenge Farmers CRM.

This module keeps Primary cooperative individual records inside their own portals
while giving Secondary executives a dedicated workspace for matters that are
truly shared between the constituent Primary cooperatives: joint projects,
shared assets, procurement, cooperative-to-cooperative contributions, marketing
contracts and aggregate Primary summaries.
"""
from datetime import date
import importlib
import sys

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy import func


_CORE_NAMES = (
    "db", "User", "UserAccess", "Cooperative", "Farmer", "Farm", "Crop", "Harvest",
    "Payment", "Expense", "Contribution", "Task", "SECONDARY_EXECUTIVE_ROLES",
    "CONFIRMED_EXPENSE_STATUSES", "CONFIRMED_CONTRIBUTION_STATUSES", "PAYMENT_VALUE_STATUSES",
    "current_access", "current_cooperative", "login_required", "roles_required", "add_audit_log",
    "utc_now", "crm_today", "parse_int", "parse_float", "parse_date",
)
_core = sys.modules.get("__main__")
if _core is None or not hasattr(_core, "db"):
    _core = importlib.import_module("app")
for _name in _CORE_NAMES:
    globals()[_name] = getattr(_core, _name)


bp = Blueprint("jointops", __name__)

JOINT_GOVERNANCE_RECORD_ROLES = {
    "Secondary Chairperson",
    "Secondary Vice Chairperson",
    "Secondary Secretary",
    "Secondary Vice Secretary",
}
JOINT_FINANCE_RECORD_ROLES = {"Secondary Treasurer"}
JOINT_FINANCE_APPROVAL_ROLES = {"Secondary Chairperson"}
JOINT_ASSET_RECORD_ROLES = JOINT_GOVERNANCE_RECORD_ROLES | JOINT_FINANCE_RECORD_ROLES

PROJECT_TYPES = (
    "Production Programme", "Infrastructure", "Marketing", "Procurement",
    "Shared Services", "Funding Programme", "Other",
)
ASSET_CATEGORIES = (
    "Tractor", "Implement", "Vehicle", "Irrigation", "Storage", "Building", "Equipment", "Other",
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class JointProject(db.Model):
    __tablename__ = "joint_project"

    id = db.Column(db.Integer, primary_key=True)
    secondary_cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False, index=True)
    title = db.Column(db.String(180), nullable=False)
    project_type = db.Column(db.String(80), nullable=False)
    description = db.Column(db.Text, nullable=True)
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)
    budget_amount = db.Column(db.Float, nullable=False, default=0)
    status = db.Column(db.String(40), nullable=False, default="Planned", index=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)

    secondary_cooperative = db.relationship("Cooperative", foreign_keys=[secondary_cooperative_id])
    created_by = db.relationship("User", foreign_keys=[created_by_user_id])


class JointProjectAllocation(db.Model):
    __tablename__ = "joint_project_allocation"
    __table_args__ = (
        db.UniqueConstraint("project_id", "primary_cooperative_id", name="uq_joint_project_primary"),
    )

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("joint_project.id", ondelete="CASCADE"), nullable=False, index=True)
    secondary_cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False, index=True)
    primary_cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False, index=True)
    allocated_amount = db.Column(db.Float, nullable=False, default=0)
    hectares = db.Column(db.Float, nullable=False, default=0)
    progress_percentage = db.Column(db.Integer, nullable=False, default=0)
    notes = db.Column(db.Text, nullable=True)
    updated_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    project = db.relationship(
        "JointProject",
        backref=db.backref("allocations", cascade="all, delete-orphan", order_by="JointProjectAllocation.id"),
    )
    secondary_cooperative = db.relationship("Cooperative", foreign_keys=[secondary_cooperative_id])
    primary_cooperative = db.relationship("Cooperative", foreign_keys=[primary_cooperative_id])
    updated_by = db.relationship("User", foreign_keys=[updated_by_user_id])


class SharedAsset(db.Model):
    __tablename__ = "shared_asset"

    id = db.Column(db.Integer, primary_key=True)
    secondary_cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False, index=True)
    name = db.Column(db.String(160), nullable=False)
    category = db.Column(db.String(80), nullable=False)
    identifier = db.Column(db.String(120), nullable=True)
    acquisition_date = db.Column(db.Date, nullable=True)
    acquisition_value = db.Column(db.Float, nullable=False, default=0)
    location = db.Column(db.String(200), nullable=True)
    status = db.Column(db.String(40), nullable=False, default="Available", index=True)
    notes = db.Column(db.Text, nullable=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)

    secondary_cooperative = db.relationship("Cooperative", foreign_keys=[secondary_cooperative_id])
    created_by = db.relationship("User", foreign_keys=[created_by_user_id])


class SharedAssetUsage(db.Model):
    __tablename__ = "shared_asset_usage"

    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey("shared_asset.id", ondelete="CASCADE"), nullable=False, index=True)
    secondary_cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False, index=True)
    primary_cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False, index=True)
    purpose = db.Column(db.String(220), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=True)
    estimated_cost = db.Column(db.Float, nullable=False, default=0)
    actual_cost = db.Column(db.Float, nullable=False, default=0)
    status = db.Column(db.String(40), nullable=False, default="Scheduled", index=True)
    notes = db.Column(db.Text, nullable=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)

    asset = db.relationship(
        "SharedAsset",
        backref=db.backref("usage_records", cascade="all, delete-orphan", order_by="SharedAssetUsage.start_date.desc()"),
    )
    secondary_cooperative = db.relationship("Cooperative", foreign_keys=[secondary_cooperative_id])
    primary_cooperative = db.relationship("Cooperative", foreign_keys=[primary_cooperative_id])
    created_by = db.relationship("User", foreign_keys=[created_by_user_id])


class JointProcurement(db.Model):
    __tablename__ = "joint_procurement"

    id = db.Column(db.Integer, primary_key=True)
    secondary_cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False, index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("joint_project.id"), nullable=True, index=True)
    title = db.Column(db.String(180), nullable=False)
    category = db.Column(db.String(100), nullable=False)
    quantity = db.Column(db.Float, nullable=False, default=0)
    unit = db.Column(db.String(40), nullable=True)
    supplier_name = db.Column(db.String(180), nullable=True)
    estimated_cost = db.Column(db.Float, nullable=False, default=0)
    actual_cost = db.Column(db.Float, nullable=False, default=0)
    order_date = db.Column(db.Date, nullable=True)
    delivery_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(40), nullable=False, default="Pending Approval", index=True)
    notes = db.Column(db.Text, nullable=True)
    requested_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    approved_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)

    secondary_cooperative = db.relationship("Cooperative", foreign_keys=[secondary_cooperative_id])
    project = db.relationship("JointProject", foreign_keys=[project_id])
    requested_by = db.relationship("User", foreign_keys=[requested_by_user_id])
    approved_by = db.relationship("User", foreign_keys=[approved_by_user_id])


class PrimaryContributionAccount(db.Model):
    __tablename__ = "primary_contribution_account"
    __table_args__ = (
        db.UniqueConstraint(
            "secondary_cooperative_id", "primary_cooperative_id", "fiscal_year",
            name="uq_primary_contribution_account",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    secondary_cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False, index=True)
    primary_cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False, index=True)
    fiscal_year = db.Column(db.Integer, nullable=False, index=True)
    expected_amount = db.Column(db.Float, nullable=False, default=0)
    notes = db.Column(db.Text, nullable=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)

    secondary_cooperative = db.relationship("Cooperative", foreign_keys=[secondary_cooperative_id])
    primary_cooperative = db.relationship("Cooperative", foreign_keys=[primary_cooperative_id])
    created_by = db.relationship("User", foreign_keys=[created_by_user_id])

    @property
    def confirmed_paid(self):
        return sum(float(p.amount or 0) for p in self.payments if p.status == "Confirmed")

    @property
    def pending_paid(self):
        return sum(float(p.amount or 0) for p in self.payments if p.status == "Pending Confirmation")

    @property
    def outstanding_amount(self):
        return max(float(self.expected_amount or 0) - self.confirmed_paid, 0.0)

    @property
    def recordable_amount(self):
        """Amount still safe for the Treasurer to record after confirmed and pending receipts."""
        return max(float(self.expected_amount or 0) - self.confirmed_paid - self.pending_paid, 0.0)


class PrimaryContributionPayment(db.Model):
    __tablename__ = "primary_contribution_payment"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("primary_contribution_account.id", ondelete="CASCADE"), nullable=False, index=True)
    secondary_cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False, index=True)
    primary_cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False, index=True)
    amount = db.Column(db.Float, nullable=False)
    payment_date = db.Column(db.Date, nullable=False, index=True)
    method = db.Column(db.String(60), nullable=True)
    reference = db.Column(db.String(120), nullable=True)
    status = db.Column(db.String(40), nullable=False, default="Pending Confirmation", index=True)
    notes = db.Column(db.Text, nullable=True)
    recorded_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    decided_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    decided_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)

    account = db.relationship(
        "PrimaryContributionAccount",
        backref=db.backref("payments", cascade="all, delete-orphan", order_by="PrimaryContributionPayment.payment_date.desc()"),
    )
    secondary_cooperative = db.relationship("Cooperative", foreign_keys=[secondary_cooperative_id])
    primary_cooperative = db.relationship("Cooperative", foreign_keys=[primary_cooperative_id])
    recorded_by = db.relationship("User", foreign_keys=[recorded_by_user_id])
    decided_by = db.relationship("User", foreign_keys=[decided_by_user_id])


class JointMarketContract(db.Model):
    __tablename__ = "joint_market_contract"

    id = db.Column(db.Integer, primary_key=True)
    secondary_cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False, index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("joint_project.id"), nullable=True, index=True)
    title = db.Column(db.String(180), nullable=False)
    buyer_name = db.Column(db.String(180), nullable=False)
    product = db.Column(db.String(120), nullable=False)
    target_quantity = db.Column(db.Float, nullable=False, default=0)
    unit = db.Column(db.String(40), nullable=True)
    contract_value = db.Column(db.Float, nullable=False, default=0)
    delivery_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(40), nullable=False, default="Planned", index=True)
    notes = db.Column(db.Text, nullable=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)

    secondary_cooperative = db.relationship("Cooperative", foreign_keys=[secondary_cooperative_id])
    project = db.relationship("JointProject", foreign_keys=[project_id])
    created_by = db.relationship("User", foreign_keys=[created_by_user_id])


# ---------------------------------------------------------------------------
# Scope helpers
# ---------------------------------------------------------------------------
def _secondary_context():
    access = current_access()
    cooperative = current_cooperative()
    if (
        not access
        or access.role not in SECONDARY_EXECUTIVE_ROLES
        or not cooperative
        or cooperative.cooperative_type != "Secondary"
        or access.cooperative_id != cooperative.id
    ):
        abort(403)
    return access, cooperative


def _child_primary(secondary_id, primary_id):
    return Cooperative.query.filter_by(
        id=primary_id, parent_id=secondary_id, cooperative_type="Primary", status="Active"
    ).first()


def _project_or_404(secondary_id, project_id):
    return JointProject.query.filter_by(id=project_id, secondary_cooperative_id=secondary_id).first_or_404()


def _asset_or_404(secondary_id, asset_id):
    return SharedAsset.query.filter_by(id=asset_id, secondary_cooperative_id=secondary_id).first_or_404()


def _money(value, field_name):
    parsed = parse_float(value, 0)
    if parsed is None or parsed < 0:
        raise ValueError(f"{field_name} cannot be negative.")
    return float(parsed)


def _date_value(raw, field_name, required=False):
    try:
        value = parse_date(raw)
    except ValueError as exc:
        raise ValueError(f"Enter a valid {field_name.lower()}.") from exc
    if required and not value:
        raise ValueError(f"{field_name} is required.")
    return value


# ---------------------------------------------------------------------------
# Joint Operations dashboard
# ---------------------------------------------------------------------------
@bp.route("/joint-operations")
@roles_required(*SECONDARY_EXECUTIVE_ROLES)
def dashboard():
    access, cooperative = _secondary_context()
    secondary_id = cooperative.id
    year = parse_int(request.args.get("year")) or crm_today().year
    if year < 2020 or year > 2100:
        year = crm_today().year

    primaries = Cooperative.query.filter_by(
        parent_id=secondary_id, cooperative_type="Primary", status="Active"
    ).order_by(Cooperative.name.asc()).all()
    projects = JointProject.query.filter_by(secondary_cooperative_id=secondary_id).order_by(
        JointProject.created_at.desc()
    ).all()
    assets = SharedAsset.query.filter_by(secondary_cooperative_id=secondary_id).order_by(
        SharedAsset.name.asc()
    ).all()
    usages = SharedAssetUsage.query.filter_by(secondary_cooperative_id=secondary_id).order_by(
        SharedAssetUsage.start_date.desc()
    ).limit(30).all()
    procurements = JointProcurement.query.filter_by(secondary_cooperative_id=secondary_id).order_by(
        JointProcurement.created_at.desc()
    ).all()
    contribution_accounts = PrimaryContributionAccount.query.filter_by(
        secondary_cooperative_id=secondary_id, fiscal_year=year
    ).order_by(PrimaryContributionAccount.id.asc()).all()
    payments = PrimaryContributionPayment.query.filter_by(secondary_cooperative_id=secondary_id).order_by(
        PrimaryContributionPayment.payment_date.desc(), PrimaryContributionPayment.created_at.desc()
    ).limit(30).all()
    contracts = JointMarketContract.query.filter_by(secondary_cooperative_id=secondary_id).order_by(
        JointMarketContract.created_at.desc()
    ).all()

    expected = sum(float(a.expected_amount or 0) for a in contribution_accounts)
    confirmed = sum(a.confirmed_paid for a in contribution_accounts)
    pending = sum(a.pending_paid for a in contribution_accounts)
    stats = {
        "active_projects": sum(1 for p in projects if p.status not in {"Completed", "Cancelled"}),
        "shared_assets": sum(1 for a in assets if a.status != "Retired"),
        "pending_procurement": sum(1 for p in procurements if p.status == "Pending Approval"),
        "pending_contribution_payments": sum(1 for p in payments if p.status == "Pending Confirmation"),
        "expected_contributions": expected,
        "confirmed_contributions": confirmed,
        "pending_contributions": pending,
        "outstanding_contributions": max(expected - confirmed, 0.0),
    }

    primary_summaries = []
    for primary in primaries:
        primary_summaries.append({
            "cooperative": primary,
            "members": Farmer.query.filter_by(cooperative_id=primary.id, status="Active").count(),
            "farms": Farm.query.filter_by(cooperative_id=primary.id, status="Active").count(),
            "crops": Crop.query.filter_by(cooperative_id=primary.id).count(),
            "open_actions": Task.query.filter(
                Task.cooperative_id == primary.id,
                Task.resolution_id.isnot(None),
                Task.status.notin_(["Verified", "Completed", "Closed"]),
            ).count(),
        })

    return render_template(
        "joint_operations/dashboard.html",
        year=year,
        primaries=primaries,
        primary_summaries=primary_summaries,
        projects=projects,
        assets=assets,
        usages=usages,
        procurements=procurements,
        contribution_accounts=contribution_accounts,
        contribution_payments=payments,
        contracts=contracts,
        stats=stats,
        project_types=PROJECT_TYPES,
        asset_categories=ASSET_CATEGORIES,
        can_governance_record=access.role in JOINT_GOVERNANCE_RECORD_ROLES,
        can_asset_record=access.role in JOINT_ASSET_RECORD_ROLES,
        can_finance_record=access.role in JOINT_FINANCE_RECORD_ROLES,
        can_finance_approve=access.role in JOINT_FINANCE_APPROVAL_ROLES,
    )


# ---------------------------------------------------------------------------
# Joint projects and Primary allocations
# ---------------------------------------------------------------------------
@bp.route("/joint-operations/projects", methods=["POST"])
@roles_required(*JOINT_GOVERNANCE_RECORD_ROLES)
def project_create():
    access, cooperative = _secondary_context()
    title = request.form.get("title", "").strip()
    project_type = request.form.get("project_type", "").strip()
    if not title or project_type not in PROJECT_TYPES:
        return "Project title and a valid project type are required.", 400
    try:
        start_date = _date_value(request.form.get("start_date"), "Start date")
        end_date = _date_value(request.form.get("end_date"), "End date")
        budget_amount = _money(request.form.get("budget_amount"), "Budget amount")
    except ValueError as exc:
        return str(exc), 400
    if start_date and end_date and end_date < start_date:
        return "End date cannot be before the start date.", 400
    item = JointProject(
        secondary_cooperative_id=cooperative.id,
        title=title[:180],
        project_type=project_type,
        description=request.form.get("description", "").strip() or None,
        start_date=start_date,
        end_date=end_date,
        budget_amount=budget_amount,
        status=request.form.get("status", "Planned").strip() or "Planned",
        created_by_user_id=session["user_id"],
    )
    db.session.add(item)
    db.session.flush()
    add_audit_log(
        "JOINT_PROJECT_CREATED", "JointProject", item.id,
        f"{item.title} ({item.project_type})",
        cooperative_id=cooperative.id,
    )
    db.session.commit()
    flash("Joint project created.", "success")
    return redirect(url_for("jointops.dashboard"))


@bp.route("/joint-operations/projects/<int:project_id>/allocation", methods=["POST"])
@roles_required(*JOINT_GOVERNANCE_RECORD_ROLES)
def project_allocation(project_id):
    access, cooperative = _secondary_context()
    project = _project_or_404(cooperative.id, project_id)
    primary_id = parse_int(request.form.get("primary_cooperative_id"))
    primary = _child_primary(cooperative.id, primary_id)
    if not primary:
        return "Choose a Primary cooperative that belongs to this Secondary cooperative.", 400
    try:
        allocated_amount = _money(request.form.get("allocated_amount"), "Allocated amount")
        hectares = _money(request.form.get("hectares"), "Hectares")
    except ValueError as exc:
        return str(exc), 400
    progress = parse_int(request.form.get("progress_percentage"))
    progress = 0 if progress is None else progress
    if progress < 0 or progress > 100:
        return "Progress must be between 0 and 100 percent.", 400
    item = JointProjectAllocation.query.filter_by(
        project_id=project.id, primary_cooperative_id=primary.id
    ).first()
    if not item:
        item = JointProjectAllocation(
            project_id=project.id,
            secondary_cooperative_id=cooperative.id,
            primary_cooperative_id=primary.id,
            updated_by_user_id=session["user_id"],
        )
        db.session.add(item)
    item.allocated_amount = allocated_amount
    item.hectares = hectares
    item.progress_percentage = progress
    item.notes = request.form.get("notes", "").strip() or None
    item.updated_by_user_id = session["user_id"]
    item.updated_at = utc_now()
    db.session.flush()
    add_audit_log(
        "JOINT_PROJECT_ALLOCATION_UPDATED", "JointProjectAllocation", item.id,
        f"{project.title}: {primary.name} R{allocated_amount:.2f}, {hectares:.2f} ha, {progress}%",
        cooperative_id=cooperative.id,
    )
    db.session.commit()
    flash(f"{primary.name} allocation updated.", "success")
    return redirect(url_for("jointops.dashboard"))


@bp.route("/joint-operations/projects/<int:project_id>/status", methods=["POST"])
@roles_required(*JOINT_GOVERNANCE_RECORD_ROLES)
def project_status(project_id):
    access, cooperative = _secondary_context()
    project = _project_or_404(cooperative.id, project_id)
    status = request.form.get("status", "").strip()
    if status not in {"Planned", "In Progress", "On Hold", "Completed", "Cancelled"}:
        return "Choose a valid project status.", 400
    project.status = status
    add_audit_log(
        "JOINT_PROJECT_STATUS_CHANGED", "JointProject", project.id, status,
        cooperative_id=cooperative.id,
    )
    db.session.commit()
    return redirect(url_for("jointops.dashboard"))


# ---------------------------------------------------------------------------
# Shared assets and allocation/usage
# ---------------------------------------------------------------------------
@bp.route("/joint-operations/assets", methods=["POST"])
@roles_required(*JOINT_ASSET_RECORD_ROLES)
def asset_create():
    access, cooperative = _secondary_context()
    name = request.form.get("name", "").strip()
    category = request.form.get("category", "").strip()
    if not name or category not in ASSET_CATEGORIES:
        return "Asset name and a valid category are required.", 400
    try:
        acquisition_date = _date_value(request.form.get("acquisition_date"), "Acquisition date")
        acquisition_value = _money(request.form.get("acquisition_value"), "Acquisition value")
    except ValueError as exc:
        return str(exc), 400
    item = SharedAsset(
        secondary_cooperative_id=cooperative.id,
        name=name[:160], category=category,
        identifier=request.form.get("identifier", "").strip()[:120] or None,
        acquisition_date=acquisition_date,
        acquisition_value=acquisition_value,
        location=request.form.get("location", "").strip()[:200] or None,
        status=request.form.get("status", "Available").strip() or "Available",
        notes=request.form.get("notes", "").strip() or None,
        created_by_user_id=session["user_id"],
    )
    db.session.add(item)
    db.session.flush()
    add_audit_log("SHARED_ASSET_REGISTERED", "SharedAsset", item.id, item.name, cooperative_id=cooperative.id)
    db.session.commit()
    flash("Shared asset registered.", "success")
    return redirect(url_for("jointops.dashboard"))


@bp.route("/joint-operations/assets/<int:asset_id>/usage", methods=["POST"])
@roles_required(*JOINT_GOVERNANCE_RECORD_ROLES)
def asset_usage_add(asset_id):
    access, cooperative = _secondary_context()
    asset = _asset_or_404(cooperative.id, asset_id)
    primary_id = parse_int(request.form.get("primary_cooperative_id"))
    primary = _child_primary(cooperative.id, primary_id)
    if not primary:
        return "Choose a Primary cooperative that belongs to this Secondary cooperative.", 400
    purpose = request.form.get("purpose", "").strip()
    if not purpose:
        return "Purpose is required.", 400
    try:
        start_date = _date_value(request.form.get("start_date"), "Start date", required=True)
        end_date = _date_value(request.form.get("end_date"), "End date")
        estimated_cost = _money(request.form.get("estimated_cost"), "Estimated cost")
        actual_cost = _money(request.form.get("actual_cost"), "Actual cost")
    except ValueError as exc:
        return str(exc), 400
    if end_date and end_date < start_date:
        return "End date cannot be before the start date.", 400
    item = SharedAssetUsage(
        asset_id=asset.id,
        secondary_cooperative_id=cooperative.id,
        primary_cooperative_id=primary.id,
        purpose=purpose[:220],
        start_date=start_date,
        end_date=end_date,
        estimated_cost=estimated_cost,
        actual_cost=actual_cost,
        status=request.form.get("status", "Scheduled").strip() or "Scheduled",
        notes=request.form.get("notes", "").strip() or None,
        created_by_user_id=session["user_id"],
    )
    db.session.add(item)
    db.session.flush()
    add_audit_log(
        "SHARED_ASSET_USAGE_RECORDED", "SharedAssetUsage", item.id,
        f"{asset.name} → {primary.name}: {purpose}", cooperative_id=cooperative.id,
    )
    db.session.commit()
    flash("Shared asset usage recorded.", "success")
    return redirect(url_for("jointops.dashboard"))


# ---------------------------------------------------------------------------
# Joint procurement: Treasurer records, Chairperson approves
# ---------------------------------------------------------------------------
@bp.route("/joint-operations/procurements", methods=["POST"])
@roles_required(*JOINT_FINANCE_RECORD_ROLES)
def procurement_create():
    access, cooperative = _secondary_context()
    title = request.form.get("title", "").strip()
    category = request.form.get("category", "").strip()
    if not title or not category:
        return "Procurement title and category are required.", 400
    try:
        quantity = _money(request.form.get("quantity"), "Quantity")
        estimated_cost = _money(request.form.get("estimated_cost"), "Estimated cost")
    except ValueError as exc:
        return str(exc), 400
    project_id = parse_int(request.form.get("project_id"))
    project = _project_or_404(cooperative.id, project_id) if project_id else None
    item = JointProcurement(
        secondary_cooperative_id=cooperative.id,
        project_id=project.id if project else None,
        title=title[:180], category=category[:100], quantity=quantity,
        unit=request.form.get("unit", "").strip()[:40] or None,
        supplier_name=request.form.get("supplier_name", "").strip()[:180] or None,
        estimated_cost=estimated_cost,
        status="Pending Approval",
        notes=request.form.get("notes", "").strip() or None,
        requested_by_user_id=session["user_id"],
    )
    db.session.add(item)
    db.session.flush()
    add_audit_log(
        "JOINT_PROCUREMENT_SUBMITTED", "JointProcurement", item.id,
        f"{item.title}: R{estimated_cost:.2f}", cooperative_id=cooperative.id,
    )
    db.session.commit()
    flash("Joint procurement submitted for Chairperson approval.", "success")
    return redirect(url_for("jointops.dashboard"))


@bp.route("/joint-operations/procurements/<int:procurement_id>/decision", methods=["POST"])
@roles_required(*JOINT_FINANCE_APPROVAL_ROLES)
def procurement_decision(procurement_id):
    access, cooperative = _secondary_context()
    item = JointProcurement.query.filter_by(
        id=procurement_id, secondary_cooperative_id=cooperative.id
    ).first_or_404()
    if item.status != "Pending Approval":
        return "Only pending procurements can be decided.", 400
    decision = request.form.get("decision", "").strip().lower()
    if decision not in {"approve", "reject"}:
        return "Choose approve or reject.", 400
    item.status = "Approved" if decision == "approve" else "Rejected"
    item.approved_by_user_id = session["user_id"]
    item.approved_at = utc_now()
    add_audit_log(
        "JOINT_PROCUREMENT_APPROVED" if decision == "approve" else "JOINT_PROCUREMENT_REJECTED",
        "JointProcurement", item.id, item.title, cooperative_id=cooperative.id,
    )
    db.session.commit()
    flash(f"Procurement {item.status.lower()}.", "success" if decision == "approve" else "warning")
    return redirect(url_for("jointops.dashboard"))


@bp.route("/joint-operations/procurements/<int:procurement_id>/progress", methods=["POST"])
@roles_required(*JOINT_FINANCE_RECORD_ROLES)
def procurement_progress(procurement_id):
    access, cooperative = _secondary_context()
    item = JointProcurement.query.filter_by(
        id=procurement_id, secondary_cooperative_id=cooperative.id
    ).first_or_404()
    status = request.form.get("status", "").strip()
    if item.status not in {"Approved", "Ordered", "Delivered"} or status not in {"Ordered", "Delivered", "Cancelled"}:
        return "Only approved procurement can progress to ordered, delivered or cancelled.", 400
    try:
        actual_cost = _money(request.form.get("actual_cost"), "Actual cost")
        order_date = _date_value(request.form.get("order_date"), "Order date")
        delivery_date = _date_value(request.form.get("delivery_date"), "Delivery date")
    except ValueError as exc:
        return str(exc), 400
    if order_date and delivery_date and delivery_date < order_date:
        return "Delivery date cannot be before order date.", 400
    item.status = status
    item.actual_cost = actual_cost
    item.order_date = order_date
    item.delivery_date = delivery_date
    add_audit_log(
        "JOINT_PROCUREMENT_PROGRESS", "JointProcurement", item.id,
        f"{status}; actual R{actual_cost:.2f}", cooperative_id=cooperative.id,
    )
    db.session.commit()
    return redirect(url_for("jointops.dashboard"))


# ---------------------------------------------------------------------------
# Primary cooperative contributions to MFPSU
# ---------------------------------------------------------------------------
@bp.route("/joint-operations/contribution-accounts", methods=["POST"])
@roles_required(*JOINT_FINANCE_RECORD_ROLES)
def contribution_account_save():
    access, cooperative = _secondary_context()
    primary_id = parse_int(request.form.get("primary_cooperative_id"))
    primary = _child_primary(cooperative.id, primary_id)
    if not primary:
        return "Choose a Primary cooperative that belongs to this Secondary cooperative.", 400
    year = parse_int(request.form.get("fiscal_year"))
    if not year or year < 2020 or year > 2100:
        return "Enter a valid fiscal year.", 400
    try:
        expected = _money(request.form.get("expected_amount"), "Expected contribution")
    except ValueError as exc:
        return str(exc), 400
    item = PrimaryContributionAccount.query.filter_by(
        secondary_cooperative_id=cooperative.id,
        primary_cooperative_id=primary.id,
        fiscal_year=year,
    ).first()
    if not item:
        item = PrimaryContributionAccount(
            secondary_cooperative_id=cooperative.id,
            primary_cooperative_id=primary.id,
            fiscal_year=year,
            created_by_user_id=session["user_id"],
        )
        db.session.add(item)
    item.expected_amount = expected
    item.notes = request.form.get("notes", "").strip() or None
    db.session.flush()
    add_audit_log(
        "PRIMARY_CONTRIBUTION_ACCOUNT_SET", "PrimaryContributionAccount", item.id,
        f"{primary.name} {year}: expected R{expected:.2f}", cooperative_id=cooperative.id,
    )
    db.session.commit()
    flash(f"{primary.name} contribution target saved.", "success")
    return redirect(url_for("jointops.dashboard", year=year))


@bp.route("/joint-operations/contribution-accounts/<int:account_id>/payments", methods=["POST"])
@roles_required(*JOINT_FINANCE_RECORD_ROLES)
def contribution_payment_add(account_id):
    access, cooperative = _secondary_context()
    account = PrimaryContributionAccount.query.filter_by(
        id=account_id, secondary_cooperative_id=cooperative.id
    ).first_or_404()
    try:
        amount = _money(request.form.get("amount"), "Payment amount")
        payment_date = _date_value(request.form.get("payment_date"), "Payment date", required=True)
    except ValueError as exc:
        return str(exc), 400
    if amount <= 0:
        return "Payment amount must be greater than zero.", 400
    available = account.recordable_amount
    if available <= 1e-9:
        return "This Primary cooperative has no contribution amount left to record for this year.", 400
    if amount > available + 1e-9:
        return f"Payment exceeds the amount still available to record. Maximum: R {available:.2f}.", 400
    item = PrimaryContributionPayment(
        account_id=account.id,
        secondary_cooperative_id=cooperative.id,
        primary_cooperative_id=account.primary_cooperative_id,
        amount=amount,
        payment_date=payment_date,
        method=request.form.get("method", "").strip()[:60] or None,
        reference=request.form.get("reference", "").strip()[:120] or None,
        status="Pending Confirmation",
        notes=request.form.get("notes", "").strip() or None,
        recorded_by_user_id=session["user_id"],
    )
    db.session.add(item)
    db.session.flush()
    add_audit_log(
        "PRIMARY_CONTRIBUTION_RECORDED", "PrimaryContributionPayment", item.id,
        f"{account.primary_cooperative.name}: R{amount:.2f}", cooperative_id=cooperative.id,
    )
    db.session.commit()
    flash("Primary cooperative contribution recorded for Chairperson confirmation.", "success")
    return redirect(url_for("jointops.dashboard", year=account.fiscal_year))


@bp.route("/joint-operations/contribution-payments/<int:payment_id>/decision", methods=["POST"])
@roles_required(*JOINT_FINANCE_APPROVAL_ROLES)
def contribution_payment_decision(payment_id):
    access, cooperative = _secondary_context()
    item = PrimaryContributionPayment.query.filter_by(
        id=payment_id, secondary_cooperative_id=cooperative.id
    ).first_or_404()
    if item.status != "Pending Confirmation":
        return "Only pending contribution payments can be decided.", 400
    decision = request.form.get("decision", "").strip().lower()
    if decision not in {"approve", "reject"}:
        return "Choose approve or reject.", 400
    item.status = "Confirmed" if decision == "approve" else "Rejected"
    item.decided_by_user_id = session["user_id"]
    item.decided_at = utc_now()
    add_audit_log(
        "PRIMARY_CONTRIBUTION_CONFIRMED" if decision == "approve" else "PRIMARY_CONTRIBUTION_REJECTED",
        "PrimaryContributionPayment", item.id,
        f"{item.primary_cooperative.name}: R{item.amount:.2f}", cooperative_id=cooperative.id,
    )
    db.session.commit()
    flash(f"Contribution payment {item.status.lower()}.", "success" if decision == "approve" else "warning")
    return redirect(url_for("jointops.dashboard", year=item.account.fiscal_year))


# ---------------------------------------------------------------------------
# Joint marketing / combined production contracts
# ---------------------------------------------------------------------------
@bp.route("/joint-operations/market-contracts", methods=["POST"])
@roles_required(*JOINT_GOVERNANCE_RECORD_ROLES)
def market_contract_create():
    access, cooperative = _secondary_context()
    title = request.form.get("title", "").strip()
    buyer_name = request.form.get("buyer_name", "").strip()
    product = request.form.get("product", "").strip()
    if not title or not buyer_name or not product:
        return "Contract title, buyer and product are required.", 400
    try:
        target_quantity = _money(request.form.get("target_quantity"), "Target quantity")
        contract_value = _money(request.form.get("contract_value"), "Contract value")
        delivery_date = _date_value(request.form.get("delivery_date"), "Delivery date")
    except ValueError as exc:
        return str(exc), 400
    project_id = parse_int(request.form.get("project_id"))
    project = _project_or_404(cooperative.id, project_id) if project_id else None
    item = JointMarketContract(
        secondary_cooperative_id=cooperative.id,
        project_id=project.id if project else None,
        title=title[:180], buyer_name=buyer_name[:180], product=product[:120],
        target_quantity=target_quantity,
        unit=request.form.get("unit", "").strip()[:40] or None,
        contract_value=contract_value,
        delivery_date=delivery_date,
        status=request.form.get("status", "Planned").strip() or "Planned",
        notes=request.form.get("notes", "").strip() or None,
        created_by_user_id=session["user_id"],
    )
    db.session.add(item)
    db.session.flush()
    add_audit_log(
        "JOINT_MARKET_CONTRACT_CREATED", "JointMarketContract", item.id,
        f"{item.product} → {item.buyer_name}; R{contract_value:.2f}", cooperative_id=cooperative.id,
    )
    db.session.commit()
    flash("Joint marketing contract/programme recorded.", "success")
    return redirect(url_for("jointops.dashboard"))


@bp.route("/joint-operations/market-contracts/<int:contract_id>/status", methods=["POST"])
@roles_required(*JOINT_GOVERNANCE_RECORD_ROLES)
def market_contract_status(contract_id):
    access, cooperative = _secondary_context()
    item = JointMarketContract.query.filter_by(
        id=contract_id, secondary_cooperative_id=cooperative.id
    ).first_or_404()
    status = request.form.get("status", "").strip()
    if status not in {"Planned", "Negotiating", "Contracted", "Delivering", "Completed", "Cancelled"}:
        return "Choose a valid contract status.", 400
    item.status = status
    add_audit_log("JOINT_MARKET_STATUS_CHANGED", "JointMarketContract", item.id, status, cooperative_id=cooperative.id)
    db.session.commit()
    return redirect(url_for("jointops.dashboard"))


# ---------------------------------------------------------------------------
# Read-only aggregate Primary cooperative summaries for Secondary oversight
# ---------------------------------------------------------------------------
@bp.route("/joint-operations/primary/<int:primary_id>")
@roles_required(*SECONDARY_EXECUTIVE_ROLES)
def primary_summary(primary_id):
    access, cooperative = _secondary_context()
    primary = _child_primary(cooperative.id, primary_id)
    if not primary:
        abort(404)

    active_members = Farmer.query.filter_by(cooperative_id=primary.id, status="Active").count()
    farms = Farm.query.filter_by(cooperative_id=primary.id, status="Active").all()
    total_hectares = sum(float(f.size or 0) for f in farms)
    crops = Crop.query.filter_by(cooperative_id=primary.id).all()
    crop_summary = {}
    for crop in crops:
        row = crop_summary.setdefault(crop.name, {"count": 0, "hectares": 0.0})
        row["count"] += 1
        row["hectares"] += float(crop.area_planted or 0)

    harvests = Harvest.query.filter_by(cooperative_id=primary.id).all()
    harvest_kg = 0.0
    for harvest in harvests:
        unit = (harvest.unit or "").strip().lower()
        if unit in {"kg", "kilogram", "kilograms"}:
            harvest_kg += float(harvest.quantity or 0)
        elif unit in {"tonne", "tonnes", "ton", "tons"}:
            harvest_kg += float(harvest.quantity or 0) * 1000

    open_actions = Task.query.filter(
        Task.cooperative_id == primary.id,
        Task.resolution_id.isnot(None),
        Task.status.notin_(["Verified", "Completed", "Closed"]),
    ).count()

    allocations = JointProjectAllocation.query.filter_by(
        secondary_cooperative_id=cooperative.id, primary_cooperative_id=primary.id
    ).order_by(JointProjectAllocation.updated_at.desc()).all()
    usages = SharedAssetUsage.query.filter_by(
        secondary_cooperative_id=cooperative.id, primary_cooperative_id=primary.id
    ).order_by(SharedAssetUsage.start_date.desc()).limit(20).all()
    accounts = PrimaryContributionAccount.query.filter_by(
        secondary_cooperative_id=cooperative.id, primary_cooperative_id=primary.id
    ).order_by(PrimaryContributionAccount.fiscal_year.desc()).all()

    summary = {
        "active_members": active_members,
        "farms": len(farms),
        "total_hectares": total_hectares,
        "crops": len(crops),
        "harvest_kg": harvest_kg,
        "open_actions": open_actions,
        "joint_allocated_amount": sum(float(item.allocated_amount or 0) for item in allocations),
        "shared_asset_cost": sum(float(item.actual_cost or 0) for item in usages),
        "secondary_contribution_confirmed": sum(float(item.confirmed_paid or 0) for item in accounts),
        "secondary_contribution_pending": sum(float(item.pending_paid or 0) for item in accounts),
        "secondary_contribution_outstanding": sum(float(item.outstanding_amount or 0) for item in accounts),
    }
    return render_template(
        "joint_operations/primary_summary.html",
        primary=primary,
        summary=summary,
        crop_summary=crop_summary,
        allocations=allocations,
        usages=usages,
        contribution_accounts=accounts,
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
def register_joint_operations(app):
    """Register the MFPSU joint-operations blueprint once the core app is loaded."""
    if "jointops" not in app.blueprints:
        app.register_blueprint(bp)
