"""Cooperative cash and bank account ledger."""
import importlib
import json
import sys

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy import func, or_

_core = sys.modules.get("__main__")
if _core is None or not hasattr(_core, "db"):
    _core = importlib.import_module("app")
for _name in (
    "db", "UserAccess", "FINANCE_VIEW_ROLES", "FINANCE_RECORD_ROLES", "FINANCE_APPROVAL_ROLES",
    "current_access", "current_cooperative", "roles_required", "parse_int", "parse_float", "parse_date",
    "add_audit_log", "utc_now",
):
    globals()[_name] = getattr(_core, _name)
from phase7 import _upsert_notification, _save_document, DOCUMENT_UPLOAD_DIR, CooperativeDocument

bp = Blueprint("ledger", __name__)
ACCOUNT_TYPES = ("Bank Account", "Cash Box", "Mobile Money", "Savings", "Other")
TRANSACTION_TYPES = ("Opening Balance", "Income", "Expense", "Transfer")
REVERSAL_TYPE = "Reversal"
PAYMENT_METHODS = ("Cash", "EFT / Bank Transfer", "Card", "Mobile Money", "Cheque", "Other")
INCOME_CATEGORIES = ("Product Sale", "Bulk Sale", "Membership Fee", "Primary Contribution", "Grant", "Loan", "Other Income")
EXPENSE_CATEGORIES = ("Farm Inputs", "Transport", "Packaging", "Equipment", "Wages", "Bank Charges", "Loan Repayment", "Refund", "Other Expense")
SYSTEM_CATEGORIES = ("Opening Balance", "Transfer")
ALL_CATEGORIES = INCOME_CATEGORIES + EXPENSE_CATEGORIES + SYSTEM_CATEGORIES
CATEGORY_GROUPS = {
    "Sales Income": ("Product Sale", "Bulk Sale"),
    "Member Contributions": ("Membership Fee", "Primary Contribution"),
    "Grants/Funding": ("Grant", "Loan"),
    "Other Income": ("Other Income",),
    "Farm Inputs": ("Farm Inputs",),
    "Machinery": ("Equipment",),
    "Labour": ("Wages",),
    "Transport": ("Transport",),
    "Debt Repayment": ("Loan Repayment",),
    "Other Expenses": ("Packaging", "Bank Charges", "Refund", "Other Expense"),
}
SOURCE_MODELS = {"Sale": "Sale", "Payment": "Payment", "Expense": "Expense", "Contribution": "Contribution"}


STRUCTURAL_EVIDENCE_CATEGORIES = {"Loan", "Grant", "Bulk Sale"}
EVIDENCE_FILE_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "webp"}


def _evidence_policy(transaction_type, category, amount):
    amount = float(amount or 0)
    if category in STRUCTURAL_EVIDENCE_CATEGORIES:
        return {
            "tier": "Structural",
            "required_files": 1,
            "bypass_allowed": False,
            "budget_justification_required": False,
        }
    if amount < 500:
        return {
            "tier": "Low",
            "required_files": 0,
            "bypass_allowed": False,
            "budget_justification_required": False,
        }
    if amount < 10000:
        return {
            "tier": "Medium",
            "required_files": 1,
            "bypass_allowed": True,
            "budget_justification_required": False,
        }
    return {
        "tier": "High",
        "required_files": 2,
        "bypass_allowed": True,
        "budget_justification_required": True,
    }


def _transaction_evidence_files():
    return [
        item for item in (
            request.files.get("evidence_file_1"),
            request.files.get("evidence_file_2"),
        )
        if item and item.filename
    ]


def _validate_evidence_file_names(files):
    for file_storage in files:
        filename = (file_storage.filename or "").strip()
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in EVIDENCE_FILE_EXTENSIONS:
            return "Evidence Wall accepts PDF or image files only.", 400
    return None


def _attach_transaction_evidence(row, files):
    saved_paths = []
    docs = []
    try:
        for index, file_storage in enumerate(files, start=1):
            original, stored, digest = _save_document(file_storage)
            saved_paths.append(DOCUMENT_UPLOAD_DIR / stored)
            doc = CooperativeDocument(
                cooperative_id=row.cooperative_id,
                document_type="Financial Document",
                title=f"Transaction {row.id} evidence {index}",
                entity_type="LedgerTransaction",
                entity_id=row.id,
                original_name=original,
                stored_name=stored,
                file_sha256=digest,
                uploaded_by_user_id=session["user_id"],
                notes=f"Evidence Wall upload for {row.evidence_tier or 'transaction'} tier.",
            )
            db.session.add(doc)
            db.session.flush()
            add_audit_log(
                "DOCUMENT_UPLOADED",
                "CooperativeDocument",
                doc.id,
                f"{doc.document_type}: {doc.title} sha256={digest}",
                cooperative_id=row.cooperative_id,
            )
            docs.append(doc)
    except Exception:
        for path in saved_paths:
            path.unlink(missing_ok=True)
        raise
    return docs



