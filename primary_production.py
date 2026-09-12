"""Primary cooperative production command centre.

Separates production oversight from routine field recording:
- Primary Chairperson approves production plans and verifies completed activities.
- Primary Vice Chairperson coordinates field operations and records usage/progress.
- Treasurer finance stays in the finance modules; this module only reports confirmed
  farm expenses alongside operational production usage.
"""
import importlib
import sys

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy import func


_CORE_NAMES = (
    "db", "User", "UserAccess", "Cooperative", "Farm", "Crop", "Harvest", "Expense",
    "InventoryItem", "InventoryTransaction", "Equipment", "CONFIRMED_EXPENSE_STATUSES",
    "current_access", "current_cooperative", "roles_required", "add_audit_log",
    "utc_now", "crm_today", "parse_int", "parse_float", "parse_date",
)
_core = sys.modules.get("__main__")
if _core is None or not hasattr(_core, "db"):
    _core = importlib.import_module("app")
for _name in _CORE_NAMES:
    globals()[_name] = getattr(_core, _name)

_phase7 = importlib.import_module("phase7")
ProductionInput = _phase7.ProductionInput

bp = Blueprint("primaryprod", __name__)

PRIMARY_PRODUCTION_VIEW_ROLES = {"Primary Chairperson", "Primary Vice Chairperson"}
PRIMARY_PRODUCTION_COORDINATOR_ROLES = {"Primary Vice Chairperson"}
PRIMARY_PRODUCTION_APPROVAL_ROLES = {"Primary Chairperson"}

PLAN_STATUSES = {"Pending Approval", "Approved", "Rejected", "Completed", "Cancelled"}
ACTIVITY_STATUSES = {"Planned", "In Progress", "Blocked", "Completed", "Verified"}
ACTIVITY_TYPES = (
    "Land Preparation", "Planting", "Fertilizer", "Irrigation", "Spraying", "Weeding",
    "Harvest Preparation", "Harvesting", "Transport", "Other",
)


class ProductionPlan(db.Model):
    __tablename__ = "production_plan"
    __table_args__ = (
        db.UniqueConstraint("crop_id", name="uq_production_plan_crop"),
    )

    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False, index=True)
    crop_id = db.Column(db.Integer, db.ForeignKey("crop.id", ondelete="CASCADE"), nullable=False, index=True)
    target_yield_per_ha_kg = db.Column(db.Float, nullable=False, default=0)
    approved_budget = db.Column(db.Float, nullable=False, default=0)
    status = db.Column(db.String(40), nullable=False, default="Pending Approval", index=True)
    notes = db.Column(db.Text, nullable=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    approved_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id])
    crop = db.relationship("Crop", backref=db.backref("production_plan", uselist=False, cascade="all, delete-orphan"))
    created_by = db.relationship("User", foreign_keys=[created_by_user_id])
    approved_by = db.relationship("User", foreign_keys=[approved_by_user_id])

    @property
    def target_total_kg(self):
        hectares = float(self.crop.area_planted or 0) if self.crop else 0
        return max(float(self.target_yield_per_ha_kg or 0) * hectares, 0.0)


class ProductionActivity(db.Model):
    __tablename__ = "production_activity"

    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False, index=True)
    plan_id = db.Column(db.Integer, db.ForeignKey("production_plan.id", ondelete="CASCADE"), nullable=False, index=True)
    activity_type = db.Column(db.String(80), nullable=False)
    title = db.Column(db.String(180), nullable=False)
    planned_date = db.Column(db.Date, nullable=True)
    due_date = db.Column(db.Date, nullable=True, index=True)
    status = db.Column(db.String(30), nullable=False, default="Planned", index=True)
    responsible_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    evidence_reference = db.Column(db.String(250), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)
    verified_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    verified_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)

    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id])
    plan = db.relationship(
        "ProductionPlan",
        backref=db.backref("activities", cascade="all, delete-orphan", order_by="ProductionActivity.due_date.asc()"),
    )
    responsible_user = db.relationship("User", foreign_keys=[responsible_user_id])
    created_by = db.relationship("User", foreign_keys=[created_by_user_id])
    verified_by = db.relationship("User", foreign_keys=[verified_by_user_id])

    @property
    def is_overdue(self):
        return bool(self.due_date and self.due_date < crm_today() and self.status not in {"Verified", "Completed"})


