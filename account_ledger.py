"""Cooperative cash and bank account ledger."""
import importlib
import sys
from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy import func

_core=sys.modules.get("__main__")
if _core is None or not hasattr(_core,"db"): _core=importlib.import_module("app")
for _name in ("db","UserAccess","FINANCE_VIEW_ROLES","FINANCE_RECORD_ROLES","FINANCE_APPROVAL_ROLES",
              "current_access","current_cooperative","roles_required","parse_int","parse_float","parse_date",
              "add_audit_log","utc_now"):
    globals()[_name]=getattr(_core,_name)
from phase7 import _upsert_notification

bp=Blueprint("ledger",__name__)
ACCOUNT_TYPES=("Bank Account","Cash Box","Mobile Money","Savings","Other")
TRANSACTION_TYPES=("Opening Balance","Income","Expense","Transfer")
INCOME_CATEGORIES=("Product Sale","Bulk Sale","Membership Fee","Primary Contribution","Grant","Loan","Other Income")
EXPENSE_CATEGORIES=("Farm Inputs","Transport","Packaging","Equipment","Wages","Bank Charges","Refund","Other Expense")
ALL_CATEGORIES=INCOME_CATEGORIES+EXPENSE_CATEGORIES

class FinanceAccount(db.Model):
    __tablename__="finance_account"
    __table_args__=(db.UniqueConstraint("cooperative_id","name",name="uq_finance_account_name"),)
    id=db.Column(db.Integer,primary_key=True)
    cooperative_id=db.Column(db.Integer,db.ForeignKey("cooperative.id"),nullable=False,index=True)
    name=db.Column(db.String(120),nullable=False)
    account_type=db.Column(db.String(40),nullable=False)
    institution=db.Column(db.String(120))
    account_last4=db.Column(db.String(4))
    opening_balance=db.Column(db.Float,nullable=False,default=0)
    status=db.Column(db.String(20),nullable=False,default="Active",index=True)
    notes=db.Column(db.Text)
    created_by_user_id=db.Column(db.Integer,db.ForeignKey("user.id"),nullable=False)
    created_at=db.Column(db.DateTime,nullable=False,default=utc_now)
    cooperative=db.relationship("Cooperative",foreign_keys=[cooperative_id])
    @property
    def confirmed_balance(self):
        total=float(self.opening_balance or 0)
        for row in self.incoming_transactions:
            if row.status=="Confirmed": total+=float(row.amount or 0)
        for row in self.outgoing_transactions:
            if row.status=="Confirmed": total-=float(row.amount or 0)
        return total
    @property
    def pending_change(self):
        incoming=sum(float(x.amount or 0) for x in self.incoming_transactions if x.status=="Pending Confirmation")
        outgoing=sum(float(x.amount or 0) for x in self.outgoing_transactions if x.status=="Pending Confirmation")
        return incoming-outgoing

class LedgerTransaction(db.Model):
    __tablename__="ledger_transaction"
    id=db.Column(db.Integer,primary_key=True)
    cooperative_id=db.Column(db.Integer,db.ForeignKey("cooperative.id"),nullable=False,index=True)
    transaction_type=db.Column(db.String(30),nullable=False,index=True)
    category=db.Column(db.String(100),nullable=False,index=True)
    amount=db.Column(db.Float,nullable=False)
    transaction_date=db.Column(db.Date,nullable=False,index=True)
    from_account_id=db.Column(db.Integer,db.ForeignKey("finance_account.id"))
    to_account_id=db.Column(db.Integer,db.ForeignKey("finance_account.id"))
    counterparty=db.Column(db.String(180))
    reference=db.Column(db.String(120))
    source_type=db.Column(db.String(60))
    source_id=db.Column(db.Integer)
    status=db.Column(db.String(40),nullable=False,default="Pending Confirmation",index=True)
    notes=db.Column(db.Text)
    recorded_by_user_id=db.Column(db.Integer,db.ForeignKey("user.id"),nullable=False)
    decided_by_user_id=db.Column(db.Integer,db.ForeignKey("user.id"))
    decided_at=db.Column(db.DateTime)
    created_at=db.Column(db.DateTime,nullable=False,default=utc_now)
    cooperative=db.relationship("Cooperative",foreign_keys=[cooperative_id])
    from_account=db.relationship("FinanceAccount",foreign_keys=[from_account_id],backref=db.backref("outgoing_transactions",lazy=True))
    to_account=db.relationship("FinanceAccount",foreign_keys=[to_account_id],backref=db.backref("incoming_transactions",lazy=True))
    recorded_by=db.relationship("User",foreign_keys=[recorded_by_user_id])
    decided_by=db.relationship("User",foreign_keys=[decided_by_user_id])