class FinanceAccount(db.Model):
    __tablename__ = "finance_account"
    __table_args__ = (db.UniqueConstraint("cooperative_id", "name", name="uq_finance_account_name"),)

    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    account_type = db.Column(db.String(40), nullable=False)
    institution = db.Column(db.String(120))
    account_last4 = db.Column(db.String(4))
    opening_balance = db.Column(db.Float, nullable=False, default=0)
    opening_balance_date = db.Column(db.Date, index=True)
    status = db.Column(db.String(20), nullable=False, default="Active", index=True)
    notes = db.Column(db.Text)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id])

    @property
    def confirmed_balance(self):
        total = float(self.opening_balance or 0)
        total += sum(float(x.amount or 0) for x in self.incoming_transactions if x.status == "Confirmed")
        total -= sum(float(x.amount or 0) for x in self.outgoing_transactions if x.status == "Confirmed")
        return total

    @property
    def pending_change(self):
        return (
            sum(float(x.amount or 0) for x in self.incoming_transactions if x.status == "Pending Confirmation")
            - sum(float(x.amount or 0) for x in self.outgoing_transactions if x.status == "Pending Confirmation")
        )


class LedgerTransaction(db.Model):
    __tablename__ = "ledger_transaction"
    __table_args__ = (db.UniqueConstraint("cooperative_id", "source_type", "source_id", name="uq_ledger_source"),)

    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False, index=True)
    transaction_type = db.Column(db.String(30), nullable=False, index=True)
    category = db.Column(db.String(100), nullable=False, index=True)
    amount = db.Column(db.Float, nullable=False)
    transaction_date = db.Column(db.Date, nullable=False, index=True)
    from_account_id = db.Column(db.Integer, db.ForeignKey("finance_account.id"))
    to_account_id = db.Column(db.Integer, db.ForeignKey("finance_account.id"))
    counterparty = db.Column(db.String(180))
    reference = db.Column(db.String(120))
    payment_method = db.Column(db.String(40), index=True)
    project_reference = db.Column(db.String(140), index=True)
    source_type = db.Column(db.String(60))
    source_id = db.Column(db.Integer)
    reversal_of_transaction_id = db.Column(
        db.Integer,
        db.ForeignKey("ledger_transaction.id"),
        nullable=True,
        unique=True,
        index=True,
    )
    status = db.Column(db.String(40), nullable=False, default="Pending Confirmation", index=True)
    notes = db.Column(db.Text)
    decision_note = db.Column(db.Text)
    recorded_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    decided_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    decided_at = db.Column(db.DateTime)
    evidence_tier = db.Column(db.String(24), nullable=True, index=True)
    evidence_bypass = db.Column(db.Boolean, nullable=False, default=False)
    evidence_bypass_reason = db.Column(db.Text)
    evidence_bypass_acknowledged_at = db.Column(db.DateTime)
    budget_justification = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)

    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id])
    from_account = db.relationship("FinanceAccount", foreign_keys=[from_account_id], backref=db.backref("outgoing_transactions", lazy=True))
    to_account = db.relationship("FinanceAccount", foreign_keys=[to_account_id], backref=db.backref("incoming_transactions", lazy=True))
    recorded_by = db.relationship("User", foreign_keys=[recorded_by_user_id])
    decided_by = db.relationship("User", foreign_keys=[decided_by_user_id])
    reversal_of = db.relationship(
        "LedgerTransaction",
        remote_side=[id],
        foreign_keys=[reversal_of_transaction_id],
        backref=db.backref("reversal_transaction", uselist=False),
    )


class LedgerTransactionRevision(db.Model):
    __tablename__ = "ledger_transaction_revision"
    __table_args__ = (
        db.UniqueConstraint("transaction_id", "revision_number", name="uq_ledger_transaction_revision_number"),
    )

    id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey("ledger_transaction.id"), nullable=False, index=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False, index=True)
    revision_number = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(250), nullable=False)
    snapshot_json = db.Column(db.Text, nullable=False)
    changed_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)

    transaction = db.relationship("LedgerTransaction", foreign_keys=[transaction_id])
    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id])
    changed_by = db.relationship("User", foreign_keys=[changed_by_user_id])

    @property
    def snapshot(self):
        try:
            return json.loads(self.snapshot_json or "{}")
        except (TypeError, ValueError):
            return {}


class FinanceReconciliation(db.Model):
    __tablename__ = "finance_reconciliation"
    __table_args__ = (
        db.UniqueConstraint("cooperative_id", "finance_account_id", "statement_date", name="uq_finance_reconciliation_scope"),
    )

    id = db.Column(db.Integer, primary_key=True)
    cooperative_id = db.Column(db.Integer, db.ForeignKey("cooperative.id"), nullable=False, index=True)
    finance_account_id = db.Column(db.Integer, db.ForeignKey("finance_account.id"), nullable=False, index=True)
    statement_date = db.Column(db.Date, nullable=False, index=True)
    statement_balance = db.Column(db.Float, nullable=False)
    book_balance = db.Column(db.Float, nullable=False)
    difference = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(30), nullable=False, default="Pending Review", index=True)
    notes = db.Column(db.Text)
    prepared_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    reviewed_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    reviewed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)

    cooperative = db.relationship("Cooperative", foreign_keys=[cooperative_id])
    finance_account = db.relationship("FinanceAccount", foreign_keys=[finance_account_id], backref=db.backref("reconciliations", lazy=True))
    prepared_by = db.relationship("User", foreign_keys=[prepared_by_user_id])
    reviewed_by = db.relationship("User", foreign_keys=[reviewed_by_user_id])