class ProductionEquipmentLog(db.Model):
    __tablename__ = "production_equipment_log"

    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False, index=True)
    crop_id = db.Column(db.Integer, db.ForeignKey("crop.id", ondelete="CASCADE"), nullable=False, index=True)
    equipment_id = db.Column(db.Integer, db.ForeignKey("equipment.id"), nullable=False, index=True)
    farm_id = db.Column(db.Integer, db.ForeignKey("farm.id"), nullable=False, index=True)
    purpose = db.Column(db.String(220), nullable=False)
    use_date = db.Column(db.Date, nullable=False, index=True)
    hours_used = db.Column(db.Float, nullable=False, default=0)
    fuel_litres = db.Column(db.Float, nullable=False, default=0)
    responsible_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)

    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id])
    crop = db.relationship("Crop", foreign_keys=[crop_id])
    equipment = db.relationship("Equipment", foreign_keys=[equipment_id])
    farm = db.relationship("Farm", foreign_keys=[farm_id])
    responsible_user = db.relationship("User", foreign_keys=[responsible_user_id])
    created_by = db.relationship("User", foreign_keys=[created_by_user_id])


def _primary_context():
    access = current_access()
    cooperative = current_cooperative()
    if (
        not access
        or access.role not in PRIMARY_PRODUCTION_VIEW_ROLES
        or not cooperative
        or cooperative.cooperative_type != "Primary"
        or access.cooperative_id != cooperative.id
    ):
        abort(403)
    return access, cooperative


def _own_crop(cooperative_id, crop_id):
    return Crop.query.filter_by(id=crop_id, cooperative_id=cooperative_id).first()


def _own_plan(cooperative_id, plan_id):
    return ProductionPlan.query.filter_by(id=plan_id, cooperative_id=cooperative_id).first()


def _date(raw, name, required=False):
    try:
        value = parse_date(raw)
    except ValueError as exc:
        raise ValueError(f"Enter a valid {name.lower()}.") from exc
    if required and not value:
        raise ValueError(f"{name} is required.")
    return value


def _non_negative(raw, name, default=0):
    value = parse_float(raw, default)
    value = default if value is None else float(value)
    if value < 0:
        raise ValueError(f"{name} cannot be negative.")
    return value


def _harvest_summary(crop):
    kg = 0.0
    other = {}
    for harvest in crop.harvests:
        if harvest.unit == "kg":
            kg += float(harvest.quantity or 0)
        elif harvest.unit == "tonnes":
            kg += float(harvest.quantity or 0) * 1000.0
        else:
            other[harvest.unit or "units"] = other.get(harvest.unit or "units", 0.0) + float(harvest.quantity or 0)
    return kg, other


def _confirmed_farm_expenses(crop):
    if not crop.farm_id:
        return 0.0
    query = Expense.query.filter(
        Expense.cooperative_id == crop.cooperative_id,
        Expense.farm_id == crop.farm_id,
        Expense.status.in_(CONFIRMED_EXPENSE_STATUSES),
    )
    if crop.planting_date:
        query = query.filter(Expense.expense_date >= crop.planting_date)
    if crop.expected_harvest_date:
        query = query.filter(Expense.expense_date <= crop.expected_harvest_date)
    return float(query.with_entities(func.coalesce(func.sum(Expense.amount), 0)).scalar() or 0)


def _activity_progress(plan):
    total = len(plan.activities)
    if not total:
        return 0
    verified = sum(1 for activity in plan.activities if activity.status == "Verified")
    completed = sum(1 for activity in plan.activities if activity.status == "Completed")
    return min(100, round(((verified + completed * 0.75) / total) * 100))


