"""Secondary cooperative bulk purchasing and collective-sales ledger."""
from datetime import datetime
import importlib
import sys

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy import func

_core = sys.modules.get("__main__")
if _core is None or not hasattr(_core, "db"):
    _core = importlib.import_module("app")
for _name in (
    "db", "UserAccess", "Cooperative", "SECONDARY_EXECUTIVE_ROLES",
    "current_access", "current_cooperative", "roles_required", "parse_int",
    "parse_float", "parse_date", "add_audit_log", "utc_now",
):
    globals()[_name] = getattr(_core, _name)

from phase7 import _upsert_notification

bp = Blueprint("bulktrade", __name__)

SECONDARY_FINANCE_RECORD = {"Secondary Treasurer"}
SECONDARY_APPROVAL = {"Secondary Chairperson"}
SECONDARY_GOVERNANCE = {
    "Secondary Chairperson", "Secondary Vice Chairperson",
    "Secondary Secretary", "Secondary Vice Secretary", "Secondary Treasurer",
}
PRIMARY_NOTICE_ROLES = {
    "Primary Chairperson", "Primary Vice Chairperson", "Primary Treasurer",
}


class BulkPurchase(db.Model):
    __tablename__ = "bulk_purchase"
    id = db.Column(db.Integer, primary_key=True)
    secondary_cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False, index=True)
    title = db.Column(db.String(180), nullable=False)
    product = db.Column(db.String(120), nullable=False)
    supplier_name = db.Column(db.String(180), nullable=False)
    quantity = db.Column(db.Float, nullable=False, default=0)
    unit = db.Column(db.String(40), nullable=False)
    estimated_cost = db.Column(db.Float, nullable=False, default=0)
    actual_cost = db.Column(db.Float, nullable=False, default=0)
    order_date = db.Column(db.Date, nullable=True)
    expected_delivery_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(40), nullable=False, default="Pending Approval", index=True)
    notes = db.Column(db.Text)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    approved_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    approved_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)

    secondary_cooperative = db.relationship("Cooperative", foreign_keys=[secondary_cooperative_id])
    created_by = db.relationship("User", foreign_keys=[created_by_user_id])
    approved_by = db.relationship("User", foreign_keys=[approved_by_user_id])

    @property
    def allocated_quantity(self):
        return sum(float(x.allocated_quantity or 0) for x in self.allocations)

    @property
    def received_quantity(self):
        return sum(float(x.received_quantity or 0) for x in self.allocations)


class BulkPurchaseAllocation(db.Model):
    __tablename__ = "bulk_purchase_allocation"
    __table_args__ = (db.UniqueConstraint("purchase_id", "primary_cooperative_id", name="uq_bulk_purchase_primary"),)
    id = db.Column(db.Integer, primary_key=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey("bulk_purchase.id", ondelete="CASCADE"), nullable=False, index=True)
    secondary_cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False, index=True)
    primary_cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False, index=True)
    requested_quantity = db.Column(db.Float, nullable=False, default=0)
    allocated_quantity = db.Column(db.Float, nullable=False, default=0)
    received_quantity = db.Column(db.Float, nullable=False, default=0)
    amount_due = db.Column(db.Float, nullable=False, default=0)
    status = db.Column(db.String(40), nullable=False, default="Planned", index=True)
    notes = db.Column(db.Text)
    updated_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    updated_at = db.Column(db.DateTime, nullable=False, default=utc_now, onupdate=utc_now)

    purchase = db.relationship("BulkPurchase", backref=db.backref("allocations", cascade="all, delete-orphan"))
    primary_cooperative = db.relationship("Cooperative", foreign_keys=[primary_cooperative_id])
    secondary_cooperative = db.relationship("Cooperative", foreign_keys=[secondary_cooperative_id])
    updated_by = db.relationship("User", foreign_keys=[updated_by_user_id])


