from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str, label: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return False
    if old not in text:
        raise RuntimeError(f"Missing anchor for {label} in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return True


def patch_app() -> bool:
    path = ROOT / "app.py"
    changed = False

    changed |= replace_once(
        path,
        'MEMBERSHIP_FEE_CATEGORY = "Membership Fee"\nMEMBERSHIP_FEE_CATEGORY_ALIASES = {"membership fee", "membership"}\n',
        'MEMBERSHIP_FEE_CATEGORY = "Membership Fee"\nMEMBERSHIP_FEE_CATEGORY_ALIASES = {"membership fee", "membership"}\nMEMBER_CREDIT_CATEGORY = "Member Credit"\nMEMBER_CREDIT_CATEGORY_ALIASES = {"member credit", "membership credit", "credit"}\n',
        "member credit constants",
    )

    old = '''    @property
    def fee_status(self):
        expected = float(self.fee_amount or 0)
        confirmed = float(self.fee_paid or 0)
        pending = float(self.fee_pending or 0)
'''
    new = '''    @property
    def fee_credit_confirmed(self):
        """Confirmed money received above the required membership fee."""
        explicit_credit = sum(
            float(contribution.amount or 0)
            for contribution in self.contributions
            if contribution.status == "Confirmed"
            and (contribution.category or "").strip().casefold() in MEMBER_CREDIT_CATEGORY_ALIASES
        )
        legacy_credit = max(float(self.fee_paid or 0) - float(self.fee_amount or 0), 0.0)
        return explicit_credit + legacy_credit

    @property
    def fee_credit_pending(self):
        """Overpayment recorded by the Treasurer and awaiting confirmation."""
        return sum(
            float(contribution.amount or 0)
            for contribution in self.contributions
            if contribution.status == "Pending Confirmation"
            and (contribution.category or "").strip().casefold() in MEMBER_CREDIT_CATEGORY_ALIASES
        )

    @property
    def fee_credit(self):
        return self.fee_credit_confirmed + self.fee_credit_pending

    @property
    def fee_paid_applied(self):
        """Confirmed membership money actually allocated to the required fee."""
        return min(float(self.fee_paid or 0), float(self.fee_amount or 0))

    @property
    def fee_status(self):
        expected = float(self.fee_amount or 0)
        confirmed = float(self.fee_paid or 0)
        pending = float(self.fee_pending or 0)
'''
    changed |= replace_once(path, old, new, "membership credit properties")

    old = '''            available = linked_membership.fee_outstanding
            if amount > available + 1e-9:
                return f"Membership-fee contribution exceeds the amount still due. Maximum: R {available:.2f}.", 400

        contribution = Contribution(
            cooperative_id=access.cooperative_id,
            farmer_id=farmer.id,
            membership_id=linked_membership.id if linked_membership else None,
            amount=amount,
            contribution_date=contribution_date,
            category=category,
            method=request.form.get("method", "").strip() or None,
            reference=request.form.get("reference", "").strip() or None,
            status="Pending Confirmation",
            notes=request.form.get("notes", "").strip() or None,
        )
        db.session.add(contribution)
        db.session.flush()
        if linked_membership:
            record_membership_history(
                linked_membership,
                "FEE_RECORDED",
                description=f"Treasurer recorded R{amount:.2f} membership fee; pending Chairperson confirmation.",
                from_status=linked_membership.status,
                to_status=linked_membership.status,
            )
        add_audit_log(
            "FINANCE_RECORDED",
            "Contribution",
            contribution.id,
            f"{farmer.fullname} - R{amount:.2f} - {category or 'Contribution'} - pending Chairperson confirmation",
            cooperative_id=contribution.cooperative_id,
        )
        db.session.commit()
        return redirect(url_for("contributions_list"))
'''
    new = '''            available = linked_membership.fee_outstanding

        method = request.form.get("method", "").strip() or None
        reference = request.form.get("reference", "").strip() or None
        notes = request.form.get("notes", "").strip() or None

        fee_allocation = amount
        credit_allocation = 0.0
        if linked_membership:
            fee_allocation = min(amount, float(linked_membership.fee_outstanding or 0))
            credit_allocation = max(amount - fee_allocation, 0.0)

        created = []
        if fee_allocation > 1e-9:
            contribution = Contribution(
                cooperative_id=access.cooperative_id,
                farmer_id=farmer.id,
                membership_id=linked_membership.id if linked_membership else None,
                amount=fee_allocation,
                contribution_date=contribution_date,
                category=category,
                method=method,
                reference=reference,
                status="Pending Confirmation",
                notes=notes,
            )
            db.session.add(contribution)
            db.session.flush()
            created.append(contribution)
            add_audit_log(
                "FINANCE_RECORDED", "Contribution", contribution.id,
                f"{farmer.fullname} - R{fee_allocation:.2f} - {category or 'Contribution'} - pending Chairperson confirmation",
                cooperative_id=contribution.cooperative_id,
            )

        credit_contribution = None
        if linked_membership and credit_allocation > 1e-9:
            credit_contribution = Contribution(
                cooperative_id=access.cooperative_id,
                farmer_id=farmer.id,
                membership_id=linked_membership.id,
                amount=credit_allocation,
                contribution_date=contribution_date,
                category=MEMBER_CREDIT_CATEGORY,
                method=method,
                reference=reference,
                status="Pending Confirmation",
                notes=(f"Unallocated member credit from R{amount:.2f} receipt. " + (notes or "")).strip(),
            )
            db.session.add(credit_contribution)
            db.session.flush()
            created.append(credit_contribution)
            add_audit_log(
                "MEMBER_CREDIT_RECORDED", "Contribution", credit_contribution.id,
                f"{farmer.fullname} - R{credit_allocation:.2f} unallocated member credit - pending Chairperson confirmation",
                cooperative_id=credit_contribution.cooperative_id,
            )

        if not created:
            return "No amount was available to record.", 400

        if linked_membership:
            description = f"Treasurer recorded R{amount:.2f}. R{fee_allocation:.2f} allocated to membership fee"
            if credit_allocation > 1e-9:
                description += f" and R{credit_allocation:.2f} recorded as unallocated member credit"
            description += "; pending Chairperson confirmation."
            record_membership_history(
                linked_membership,
                "FEE_RECORDED",
                description=description,
                from_status=linked_membership.status,
                to_status=linked_membership.status,
            )

        db.session.commit()
        return redirect(url_for("contributions_list"))
'''
    changed |= replace_once(path, old, new, "split membership overpayment into fee and credit")

    old = '''        if linked_membership:
            record_membership_history(
                linked_membership,
                "FEE_REJECTED",
                description=f"Chairperson rejected R{float(contribution.amount or 0):.2f} membership-fee record.",
                from_status=linked_membership.status,
                to_status=linked_membership.status,
            )
'''
    new = '''        if linked_membership and (contribution.category or "").strip().casefold() in MEMBERSHIP_FEE_CATEGORY_ALIASES:
            record_membership_history(
                linked_membership,
                "FEE_REJECTED",
                description=f"Chairperson rejected R{float(contribution.amount or 0):.2f} membership-fee record.",
                from_status=linked_membership.status,
                to_status=linked_membership.status,
            )
'''
    changed |= replace_once(path, old, new, "credit rejection history separation")

    old = '''    linked_membership = contribution.membership
    if linked_membership:
        record_membership_history(
            linked_membership,
            "FEE_RECORD_REMOVED",
            description=f"Treasurer removed unconfirmed/rejected R{float(contribution.amount or 0):.2f} membership-fee record.",
            from_status=linked_membership.status,
            to_status=linked_membership.status,
        )
'''
    new = '''    linked_membership = contribution.membership
    if linked_membership and (contribution.category or "").strip().casefold() in MEMBERSHIP_FEE_CATEGORY_ALIASES:
        record_membership_history(
            linked_membership,
            "FEE_RECORD_REMOVED",
            description=f"Treasurer removed unconfirmed/rejected R{float(contribution.amount or 0):.2f} membership-fee record.",
            from_status=linked_membership.status,
            to_status=linked_membership.status,
        )
'''
    changed |= replace_once(path, old, new, "credit deletion history separation")

    old = '''    total_paid = sum(float(m.fee_paid or 0) for m in fee_memberships)
    total_pending = sum(float(m.fee_pending or 0) for m in fee_memberships)
    total_outstanding = sum(float(m.fee_outstanding or 0) for m in fee_memberships)
'''
    new = '''    total_paid = sum(float(m.fee_paid_applied or 0) for m in fee_memberships)
    total_pending = sum(float(m.fee_pending or 0) for m in fee_memberships)
    total_outstanding = sum(float(m.fee_outstanding or 0) for m in fee_memberships)
    total_credit = sum(float(m.fee_credit_confirmed or 0) for m in fee_memberships)
    total_credit_pending = sum(float(m.fee_credit_pending or 0) for m in fee_memberships)
'''
    changed |= replace_once(path, old, new, "membership totals credit")

    changed |= replace_once(
        path,
        '''        total_pending=total_pending,\n        total_outstanding=total_outstanding,\n    )\n''',
        '''        total_pending=total_pending,\n        total_outstanding=total_outstanding,\n        total_credit=total_credit,\n        total_credit_pending=total_credit_pending,\n    )\n''',
        "membership credit template context",
    )

    return changed


def patch_contribution_form() -> bool:
    path = ROOT / "templates" / "contribution_form.html"
    changed = False
    changed |= replace_once(
        path,
        'Expected: R {{ "{:,.2f}".format(selected_membership.fee_amount|float) }} · Confirmed: R {{ "{:,.2f}".format(selected_membership.fee_paid|float) }} · Pending: R {{ "{:,.2f}".format(selected_membership.fee_pending) }} · Still to pay: <strong>R {{ "{:,.2f}".format(selected_membership.fee_outstanding) }}</strong>. This payment will be linked permanently to the membership history.',
        'Expected: R {{ "{:,.2f}".format(selected_membership.fee_amount|float) }} · Confirmed fee: R {{ "{:,.2f}".format(selected_membership.fee_paid_applied|float) }} · Pending fee: R {{ "{:,.2f}".format(selected_membership.fee_pending) }} · Still to pay: <strong>R {{ "{:,.2f}".format(selected_membership.fee_outstanding) }}</strong> · Confirmed credit: <strong>R {{ "{:,.2f}".format(selected_membership.fee_credit_confirmed) }}</strong>. If this receipt is more than the amount still due, the excess is automatically recorded as <strong>Member Credit</strong> instead of being treated as membership fee.',
        "contribution credit explanation",
    )
    changed |= replace_once(
        path,
        '<div class="group"><label for="amount">Amount (R) *</label><input id="amount" name="amount" type="number" min="0.01" step="0.01" required {% if selected_membership %}max="{{ \'%.2f\'|format(selected_membership.fee_outstanding) }}" value="{{ \'%.2f\'|format(selected_membership.fee_outstanding) }}"{% endif %}></div>',
        '<div class="group"><label for="amount">Amount Received (R) *</label><input id="amount" name="amount" type="number" min="0.01" step="0.01" required {% if selected_membership %}value="{{ \'%.2f\'|format(selected_membership.fee_outstanding) }}"{% endif %}><span class="help">You may enter the full amount actually received. Any amount above the membership fee still due will be separated into Member Credit.</span></div>',
        "remove fee overpayment max",
    )
    return changed


def patch_memberships_template() -> bool:
    path = ROOT / "templates" / "memberships.html"
    changed = False
    changed |= replace_once(
        path,
        '.stats-grid{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:14px}',
        '.stats-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}',
        "membership stats layout",
    )
    changed |= replace_once(
        path,
        '<article class="stat-card"><span class="stat-label">Fees Outstanding</span><span class="stat-value">R {{ "{:,.2f}".format(total_outstanding) }}</span><span class="stat-note">Still to be paid after confirmed + pending receipts</span></article>\n    </section>',
        '<article class="stat-card"><span class="stat-label">Fees Outstanding</span><span class="stat-value">R {{ "{:,.2f}".format(total_outstanding) }}</span><span class="stat-note">Still to be paid after confirmed + pending receipts</span></article>\n        <article class="stat-card"><span class="stat-label">Member Credit</span><span class="stat-value">R {{ "{:,.2f}".format(total_credit) }}</span><span class="stat-note">Confirmed overpayments held as unallocated member credit</span></article>\n        <article class="stat-card"><span class="stat-label">Credit Pending</span><span class="stat-value">R {{ "{:,.2f}".format(total_credit_pending) }}</span><span class="stat-note">Overpayments awaiting Chairperson confirmation</span></article>\n    </section>',
        "membership credit summary cards",
    )
    changed |= replace_once(
        path,
        '<div class="fee-row"><span class="fee-label">Confirmed</span><span class="fee-value fee-paid">R {{ "{:,.2f}".format(membership.fee_paid|float) }}</span></div>\n                        <div class="fee-row"><span class="fee-label">Pending</span><span class="fee-value {% if membership.fee_pending > 0 %}fee-due{% endif %}">R {{ "{:,.2f}".format(membership.fee_pending) }}</span></div>\n                        <div class="fee-row"><span class="fee-label">Outstanding</span><span class="fee-value {% if membership.fee_outstanding > 0 %}fee-due{% else %}fee-paid{% endif %}">R {{ "{:,.2f}".format(membership.fee_outstanding) }}</span></div>',
        '<div class="fee-row"><span class="fee-label">Confirmed Fee</span><span class="fee-value fee-paid">R {{ "{:,.2f}".format(membership.fee_paid_applied|float) }}</span></div>\n                        <div class="fee-row"><span class="fee-label">Pending Fee</span><span class="fee-value {% if membership.fee_pending > 0 %}fee-due{% endif %}">R {{ "{:,.2f}".format(membership.fee_pending) }}</span></div>\n                        <div class="fee-row"><span class="fee-label">Outstanding</span><span class="fee-value {% if membership.fee_outstanding > 0 %}fee-due{% else %}fee-paid{% endif %}">R {{ "{:,.2f}".format(membership.fee_outstanding) }}</span></div>\n                        {% if membership.fee_credit_confirmed > 0 %}<div class="fee-row"><span class="fee-label">Credit</span><span class="fee-value fee-paid">R {{ "{:,.2f}".format(membership.fee_credit_confirmed) }}</span></div>{% endif %}\n                        {% if membership.fee_credit_pending > 0 %}<div class="fee-row"><span class="fee-label">Credit Pending</span><span class="fee-value fee-due">R {{ "{:,.2f}".format(membership.fee_credit_pending) }}</span></div>{% endif %}',
        "member row credit labels",
    )
    return changed


def patch_phase7() -> bool:
    path = ROOT / "phase7.py"
    old = '''    return render_template(
        "phase7/finance_control.html", budget_rows=budget_rows, reconciliations=reconciliations,
        finance_docs=finance_docs, year=year, book_balance=_confirmed_book_balance(coop_id),
        can_record=access.role in FINANCE_RECORD_ROLES, can_approve=access.role in FINANCE_APPROVAL_ROLES,
    )
'''
    new = '''    memberships = Membership.query.filter_by(cooperative_id=coop_id).all()
    member_fee_expected = sum(float(m.fee_amount or 0) for m in memberships)
    member_fee_confirmed = sum(float(m.fee_paid_applied or 0) for m in memberships)
    member_fee_pending = sum(float(m.fee_pending or 0) for m in memberships)
    member_fee_outstanding = sum(float(m.fee_outstanding or 0) for m in memberships)
    member_credit_confirmed = sum(float(m.fee_credit_confirmed or 0) for m in memberships)
    member_credit_pending = sum(float(m.fee_credit_pending or 0) for m in memberships)
    book_balance = _confirmed_book_balance(coop_id)
    latest_reconciliation = reconciliations[0] if reconciliations else None
    return render_template(
        "phase7/finance_control.html", budget_rows=budget_rows, reconciliations=reconciliations,
        finance_docs=finance_docs, year=year, book_balance=book_balance,
        member_fee_expected=member_fee_expected, member_fee_confirmed=member_fee_confirmed,
        member_fee_pending=member_fee_pending, member_fee_outstanding=member_fee_outstanding,
        member_credit_confirmed=member_credit_confirmed, member_credit_pending=member_credit_pending,
        latest_reconciliation=latest_reconciliation,
        can_record=access.role in FINANCE_RECORD_ROLES, can_approve=access.role in FINANCE_APPROVAL_ROLES,
    )
'''
    return replace_once(path, old, new, "finance control member ledger summary")


def patch_finance_template() -> bool:
    path = ROOT / "templates" / "phase7" / "finance_control.html"
    changed = False
    changed |= replace_once(
        path,
        '<div class="p7-grid-4"><div class="p7-stat good"><span>Confirmed Book Balance</span><strong>R {{ "{:,.2f}".format(book_balance|float) }}</strong><small>Confirmed member/Primary contributions + sale payments − confirmed expenses</small></div><div class="p7-stat"><span>Budget Lines</span><strong>{{ budget_rows|length }}</strong><small>{{ year }} planning lines</small></div><div class="p7-stat"><span>Reconciliations</span><strong>{{ reconciliations|length }}</strong><small>Most recent bank checks</small></div><div class="p7-stat"><span>Supporting Documents</span><strong>{{ finance_docs|length }}</strong><small>Recent receipts, invoices and proof</small></div></div>',
        '<div class="p7-grid-4"><div class="p7-stat good"><span>Confirmed Book Balance</span><strong>R {{ "{:,.2f}".format(book_balance|float) }}</strong><small>Confirmed receipts + sale payments − confirmed expenses</small></div><div class="p7-stat"><span>Member Credit</span><strong>R {{ "{:,.2f}".format(member_credit_confirmed|float) }}</strong><small>Confirmed overpayments not allocated to the membership fee</small></div><div class="p7-stat"><span>Outstanding Fees</span><strong>R {{ "{:,.2f}".format(member_fee_outstanding|float) }}</strong><small>Membership fee still to be collected</small></div><div class="p7-stat"><span>Bank Difference</span><strong>{% if latest_reconciliation %}R {{ "{:,.2f}".format(latest_reconciliation.difference|float) }}{% else %}—{% endif %}</strong><small>{% if latest_reconciliation %}Latest reconciliation: {{ latest_reconciliation.statement_date.strftime(\'%d %b %Y\') }}{% else %}No bank reconciliation recorded yet{% endif %}</small></div></div>\n\n<section class="p7-card"><div class="p7-card-head"><h2>Member Money Allocation</h2></div><div class="p7-table-wrap"><table class="p7-table"><thead><tr><th>Expected Fees</th><th>Confirmed Fee</th><th>Pending Fee</th><th>Outstanding</th><th>Confirmed Credit</th><th>Credit Pending</th></tr></thead><tbody><tr><td>R {{ "{:,.2f}".format(member_fee_expected|float) }}</td><td>R {{ "{:,.2f}".format(member_fee_confirmed|float) }}</td><td>R {{ "{:,.2f}".format(member_fee_pending|float) }}</td><td>R {{ "{:,.2f}".format(member_fee_outstanding|float) }}</td><td><strong>R {{ "{:,.2f}".format(member_credit_confirmed|float) }}</strong></td><td>R {{ "{:,.2f}".format(member_credit_pending|float) }}</td></tr></tbody></table></div></section>',
        "finance allocation dashboard",
    )
    return changed


def patch_tests() -> bool:
    path = ROOT / "membership_regression_tests.py"
    old = '''    def test_membership_fee_overpayment_is_rejected(self):
        self.register_member(fee="100")
        with self.crm.app.app_context():
            membership_id = self.crm.Membership.query.one().id
        self.client = self.crm.app.test_client()
        self.login_as("primary_treasurer")
        response = self.client.post("/contributions/add", data={
            "membership_id": str(membership_id), "farmer_id": str(self.farmer_a_id), "amount": "150",
            "category": "Membership Fee", "contribution_date": date.today().isoformat(), "method": "Cash"
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        with self.crm.app.app_context():
            self.assertEqual(self.crm.Contribution.query.count(), 0)
'''
    new = '''    def test_membership_fee_overpayment_becomes_member_credit(self):
        self.register_member(fee="100")
        with self.crm.app.app_context():
            membership_id = self.crm.Membership.query.one().id
        self.client = self.crm.app.test_client()
        self.login_as("primary_treasurer")
        response = self.client.post("/contributions/add", data={
            "membership_id": str(membership_id), "farmer_id": str(self.farmer_a_id), "amount": "150",
            "category": "Membership Fee", "contribution_date": date.today().isoformat(), "method": "Cash",
            "reference": "OVERPAY-150",
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        with self.crm.app.app_context():
            membership = self.crm.db.session.get(self.crm.Membership, membership_id)
            entries = self.crm.Contribution.query.filter_by(membership_id=membership_id).order_by(self.crm.Contribution.id.asc()).all()
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0].category, "Membership Fee")
            self.assertAlmostEqual(entries[0].amount, 100.0)
            self.assertEqual(entries[1].category, "Member Credit")
            self.assertAlmostEqual(entries[1].amount, 50.0)
            self.assertAlmostEqual(membership.fee_pending, 100.0)
            self.assertAlmostEqual(membership.fee_credit_pending, 50.0)
            self.assertAlmostEqual(membership.fee_outstanding, 0.0)
'''
    return replace_once(path, old, new, "overpayment regression test")


def main():
    changed = []
    for name, fn in [
        ("app.py", patch_app),
        ("templates/contribution_form.html", patch_contribution_form),
        ("templates/memberships.html", patch_memberships_template),
        ("phase7.py", patch_phase7),
        ("templates/phase7/finance_control.html", patch_finance_template),
        ("membership_regression_tests.py", patch_tests),
    ]:
        if fn():
            changed.append(name)
    print("Finance/member-credit upgrade applied:", ", ".join(changed) if changed else "already up to date")


if __name__ == "__main__":
    main()