@bp.route("/production-control")
@roles_required(*PRIMARY_PRODUCTION_VIEW_ROLES)
def dashboard():
    access, cooperative = _primary_context()
    crops = Crop.query.filter_by(cooperative_id=cooperative.id).order_by(
        Crop.planting_date.desc().nullslast(), Crop.created_at.desc()
    ).all()
    rows = []
    total_area = 0.0
    operational_cost = 0.0
    finance_cost = 0.0
    target_kg = 0.0
    harvested_kg = 0.0
    overdue = 0
    blocked = 0
    for crop in crops:
        plan = ProductionPlan.query.filter_by(crop_id=crop.id, cooperative_id=cooperative.id).first()
        op_cost = sum(float(item.total_cost or 0) for item in crop.production_inputs)
        yield_kg, other_yield = _harvest_summary(crop)
        hectares = float(crop.area_planted or 0)
        confirmed_cost = _confirmed_farm_expenses(crop)
        crop_target = plan.target_total_kg if plan else 0.0
        crop_overdue = sum(1 for a in (plan.activities if plan else []) if a.is_overdue)
        crop_blocked = sum(1 for a in (plan.activities if plan else []) if a.status == "Blocked")
        rows.append({
            "crop": crop,
            "plan": plan,
            "operational_cost": op_cost,
            "confirmed_finance_cost": confirmed_cost,
            "harvested_kg": yield_kg,
            "other_yield": other_yield,
            "yield_per_ha": (yield_kg / hectares) if hectares > 0 else None,
            "target_kg": crop_target,
            "progress": _activity_progress(plan) if plan else 0,
            "overdue": crop_overdue,
            "blocked": crop_blocked,
        })
        total_area += hectares
        operational_cost += op_cost
        finance_cost += confirmed_cost
        target_kg += crop_target
        harvested_kg += yield_kg
        overdue += crop_overdue
        blocked += crop_blocked

    plans = ProductionPlan.query.filter_by(cooperative_id=cooperative.id).order_by(ProductionPlan.updated_at.desc()).all()
    active_crops = [crop for crop in crops if crop.status not in {"Harvested", "Failed"}]
    plan_by_crop = {plan.crop_id: plan for plan in plans}
    plan_crops = [
        crop for crop in active_crops
        if crop.id not in plan_by_crop or plan_by_crop[crop.id].status == "Rejected"
    ]
    activities = ProductionActivity.query.filter_by(cooperative_id=cooperative.id).order_by(
        ProductionActivity.due_date.asc().nullslast(), ProductionActivity.created_at.desc()
    ).limit(60).all()
    equipment_logs = ProductionEquipmentLog.query.filter_by(cooperative_id=cooperative.id).order_by(
        ProductionEquipmentLog.use_date.desc(), ProductionEquipmentLog.created_at.desc()
    ).limit(30).all()
    inventory = InventoryItem.query.filter_by(cooperative_id=cooperative.id, status="Active").order_by(InventoryItem.name.asc()).all()
    equipment = Equipment.query.filter_by(cooperative_id=cooperative.id).order_by(Equipment.name.asc()).all()
    users = User.query.join(UserAccess, UserAccess.user_id == User.id).filter(
        UserAccess.cooperative_id == cooperative.id, UserAccess.status == "Active"
    ).order_by(User.fullname.asc()).all()

    stats = {
        "active_crops": sum(1 for crop in crops if crop.status not in {"Harvested", "Failed"}),
        "total_area": total_area,
        "approved_budget": sum(float(p.approved_budget or 0) for p in plans if p.status in {"Approved", "Completed"}),
        "operational_cost": operational_cost,
        "confirmed_finance_cost": finance_cost,
        "target_kg": target_kg,
        "harvested_kg": harvested_kg,
        "overdue": overdue,
        "blocked": blocked,
    }
    return render_template(
        "primary_production/dashboard.html",
        rows=rows, plans=plans, activities=activities, equipment_logs=equipment_logs,
        crops=crops, active_crops=active_crops, plan_crops=plan_crops,
        inventory=inventory, equipment=equipment, users=users, stats=stats,
        activity_types=ACTIVITY_TYPES,
        can_coordinate=access.role in PRIMARY_PRODUCTION_COORDINATOR_ROLES,
        can_approve=access.role in PRIMARY_PRODUCTION_APPROVAL_ROLES,
    )