def _context():
    access, coop = current_access(), current_cooperative()
    if not access or access.role not in FINANCE_VIEW_ROLES or not coop:
        abort(403)
    return access, coop


def _notify(coop_id, roles, title, message, source_type, source_id, severity="Info", link=None):
    for access in UserAccess.query.filter(
        UserAccess.cooperative_id == coop_id,
        UserAccess.status == "Active",
        UserAccess.role.in_(tuple(roles)),
    ).all():
        _upsert_notification(
            access.user_id,
            coop_id,
            "Finance",
            title,
            message,
            severity,
            link or url_for("ledger.dashboard"),
            source_type=source_type,
            source_id=source_id,
        )


def _validate_source(coop_id, source_type, source_id, exclude_transaction_id=None):
    if not source_type and not source_id:
        return None
    if not source_type or not source_id:
        abort(400, "Source type and source ID must be supplied together.")
    model_name = SOURCE_MODELS.get(source_type)
    if not model_name:
        abort(400, "Choose a supported source record type.")
    model = getattr(_core, model_name, None)
    if model is None:
        abort(400, "Source model is unavailable.")
    row = model.query.filter_by(id=source_id, cooperative_id=coop_id).first()
    if row is None:
        abort(400, "Source record does not belong to this cooperative or does not exist.")
    existing = LedgerTransaction.query.filter_by(
        cooperative_id=coop_id,
        source_type=source_type,
        source_id=source_id,
    ).first()
    if existing and existing.id != exclude_transaction_id:
        abort(409, "This source record is already linked to ledger transaction #%s." % existing.id)
    return row


def _confirmed_account_balance_through(account, through_date):
    total = float(account.opening_balance or 0) if not account.opening_balance_date or account.opening_balance_date <= through_date else 0.0
    incoming = LedgerTransaction.query.filter_by(
        cooperative_id=account.cooperative_id,
        to_account_id=account.id,
        status="Confirmed",
    ).filter(LedgerTransaction.transaction_date <= through_date).all()
    outgoing = LedgerTransaction.query.filter_by(
        cooperative_id=account.cooperative_id,
        from_account_id=account.id,
        status="Confirmed",
    ).filter(LedgerTransaction.transaction_date <= through_date).all()
    total += sum(float(x.amount or 0) for x in incoming)
    total -= sum(float(x.amount or 0) for x in outgoing)
    return total


def _category_reporting_amount(row):
    """Return the category amount after accounting for confirmed reversals."""
    amount = float(row.amount or 0)
    return -amount if row.reversal_of_transaction_id else amount


def _transaction_payload_from_request(coop, exclude_transaction_id=None):
    kind = request.form.get("transaction_type", "").strip()
    if kind not in TRANSACTION_TYPES:
        return None, ("Choose a valid transaction type.", 400)

    amount = parse_float(request.form.get("amount"))
    if amount is None or amount <= 0:
        return None, ("Amount must be greater than zero.", 400)

    try:
        transaction_date = parse_date(request.form.get("transaction_date"))
    except ValueError:
        return None, ("Enter a valid transaction date.", 400)
    if not transaction_date:
        return None, ("Transaction date is required.", 400)

    from_id = parse_int(request.form.get("from_account_id"))
    to_id = parse_int(request.form.get("to_account_id"))
    account_ids = [x for x in (from_id, to_id) if x]
    owned = {
        x.id: x
        for x in FinanceAccount.query.filter(
            FinanceAccount.cooperative_id == coop.id,
            FinanceAccount.id.in_(account_ids or [-1]),
        ).all()
    }

    if kind in {"Income", "Opening Balance"}:
        from_id = None
        if not to_id or to_id not in owned:
            return None, ("Choose the account receiving the money.", 400)
    elif kind == "Expense":
        to_id = None
        if not from_id or from_id not in owned:
            return None, ("Choose the account paying the money.", 400)
    else:
        if not from_id or not to_id or from_id == to_id or from_id not in owned or to_id not in owned:
            return None, ("Choose two different accounts in this cooperative for a transfer.", 400)

    if kind == "Income":
        allowed = INCOME_CATEGORIES
        category = request.form.get("category", "").strip()
    elif kind == "Expense":
        allowed = EXPENSE_CATEGORIES
        category = request.form.get("category", "").strip()
    elif kind == "Transfer":
        allowed = ("Transfer",)
        category = "Transfer"
    else:
        allowed = ("Opening Balance",)
        category = "Opening Balance"
    if category not in allowed:
        return None, ("Choose a valid category for this transaction type.", 400)

    payment_method = request.form.get("payment_method", "").strip() or None
    if payment_method and payment_method not in PAYMENT_METHODS:
        return None, ("Choose a valid payment method.", 400)

    source_type = request.form.get("source_type", "").strip() or None
    source_id = parse_int(request.form.get("source_id"))
    _validate_source(coop.id, source_type, source_id, exclude_transaction_id=exclude_transaction_id)

    return {
        "transaction_type": kind,
        "category": category,
        "amount": float(amount),
        "transaction_date": transaction_date,
        "from_account_id": from_id,
        "to_account_id": to_id,
        "counterparty": request.form.get("counterparty", "").strip()[:180] or None,
        "reference": request.form.get("reference", "").strip()[:120] or None,
        "payment_method": payment_method,
        "project_reference": request.form.get("project_reference", "").strip()[:140] or None,
        "source_type": source_type,
        "source_id": source_id,
        "notes": request.form.get("notes", "").strip() or None,
    }, None