class BulkSale(db.Model):
    __tablename__ = "bulk_sale"
    id = db.Column(db.Integer, primary_key=True)
    secondary_cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False, index=True)
    title = db.Column(db.String(180), nullable=False)
    buyer_name = db.Column(db.String(180), nullable=False)
    product = db.Column(db.String(120), nullable=False)
    target_quantity = db.Column(db.Float, nullable=False, default=0)
    unit = db.Column(db.String(40), nullable=False)
    contract_value = db.Column(db.Float, nullable=False, default=0)
    delivery_date = db.Column(db.Date)
    status = db.Column(db.String(40), nullable=False, default="Pending Approval", index=True)
    notes = db.Column(db.Text)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    approved_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    approved_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)

    secondary_cooperative = db.relationship("Cooperative", foreign_keys=[secondary_cooperative_id])
    created_by = db.relationship("User", foreign_keys=[created_by_user_id])
    approved_by = db.relationship("User", foreign_keys=[approved_by_user_id])

    @property
    def accepted_quantity(self):
        return sum(float(x.accepted_quantity or 0) for x in self.commitments)

    @property
    def confirmed_receipts(self):
        return sum(float(x.amount or 0) for x in self.receipts if x.status == "Confirmed")


class BulkSaleCommitment(db.Model):
    __tablename__ = "bulk_sale_commitment"
    __table_args__ = (db.UniqueConstraint("sale_id", "primary_cooperative_id", name="uq_bulk_sale_primary"),)
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey("bulk_sale.id", ondelete="CASCADE"), nullable=False, index=True)
    secondary_cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False, index=True)
    primary_cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False, index=True)
    committed_quantity = db.Column(db.Float, nullable=False, default=0)
    accepted_quantity = db.Column(db.Float, nullable=False, default=0)
    quality_grade = db.Column(db.String(80))
    status = db.Column(db.String(40), nullable=False, default="Committed", index=True)
    notes = db.Column(db.Text)
    updated_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    updated_at = db.Column(db.DateTime, nullable=False, default=utc_now, onupdate=utc_now)

    sale = db.relationship("BulkSale", backref=db.backref("commitments", cascade="all, delete-orphan"))
    primary_cooperative = db.relationship("Cooperative", foreign_keys=[primary_cooperative_id])
    secondary_cooperative = db.relationship("Cooperative", foreign_keys=[secondary_cooperative_id])


class BulkSaleReceipt(db.Model):
    __tablename__ = "bulk_sale_receipt"
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey("bulk_sale.id", ondelete="CASCADE"), nullable=False, index=True)
    secondary_cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False, index=True)
    amount = db.Column(db.Float, nullable=False)
    payment_date = db.Column(db.Date, nullable=False)
    method = db.Column(db.String(60))
    reference = db.Column(db.String(120))
    status = db.Column(db.String(40), nullable=False, default="Pending Confirmation", index=True)
    recorded_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    decided_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    decided_at = db.Column(db.DateTime)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)

    sale = db.relationship("BulkSale", backref=db.backref("receipts", cascade="all, delete-orphan"))
    recorded_by = db.relationship("User", foreign_keys=[recorded_by_user_id])
    decided_by = db.relationship("User", foreign_keys=[decided_by_user_id])


class BulkSaleDistribution(db.Model):
    __tablename__ = "bulk_sale_distribution"
    __table_args__ = (db.UniqueConstraint("sale_id", "primary_cooperative_id", name="uq_bulk_distribution_primary"),)
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey("bulk_sale.id", ondelete="CASCADE"), nullable=False, index=True)
    secondary_cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False, index=True)
    primary_cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False, index=True)
    gross_share = db.Column(db.Float, nullable=False, default=0)
    deductions = db.Column(db.Float, nullable=False, default=0)
    net_amount = db.Column(db.Float, nullable=False, default=0)
    status = db.Column(db.String(40), nullable=False, default="Pending Approval", index=True)
    notes = db.Column(db.Text)
    prepared_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    approved_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    approved_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)

    sale = db.relationship("BulkSale", backref=db.backref("distributions", cascade="all, delete-orphan"))
    primary_cooperative = db.relationship("Cooperative", foreign_keys=[primary_cooperative_id])


def _secondary_context():
    access, coop = current_access(), current_cooperative()
    if not access or access.role not in SECONDARY_EXECUTIVE_ROLES or not coop or coop.cooperative_type != "Secondary":
        abort(403)
    return access, coop


