from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path, old, new, label):
    text = path.read_text(encoding="utf-8")
    if new in text:
        return False
    if old not in text:
        raise RuntimeError(f"Missing {label} anchor in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return True


def main():
    changed = []

    app_path = ROOT / "app.py"
    app_text = app_path.read_text(encoding="utf-8")

    old = '''    crops = own_cooperative_query(Crop).order_by(Crop.name.asc()).all()\n\n    if request.method == "POST":\n        crop_id = request.form.get("crop_id", "").strip()\n'''
    new = '''    crops = (\n        own_cooperative_query(Crop)\n        .filter(Crop.status.notin_(["Harvested", "Failed"]))\n        .order_by(Crop.name.asc())\n        .all()\n    )\n\n    if request.method == "POST":\n        crop_id = request.form.get("crop_id", "").strip()\n'''
    if replace_once(app_path, old, new, "add-harvest eligible crops"):
        changed.append("app.py")

    app_text = app_path.read_text(encoding="utf-8")
    old = '''        if crop.status == "Failed":\n            return "A failed crop cannot receive a harvest record. Update the crop status first if harvesting is possible.", 400\n'''
    new = '''        if crop.status in {"Harvested", "Failed"}:\n            return f"A {crop.status.lower()} crop cannot receive another harvest record.", 400\n'''
    if replace_once(app_path, old, new, "add-harvest completed guard"):
        if "app.py" not in changed:
            changed.append("app.py")

    old = '''    harvests = own_cooperative_query(Harvest).order_by(Harvest.harvest_date.desc()).all()\n\n    if request.method == "POST":\n        harvest_id = request.form.get("harvest_id", "").strip()\n'''
    new = '''    harvests = [\n        harvest for harvest in own_cooperative_query(Harvest).order_by(Harvest.harvest_date.desc()).all()\n        if harvest.status not in {"Sold", "Spoiled"} and harvest_available_quantity(harvest) > 1e-9\n    ]\n\n    if request.method == "POST":\n        harvest_id = request.form.get("harvest_id", "").strip()\n'''
    if replace_once(app_path, old, new, "add-sale eligible harvests"):
        if "app.py" not in changed:
            changed.append("app.py")

    old = '''        if not harvest or harvest.cooperative_id != own_cooperative_id():\n            return "Please select a harvest from your own cooperative.", 400\n\n        if quantity_value <= 0:\n'''
    new = '''        if not harvest or harvest.cooperative_id != own_cooperative_id():\n            return "Please select a harvest from your own cooperative.", 400\n        if harvest.status in {"Sold", "Spoiled"} or harvest_available_quantity(harvest) <= 1e-9:\n            return "That harvest is complete or has no quantity left to sell.", 400\n\n        if quantity_value <= 0:\n'''
    if replace_once(app_path, old, new, "add-sale completed guard"):
        if "app.py" not in changed:
            changed.append("app.py")

    old = '''    sales = own_cooperative_query(Sale).order_by(Sale.sale_date.desc()).all()\n\n    if request.method == "POST":\n        sale_id = request.form.get("sale_id", "").strip()\n'''
    new = '''    sales = [\n        sale for sale in own_cooperative_query(Sale).order_by(Sale.sale_date.desc()).all()\n        if sale.status != "Cancelled"\n        and sale_recorded_payment_amount(sale) + 1e-9 < float(sale.total_amount or 0)\n    ]\n\n    if request.method == "POST":\n        sale_id = request.form.get("sale_id", "").strip()\n'''
    if replace_once(app_path, old, new, "add-payment eligible sales"):
        if "app.py" not in changed:
            changed.append("app.py")

    old = '''        already_recorded = sale_recorded_payment_amount(sale)\n        if status != "Reversed" and already_recorded + amount_value > float(sale.total_amount or 0) + 1e-9:\n'''
    new = '''        already_recorded = sale_recorded_payment_amount(sale)\n        if status != "Reversed" and already_recorded + 1e-9 >= float(sale.total_amount or 0):\n            return "This sale is already fully paid and no longer accepts new payments.", 400\n        if status != "Reversed" and already_recorded + amount_value > float(sale.total_amount or 0) + 1e-9:\n'''
    if replace_once(app_path, old, new, "add-payment completed guard"):
        if "app.py" not in changed:
            changed.append("app.py")

    old = '''    farmers = own_cooperative_query(Farmer).order_by(Farmer.fullname.asc()).all()\n    selected_membership = None\n\n    requested_membership_id = parse_int(request.args.get("membership_id"))\n    if requested_membership_id:\n        candidate = scoped_get(Membership, requested_membership_id)\n        if candidate and candidate.cooperative_id == access.cooperative_id:\n            selected_membership = candidate\n'''
    new = '''    eligible_memberships = (\n        Membership.query\n        .join(Farmer, Farmer.id == Membership.farmer_id)\n        .filter(\n            Membership.cooperative_id == access.cooperative_id,\n            Membership.status.notin_(["Resigned", "Deceased", "Inactive"]),\n        )\n        .order_by(Farmer.fullname.asc())\n        .all()\n    )\n    eligible_memberships = [m for m in eligible_memberships if m.fee_outstanding > 1e-9]\n    farmers = [m.farmer for m in eligible_memberships]\n    eligible_farmer_ids = {farmer.id for farmer in farmers}\n    selected_membership = None\n\n    requested_membership_id = parse_int(request.args.get("membership_id"))\n    if requested_membership_id:\n        candidate = scoped_get(Membership, requested_membership_id)\n        if (\n            candidate\n            and candidate.cooperative_id == access.cooperative_id\n            and candidate.fee_outstanding > 1e-9\n            and candidate.status not in {"Resigned", "Deceased", "Inactive"}\n        ):\n            selected_membership = candidate\n'''
    if replace_once(app_path, old, new, "contribution actionable members"):
        if "app.py" not in changed:
            changed.append("app.py")

    old = '''        if not farmer or farmer.cooperative_id != access.cooperative_id:\n            return "Please select a valid member/farmer from your cooperative.", 400\n        if amount is None or amount <= 0:\n'''
    new = '''        if not farmer or farmer.cooperative_id != access.cooperative_id:\n            return "Please select a valid member/farmer from your cooperative.", 400\n        if farmer.id not in eligible_farmer_ids:\n            return "This member has no contribution amount left to record and is no longer an actionable option.", 400\n        if amount is None or amount <= 0:\n'''
    if replace_once(app_path, old, new, "contribution completed guard"):
        if "app.py" not in changed:
            changed.append("app.py")

    contribution_template = ROOT / "templates" / "contribution_form.html"
    old = '''                <label for="farmer_id">Member / Farmer *</label>\n                <select id="farmer_id" name="farmer_id" required {% if selected_membership %}disabled style="background:#f7f9f8"{% endif %}>\n                    <option value="">Select person</option>\n                    {% for farmer in farmers %}<option value="{{ farmer.id }}" {% if selected_membership and selected_membership.farmer_id == farmer.id %}selected{% endif %}>{{ farmer.fullname }} — {{ farmer.phone }}</option>{% endfor %}\n                </select>\n                {% if selected_membership %}<input type="hidden" name="farmer_id" value="{{ selected_membership.farmer_id }}">{% endif %}\n'''
    new = '''                <label for="farmer_id">Member / Farmer *</label>\n                <select id="farmer_id" name="farmer_id" required {% if selected_membership %}disabled style="background:#f7f9f8"{% endif %}>\n                    <option value="">{% if farmers %}Select person with amount still due{% else %}No outstanding members{% endif %}</option>\n                    {% for farmer in farmers %}<option value="{{ farmer.id }}" {% if selected_membership and selected_membership.farmer_id == farmer.id %}selected{% endif %}>{{ farmer.fullname }} — {{ farmer.phone }}</option>{% endfor %}\n                </select>\n                <span class="help">Members whose required contribution is fully confirmed, or fully covered by a pending record, are removed from this action list automatically.</span>\n                {% if selected_membership %}<input type="hidden" name="farmer_id" value="{{ selected_membership.farmer_id }}">{% endif %}\n'''
    if replace_once(contribution_template, old, new, "contribution form actionable note"):
        changed.append("templates/contribution_form.html")

    joint_path = ROOT / "joint_operations.py"
    old = '''    @property\n    def outstanding_amount(self):\n        return max(float(self.expected_amount or 0) - self.confirmed_paid, 0.0)\n'''
    new = '''    @property\n    def outstanding_amount(self):\n        return max(float(self.expected_amount or 0) - self.confirmed_paid, 0.0)\n\n    @property\n    def recordable_amount(self):\n        """Amount still safe for the Treasurer to record after confirmed and pending receipts."""\n        return max(float(self.expected_amount or 0) - self.confirmed_paid - self.pending_paid, 0.0)\n'''
    if replace_once(joint_path, old, new, "secondary contribution recordable amount"):
        changed.append("joint_operations.py")

    old = '''    if amount <= 0:\n        return "Payment amount must be greater than zero.", 400\n    item = PrimaryContributionPayment(\n'''
    new = '''    if amount <= 0:\n        return "Payment amount must be greater than zero.", 400\n    available = account.recordable_amount\n    if available <= 1e-9:\n        return "This Primary cooperative has no contribution amount left to record for this year.", 400\n    if amount > available + 1e-9:\n        return f"Payment exceeds the amount still available to record. Maximum: R {available:.2f}.", 400\n    item = PrimaryContributionPayment(\n'''
    if replace_once(joint_path, old, new, "secondary contribution completed guard"):
        if "joint_operations.py" not in changed:
            changed.append("joint_operations.py")

    joint_template = ROOT / "templates" / "joint_operations" / "dashboard.html"
    old = '''<td>R {{ "{:,.2f}".format(account.outstanding_amount|float) }}</td><td>{% if can_finance_record %}<details><summary class="p7-btn">Record Payment</summary><form class="p7-form" method="POST" action="{{ url_for('jointops.contribution_payment_add', account_id=account.id) }}" style="margin-top:8px;min-width:300px"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><div class="p7-field"><label>Amount (R)</label><input name="amount" type="number" min="0.01" step="0.01" required></div>'''
    new = '''<td>R {{ "{:,.2f}".format(account.outstanding_amount|float) }}</td><td>{% if can_finance_record and account.recordable_amount > 0 %}<details><summary class="p7-btn">Record Payment</summary><form class="p7-form" method="POST" action="{{ url_for('jointops.contribution_payment_add', account_id=account.id) }}" style="margin-top:8px;min-width:300px"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><div class="p7-field"><label>Amount (R)</label><input name="amount" type="number" min="0.01" max="{{ '%.2f'|format(account.recordable_amount) }}" value="{{ '%.2f'|format(account.recordable_amount) }}" step="0.01" required></div>'''
    if replace_once(joint_template, old, new, "secondary contribution actionable payment"):
        changed.append("templates/joint_operations/dashboard.html")

    old = '''<div class="p7-field full"><button class="p7-btn primary" type="submit">Submit for Chairperson Confirmation</button></div></form></details>{% else %}—{% endif %}</td></tr>'''
    new = '''<div class="p7-field full"><button class="p7-btn primary" type="submit">Submit for Chairperson Confirmation</button></div></form></details>{% elif can_finance_record %}<span class="p7-badge good">Complete / already pending</span>{% else %}—{% endif %}</td></tr>'''
    if replace_once(joint_template, old, new, "secondary contribution completed label"):
        if "templates/joint_operations/dashboard.html" not in changed:
            changed.append("templates/joint_operations/dashboard.html")

    prod_path = ROOT / "primary_production.py"
    old = '''    plans = ProductionPlan.query.filter_by(cooperative_id=cooperative.id).order_by(ProductionPlan.updated_at.desc()).all()\n    activities = ProductionActivity.query.filter_by(cooperative_id=cooperative.id).order_by(\n'''
    new = '''    plans = ProductionPlan.query.filter_by(cooperative_id=cooperative.id).order_by(ProductionPlan.updated_at.desc()).all()\n    plan_by_crop = {plan.crop_id: plan for plan in plans}\n    plan_crops = [\n        crop for crop in crops\n        if crop.status not in {"Harvested", "Failed"}\n        and (crop.id not in plan_by_crop or plan_by_crop[crop.id].status in {"Rejected"})\n    ]\n    active_crops = [crop for crop in crops if crop.status not in {"Harvested", "Failed"}]\n    actionable_plans = [plan for plan in plans if plan.status == "Approved"]\n    activities = ProductionActivity.query.filter_by(cooperative_id=cooperative.id).order_by(\n'''
    if replace_once(prod_path, old, new, "production actionable collections"):
        changed.append("primary_production.py")

    old = '''        rows=rows, plans=plans, activities=activities, equipment_logs=equipment_logs,\n        crops=crops, inventory=inventory, equipment=equipment, users=users, stats=stats,\n'''
    new = '''        rows=rows, plans=plans, activities=activities, equipment_logs=equipment_logs,\n        crops=crops, plan_crops=plan_crops, active_crops=active_crops, actionable_plans=actionable_plans,\n        inventory=inventory, equipment=equipment, users=users, stats=stats,\n'''
    if replace_once(prod_path, old, new, "production actionable template context"):
        if "primary_production.py" not in changed:
            changed.append("primary_production.py")

    old = '''    if plan.status == "Approved":\n        return "Approved production plans must be returned/revised through a new approval cycle.", 400\n'''
    new = '''    if plan.status in {"Approved", "Completed"}:\n        return "Approved or completed production plans are no longer available for routine resubmission.", 400\n'''
    if replace_once(prod_path, old, new, "production completed plan guard"):
        if "primary_production.py" not in changed:
            changed.append("primary_production.py")

    old = '''    if not plan or plan.status not in {"Approved", "Completed"}:\n        return "Choose an approved production plan.", 400\n'''
    new = '''    if not plan or plan.status != "Approved":\n        return "Choose an active approved production plan.", 400\n'''
    if replace_once(prod_path, old, new, "production completed activity guard"):
        if "primary_production.py" not in changed:
            changed.append("primary_production.py")

    prod_template = ROOT / "templates" / "primary_production" / "dashboard.html"
    replacements = [
        ('''{% for c in crops %}<option value="{{ c.id }}">{{ c.name }} · {{ c.farm.name if c.farm else 'Farm' }}</option>{% endfor %}''', '''{% for c in plan_crops %}<option value="{{ c.id }}">{{ c.name }} · {{ c.farm.name if c.farm else 'Farm' }}</option>{% endfor %}''', "production plan crop options"),
        ('''{% for p in plans if p.status in ['Approved','Completed'] %}<option value="{{ p.id }}">{{ p.crop.name }} · {{ p.crop.farm.name if p.crop and p.crop.farm else 'Farm' }}</option>{% endfor %}''', '''{% for p in actionable_plans %}<option value="{{ p.id }}">{{ p.crop.name }} · {{ p.crop.farm.name if p.crop and p.crop.farm else 'Farm' }}</option>{% endfor %}''', "production activity plan options"),
    ]
    for old_t, new_t, label in replacements:
        if replace_once(prod_template, old_t, new_t, label):
            if "templates/primary_production/dashboard.html" not in changed:
                changed.append("templates/primary_production/dashboard.html")

    # Replace the two remaining crop selects (input usage and equipment usage) with active crops.
    text = prod_template.read_text(encoding="utf-8")
    old_loop = '''{% for c in crops %}<option value="{{ c.id }}">{{ c.name }} · {{ c.farm.name if c.farm else 'Farm' }}</option>{% endfor %}'''
    if old_loop in text:
        text = text.replace(old_loop, '''{% for c in active_crops %}<option value="{{ c.id }}">{{ c.name }} · {{ c.farm.name if c.farm else 'Farm' }}</option>{% endfor %}''')
        prod_template.write_text(text, encoding="utf-8")
        if "templates/primary_production/dashboard.html" not in changed:
            changed.append("templates/primary_production/dashboard.html")

    runner = ROOT / "run_regression_tests.py"
    old = '''    "joint_operations_regression_tests.py",\n]'''
    new = '''    "joint_operations_regression_tests.py",\n    "actionable_options_regression_tests.py",\n]'''
    if replace_once(runner, old, new, "regression runner"):
        changed.append("run_regression_tests.py")

    print("Updated: " + ", ".join(changed))


if __name__ == "__main__":
    main()