def _context():
    access,coop=current_access(),current_cooperative()
    if not access or access.role not in FINANCE_VIEW_ROLES or not coop: abort(403)
    return access,coop

def _notify(coop_id,roles,title,message,source_type,source_id,severity="Info"):
    for access in UserAccess.query.filter(UserAccess.cooperative_id==coop_id,UserAccess.status=="Active",UserAccess.role.in_(tuple(roles))).all():
        _upsert_notification(access.user_id,coop_id,"Finance",title,message,severity,url_for("ledger.dashboard"),source_type=source_type,source_id=source_id)

@bp.route("/finance/accounts")
@roles_required(*FINANCE_VIEW_ROLES)
def dashboard():
    access,coop=_context()
    accounts=FinanceAccount.query.filter_by(cooperative_id=coop.id).order_by(FinanceAccount.name).all()
    query=LedgerTransaction.query.filter_by(cooperative_id=coop.id)
    category=request.args.get("category","").strip(); status=request.args.get("status","").strip(); account_id=parse_int(request.args.get("account_id"))
    if category in ALL_CATEGORIES: query=query.filter(LedgerTransaction.category==category)
    if status in {"Pending Confirmation","Confirmed","Rejected"}: query=query.filter(LedgerTransaction.status==status)
    if account_id and any(a.id==account_id for a in accounts): query=query.filter((LedgerTransaction.from_account_id==account_id)|(LedgerTransaction.to_account_id==account_id))
    transactions=query.order_by(LedgerTransaction.transaction_date.desc(),LedgerTransaction.created_at.desc()).limit(250).all()
    confirmed_total=sum(a.confirmed_balance for a in accounts); pending_total=sum(a.pending_change for a in accounts)
    return render_template("finance_accounts/dashboard.html",accounts=accounts,transactions=transactions,confirmed_total=confirmed_total,pending_total=pending_total,
                           account_types=ACCOUNT_TYPES,income_categories=INCOME_CATEGORIES,expense_categories=EXPENSE_CATEGORIES,all_categories=ALL_CATEGORIES,
                           selected_category=category,selected_status=status,selected_account_id=account_id,
                           can_record=access.role in FINANCE_RECORD_ROLES,can_approve=access.role in FINANCE_APPROVAL_ROLES)

@bp.route("/finance/transactions/<int:item_id>")
@roles_required(*FINANCE_VIEW_ROLES)
def transaction_detail(item_id):
    access,coop=_context(); row=LedgerTransaction.query.filter_by(id=item_id,cooperative_id=coop.id).first_or_404()
    return render_template("finance_accounts/transaction_detail.html",transaction=row,can_approve=access.role in FINANCE_APPROVAL_ROLES)

@bp.route("/finance/accounts",methods=["POST"])
@roles_required(*FINANCE_RECORD_ROLES)
def account_create():
    access,coop=_context(); name=request.form.get("name","").strip(); account_type=request.form.get("account_type","").strip()
    if not name or account_type not in ACCOUNT_TYPES: return "Account name and valid type are required.",400
    opening=parse_float(request.form.get("opening_balance"),0)
    if opening is None: return "Enter a valid opening balance.",400
    if FinanceAccount.query.filter(func.lower(FinanceAccount.name)==name.lower(),FinanceAccount.cooperative_id==coop.id).first(): return "An account with this name already exists.",400
    item=FinanceAccount(cooperative_id=coop.id,name=name[:120],account_type=account_type,institution=request.form.get("institution","").strip()[:120] or None,
                        account_last4=request.form.get("account_last4","").strip()[-4:] or None,opening_balance=float(opening),notes=request.form.get("notes","").strip() or None,
                        created_by_user_id=session["user_id"])
    db.session.add(item); db.session.flush(); add_audit_log("FINANCE_ACCOUNT_CREATED","FinanceAccount",item.id,item.name,cooperative_id=coop.id)
    db.session.commit(); flash("Financial account created.","success"); return redirect(url_for("ledger.dashboard"))

