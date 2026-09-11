from pathlib import Path


def replace_once(text, old, new, label):
    if old not in text:
        raise SystemExit(f"Could not find {label} patch anchor.")
    return text.replace(old, new, 1)


phase7_path = Path("phase7.py")
phase7 = phase7_path.read_text(encoding="utf-8")

if "pending_b = Budget.query.filter_by" not in phase7:
    old = '''        if access.role in FINANCE_APPROVAL_ROLES:\n            pending_c = Contribution.query.filter_by(cooperative_id=coop_id, status="Pending Confirmation").count()\n            pending_e = Expense.query.filter_by(cooperative_id=coop_id, status="Pending Confirmation").count()\n            if pending_c:\n                add("Finance", "Contributions awaiting approval", f"{pending_c} contribution(s) need your decision.",\n                    "Warning", url_for("contributions_list"), source_type="FinanceQueue", source_id=1)\n            if pending_e:\n                add("Finance", "Expenses awaiting approval", f"{pending_e} expense(s) need your decision.",\n                    "Warning", url_for("expenses_list"), source_type="FinanceQueue", source_id=2)\n\n        if access.role in FINANCE_RECORD_ROLES:\n            rejected = Contribution.query.filter_by(cooperative_id=coop_id, status="Rejected").count() + \\\n                       Expense.query.filter_by(cooperative_id=coop_id, status="Rejected").count()\n            if rejected:\n                add("Finance", "Rejected finance needs correction", f"{rejected} rejected finance record(s) need correction or review.",\n                    "Warning", url_for("phase7.finance_control"), source_type="FinanceQueue", source_id=3)\n'''
    new = '''        if access.role in FINANCE_APPROVAL_ROLES:\n            pending_c = Contribution.query.filter_by(cooperative_id=coop_id, status="Pending Confirmation").count()\n            pending_e = Expense.query.filter_by(cooperative_id=coop_id, status="Pending Confirmation").count()\n            pending_b = Budget.query.filter_by(cooperative_id=coop_id, status="Pending Approval").count()\n            if pending_c:\n                add("Finance", "Contributions awaiting approval", f"{pending_c} contribution(s) need your decision.",\n                    "Warning", url_for("contributions_list"), source_type="FinanceQueue", source_id=1)\n            if pending_e:\n                add("Finance", "Expenses awaiting approval", f"{pending_e} expense(s) need your decision.",\n                    "Warning", url_for("expenses_list"), source_type="FinanceQueue", source_id=2)\n            if pending_b:\n                add("Finance", "Budgets awaiting approval", f"{pending_b} budget line(s) need your decision.",\n                    "Warning", url_for("phase7.finance_control"), source_type="FinanceQueue", source_id=4)\n\n        if access.role in FINANCE_RECORD_ROLES:\n            rejected = (\n                Contribution.query.filter_by(cooperative_id=coop_id, status="Rejected").count()\n                + Expense.query.filter_by(cooperative_id=coop_id, status="Rejected").count()\n                + Budget.query.filter_by(cooperative_id=coop_id, status="Rejected").count()\n            )\n            if rejected:\n                add("Finance", "Rejected finance needs correction", f"{rejected} rejected finance record(s) need correction or review.",\n                    "Warning", url_for("phase7.finance_control"), source_type="FinanceQueue", source_id=3)\n'''
    phase7 = replace_once(phase7, old, new, "finance notification")