def _transaction_snapshot(row):
    return json.dumps({
        "transaction_type": row.transaction_type,
        "category": row.category,
        "amount": float(row.amount or 0),
        "transaction_date": row.transaction_date.isoformat() if row.transaction_date else None,
        "from_account_id": row.from_account_id,
        "from_account_name": row.from_account.name if row.from_account else None,
        "to_account_id": row.to_account_id,
        "to_account_name": row.to_account.name if row.to_account else None,
        "counterparty": row.counterparty,
        "reference": row.reference,
        "payment_method": row.payment_method,
        "project_reference": row.project_reference,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "reversal_of_transaction_id": row.reversal_of_transaction_id,
        "status": row.status,
        "notes": row.notes,
        "decision_note": row.decision_note,
        "decided_by_user_id": row.decided_by_user_id,
        "decided_by_name": row.decided_by.fullname if row.decided_by else None,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        "evidence_tier": row.evidence_tier,
        "evidence_bypass": bool(row.evidence_bypass),
        "evidence_bypass_reason": row.evidence_bypass_reason,
        "evidence_bypass_acknowledged_at": (
            row.evidence_bypass_acknowledged_at.isoformat()
            if row.evidence_bypass_acknowledged_at else None
        ),
        "budget_justification": row.budget_justification,
    }, sort_keys=True)


def _next_revision_number(transaction_id):
    current = db.session.query(func.max(LedgerTransactionRevision.revision_number)).filter(
        LedgerTransactionRevision.transaction_id == transaction_id
    ).scalar()
    return int(current or 0) + 1


def _add_revision(row, reason):
    revision = LedgerTransactionRevision(
        transaction_id=row.id,
        cooperative_id=row.cooperative_id,
        revision_number=_next_revision_number(row.id),
        reason=reason[:250],
        snapshot_json=_transaction_snapshot(row),
        changed_by_user_id=session["user_id"],
    )
    db.session.add(revision)
    return revision


@bp.route("/finance/accounts")
@roles_required(*FINANCE_VIEW_ROLES)
def dashboard():
    access, coop = _context()
    accounts = FinanceAccount.query.filter_by(cooperative_id=coop.id).order_by(FinanceAccount.name).all()
    query = LedgerTransaction.query.filter_by(cooperative_id=coop.id)

    category = request.args.get("category", "").strip()
    group = request.args.get("group", "").strip()
    status = request.args.get("status", "").strip()
    account_id = parse_int(request.args.get("account_id"))
    q = request.args.get("q", "").strip()
    payment_method = request.args.get("payment_method", "").strip()
    date_from_raw = request.args.get("date_from", "").strip()
    date_to_raw = request.args.get("date_to", "").strip()

    try:
        date_from = parse_date(date_from_raw) if date_from_raw else None
        date_to = parse_date(date_to_raw) if date_to_raw else None
    except ValueError:
        return "Enter valid ledger filter dates.", 400
    if date_from and date_to and date_from > date_to:
        return "The from date cannot be after the to date.", 400

    if group in CATEGORY_GROUPS:
        query = query.filter(LedgerTransaction.category.in_(CATEGORY_GROUPS[group]))
    elif category in ALL_CATEGORIES:
        query = query.filter(LedgerTransaction.category == category)
    if status in {"Pending Confirmation", "Confirmed", "Rejected"}:
        query = query.filter(LedgerTransaction.status == status)
    if account_id and any(a.id == account_id for a in accounts):
        query = query.filter((LedgerTransaction.from_account_id == account_id) | (LedgerTransaction.to_account_id == account_id))
    if payment_method in PAYMENT_METHODS:
        query = query.filter(LedgerTransaction.payment_method == payment_method)
    if date_from:
        query = query.filter(LedgerTransaction.transaction_date >= date_from)
    if date_to:
        query = query.filter(LedgerTransaction.transaction_date <= date_to)
    if q:
        pattern = f"%{q}%"
        query = query.filter(or_(
            LedgerTransaction.counterparty.ilike(pattern),
            LedgerTransaction.reference.ilike(pattern),
            LedgerTransaction.project_reference.ilike(pattern),
            LedgerTransaction.notes.ilike(pattern),
            LedgerTransaction.category.ilike(pattern),
        ))

    transactions = query.order_by(LedgerTransaction.transaction_date.desc(), LedgerTransaction.created_at.desc()).limit(250).all()
    group_totals = {}
    for label, categories in CATEGORY_GROUPS.items():
        rows = LedgerTransaction.query.filter(
            LedgerTransaction.cooperative_id == coop.id,
            LedgerTransaction.status == "Confirmed",
            LedgerTransaction.category.in_(categories),
        ).all()
        group_totals[label] = sum(_category_reporting_amount(r) for r in rows)

    return render_template(
        "finance_accounts/dashboard.html",
        accounts=accounts,
        transactions=transactions,
        confirmed_total=sum(a.confirmed_balance for a in accounts),
        pending_total=sum(a.pending_change for a in accounts),
        account_types=ACCOUNT_TYPES,
        payment_methods=PAYMENT_METHODS,
        income_categories=INCOME_CATEGORIES,
        expense_categories=EXPENSE_CATEGORIES,
        all_categories=ALL_CATEGORIES,
        category_groups=CATEGORY_GROUPS,
        group_totals=group_totals,
        selected_group=group,
        selected_category=category,
        selected_status=status,
        selected_account_id=account_id,
        selected_payment_method=payment_method,
        selected_q=q,
        selected_date_from=date_from_raw,
        selected_date_to=date_to_raw,
        can_record=access.role in FINANCE_RECORD_ROLES,
        can_approve=access.role in FINANCE_APPROVAL_ROLES,
    )