@bp.route("/production-control/plans", methods=["POST"])
@roles_required(*PRIMARY_PRODUCTION_COORDINATOR_ROLES)
def plan_save():
    access, cooperative = _primary_context()
    crop_id = parse_int(request.form.get("crop_id"))
    crop = _own_crop(cooperative.id, crop_id)
    if not crop:
        return "Choose a crop from your Primary cooperative.", 400
    if crop.status in {"Harvested", "Failed"}:
        return "This crop is closed and is no longer eligible for a production plan action.", 400
    try:
        target = _non_negative(request.form.get("target_yield_per_ha_kg"), "Target yield per hectare")
        budget = _non_negative(request.form.get("approved_budget"), "Planned production budget")
    except ValueError as exc:
        return str(exc), 400
    plan = ProductionPlan.query.filter_by(crop_id=crop.id, cooperative_id=cooperative.id).first()
    if not plan:
        plan = ProductionPlan(
            cooperative_id=cooperative.id,
            crop_id=crop.id,
            created_by_user_id=session["user_id"],
        )
        db.session.add(plan)
    if plan.status in {"Pending Approval", "Approved", "Completed"}:
        return "This production plan already has an active or completed workflow and is no longer available in the create/revise list.", 400
    plan.target_yield_per_ha_kg = target
    plan.approved_budget = budget
    plan.notes = request.form.get("notes", "").strip() or None
    plan.status = "Pending Approval"
    plan.approved_by_user_id = None
    plan.approved_at = None
    plan.updated_at = utc_now()
    db.session.flush()
    add_audit_log(
        "PRODUCTION_PLAN_SUBMITTED", "ProductionPlan", plan.id,
        f"{crop.name}: target {target:.2f} kg/ha; budget R{budget:.2f}",
        cooperative_id=cooperative.id,
    )
    db.session.commit()
    flash("Production plan submitted to the Primary Chairperson for approval.", "success")
    return redirect(url_for("primaryprod.dashboard"))


@bp.route("/production-control/plans/<int:plan_id>/decision", methods=["POST"])
@roles_required(*PRIMARY_PRODUCTION_APPROVAL_ROLES)
def plan_decision(plan_id):
    access, cooperative = _primary_context()
    plan = _own_plan(cooperative.id, plan_id)
    if not plan:
        abort(404)
    if plan.status != "Pending Approval":
        return "Only pending production plans can be decided.", 400
    decision = request.form.get("decision", "").strip().lower()
    if decision not in {"approve", "reject"}:
        return "Choose approve or reject.", 400
    plan.status = "Approved" if decision == "approve" else "Rejected"
    plan.approved_by_user_id = session["user_id"]
    plan.approved_at = utc_now()
    add_audit_log(
        "PRODUCTION_PLAN_APPROVED" if decision == "approve" else "PRODUCTION_PLAN_REJECTED",
        "ProductionPlan", plan.id, plan.crop.name if plan.crop else str(plan.id), cooperative_id=cooperative.id,
    )
    db.session.commit()
    flash(f"Production plan {plan.status.lower()}.", "success" if decision == "approve" else "warning")
    return redirect(url_for("primaryprod.dashboard"))


@bp.route("/production-control/activities", methods=["POST"])
@roles_required(*PRIMARY_PRODUCTION_COORDINATOR_ROLES)
def activity_add():
    access, cooperative = _primary_context()
    plan_id = parse_int(request.form.get("plan_id"))
    plan = _own_plan(cooperative.id, plan_id)
    if not plan or plan.status != "Approved":
        return "Choose an approved production plan that is still active.", 400
    activity_type = request.form.get("activity_type", "").strip()
    title = request.form.get("title", "").strip()
    if activity_type not in ACTIVITY_TYPES or not title:
        return "Activity type and title are required.", 400
    try:
        planned_date = _date(request.form.get("planned_date"), "Planned date")
        due_date = _date(request.form.get("due_date"), "Due date")
    except ValueError as exc:
        return str(exc), 400
    if planned_date and due_date and due_date < planned_date:
        return "Due date cannot be before the planned date.", 400
    responsible_user_id = parse_int(request.form.get("responsible_user_id"))
    if responsible_user_id:
        responsible = UserAccess.query.filter_by(
            user_id=responsible_user_id, cooperative_id=cooperative.id, status="Active"
        ).first()
        if not responsible:
            return "Responsible person must be an active user of this Primary cooperative.", 400
    activity = ProductionActivity(
        cooperative_id=cooperative.id, plan_id=plan.id, activity_type=activity_type,
        title=title[:180], planned_date=planned_date, due_date=due_date, status="Planned",
        responsible_user_id=responsible_user_id,
        notes=request.form.get("notes", "").strip() or None,
        created_by_user_id=session["user_id"],
    )
    db.session.add(activity)
    db.session.flush()
    add_audit_log(
        "PRODUCTION_ACTIVITY_CREATED", "ProductionActivity", activity.id,
        f"{plan.crop.name}: {activity.title}", cooperative_id=cooperative.id,
    )
    db.session.commit()
    return redirect(url_for("primaryprod.dashboard"))