def _child_primary(secondary_id, primary_id):
    return Cooperative.query.filter_by(id=primary_id, parent_id=secondary_id, cooperative_type="Primary", status="Active").first()


def _amount(raw, label):
    value = parse_float(raw)
    if value is None or value < 0:
        raise ValueError(f"{label} must be zero or greater.")
    return float(value)


def _date(raw, label, required=False):
    try:
        value = parse_date(raw)
    except ValueError as exc:
        raise ValueError(f"Enter a valid {label.lower()}.") from exc
    if required and not value:
        raise ValueError(f"{label} is required.")
    return value


def _notify_cooperative(cooperative_id, roles, title, message, source_type, source_id, link=None, severity="Info"):
    recipients = UserAccess.query.filter(
        UserAccess.cooperative_id == cooperative_id,
        UserAccess.status == "Active",
        UserAccess.role.in_(tuple(roles)),
    ).all()
    for recipient in recipients:
        _upsert_notification(recipient.user_id, cooperative_id, "Bulk Trade", title, message, severity, link,
                             source_type=source_type, source_id=source_id)


@bp.route("/joint-operations/bulk-trade")
@roles_required(*SECONDARY_EXECUTIVE_ROLES)
def dashboard():
    access, coop = _secondary_context()
    primaries = Cooperative.query.filter_by(parent_id=coop.id, cooperative_type="Primary", status="Active").order_by(Cooperative.name).all()
    purchases = BulkPurchase.query.filter_by(secondary_cooperative_id=coop.id).order_by(BulkPurchase.created_at.desc()).all()
    sales = BulkSale.query.filter_by(secondary_cooperative_id=coop.id).order_by(BulkSale.created_at.desc()).all()
    return render_template("bulk_trade/dashboard.html", primaries=primaries, purchases=purchases, sales=sales,
                           can_record=access.role in SECONDARY_FINANCE_RECORD,
                           can_approve=access.role in SECONDARY_APPROVAL,
                           can_govern=access.role in SECONDARY_GOVERNANCE)


@bp.route("/joint-operations/bulk-purchases", methods=["POST"])
@roles_required(*SECONDARY_FINANCE_RECORD)
def purchase_create():
    access, coop = _secondary_context()
    try:
        quantity = _amount(request.form.get("quantity"), "Quantity")
        cost = _amount(request.form.get("estimated_cost"), "Estimated cost")
        delivery = _date(request.form.get("expected_delivery_date"), "Expected delivery date")
    except ValueError as exc:
        return str(exc), 400
    title, product, supplier, unit = (request.form.get(x, "").strip() for x in ("title", "product", "supplier_name", "unit"))
    if not all((title, product, supplier, unit)) or quantity <= 0:
        return "Title, product, supplier, unit and a positive quantity are required.", 400
    item = BulkPurchase(secondary_cooperative_id=coop.id, title=title[:180], product=product[:120],
                        supplier_name=supplier[:180], quantity=quantity, unit=unit[:40], estimated_cost=cost,
                        expected_delivery_date=delivery, status="Pending Approval",
                        notes=request.form.get("notes", "").strip() or None, created_by_user_id=session["user_id"])
    db.session.add(item); db.session.flush()
    _notify_cooperative(coop.id, SECONDARY_APPROVAL, "Bulk purchase awaiting approval",
                        f"{item.title}: {quantity:g} {item.unit} from {item.supplier_name}, estimated R{cost:.2f}.",
                        "BulkPurchaseApproval", item.id, url_for("bulktrade.dashboard"), "Warning")
    add_audit_log("BULK_PURCHASE_SUBMITTED", "BulkPurchase", item.id, item.title, cooperative_id=coop.id)
    db.session.commit()
    flash("Bulk purchase submitted for Secondary Chairperson approval.", "success")
    return redirect(url_for("bulktrade.dashboard"))