@bp.route("/finance/transactions/<int:item_id>")
@roles_required(*FINANCE_VIEW_ROLES)
def transaction_detail(item_id):
    access, coop = _context()
    row = LedgerTransaction.query.filter_by(id=item_id, cooperative_id=coop.id).first_or_404()
    documents = CooperativeDocument.query.filter_by(
        cooperative_id=coop.id,
        entity_type="LedgerTransaction",
        entity_id=row.id,
    ).order_by(CooperativeDocument.created_at.desc()).all()
    revisions = LedgerTransactionRevision.query.filter_by(
        cooperative_id=coop.id,
        transaction_id=row.id,
    ).order_by(LedgerTransactionRevision.revision_number.desc()).all()
    accounts = FinanceAccount.query.filter_by(cooperative_id=coop.id).order_by(FinanceAccount.name).all()
    return render_template(
        "finance_accounts/transaction_detail.html",
        transaction=row,
        documents=documents,
        revisions=revisions,
        accounts=accounts,
        payment_methods=PAYMENT_METHODS,
        income_categories=INCOME_CATEGORIES,
        expense_categories=EXPENSE_CATEGORIES,
        source_types=tuple(SOURCE_MODELS.keys()),
        can_record=access.role in FINANCE_RECORD_ROLES,
        can_approve=access.role in FINANCE_APPROVAL_ROLES,
    )


@bp.route("/finance/reconciliations")
@roles_required(*FINANCE_VIEW_ROLES)
def reconciliation_list():
    access, coop = _context()
    accounts = FinanceAccount.query.filter_by(cooperative_id=coop.id).order_by(FinanceAccount.name).all()
    account_id = parse_int(request.args.get("account_id"))
    query = FinanceReconciliation.query.filter_by(cooperative_id=coop.id)
    if account_id and any(a.id == account_id for a in accounts):
        query = query.filter(FinanceReconciliation.finance_account_id == account_id)
    rows = query.order_by(FinanceReconciliation.statement_date.desc(), FinanceReconciliation.created_at.desc()).limit(100).all()
    return render_template(
        "finance_accounts/reconciliations.html",
        accounts=accounts,
        reconciliations=rows,
        selected_account_id=account_id,
        can_record=access.role in FINANCE_RECORD_ROLES,
        can_approve=access.role in FINANCE_APPROVAL_ROLES,
    )


@bp.route("/finance/reconciliations/<int:item_id>")
@roles_required(*FINANCE_VIEW_ROLES)
def reconciliation_detail(item_id):
    access, coop = _context()
    row = FinanceReconciliation.query.filter_by(id=item_id, cooperative_id=coop.id).first_or_404()
    documents = CooperativeDocument.query.filter_by(
        cooperative_id=coop.id,
        entity_type="FinanceReconciliation",
        entity_id=row.id,
    ).order_by(CooperativeDocument.created_at.desc()).all()
    return render_template(
        "finance_accounts/reconciliation_detail.html",
        reconciliation=row,
        documents=documents,
        can_record=access.role in FINANCE_RECORD_ROLES,
        can_approve=access.role in FINANCE_APPROVAL_ROLES,
    )


@bp.route("/finance/accounts", methods=["POST"])
@roles_required(*FINANCE_RECORD_ROLES)
def account_create():
    access, coop = _context()
    name = request.form.get("name", "").strip()
    account_type = request.form.get("account_type", "").strip()
    if not name or account_type not in ACCOUNT_TYPES:
        return "Account name and valid type are required.", 400
    opening = parse_float(request.form.get("opening_balance"), 0)
    if opening is None:
        return "Enter a valid opening balance.", 400
    try:
        opening_date = parse_date(request.form.get("opening_balance_date"))
    except ValueError:
        return "Enter a valid opening balance date.", 400
    if abs(float(opening)) > 1e-9 and not opening_date:
        return "Opening balance date is required when the opening balance is not zero.", 400
    if FinanceAccount.query.filter(
        func.lower(FinanceAccount.name) == name.lower(),
        FinanceAccount.cooperative_id == coop.id,
    ).first():
        return "An account with this name already exists.", 400
    item = FinanceAccount(
        cooperative_id=coop.id,
        name=name[:120],
        account_type=account_type,
        institution=request.form.get("institution", "").strip()[:120] or None,
        account_last4=request.form.get("account_last4", "").strip()[-4:] or None,
        opening_balance=float(opening),
        opening_balance_date=opening_date,
        notes=request.form.get("notes", "").strip() or None,
        created_by_user_id=session["user_id"],
    )
    db.session.add(item)
    db.session.flush()
    opening_label = opening_date.isoformat() if opening_date else "legacy/unspecified"
    add_audit_log(
        "FINANCE_ACCOUNT_CREATED",
        "FinanceAccount",
        item.id,
        f"{item.name}; opening R{float(opening):.2f} as at {opening_label}",
        cooperative_id=coop.id,
    )
    db.session.commit()
    flash("Financial account created.", "success")
    return redirect(url_for("ledger.dashboard"))