@bp.route("/production-control/activities/<int:activity_id>/progress", methods=["POST"])
@roles_required(*PRIMARY_PRODUCTION_COORDINATOR_ROLES)
def activity_progress(activity_id):
    access, cooperative = _primary_context()
    activity = ProductionActivity.query.filter_by(id=activity_id, cooperative_id=cooperative.id).first_or_404()
    status = request.form.get("status", "").strip()
    if status not in {"Planned", "In Progress", "Blocked", "Completed"}:
        return "Choose a valid activity status.", 400
    activity.status = status
    activity.evidence_reference = request.form.get("evidence_reference", "").strip()[:250] or activity.evidence_reference
    activity.notes = request.form.get("notes", "").strip() or activity.notes
    activity.completed_at = utc_now() if status == "Completed" else None
    if status != "Completed":
        activity.verified_by_user_id = None
        activity.verified_at = None
    add_audit_log(
        "PRODUCTION_ACTIVITY_PROGRESS", "ProductionActivity", activity.id,
        f"{activity.title}: {status}", cooperative_id=cooperative.id,
    )
    db.session.commit()
    return redirect(url_for("primaryprod.dashboard"))


@bp.route("/production-control/activities/<int:activity_id>/verify", methods=["POST"])
@roles_required(*PRIMARY_PRODUCTION_APPROVAL_ROLES)
def activity_verify(activity_id):
    access, cooperative = _primary_context()
    activity = ProductionActivity.query.filter_by(id=activity_id, cooperative_id=cooperative.id).first_or_404()
    if activity.status != "Completed":
        return "Only completed production activities can be verified.", 400
    if activity.responsible_user_id == session.get("user_id"):
        return "The person responsible for the activity cannot verify their own completion.", 400
    activity.status = "Verified"
    activity.verified_by_user_id = session["user_id"]
    activity.verified_at = utc_now()
    add_audit_log(
        "PRODUCTION_ACTIVITY_VERIFIED", "ProductionActivity", activity.id,
        activity.title, cooperative_id=cooperative.id,
    )
    db.session.commit()
    flash("Production activity verified.", "success")
    return redirect(url_for("primaryprod.dashboard"))