@bp.route("/joint-operations/bulk-purchases/<int:item_id>/decision", methods=["POST"])
@roles_required(*SECONDARY_APPROVAL)
def purchase_decision(item_id):
    access, coop = _secondary_context()
    item = BulkPurchase.query.filter_by(id=item_id, secondary_cooperative_id=coop.id).first_or_404()
    if item.status != "Pending Approval":
        return "Only pending purchases can be decided.", 400
    decision = request.form.get("decision", "").lower()
    if decision not in {"approve", "reject"}:
        return "Choose approve or reject.", 400
    item.status = "Approved" if decision == "approve" else "Rejected"
    item.approved_by_user_id = session["user_id"]; item.approved_at = utc_now()
    _notify_cooperative(coop.id, SECONDARY_FINANCE_RECORD, f"Bulk purchase {item.status.lower()}",
                        f"{item.title} was {item.status.lower()} by the Secondary Chairperson.",
                        "BulkPurchaseDecision", item.id, url_for("bulktrade.dashboard"),
                        "Info" if decision == "approve" else "Warning")
    add_audit_log("BULK_PURCHASE_APPROVED" if decision == "approve" else "BULK_PURCHASE_REJECTED",
                  "BulkPurchase", item.id, item.title, cooperative_id=coop.id)
    db.session.commit()
    return redirect(url_for("bulktrade.dashboard"))


@bp.route("/joint-operations/bulk-purchases/<int:item_id>/allocations", methods=["POST"])
@roles_required(*SECONDARY_FINANCE_RECORD)
def purchase_allocation(item_id):
    access, coop = _secondary_context()
    item = BulkPurchase.query.filter_by(id=item_id, secondary_cooperative_id=coop.id).first_or_404()
    if item.status not in {"Approved", "Ordered", "Partially Delivered", "Delivered"}:
        return "The purchase must be approved before allocation.", 400
    primary = _child_primary(coop.id, parse_int(request.form.get("primary_cooperative_id")))
    if not primary:
        return "Choose a Primary cooperative in this Secondary cooperative.", 400
    try:
        requested = _amount(request.form.get("requested_quantity"), "Requested quantity")
        allocated = _amount(request.form.get("allocated_quantity"), "Allocated quantity")
        received = _amount(request.form.get("received_quantity"), "Received quantity")
        due = _amount(request.form.get("amount_due"), "Amount due")
    except ValueError as exc:
        return str(exc), 400
    existing = BulkPurchaseAllocation.query.filter_by(purchase_id=item.id, primary_cooperative_id=primary.id).first()
    other_allocated = item.allocated_quantity - (float(existing.allocated_quantity or 0) if existing else 0)
    if other_allocated + allocated > float(item.quantity or 0) + 1e-9:
        return "Primary allocations cannot exceed the bulk quantity purchased.", 400
    if received > allocated + 1e-9:
        return "Received quantity cannot exceed this Primary allocation.", 400
    row = existing or BulkPurchaseAllocation(purchase_id=item.id, secondary_cooperative_id=coop.id,
                                             primary_cooperative_id=primary.id, updated_by_user_id=session["user_id"])
    if not existing: db.session.add(row)
    row.requested_quantity=requested; row.allocated_quantity=allocated; row.received_quantity=received
    row.amount_due=due; row.status="Received" if allocated > 0 and received >= allocated else ("Partially Received" if received > 0 else "Allocated")
    row.notes=request.form.get("notes", "").strip() or None; row.updated_by_user_id=session["user_id"]; row.updated_at=utc_now()
    db.session.flush()
    _notify_cooperative(primary.id, PRIMARY_NOTICE_ROLES, "Bulk purchase allocation updated",
                        f"{primary.name}: {allocated:g} {item.unit} allocated; {received:g} received; R{due:.2f} due.",
                        "BulkPurchaseAllocation", row.id, severity="Info")
    add_audit_log("BULK_PURCHASE_ALLOCATION_UPDATED", "BulkPurchaseAllocation", row.id,
                  f"{primary.name}: {allocated:g} {item.unit}", cooperative_id=coop.id)
    db.session.commit()
    flash(f"{primary.name} purchase allocation saved.", "success")
    return redirect(url_for("bulktrade.dashboard"))