@bp.route("/finance/transactions", methods=["POST"])
@roles_required(*FINANCE_RECORD_ROLES)
def transaction_create():
    access, coop = _context()
    payload, error = _transaction_payload_from_request(coop)
    if error:
        return error

    policy = _evidence_policy(payload["transaction_type"], payload["category"], payload["amount"])
    files = _transaction_evidence_files()
    file_error = _validate_evidence_file_names(files)
    if file_error:
        return file_error

    bypass = request.form.get("evidence_bypass") == "yes"
    bypass_reason = request.form.get("evidence_bypass_reason", "").strip()
    budget_justification = request.form.get("budget_justification", "").strip()

    if policy["budget_justification_required"] and len(budget_justification) < 10:
        return "High-value transactions require a clear approved-budget justification.", 400
    if len(files) < policy["required_files"]:
        if not policy["bypass_allowed"] or not bypass:
            if policy["tier"] == "Structural":
                return "Loans, grants and bulk sales require official supporting evidence before submission.", 400
            return f"{policy['tier']} transactions require {policy['required_files']} evidence file(s) before submission, unless the emergency bypass is used.", 400
        if len(bypass_reason) < 10:
            return "Explain the emergency reason before bypassing the Evidence Wall.", 400
    elif bypass:
        return "Emergency bypass is only needed when required evidence cannot be attached.", 400

    row = LedgerTransaction(
        cooperative_id=coop.id,
        status="Pending Confirmation",
        recorded_by_user_id=session["user_id"],
        evidence_tier=policy["tier"],
        evidence_bypass=bool(bypass),
        evidence_bypass_reason=bypass_reason or None,
        budget_justification=budget_justification or None,
        **payload,
    )
    db.session.add(row)
    db.session.flush()
    try:
        _attach_transaction_evidence(row, files)
    except ValueError as exc:
        db.session.rollback()
        return str(exc), 400

    context = f"{row.transaction_type} R{row.amount:.2f}; {row.category}; evidence tier {row.evidence_tier}"
    if row.evidence_bypass:
        context += f"; EMERGENCY BYPASS: {row.evidence_bypass_reason}"
    if row.payment_method:
        context += f"; {row.payment_method}"
    if row.project_reference:
        context += f"; project {row.project_reference}"
    _notify(
        coop.id,
        FINANCE_APPROVAL_ROLES,
        "Account transaction awaiting approval",
        (
            f"{row.transaction_type}: R{row.amount:.2f} — {row.category}."
            + (" EMERGENCY BYPASS - NO REQUIRED PROOF." if row.evidence_bypass else "")
        ),
        "LedgerTransactionApproval",
        row.id,
        "Warning",
        url_for("ledger.transaction_detail", item_id=row.id),
    )
    add_audit_log("LEDGER_TRANSACTION_RECORDED", "LedgerTransaction", row.id, context, cooperative_id=coop.id)
    db.session.commit()
    flash("Transaction submitted for Chairperson approval.", "success")
    return redirect(url_for("ledger.transaction_detail", item_id=row.id))


@bp.route("/finance/transactions/<int:item_id>/reverse", methods=["POST"])
@roles_required(*FINANCE_RECORD_ROLES)
def transaction_reverse(item_id):
    access, coop = _context()
    original = LedgerTransaction.query.filter_by(id=item_id, cooperative_id=coop.id).first_or_404()
    if original.status != "Confirmed":
        return "Only confirmed transactions can be reversed.", 400
    if original.reversal_of_transaction_id:
        return "A reversal transaction cannot itself be reversed.", 400
    existing = LedgerTransaction.query.filter_by(
        cooperative_id=coop.id,
        reversal_of_transaction_id=original.id,
    ).first()
    if existing:
        return f"Transaction #{original.id} already has reversal transaction #{existing.id}.", 409

    try:
        reversal_date = parse_date(request.form.get("reversal_date"))
    except ValueError:
        return "Enter a valid reversal date.", 400
    if not reversal_date:
        return "Reversal date is required.", 400
    if reversal_date < original.transaction_date:
        return "A reversal cannot be dated before the original transaction.", 400

    reason = request.form.get("reversal_reason", "").strip()
    if len(reason) < 3:
        return "Explain why the confirmed transaction must be reversed.", 400

    payment_method = request.form.get("payment_method", "").strip() or original.payment_method
    if payment_method and payment_method not in PAYMENT_METHODS:
        return "Choose a valid payment method.", 400

    reference = request.form.get("reference", "").strip()[:120] or None
    counterparty = request.form.get("counterparty", "").strip()[:180] or original.counterparty
    project_reference = request.form.get("project_reference", "").strip()[:140] or original.project_reference
    extra_notes = request.form.get("notes", "").strip()
    notes = f"Reversal reason: {reason}"
    if extra_notes:
        notes += f"\n{extra_notes}"

    reversal = LedgerTransaction(
        cooperative_id=coop.id,
        transaction_type=REVERSAL_TYPE,
        category=original.category,
        amount=float(original.amount),
        transaction_date=reversal_date,
        from_account_id=original.to_account_id,
        to_account_id=original.from_account_id,
        counterparty=counterparty,
        reference=reference,
        payment_method=payment_method,
        project_reference=project_reference,
        source_type=None,
        source_id=None,
        reversal_of_transaction_id=original.id,
        status="Pending Confirmation",
        notes=notes,
        recorded_by_user_id=session["user_id"],
    )
    db.session.add(reversal)
    db.session.flush()
    _notify(
        coop.id,
        FINANCE_APPROVAL_ROLES,
        "Confirmed transaction reversal awaiting approval",
        f"Reversal #{reversal.id} for transaction #{original.id}: R{reversal.amount:.2f} — {reversal.category}.",
        "LedgerTransactionApproval",
        reversal.id,
        "Warning",
        url_for("ledger.transaction_detail", item_id=reversal.id),
    )
    add_audit_log(
        "LEDGER_TRANSACTION_REVERSAL_RECORDED",
        "LedgerTransaction",
        reversal.id,
        f"Reversal of #{original.id}; R{reversal.amount:.2f}; reason: {reason[:250]}",
        cooperative_id=coop.id,
    )
    db.session.commit()
    flash("Reversal recorded for Chairperson confirmation. The original confirmed transaction remains unchanged.", "success")
    return redirect(url_for("ledger.transaction_detail", item_id=reversal.id))