@bp.route("/finance/transactions",methods=["POST"])
@roles_required(*FINANCE_RECORD_ROLES)
def transaction_create():
    access,coop=_context(); kind=request.form.get("transaction_type","").strip()
    if kind not in TRANSACTION_TYPES: return "Choose a valid transaction type.",400
    amount=parse_float(request.form.get("amount"))
    if amount is None or amount<=0: return "Amount must be greater than zero.",400
    try: transaction_date=parse_date(request.form.get("transaction_date"))
    except ValueError: return "Enter a valid transaction date.",400
    if not transaction_date: return "Transaction date is required.",400
    from_id=parse_int(request.form.get("from_account_id")); to_id=parse_int(request.form.get("to_account_id")); account_ids=[x for x in (from_id,to_id) if x]
    owned={x.id:x for x in FinanceAccount.query.filter(FinanceAccount.cooperative_id==coop.id,FinanceAccount.id.in_(account_ids or [-1])).all()}
    if kind in {"Income","Opening Balance"}:
        from_id=None
        if not to_id or to_id not in owned: return "Choose the account receiving the money.",400
    elif kind=="Expense":
        to_id=None
        if not from_id or from_id not in owned: return "Choose the account paying the money.",400
    else:
        if not from_id or not to_id or from_id==to_id or from_id not in owned or to_id not in owned: return "Choose two different accounts in this cooperative for a transfer.",400
    category=request.form.get("category","").strip()
    allowed=INCOME_CATEGORIES if kind in {"Income","Opening Balance"} else EXPENSE_CATEGORIES if kind=="Expense" else ("Transfer",)
    if category not in allowed: return "Choose a valid category for this transaction type.",400
    row=LedgerTransaction(cooperative_id=coop.id,transaction_type=kind,category=category,amount=float(amount),transaction_date=transaction_date,
                          from_account_id=from_id,to_account_id=to_id,counterparty=request.form.get("counterparty","").strip()[:180] or None,
                          reference=request.form.get("reference","").strip()[:120] or None,source_type=request.form.get("source_type","").strip()[:60] or None,
                          source_id=parse_int(request.form.get("source_id")),status="Pending Confirmation",notes=request.form.get("notes","").strip() or None,
                          recorded_by_user_id=session["user_id"])
    db.session.add(row); db.session.flush(); _notify(coop.id,FINANCE_APPROVAL_ROLES,"Account transaction awaiting approval",f"{kind}: R{amount:.2f} — {category}.","LedgerTransactionApproval",row.id,"Warning")
    add_audit_log("LEDGER_TRANSACTION_RECORDED","LedgerTransaction",row.id,f"{kind} R{amount:.2f}",cooperative_id=coop.id); db.session.commit()
    flash("Transaction recorded for Chairperson confirmation.","success"); return redirect(url_for("ledger.transaction_detail",item_id=row.id))

@bp.route("/finance/transactions/<int:item_id>/decision",methods=["POST"])
@roles_required(*FINANCE_APPROVAL_ROLES)
def transaction_decision(item_id):
    access,coop=_context(); row=LedgerTransaction.query.filter_by(id=item_id,cooperative_id=coop.id).first_or_404()
    if row.status!="Pending Confirmation": return "Only pending transactions can be decided.",400
    decision=request.form.get("decision","").lower()
    if decision not in {"approve","reject"}: return "Choose approve or reject.",400
    if decision=="approve" and row.transaction_type in {"Expense","Transfer"} and row.from_account.confirmed_balance+1e-9<float(row.amount): return "The paying account does not have enough confirmed funds.",400
    row.status="Confirmed" if decision=="approve" else "Rejected"; row.decided_by_user_id=session["user_id"]; row.decided_at=utc_now()
    _notify(coop.id,FINANCE_RECORD_ROLES,f"Account transaction {row.status.lower()}",f"{row.transaction_type} R{row.amount:.2f} ({row.category}) was {row.status.lower()}.","LedgerTransactionDecision",row.id,"Info" if decision=="approve" else "Warning")
    add_audit_log("LEDGER_TRANSACTION_CONFIRMED" if decision=="approve" else "LEDGER_TRANSACTION_REJECTED","LedgerTransaction",row.id,f"{row.transaction_type} R{row.amount:.2f}",cooperative_id=coop.id)
    db.session.commit(); return redirect(url_for("ledger.transaction_detail",item_id=row.id))

def register_account_ledger(app):
    if "ledger" not in app.blueprints: app.register_blueprint(bp)