@bp.route("/joint-operations/bulk-sales", methods=["POST"])
@roles_required(*SECONDARY_GOVERNANCE)
def sale_create():
    access, coop = _secondary_context()
    try:
        quantity=_amount(request.form.get("target_quantity"), "Target quantity")
        value=_amount(request.form.get("contract_value"), "Contract value")
        delivery=_date(request.form.get("delivery_date"), "Delivery date")
    except ValueError as exc:
        return str(exc), 400
    title,buyer,product,unit=(request.form.get(x,"").strip() for x in ("title","buyer_name","product","unit"))
    if not all((title,buyer,product,unit)) or quantity <= 0:
        return "Title, buyer, product, unit and a positive target quantity are required.", 400
    item=BulkSale(secondary_cooperative_id=coop.id,title=title[:180],buyer_name=buyer[:180],product=product[:120],
                  target_quantity=quantity,unit=unit[:40],contract_value=value,delivery_date=delivery,
                  status="Pending Approval",notes=request.form.get("notes","").strip() or None,
                  created_by_user_id=session["user_id"])
    db.session.add(item); db.session.flush()
    _notify_cooperative(coop.id, SECONDARY_APPROVAL, "Collective sale awaiting approval",
                        f"{item.title}: {quantity:g} {unit} of {product} for {buyer}.",
                        "BulkSaleApproval", item.id, url_for("bulktrade.dashboard"), "Warning")
    add_audit_log("BULK_SALE_SUBMITTED","BulkSale",item.id,item.title,cooperative_id=coop.id)
    db.session.commit(); flash("Collective sale submitted for approval.","success")
    return redirect(url_for("bulktrade.dashboard"))


@bp.route("/joint-operations/bulk-sales/<int:item_id>/decision", methods=["POST"])
@roles_required(*SECONDARY_APPROVAL)
def sale_decision(item_id):
    access,coop=_secondary_context()
    item=BulkSale.query.filter_by(id=item_id,secondary_cooperative_id=coop.id).first_or_404()
    if item.status!="Pending Approval": return "Only pending sales can be decided.",400
    decision=request.form.get("decision","").lower()
    if decision not in {"approve","reject"}: return "Choose approve or reject.",400
    item.status="Approved" if decision=="approve" else "Rejected"; item.approved_by_user_id=session["user_id"]; item.approved_at=utc_now()
    _notify_cooperative(coop.id, SECONDARY_GOVERNANCE-{ "Secondary Chairperson" }, f"Collective sale {item.status.lower()}",
                        f"{item.title} was {item.status.lower()} by the Secondary Chairperson.",
                        "BulkSaleDecision",item.id,url_for("bulktrade.dashboard"),"Info" if decision=="approve" else "Warning")
    add_audit_log("BULK_SALE_APPROVED" if decision=="approve" else "BULK_SALE_REJECTED","BulkSale",item.id,item.title,cooperative_id=coop.id)
    db.session.commit(); return redirect(url_for("bulktrade.dashboard"))


@bp.route("/joint-operations/bulk-sales/<int:item_id>/commitments", methods=["POST"])
@roles_required(*SECONDARY_GOVERNANCE)
def sale_commitment(item_id):
    access,coop=_secondary_context()
    item=BulkSale.query.filter_by(id=item_id,secondary_cooperative_id=coop.id).first_or_404()
    if item.status not in {"Approved","Delivering"}: return "The collective sale must be approved first.",400
    primary=_child_primary(coop.id,parse_int(request.form.get("primary_cooperative_id")))
    if not primary: return "Choose a valid Primary cooperative.",400
    try:
        committed=_amount(request.form.get("committed_quantity"),"Committed quantity")
        accepted=_amount(request.form.get("accepted_quantity"),"Accepted quantity")
    except ValueError as exc: return str(exc),400
    if accepted>committed+1e-9: return "Accepted quantity cannot exceed committed quantity.",400
    row=BulkSaleCommitment.query.filter_by(sale_id=item.id,primary_cooperative_id=primary.id).first()
    other=sum(float(x.accepted_quantity or 0) for x in item.commitments if not row or x.id!=row.id)
    if other+accepted>float(item.target_quantity or 0)+1e-9: return "Accepted quantities cannot exceed the buyer contract target.",400
    if not row:
        row=BulkSaleCommitment(sale_id=item.id,secondary_cooperative_id=coop.id,primary_cooperative_id=primary.id,updated_by_user_id=session["user_id"])
        db.session.add(row)
    row.committed_quantity=committed; row.accepted_quantity=accepted
    row.quality_grade=request.form.get("quality_grade","").strip()[:80] or None
    row.status="Accepted" if accepted>0 else "Committed"; row.notes=request.form.get("notes","").strip() or None
    row.updated_by_user_id=session["user_id"]; row.updated_at=utc_now(); db.session.flush()
    _notify_cooperative(primary.id,PRIMARY_NOTICE_ROLES,"Collective sale commitment updated",
                        f"{primary.name}: {committed:g} {item.unit} committed and {accepted:g} accepted for {item.buyer_name}.",
                        "BulkSaleCommitment",row.id,severity="Info")
    add_audit_log("BULK_SALE_COMMITMENT_UPDATED","BulkSaleCommitment",row.id,
                  f"{primary.name}: {accepted:g} {item.unit} accepted",cooperative_id=coop.id)
    db.session.commit(); return redirect(url_for("bulktrade.dashboard"))