@bp.route("/finance/transactions/<int:item_id>/resubmit", methods=["POST"])
@roles_required(*FINANCE_RECORD_ROLES)
def transaction_resubmit(item_id):
    access, coop = _context()
    row = LedgerTransaction.query.filter_by(id=item_id, cooperative_id=coop.id).first_or_404()
    if row.status != "Rejected":
        return "Only rejected transactions can be corrected and resubmitted.", 400

    correction_reason = request.form.get("correction_reason", "").strip()
    if len(correction_reason) < 3:
        return "Explain what was corrected before resubmitting.", 400

    revision = _add_revision(row, correction_reason)

    if row.reversal_of_transaction_id:
        original = LedgerTransaction.query.filter_by(
            id=row.reversal_of_transaction_id,
            cooperative_id=coop.id,
            status="Confirmed",
        ).first()
        if original is None:
            db.session.rollback()
            return "The original confirmed transaction for this reversal is unavailable.", 400
        try:
            transaction_date = parse_date(request.form.get("transaction_date"))
        except ValueError:
            db.session.rollback()
            return "Enter a valid reversal date.", 400
        if not transaction_date or transaction_date < original.transaction_date:
            db.session.rollback()
            return "The reversal date must be on or after the original transaction date.", 400
        payment_method = request.form.get("payment_method", "").strip() or None
        if payment_method and payment_method not in PAYMENT_METHODS:
            db.session.rollback()
            return "Choose a valid payment method.", 400

        row.transaction_date = transaction_date
        row.counterparty = request.form.get("counterparty", "").strip()[:180] or None
        row.reference = request.form.get("reference", "").strip()[:120] or None
        row.payment_method = payment_method
        row.project_reference = request.form.get("project_reference", "").strip()[:140] or None
        row.notes = request.form.get("notes", "").strip() or row.notes
        audit_action = "LEDGER_REVERSAL_CORRECTED_RESUBMITTED"
    else:
        payload, error = _transaction_payload_from_request(coop, exclude_transaction_id=row.id)
        if error:
            db.session.rollback()
            return error
        for field, value in payload.items():
            setattr(row, field, value)
        audit_action = "LEDGER_TRANSACTION_CORRECTED_RESUBMITTED"

    row.status = "Pending Confirmation"
    row.decided_by_user_id = None
    row.decided_at = None
    row.decision_note = None

    _notify(
        coop.id,
        FINANCE_APPROVAL_ROLES,
        "Corrected account transaction awaiting approval",
        f"Transaction #{row.id} was corrected and resubmitted: R{row.amount:.2f} — {row.category}.",
        "LedgerTransactionApproval",
        row.id,
        "Warning",
        url_for("ledger.transaction_detail", item_id=row.id),
    )
    add_audit_log(
        audit_action,
        "LedgerTransaction",
        row.id,
        f"Revision {revision.revision_number}; reason: {revision.reason}",
        cooperative_id=coop.id,
    )
    db.session.commit()
    flash("Rejected transaction corrected and resubmitted for Chairperson confirmation.", "success")
    return redirect(url_for("ledger.transaction_detail", item_id=row.id))


