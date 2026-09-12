from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path, old, new, label):
    text = path.read_text(encoding="utf-8")
    if new in text:
        return False
    if old not in text:
        raise RuntimeError(f"Missing integration anchor for {label} in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return True


def replace_all(path, old, new, label, expected_min=1):
    text = path.read_text(encoding="utf-8")
    if old not in text:
        if new in text:
            return False
        raise RuntimeError(f"Missing integration anchor for {label} in {path}")
    count = text.count(old)
    if count < expected_min:
        raise RuntimeError(f"Expected at least {expected_min} anchors for {label}, found {count}")
    path.write_text(text.replace(old, new), encoding="utf-8")
    return True


def patch_app():
    path = ROOT / "app.py"
    changed = False

    old = '''def sale_recorded_payment_amount(sale, exclude_payment_id=None):
    """Calculate total recorded payment amount for a sale (including pending)."""
    total = 0.0
    for payment in sale.payments:
        if exclude_payment_id and payment.id == exclude_payment_id:
            continue
        if payment.status == "Reversed":
            continue
        total += float(payment.amount or 0)
    return total


def sale_outstanding_amount(sale):
'''
    new = '''def sale_recorded_payment_amount(sale, exclude_payment_id=None):
    """Calculate total recorded payment amount for a sale (including pending)."""
    total = 0.0
    for payment in sale.payments:
        if exclude_payment_id and payment.id == exclude_payment_id:
            continue
        if payment.status == "Reversed":
            continue
        total += float(payment.amount or 0)
    return total


def sale_recording_remaining_amount(sale, exclude_payment_id=None):
    """Amount still eligible for a new payment record, including pending receipts."""
    return max(
        float(sale.total_amount or 0) - float(sale_recorded_payment_amount(sale, exclude_payment_id=exclude_payment_id) or 0),
        0.0,
    )


def sale_outstanding_amount(sale):
'''
    changed |= replace_once(path, old, new, "sale recordable balance helper")

    old = '''def harvest_available_quantity(harvest, exclude_sale_id=None):
    """Calculate available quantity from a harvest."""
    harvested = float(harvest.quantity or 0)
    sold = harvest_sold_quantity(harvest, exclude_sale_id=exclude_sale_id)
    return max(harvested - sold, 0.0)


def crop_harvest_count(crop_id, exclude_harvest_id=None):
'''
    new = '''def harvest_available_quantity(harvest, exclude_sale_id=None):
    """Calculate available quantity from a harvest."""
    harvested = float(harvest.quantity or 0)
    sold = harvest_sold_quantity(harvest, exclude_sale_id=exclude_sale_id)
    return max(harvested - sold, 0.0)


def sync_harvest_status_after_sale_change(harvest):
    """Keep sale eligibility aligned with the quantity still available."""
    if not harvest or harvest.status == "Spoiled":
        return
    if harvest_available_quantity(harvest) <= 1e-9:
        harvest.status = "Sold"
    elif harvest.status == "Sold":
        harvest.status = "Available"


def crop_harvest_count(crop_id, exclude_harvest_id=None):
'''
    changed |= replace_once(path, old, new, "harvest completion sync helper")

    old = '''def add_membership():
    """Primary Secretary/Vice Secretary registers an individual member."""
    access = current_access()
    cooperative = current_cooperative()
    if not cooperative or cooperative.cooperative_type != "Primary":
        abort(403)

    farmers = own_cooperative_query(Farmer).order_by(Farmer.fullname.asc()).all()

    if request.method == "POST":
'''
    new = '''def add_membership():
    """Primary Secretary/Vice Secretary registers an individual member."""
    access = current_access()
    cooperative = current_cooperative()
    if not cooperative or cooperative.cooperative_type != "Primary":
        abort(403)

    registered_farmer_ids = db.session.query(Membership.farmer_id).filter(
        Membership.cooperative_id == access.cooperative_id
    )
    farmers = own_cooperative_query(Farmer).filter(
        ~Farmer.id.in_(registered_farmer_ids)
    ).order_by(Farmer.fullname.asc()).all()

    if request.method == "POST":
'''
    changed |= replace_once(path, old, new, "membership create eligibility")

    old = '''def add_harvest():
    """Add a harvest."""
    crops = own_cooperative_query(Crop).order_by(Crop.name.asc()).all()

    if request.method == "POST":
'''
    new = '''def add_harvest():
    """Add a harvest."""
    crops = own_cooperative_query(Crop).filter(
        Crop.status.notin_(["Harvested", "Failed"])
    ).order_by(Crop.name.asc()).all()

    if request.method == "POST":
'''
    changed |= replace_once(path, old, new, "harvest source eligibility")

    old = '''        if crop.status == "Failed":
            return "A failed crop cannot receive a harvest record. Update the crop status first if harvesting is possible.", 400

        if crop.planting_date and harvest_date_value < crop.planting_date:
'''
    new = '''        if crop.status == "Failed":
            return "A failed crop cannot receive a harvest record. Update the crop status first if harvesting is possible.", 400
        if crop.status == "Harvested":
            return "This crop is already marked as fully harvested and is no longer eligible for another harvest record.", 400

        if crop.planting_date and harvest_date_value < crop.planting_date:
'''
    changed |= replace_once(path, old, new, "harvest completed crop guard")

    old = '''def add_sale():
    """Add a sale."""
    harvests = own_cooperative_query(Harvest).order_by(Harvest.harvest_date.desc()).all()

    if request.method == "POST":
'''
    new = '''def add_sale():
    """Add a sale."""
    harvests = [
        harvest for harvest in own_cooperative_query(Harvest).order_by(Harvest.harvest_date.desc()).all()
        if harvest.status not in {"Sold", "Spoiled"} and harvest_available_quantity(harvest) > 1e-9
    ]

    if request.method == "POST":
'''
    changed |= replace_once(path, old, new, "sale source eligibility")

    old = '''        if not harvest or harvest.cooperative_id != own_cooperative_id():
            return "Please select a harvest from your own cooperative.", 400

        if quantity_value <= 0:
'''
    new = '''        if not harvest or harvest.cooperative_id != own_cooperative_id():
            return "Please select a harvest from your own cooperative.", 400
        if harvest.status in {"Sold", "Spoiled"}:
            return "This harvest is already closed for new sales.", 400

        if quantity_value <= 0:
'''
    changed |= replace_once(path, old, new, "sale completed harvest guard")

    old = '''        db.session.add(new_sale)
        db.session.flush()
        add_audit_log("CREATE", "Sale", new_sale.id, new_sale.buyer_name, cooperative_id=new_sale.cooperative_id)
'''
    new = '''        db.session.add(new_sale)
        db.session.flush()
        sync_harvest_status_after_sale_change(harvest)
        add_audit_log("CREATE", "Sale", new_sale.id, new_sale.buyer_name, cooperative_id=new_sale.cooperative_id)
'''
    changed |= replace_once(path, old, new, "sale creation harvest sync")

    old = '''        sale.harvest_id = harvest.id
        sale.cooperative_id = own_cooperative_id()
        sale.buyer_name = buyer_name
'''
    new = '''        old_harvest = sale.harvest
        sale.harvest_id = harvest.id
        sale.cooperative_id = own_cooperative_id()
        sale.buyer_name = buyer_name
'''
    changed |= replace_once(path, old, new, "sale edit old harvest capture")

    old = '''        sale.status = status
        sale.notes = notes or None
        add_audit_log("UPDATE", "Sale", sale.id, sale.buyer_name, cooperative_id=sale.cooperative_id)
'''
    new = '''        sale.status = status
        sale.notes = notes or None
        db.session.flush()
        sync_harvest_status_after_sale_change(harvest)
        if old_harvest and old_harvest.id != harvest.id:
            sync_harvest_status_after_sale_change(old_harvest)
        add_audit_log("UPDATE", "Sale", sale.id, sale.buyer_name, cooperative_id=sale.cooperative_id)
'''
    changed |= replace_once(path, old, new, "sale edit harvest sync")

    old = '''    if sale.payments:
        return "This sale cannot be deleted because payments are linked to it.", 400
    add_audit_log("DELETE", "Sale", sale.id, sale.buyer_name, cooperative_id=sale.cooperative_id)
    db.session.delete(sale)
    db.session.commit()
'''
    new = '''    if sale.payments:
        return "This sale cannot be deleted because payments are linked to it.", 400
    harvest = sale.harvest
    add_audit_log("DELETE", "Sale", sale.id, sale.buyer_name, cooperative_id=sale.cooperative_id)
    db.session.delete(sale)
    db.session.flush()
    sync_harvest_status_after_sale_change(harvest)
    db.session.commit()
'''
    changed |= replace_once(path, old, new, "sale delete harvest sync")

    old = '''def add_payment():
    """Add a payment."""
    sales = own_cooperative_query(Sale).order_by(Sale.sale_date.desc()).all()

    if request.method == "POST":
'''
    new = '''def add_payment():
    """Add a payment."""
    sales = [
        sale for sale in own_cooperative_query(Sale).order_by(Sale.sale_date.desc()).all()
        if sale.status != "Cancelled" and sale_recording_remaining_amount(sale) > 1e-9
    ]

    if request.method == "POST":
'''
    changed |= replace_once(path, old, new, "payment source eligibility")

    old = '''def add_contribution():
    """Treasurer records money; membership-fee money is linked to the exact member record."""
    access = current_access()
    if access and access.role.startswith("Secondary"):
        return redirect(url_for("jointops.dashboard", year=crm_today().year, _anchor="primary-contributions"))
    farmers = own_cooperative_query(Farmer).order_by(Farmer.fullname.asc()).all()
    selected_membership = None

    requested_membership_id = parse_int(request.args.get("membership_id"))
    if requested_membership_id:
        candidate = scoped_get(Membership, requested_membership_id)
        if candidate and candidate.cooperative_id == access.cooperative_id:
            selected_membership = candidate
'''
    new = '''def add_contribution():
    """Treasurer records money; completed member obligations stay out of the action list."""
    access = current_access()
    if access and access.role.startswith("Secondary"):
        return redirect(url_for("jointops.dashboard", year=crm_today().year, _anchor="primary-contributions"))

    eligible_memberships = Membership.query.filter(
        Membership.cooperative_id == access.cooperative_id,
        Membership.status.notin_(["Resigned", "Deceased", "Inactive"]),
    ).all()
    eligible_farmer_ids = [
        membership.farmer_id for membership in eligible_memberships
        if membership.fee_outstanding > 1e-9
    ]
    farmers = own_cooperative_query(Farmer).filter(
        Farmer.id.in_(eligible_farmer_ids or [-1])
    ).order_by(Farmer.fullname.asc()).all()
    selected_membership = None

    requested_membership_id = parse_int(request.args.get("membership_id"))
    if requested_membership_id:
        candidate = scoped_get(Membership, requested_membership_id)
        if (
            candidate
            and candidate.cooperative_id == access.cooperative_id
            and candidate.status not in {"Resigned", "Deceased", "Inactive"}
            and candidate.fee_outstanding > 1e-9
        ):
            selected_membership = candidate
'''
    changed |= replace_once(path, old, new, "contribution member eligibility")

    return changed


def patch_joint_operations():
    path = ROOT / "joint_operations.py"
    changed = False

    old = '''    @property
    def outstanding_amount(self):
        return max(float(self.expected_amount or 0) - self.confirmed_paid, 0.0)


class PrimaryContributionPayment(db.Model):
'''
    new = '''    @property
    def outstanding_amount(self):
        return max(float(self.expected_amount or 0) - self.confirmed_paid, 0.0)

    @property
    def recordable_amount(self):
        """Amount still available for a new Treasurer entry after confirmed + pending money."""
        return max(float(self.expected_amount or 0) - self.confirmed_paid - self.pending_paid, 0.0)


class PrimaryContributionPayment(db.Model):
'''
    changed |= replace_once(path, old, new, "joint contribution recordable amount")

    old = '''    if amount <= 0:
        return "Payment amount must be greater than zero.", 400
    item = PrimaryContributionPayment(
'''
    new = '''    if amount <= 0:
        return "Payment amount must be greater than zero.", 400
    available = account.recordable_amount
    if available <= 1e-9:
        return "This Primary cooperative has no outstanding contribution action for this account.", 400
    if amount > available + 1e-9:
        return f"Contribution exceeds the amount still available to record. Maximum: R {available:.2f}.", 400
    item = PrimaryContributionPayment(
'''
    changed |= replace_once(path, old, new, "joint contribution completed guard")

    return changed


def patch_primary_production():
    path = ROOT / "primary_production.py"
    changed = False

    old = '''    plans = ProductionPlan.query.filter_by(cooperative_id=cooperative.id).order_by(ProductionPlan.updated_at.desc()).all()
    activities = ProductionActivity.query.filter_by(cooperative_id=cooperative.id).order_by(
'''
    new = '''    plans = ProductionPlan.query.filter_by(cooperative_id=cooperative.id).order_by(ProductionPlan.updated_at.desc()).all()
    active_crops = [crop for crop in crops if crop.status not in {"Harvested", "Failed"}]
    plan_by_crop = {plan.crop_id: plan for plan in plans}
    plan_crops = [
        crop for crop in active_crops
        if crop.id not in plan_by_crop or plan_by_crop[crop.id].status == "Rejected"
    ]
    activities = ProductionActivity.query.filter_by(cooperative_id=cooperative.id).order_by(
'''
    changed |= replace_once(path, old, new, "production actionable crop lists")

    old = '''        rows=rows, plans=plans, activities=activities, equipment_logs=equipment_logs,
        crops=crops, inventory=inventory, equipment=equipment, users=users, stats=stats,
'''
    new = '''        rows=rows, plans=plans, activities=activities, equipment_logs=equipment_logs,
        crops=crops, active_crops=active_crops, plan_crops=plan_crops,
        inventory=inventory, equipment=equipment, users=users, stats=stats,
'''
    changed |= replace_once(path, old, new, "production template action lists")

    old = '''    if not crop:
        return "Choose a crop from your Primary cooperative.", 400
    try:
'''
    new = '''    if not crop:
        return "Choose a crop from your Primary cooperative.", 400
    if crop.status in {"Harvested", "Failed"}:
        return "This crop is closed and is no longer eligible for a production plan action.", 400
    try:
'''
    changed |= replace_once(path, old, new, "production plan closed crop guard")

    old = '''    if plan.status == "Approved":
        return "Approved production plans must be returned/revised through a new approval cycle.", 400
'''
    new = '''    if plan.status in {"Pending Approval", "Approved", "Completed"}:
        return "This production plan already has an active or completed workflow and is no longer available in the create/revise list.", 400
'''
    changed |= replace_once(path, old, new, "production plan completed guard")

    old = '''    if not plan or plan.status not in {"Approved", "Completed"}:
        return "Choose an approved production plan.", 400
'''
    new = '''    if not plan or plan.status != "Approved":
        return "Choose an approved production plan that is still active.", 400
'''
    changed |= replace_once(path, old, new, "production activity active plan guard")

    old = '''    if not crop:
        return "Choose a crop from your Primary cooperative.", 400
    description = request.form.get("description", "").strip()
'''
    new = '''    if not crop:
        return "Choose a crop from your Primary cooperative.", 400
    if crop.status in {"Harvested", "Failed"}:
        return "This crop is closed and cannot receive new production input usage.", 400
    description = request.form.get("description", "").strip()
'''
    changed |= replace_once(path, old, new, "production input closed crop guard")

    old = '''    if not crop or not equipment or not crop.farm or crop.farm.cooperative_id != cooperative.id:
        return "Crop and equipment must belong to your Primary cooperative.", 400
    purpose = request.form.get("purpose", "").strip()
'''
    new = '''    if not crop or not equipment or not crop.farm or crop.farm.cooperative_id != cooperative.id:
        return "Crop and equipment must belong to your Primary cooperative.", 400
    if crop.status in {"Harvested", "Failed"}:
        return "This crop is closed and cannot receive new equipment usage records.", 400
    purpose = request.form.get("purpose", "").strip()
'''
    changed |= replace_once(path, old, new, "production equipment closed crop guard")

    return changed


def patch_templates():
    changed = False

    path = ROOT / "templates" / "contribution_form.html"
    old = '''                <label for="farmer_id">Member / Farmer *</label>
                <select id="farmer_id" name="farmer_id" required {% if selected_membership %}disabled style="background:#f7f9f8"{% endif %}>
                    <option value="">Select person</option>
'''
    new = '''                <label for="farmer_id">Member with Outstanding Contribution *</label>
                <select id="farmer_id" name="farmer_id" required {% if selected_membership %}disabled style="background:#f7f9f8"{% endif %}>
                    <option value="">{% if farmers %}Select person{% else %}No outstanding members{% endif %}</option>
'''
    changed |= replace_once(path, old, new, "contribution empty action list")

    path = ROOT / "templates" / "payment_form.html"
    old = '<option value="">Select sale</option>'
    new = '<option value="">{% if sales %}Select sale{% else %}No sales with an outstanding payment action{% endif %}</option>'
    changed |= replace_once(path, old, new, "payment empty action list")

    path = ROOT / "templates" / "primary_production" / "dashboard.html"
    text = path.read_text(encoding="utf-8")
    replacements = [
        ("{% for c in crops %}<option value=\"{{ c.id }}\">{{ c.name }} · {{ c.farm.name if c.farm else 'Farm' }}</option>{% endfor %}",
         "{% for c in plan_crops %}<option value=\"{{ c.id }}\">{{ c.name }} · {{ c.farm.name if c.farm else 'Farm' }}</option>{% endfor %}", 1),
        ("{% for p in plans if p.status in ['Approved','Completed'] %}", "{% for p in plans if p.status == 'Approved' %}", 1),
    ]
    for old_text, new_text, count in replacements:
        if new_text not in text:
            if text.count(old_text) < count:
                raise RuntimeError(f"Missing production template anchor: {old_text[:60]}")
            text = text.replace(old_text, new_text, count)
            changed = True
    old_crop_loop = "{% for c in crops %}<option value=\"{{ c.id }}\">{{ c.name }} · {{ c.farm.name if c.farm else 'Farm' }}</option>{% endfor %}"
    new_crop_loop = "{% for c in active_crops %}<option value=\"{{ c.id }}\">{{ c.name }} · {{ c.farm.name if c.farm else 'Farm' }}</option>{% endfor %}"
    if old_crop_loop in text:
        text = text.replace(old_crop_loop, new_crop_loop)
        changed = True
    path.write_text(text, encoding="utf-8")

    path = ROOT / "templates" / "joint_operations" / "dashboard.html"
    old = '''<td>R {{ "{:,.2f}".format(account.outstanding_amount|float) }}</td><td>{% if can_finance_record %}<details><summary class="p7-btn">Record Payment</summary><form class="p7-form" method="POST" action="{{ url_for('jointops.contribution_payment_add', account_id=account.id) }}" style="margin-top:8px;min-width:300px"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><div class="p7-field"><label>Amount (R)</label><input name="amount" type="number" min="0.01" step="0.01" required></div><div class="p7-field"><label>Date</label><input name="payment_date" type="date" required></div><div class="p7-field"><label>Method</label><input name="method" placeholder="Bank / Cash"></div><div class="p7-field"><label>Reference</label><input name="reference"></div><div class="p7-field full"><label>Notes</label><textarea name="notes"></textarea></div><div class="p7-field full"><button class="p7-btn primary" type="submit">Submit for Chairperson Confirmation</button></div></form></details>{% else %}—{% endif %}</td>'''
    new = '''<td>R {{ "{:,.2f}".format(account.outstanding_amount|float) }}</td><td>{% if can_finance_record and account.recordable_amount > 0 %}<details><summary class="p7-btn">Record Payment</summary><form class="p7-form" method="POST" action="{{ url_for('jointops.contribution_payment_add', account_id=account.id) }}" style="margin-top:8px;min-width:300px"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><div class="p7-field"><label>Amount (R)</label><input name="amount" type="number" min="0.01" max="{{ '%.2f'|format(account.recordable_amount) }}" step="0.01" required></div><div class="p7-field"><label>Date</label><input name="payment_date" type="date" required></div><div class="p7-field"><label>Method</label><input name="method" placeholder="Bank / Cash"></div><div class="p7-field"><label>Reference</label><input name="reference"></div><div class="p7-field full"><label>Notes</label><textarea name="notes"></textarea></div><div class="p7-field full"><button class="p7-btn primary" type="submit">Submit for Chairperson Confirmation</button></div></form></details>{% elif account.recordable_amount <= 0 %}<span class="p7-badge good">No action due</span>{% else %}—{% endif %}</td>'''
    changed |= replace_once(path, old, new, "joint contribution action visibility")

    return changed


def patch_runner():
    path = ROOT / "run_regression_tests.py"
    old = '    "primary_production_regression_tests.py",\n]'
    new = '    "primary_production_regression_tests.py",\n    "outstanding_action_regression_tests.py",\n]'
    return replace_once(path, old, new, "regression runner")


def main():
    changed = []
    if patch_app(): changed.append("app.py")
    if patch_joint_operations(): changed.append("joint_operations.py")
    if patch_primary_production(): changed.append("primary_production.py")
    if patch_templates(): changed.append("templates")
    if patch_runner(): changed.append("run_regression_tests.py")
    print("Updated: " + (", ".join(changed) if changed else "nothing; already integrated"))


if __name__ == "__main__":
    main()