@bp.route("/joint-operations/bulk-sales/<int:item_id>/receipts", methods=["POST"])
@roles_required(*SECONDARY_FINANCE_RECORD)
def sale_receipt(item_id):
    access,coop=_secondary_context()
    item=BulkSale.query.filter_by(id=item_id,secondary_cooperative_id=coop.id).first_or_404()
    if item.status not in {"Approved","Delivering","Delivered"}: return "The sale must be approved before buyer money is recorded.",400
    try:
        amount=_amount(request.form.get("amount"),"Receipt amount")
        payment_date=_date(request.form.get("payment_date"),"Payment date",True)
    except ValueError as exc: return str(exc),400
    if amount<=0: return "Receipt amount must be greater than zero.",400
    row=BulkSaleReceipt(sale_id=item.id,secondary_cooperative_id=coop.id,amount=amount,payment_date=payment_date,
                        method=request.form.get("method","").strip()[:60] or None,
                        reference=request.form.get("reference","").strip()[:120] or None,
                        status="Pending Confirmation",recorded_by_user_id=session["user_id"],
                        notes=request.form.get("notes","").strip() or None)
    db.session.add(row); db.session.flush()
    _notify_cooperative(coop.id,SECONDARY_APPROVAL,"Buyer receipt awaiting confirmation",
                        f"R{amount:.2f} received from {item.buyer_name} for {item.title}.",
                        "BulkSaleReceiptApproval",row.id,url_for("bulktrade.dashboard"),"Warning")
    add_audit_log("BULK_SALE_RECEIPT_RECORDED","BulkSaleReceipt",row.id,f"R{amount:.2f}",cooperative_id=coop.id)
    db.session.commit(); return redirect(url_for("bulktrade.dashboard"))


@bp.route("/joint-operations/bulk-sale-receipts/<int:receipt_id>/decision", methods=["POST"])
@roles_required(*SECONDARY_APPROVAL)
def receipt_decision(receipt_id):
    access,coop=_secondary_context()
    row=BulkSaleReceipt.query.filter_by(id=receipt_id,secondary_cooperative_id=coop.id).first_or_404()
    if row.status!="Pending Confirmation": return "Only pending receipts can be decided.",400
    decision=request.form.get("decision","").lower()
    if decision not in {"approve","reject"}: return "Choose approve or reject.",400
    row.status="Confirmed" if decision=="approve" else "Rejected"; row.decided_by_user_id=session["user_id"]; row.decided_at=utc_now()
    _notify_cooperative(coop.id,SECONDARY_FINANCE_RECORD,f"Buyer receipt {row.status.lower()}",
                        f"R{row.amount:.2f} for {row.sale.title} was {row.status.lower()}.",
                        "BulkSaleReceiptDecision",row.id,url_for("bulktrade.dashboard"),"Info" if decision=="approve" else "Warning")
    add_audit_log("BULK_SALE_RECEIPT_CONFIRMED" if decision=="approve" else "BULK_SALE_RECEIPT_REJECTED",
                  "BulkSaleReceipt",row.id,f"R{row.amount:.2f}",cooperative_id=coop.id)
    db.session.commit(); return redirect(url_for("bulktrade.dashboard"))