if "def budget_resubmit(budget_id):" not in phase7:
    anchor = '''\n\n@bp.route("/finance-control/reconciliation", methods=["POST"])\n@roles_required(*FINANCE_RECORD_ROLES)\ndef reconciliation_create():\n'''
    route = '''\n\n@bp.route("/finance-control/budgets/<int:budget_id>/resubmit", methods=["POST"])\n@roles_required(*FINANCE_RECORD_ROLES)\ndef budget_resubmit(budget_id):\n    item = Budget.query.get_or_404(budget_id)\n    require_own_cooperative(item.cooperative_id)\n    if item.status != "Rejected":\n        return "Only rejected budget lines can be corrected and resubmitted.", 400\n\n    year = parse_int(request.form.get("fiscal_year"))\n    planned = parse_float(request.form.get("planned_amount"))\n    budget_type = request.form.get("budget_type", "").strip()\n    category = request.form.get("category", "").strip() or "All"\n    notes = request.form.get("notes", "").strip() or None\n\n    if not year or year < 2020 or year > 2100 or planned is None or planned < 0:\n        return "Enter a valid fiscal year and non-negative planned amount.", 400\n    if budget_type not in {"Expense", "Contribution", "Sales Receipts"}:\n        return "Invalid budget type.", 400\n\n    duplicate = Budget.query.filter(\n        Budget.cooperative_id == item.cooperative_id,\n        Budget.fiscal_year == year,\n        Budget.budget_type == budget_type,\n        Budget.category == category,\n        Budget.id != item.id,\n    ).first()\n    if duplicate:\n        return "Another budget line already uses that year, type and category.", 400\n\n    before = f"{item.fiscal_year} {item.budget_type} {item.category} R{float(item.planned_amount or 0):.2f}"\n    item.fiscal_year = year\n    item.budget_type = budget_type\n    item.category = category\n    item.planned_amount = planned\n    item.notes = notes\n    item.status = "Pending Approval"\n    item.approved_by_user_id = None\n    item.approved_at = None\n\n    add_audit_log(\n        "BUDGET_RESUBMITTED", "Budget", item.id,\n        f"Corrected from [{before}] to [{year} {budget_type} {category} R{planned:.2f}] and resubmitted for approval.",\n        cooperative_id=item.cooperative_id,\n    )\n    db.session.commit()\n    flash("Budget line corrected and resubmitted for Chairperson approval.", "success")\n    return redirect(url_for("phase7.finance_control", year=year))\n'''
    phase7 = replace_once(phase7, anchor, route + anchor, "budget resubmit route")

phase7_path.write_text(phase7, encoding="utf-8")


template_path = Path("templates/phase7/finance_control.html")
template = template_path.read_text(encoding="utf-8")
if "Edit &amp; Resubmit" not in template:
    start_marker = '<section class="p7-card"><div class="p7-card-head"><h2>{{ year }} Budget vs Actual</h2>'
    end_marker = '\n\n<section class="p7-card"><div class="p7-card-head"><h2>Bank Reconciliation History</h2>'
    start = template.find(start_marker)
    end = template.find(end_marker)
    if start == -1 or end == -1 or end <= start:
        raise SystemExit("Could not find finance budget table template anchors.")
    budget_section = '''<section class="p7-card">
<div class="p7-card-head"><h2>{{ year }} Budget vs Actual</h2><form method="GET"><input name="year" type="number" value="{{ year }}" min="2020" max="2100" style="height:34px;width:85px"><button class="p7-btn" type="submit">Go</button></form></div>
<div class="p7-table-wrap"><table class="p7-table">
<thead><tr><th>Type</th><th>Category</th><th>Planned</th><th>Actual</th><th>Variance</th><th>Status</th><th>Action</th></tr></thead>
<tbody>
{% for row in budget_rows %}{% set b=row.budget %}
<tr>
<td>{{ b.budget_type }}</td><td>{{ b.category }}</td><td>R {{ "{:,.2f}".format(b.planned_amount|float) }}</td><td>R {{ "{:,.2f}".format(row.actual|float) }}</td><td>R {{ "{:,.2f}".format((b.planned_amount-row.actual)|float) }}</td>
<td><span class="p7-badge {% if b.status=='Pending Approval' %}warning{% elif b.status=='Rejected' %}danger{% endif %}">{{ b.status }}</span></td>
<td>
{% if can_approve and b.status=='Pending Approval' %}
<form method="POST" action="{{ url_for('phase7.budget_decision', budget_id=b.id) }}" class="p7-actions"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><button class="p7-btn primary" name="decision" value="approve">Approve</button><button class="p7-btn danger" name="decision" value="reject">Reject</button></form>
{% elif can_record and b.status=='Rejected' %}
<details style="min-width:260px"><summary class="p7-btn">Edit &amp; Resubmit</summary>
<form class="p7-form" method="POST" action="{{ url_for('phase7.budget_resubmit', budget_id=b.id) }}" style="margin-top:10px"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
<div class="p7-field"><label>Fiscal Year</label><input name="fiscal_year" type="number" value="{{ b.fiscal_year }}" min="2020" max="2100" required></div>
<div class="p7-field"><label>Type</label><select name="budget_type" required><option value="Expense" {% if b.budget_type=='Expense' %}selected{% endif %}>Expense</option><option value="Contribution" {% if b.budget_type=='Contribution' %}selected{% endif %}>Contribution</option><option value="Sales Receipts" {% if b.budget_type=='Sales Receipts' %}selected{% endif %}>Sales Receipts</option></select></div>
<div class="p7-field"><label>Category</label><input name="category" value="{{ b.category }}" required></div>
<div class="p7-field"><label>Planned Amount (R)</label><input name="planned_amount" type="number" step="0.01" min="0" value="{{ b.planned_amount }}" required></div>
<div class="p7-field full"><label>Notes</label><textarea name="notes">{{ b.notes or '' }}</textarea></div>
<div class="p7-field full"><button class="p7-btn primary" type="submit">Resubmit for Chairperson Approval</button></div>
</form></details>
{% else %}—{% endif %}
</td>
</tr>
{% else %}<tr><td colspan="7"><div class="p7-empty">No budget lines for {{ year }}.</div></td></tr>{% endfor %}
</tbody></table></div></section>'''
    template = template[:start] + budget_section + template[end:]