@bp.route("/finance/reconciliations", methods=["POST"])
@roles_required(*FINANCE_RECORD_ROLES)
def reconciliation_create():
    access, coop = _context()
    account_id = parse_int(request.form.get("finance_account_id"))
    account = FinanceAccount.query.filter_by(id=account_id, cooperative_id=coop.id, status="Active").first()
    if account is None:
        return "Choose an active financial account belonging to this cooperative.", 400
    try:
        statement_date = parse_date(request.form.get("statement_date"))
    except ValueError:
        return "Enter a valid statement date.", 400
    statement_balance = parse_float(request.form.get("statement_balance"))
    if not statement_date or statement_balance is None:
        return "Statement date and statement balance are required.", 400
    if FinanceReconciliation.query.filter_by(
        cooperative_id=coop.id,
        finance_account_id=account.id,
        statement_date=statement_date,
    ).first():
        return "A reconciliation already exists for this account and statement date.", 409
    book = _confirmed_account_balance_through(account, statement_date)
    row = FinanceReconciliation(
        cooperative_id=coop.id,
        finance_account_id=account.id,
        statement_date=statement_date,
        statement_balance=float(statement_balance),
        book_balance=float(book),
        difference=float(statement_balance) - float(book),
        status="Pending Review",
        notes=request.form.get("notes", "").strip() or None,
        prepared_by_user_id=session["user_id"],
    )
    db.session.add(row)
    db.session.flush()
    _notify(
        coop.id,
        FINANCE_APPROVAL_ROLES,
        "Account reconciliation awaiting review",
        f"{account.name}: statement R{statement_balance:.2f}; ledger R{book:.2f}; difference R{row.difference:.2f}.",
        "FinanceReconciliationReview",
        row.id,
        "Warning",
        url_for("ledger.reconciliation_detail", item_id=row.id),
    )
    add_audit_log(
        "FINANCE_RECONCILIATION_RECORDED",
        "FinanceReconciliation",
        row.id,
        f"{account.name}: statement R{statement_balance:.2f}; ledger R{book:.2f}; difference R{row.difference:.2f}",
        cooperative_id=coop.id,
    )
    db.session.commit()
    flash("Account reconciliation recorded for Chairperson review.", "success")
    return redirect(url_for("ledger.reconciliation_detail", item_id=row.id))


@bp.route("/finance/transactions/<int:item_id>/decision", methods=["POST"])
@roles_required(*FINANCE_APPROVAL_ROLES)
def transaction_decision(item_id):
    access, coop = _context()
    row = LedgerTransaction.query.filter_by(id=item_id, cooperative_id=coop.id).first_or_404()
    if row.status != "Pending Confirmation":
        return "Only pending transactions can be decided.", 400
    if row.recorded_by_user_id == session.get("user_id"):
        return "You cannot approve or reject a transaction you recorded.", 403
    decision = request.form.get("decision", "").lower()
    if decision not in {"approve", "reject"}:
        return "Choose approve or reject.", 400
    if decision == "approve" and row.from_account_id and row.from_account.confirmed_balance + 1e-9 < float(row.amount):
        return "The paying account does not have enough confirmed funds.", 400
    if decision == "approve" and row.evidence_bypass:
        if request.form.get("acknowledge_evidence_bypass") != "yes":
            return "Acknowledge the emergency evidence bypass before approving this transaction.", 400
        row.evidence_bypass_acknowledged_at = utc_now()

    row.status = "Confirmed" if decision == "approve" else "Rejected"
    row.decision_note = request.form.get("decision_note", "").strip()[:1000] or None
    row.decided_by_user_id = session["user_id"]
    row.decided_at = utc_now()
    _notify(
        coop.id,
        FINANCE_RECORD_ROLES,
        f"Account transaction {row.status.lower()}",
        f"{row.transaction_type} R{row.amount:.2f} ({row.category}) was {row.status.lower()}.",
        "LedgerTransactionDecision",
        row.id,
        "Info" if decision == "approve" else "Warning",
        url_for("ledger.transaction_detail", item_id=row.id),
    )
    details = f"{row.transaction_type} R{row.amount:.2f}"
    if row.reversal_of_transaction_id:
        details += f"; reversal of #{row.reversal_of_transaction_id}"
    if row.evidence_bypass:
        details += f"; emergency evidence bypass acknowledged: {bool(row.evidence_bypass_acknowledged_at)}"
    if row.decision_note:
        details += f"; note: {row.decision_note}"
    add_audit_log(
        "LEDGER_TRANSACTION_CONFIRMED" if decision == "approve" else "LEDGER_TRANSACTION_REJECTED",
        "LedgerTransaction",
        row.id,
        details,
        cooperative_id=coop.id,
    )
    db.session.commit()
    return redirect(url_for("ledger.transaction_detail", item_id=row.id))


@bp.route("/finance/reconciliations/<int:item_id>/review", methods=["POST"])
@roles_required(*FINANCE_APPROVAL_ROLES)
def reconciliation_review(item_id):
    access, coop = _context()
    row = FinanceReconciliation.query.filter_by(id=item_id, cooperative_id=coop.id).first_or_404()
    if row.status != "Pending Review":
        return "Only pending reconciliations can be reviewed.", 400
    if row.prepared_by_user_id == session.get("user_id"):
        return "You cannot review a reconciliation you prepared.", 403
    row.status = "Reviewed"
    row.reviewed_by_user_id = session["user_id"]
    row.reviewed_at = utc_now()
    _notify(
        coop.id,
        FINANCE_RECORD_ROLES,
        "Account reconciliation reviewed",
        f"{row.finance_account.name}: difference R{row.difference:.2f} reviewed.",
        "FinanceReconciliationDecision",
        row.id,
        "Info",
        url_for("ledger.reconciliation_detail", item_id=row.id),
    )
    add_audit_log(
        "FINANCE_RECONCILIATION_REVIEWED",
        "FinanceReconciliation",
        row.id,
        f"{row.finance_account.name}: difference R{row.difference:.2f}",
        cooperative_id=coop.id,
    )
    db.session.commit()
    flash("Account reconciliation marked reviewed.", "success")
    return redirect(url_for("ledger.reconciliation_detail", item_id=row.id))


def register_account_ledger(app):
    if "ledger" not in app.blueprints:
        app.register_blueprint(bp)