@bp.route("/joint-operations/bulk-sales/<int:item_id>/distributions", methods=["POST"])
@roles_required(*SECONDARY_FINANCE_RECORD)
def prepare_distributions(item_id):
    access,coop=_secondary_context()
    item=BulkSale.query.filter_by(id=item_id,secondary_cooperative_id=coop.id).first_or_404()
    total_quantity=item.accepted_quantity; total_receipts=item.confirmed_receipts
    try: total_deductions=_amount(request.form.get("total_deductions"),"Total deductions")
    except ValueError as exc: return str(exc),400
    if total_quantity<=0 or total_receipts<=0: return "Accepted produce and a confirmed buyer receipt are required first.",400
    if total_deductions>total_receipts+1e-9: return "Deductions cannot exceed confirmed buyer receipts.",400
    distributable=total_receipts-total_deductions
    for commitment in item.commitments:
        if commitment.accepted_quantity<=0: continue
        ratio=float(commitment.accepted_quantity)/total_quantity
        row=BulkSaleDistribution.query.filter_by(sale_id=item.id,primary_cooperative_id=commitment.primary_cooperative_id).first()
        if not row:
            row=BulkSaleDistribution(sale_id=item.id,secondary_cooperative_id=coop.id,
                                     primary_cooperative_id=commitment.primary_cooperative_id,
                                     prepared_by_user_id=session["user_id"])
            db.session.add(row)
        row.gross_share=round(total_receipts*ratio,2); row.deductions=round(total_deductions*ratio,2)
        row.net_amount=round(distributable*ratio,2); row.status="Pending Approval"
        row.notes=request.form.get("notes","").strip() or None
    db.session.flush()
    _notify_cooperative(coop.id,SECONDARY_APPROVAL,"Sale distributions awaiting approval",
                        f"{item.title}: R{distributable:.2f} net proceeds allocated by accepted quantity.",
                        "BulkSaleDistributionApproval",item.id,url_for("bulktrade.dashboard"),"Warning")
    add_audit_log("BULK_SALE_DISTRIBUTIONS_PREPARED","BulkSale",item.id,f"Net R{distributable:.2f}",cooperative_id=coop.id)
    db.session.commit(); flash("Proceeds allocated proportionally and sent for approval.","success")
    return redirect(url_for("bulktrade.dashboard"))


@bp.route("/joint-operations/bulk-distributions/<int:distribution_id>/decision", methods=["POST"])
@roles_required(*SECONDARY_APPROVAL)
def distribution_decision(distribution_id):
    access,coop=_secondary_context()
    row=BulkSaleDistribution.query.filter_by(id=distribution_id,secondary_cooperative_id=coop.id).first_or_404()
    if row.status!="Pending Approval": return "Only pending distributions can be decided.",400
    decision=request.form.get("decision","").lower()
    if decision not in {"approve","reject"}: return "Choose approve or reject.",400
    row.status="Approved" if decision=="approve" else "Rejected"; row.approved_by_user_id=session["user_id"]; row.approved_at=utc_now()
    _notify_cooperative(row.primary_cooperative_id,PRIMARY_NOTICE_ROLES,f"Collective sale distribution {row.status.lower()}",
                        f"{row.sale.title}: R{row.net_amount:.2f} net proceeds for {row.primary_cooperative.name}.",
                        "BulkSaleDistribution",row.id,severity="Info" if decision=="approve" else "Warning")
    add_audit_log("BULK_SALE_DISTRIBUTION_APPROVED" if decision=="approve" else "BULK_SALE_DISTRIBUTION_REJECTED",
                  "BulkSaleDistribution",row.id,f"R{row.net_amount:.2f}",cooperative_id=coop.id)
    db.session.commit(); return redirect(url_for("bulktrade.dashboard"))


def register_bulk_trade(app):
    if "bulktrade" not in app.blueprints:
        app.register_blueprint(bp)