template_path.write_text(template, encoding="utf-8")


test_path = Path("phase7_regression_tests.py")
tests = test_path.read_text(encoding="utf-8")
if "def test_rejected_budget_can_be_corrected_and_resubmitted" not in tests:
    marker = '    def test_document_fingerprint_and_cooperative_scope(self):\n'
    test_method = '''    def test_rejected_budget_can_be_corrected_and_resubmitted(self):\n        c, p = self.crm, self.p7\n        today = c.crm_today()\n\n        self.login_as("treasurer_a")\n        response = self.client.post("/finance-control/budgets", data={\n            "fiscal_year": str(today.year), "budget_type": "Expense", "category": "Fuel",\n            "planned_amount": "5000", "notes": "Initial fuel plan",\n        })\n        self.assertEqual(response.status_code, 302)\n        with c.app.app_context():\n            budget_id = p.Budget.query.one().id\n\n        self.login_as("chair_a")\n        response = self.client.post(f"/finance-control/budgets/{budget_id}/decision", data={"decision": "reject"})\n        self.assertEqual(response.status_code, 302)\n        with c.app.app_context():\n            rejected = c.db.session.get(p.Budget, budget_id)\n            self.assertEqual(rejected.status, "Rejected")\n            self.assertIsNotNone(rejected.approved_by_user_id)\n\n        self.login_as("treasurer_a")\n        page = self.client.get(f"/finance-control?year={today.year}")\n        self.assertEqual(page.status_code, 200)\n        self.assertIn(b"Edit &amp; Resubmit", page.data)\n        response = self.client.post(f"/finance-control/budgets/{budget_id}/resubmit", data={\n            "fiscal_year": str(today.year), "budget_type": "Expense", "category": "Fuel",\n            "planned_amount": "6500", "notes": "Corrected fuel plan",\n        })\n        self.assertEqual(response.status_code, 302)\n        with c.app.app_context():\n            corrected = c.db.session.get(p.Budget, budget_id)\n            self.assertEqual(corrected.status, "Pending Approval")\n            self.assertAlmostEqual(corrected.planned_amount, 6500.0)\n            self.assertEqual(corrected.notes, "Corrected fuel plan")\n            self.assertIsNone(corrected.approved_by_user_id)\n            self.assertIsNone(corrected.approved_at)\n            self.assertIsNotNone(c.AuditLog.query.filter_by(action="BUDGET_RESUBMITTED", entity_id=budget_id).first())\n\n        self.login_as("chair_a")\n        self.assertEqual(self.client.post(f"/finance-control/budgets/{budget_id}/resubmit", data={\n            "fiscal_year": str(today.year), "budget_type": "Expense", "category": "Fuel",\n            "planned_amount": "7000",\n        }).status_code, 403)\n        self.assertEqual(self.client.post(f"/finance-control/budgets/{budget_id}/decision", data={"decision": "approve"}).status_code, 302)\n        with c.app.app_context():\n            self.assertEqual(c.db.session.get(p.Budget, budget_id).status, "Approved")\n\n'''
    tests = replace_once(tests, marker, test_method + marker, "budget resubmit regression test")

test_path.write_text(tests, encoding="utf-8")

print("Budget correction and resubmission workflow patch applied.")