@bp.route("/production-control/input-usage", methods=["POST"])
@roles_required(*PRIMARY_PRODUCTION_COORDINATOR_ROLES)
def input_usage_add():
    access, cooperative = _primary_context()
    crop_id = parse_int(request.form.get("crop_id"))
    crop = _own_crop(cooperative.id, crop_id)
    if not crop:
        return "Choose a crop from your Primary cooperative.", 400
    if crop.status in {"Harvested", "Failed"}:
        return "This crop is closed and cannot receive new production input usage.", 400
    description = request.form.get("description", "").strip()
    input_type = request.form.get("input_type", "").strip()
    if not description or not input_type:
        return "Input type and description are required.", 400
    try:
        activity_date = _date(request.form.get("activity_date"), "Activity date", required=True)
        quantity = _non_negative(request.form.get("quantity"), "Quantity")
        manual_unit_cost = _non_negative(request.form.get("unit_cost"), "Operational unit cost estimate")
    except ValueError as exc:
        return str(exc), 400
    if quantity <= 0:
        return "Quantity must be greater than zero.", 400

    inventory_id = parse_int(request.form.get("inventory_item_id"))
    inventory = None
    unit = request.form.get("unit", "").strip() or None
    unit_cost = manual_unit_cost
    if inventory_id:
        inventory = InventoryItem.query.filter_by(id=inventory_id, cooperative_id=cooperative.id, status="Active").first()
        if not inventory:
            return "Selected inventory item is outside your Primary cooperative.", 400
        if unit and inventory.unit and unit.casefold() != inventory.unit.casefold():
            return f"Use the inventory unit '{inventory.unit}' for this item.", 400
        if float(inventory.quantity_on_hand or 0) + 1e-9 < quantity:
            return f"Insufficient stock. {inventory.name} has {float(inventory.quantity_on_hand or 0):g} {inventory.unit} available.", 400
        unit = inventory.unit or unit
        unit_cost = float(inventory.unit_cost or 0)
        inventory.quantity_on_hand = float(inventory.quantity_on_hand or 0) - quantity
        db.session.add(InventoryTransaction(
            cooperative_id=cooperative.id,
            inventory_item_id=inventory.id,
            transaction_type="OUT",
            quantity=quantity,
            transaction_date=activity_date,
            reference=f"PRODUCTION-{crop.id}",
            notes=f"Issued to {crop.name}: {description}",
        ))

    item = ProductionInput(
        cooperative_id=cooperative.id, crop_id=crop.id,
        inventory_item_id=inventory.id if inventory else None,
        input_type=input_type[:80], description=description[:250], quantity=quantity,
        unit=unit, unit_cost=unit_cost, total_cost=quantity * unit_cost,
        activity_date=activity_date, created_by_user_id=session["user_id"],
    )
    db.session.add(item)
    db.session.flush()
    add_audit_log(
        "PRODUCTION_INPUT_ISSUED", "ProductionInput", item.id,
        f"{crop.name}: {description}; {quantity:g} {unit or 'units'}",
        cooperative_id=cooperative.id,
    )
    db.session.commit()
    flash("Production input recorded. Linked inventory stock was reduced automatically." if inventory else "Production input recorded.", "success")
    return redirect(url_for("primaryprod.dashboard"))


@bp.route("/production-control/equipment-log", methods=["POST"])
@roles_required(*PRIMARY_PRODUCTION_COORDINATOR_ROLES)
def equipment_log_add():
    access, cooperative = _primary_context()
    crop_id = parse_int(request.form.get("crop_id"))
    equipment_id = parse_int(request.form.get("equipment_id"))
    crop = _own_crop(cooperative.id, crop_id)
    equipment = Equipment.query.filter_by(id=equipment_id, cooperative_id=cooperative.id).first()
    if not crop or not equipment or not crop.farm or crop.farm.cooperative_id != cooperative.id:
        return "Crop and equipment must belong to your Primary cooperative.", 400
    if crop.status in {"Harvested", "Failed"}:
        return "This crop is closed and cannot receive new equipment usage records.", 400
    purpose = request.form.get("purpose", "").strip()
    if not purpose:
        return "Equipment purpose is required.", 400
    try:
        use_date = _date(request.form.get("use_date"), "Use date", required=True)
        hours_used = _non_negative(request.form.get("hours_used"), "Hours used")
        fuel_litres = _non_negative(request.form.get("fuel_litres"), "Fuel litres")
    except ValueError as exc:
        return str(exc), 400
    responsible_user_id = parse_int(request.form.get("responsible_user_id"))
    if responsible_user_id:
        responsible = UserAccess.query.filter_by(
            user_id=responsible_user_id, cooperative_id=cooperative.id, status="Active"
        ).first()
        if not responsible:
            return "Responsible person must belong to this Primary cooperative.", 400
    log = ProductionEquipmentLog(
        cooperative_id=cooperative.id, crop_id=crop.id, equipment_id=equipment.id,
        farm_id=crop.farm_id, purpose=purpose[:220], use_date=use_date,
        hours_used=hours_used, fuel_litres=fuel_litres,
        responsible_user_id=responsible_user_id,
        notes=request.form.get("notes", "").strip() or None,
        created_by_user_id=session["user_id"],
    )
    db.session.add(log)
    db.session.flush()
    add_audit_log(
        "PRODUCTION_EQUIPMENT_LOGGED", "ProductionEquipmentLog", log.id,
        f"{equipment.name}: {hours_used:g}h, {fuel_litres:g}L; {purpose}", cooperative_id=cooperative.id,
    )
    db.session.commit()
    flash("Equipment usage recorded as an operational record. Financial fuel cost remains in Finance.", "success")
    return redirect(url_for("primaryprod.dashboard"))


def register_primary_production(app):
    if "primaryprod" not in app.blueprints:
        app.register_blueprint(bp)
