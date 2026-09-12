"""Apply the integration edits required by joint_operations.py.

The feature itself lives in its own module. This script keeps changes to the
large legacy app/template files deterministic and reviewable in CI.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write_if_changed(path: Path, text: str):
    current = path.read_text(encoding="utf-8")
    if current != text:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def replace_once(text: str, old: str, new: str, label: str):
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"Could not find integration marker: {label}")
    return text.replace(old, new, 1)


def patch_app():
    path = ROOT / "app.py"
    text = path.read_text(encoding="utf-8")
    old = "from phase7 import register_phase7\nregister_phase7(app)\n"
    new = (
        "from phase7 import register_phase7\n"
        "register_phase7(app)\n\n"
        "# Secondary/MFPSU joint operations are isolated from Primary individual records.\n"
        "from joint_operations import register_joint_operations\n"
        "register_joint_operations(app)\n"
    )
    text = replace_once(text, old, new, "app registration")

    old = '''def contributions_list():\n    """List contributions within the user's visibility scope."""\n'''
    new = old + '''    access = current_access()\n    if access and access.role.startswith("Secondary"):\n        return redirect(url_for("jointops.dashboard", year=crm_today().year, _anchor="primary-contributions"))\n'''
    text = replace_once(text, old, new, "secondary contribution list redirect")

    old = '''def add_contribution():\n    """Treasurer records money; membership-fee money is linked to the exact member record."""\n    access = current_access()\n'''
    new = '''def add_contribution():\n    """Treasurer records money; membership-fee money is linked to the exact member record."""\n    access = current_access()\n    if access and access.role.startswith("Secondary"):\n        return redirect(url_for("jointops.dashboard", year=crm_today().year, _anchor="primary-contributions"))\n'''
    text = replace_once(text, old, new, "secondary contribution add redirect")

    old = '''def decide_contribution(contribution_id):\n    """Chairperson confirms or rejects a Treasurer-recorded contribution."""\n    contribution = scoped_get_or_404(Contribution, contribution_id)\n'''
    new = '''def decide_contribution(contribution_id):\n    """Chairperson confirms or rejects a Treasurer-recorded contribution."""\n    access = current_access()\n    if access and access.role.startswith("Secondary"):\n        abort(403)\n    contribution = scoped_get_or_404(Contribution, contribution_id)\n'''
    text = replace_once(text, old, new, "secondary legacy contribution approval block")

    old = '''def delete_contribution(contribution_id):\n    """Treasurer may remove only an unconfirmed/rejected mistaken record."""\n    contribution = scoped_get_or_404(Contribution, contribution_id)\n'''
    new = '''def delete_contribution(contribution_id):\n    """Treasurer may remove only an unconfirmed/rejected mistaken record."""\n    access = current_access()\n    if access and access.role.startswith("Secondary"):\n        abort(403)\n    contribution = scoped_get_or_404(Contribution, contribution_id)\n'''
    text = replace_once(text, old, new, "secondary legacy contribution delete block")

    return write_if_changed(path, text)


def patch_sidebar():
    path = ROOT / "templates" / "base.html"
    text = path.read_text(encoding="utf-8")
    old = '''                {% if is_leadership or is_treasurer %}\n                <a href="{{ url_for('phase7.finance_control') }}"\n                   class="nav-item {% if request.endpoint and request.endpoint.startswith('phase7.') and request.endpoint in ['phase7.finance_control','phase7.budget_create','phase7.budget_decision','phase7.reconciliation_create','phase7.reconciliation_review'] %}active{% endif %}">\n                    <span>🏦</span><span>Finance Control</span>\n                </a>\n                {% endif %}\n'''
    new = old + '''\n                {% if is_secondary %}\n                <a href="{{ url_for('jointops.dashboard') }}"\n                   class="nav-item {% if request.endpoint and request.endpoint.startswith('jointops.') %}active{% endif %}">\n                    <span>🤝</span><span>Joint Operations</span>\n                </a>\n                {% endif %}\n'''
    text = replace_once(text, old, new, "secondary Joint Operations sidebar link")

    treasurer_old = '''                    <a href="{{ url_for('contributions_list') }}"\n                       class="nav-item {% if request.endpoint in [\n                           'contributions_list',\n                           'add_contribution',\n                           'delete_contribution'\n                       ] %}active{% endif %}">\n                        <span>🏦</span>\n                        <span>Contributions</span>\n                    </a>\n'''
    treasurer_new = '''                    {% if is_secondary %}\n                    <a href="{{ url_for('jointops.dashboard', _anchor='primary-contributions') }}"\n                       class="nav-item {% if request.endpoint and request.endpoint.startswith('jointops.') %}active{% endif %}">\n                        <span>🏦</span>\n                        <span>Primary Contributions</span>\n                    </a>\n                    {% else %}\n                    <a href="{{ url_for('contributions_list') }}"\n                       class="nav-item {% if request.endpoint in [\n                           'contributions_list',\n                           'add_contribution',\n                           'delete_contribution'\n                       ] %}active{% endif %}">\n                        <span>🏦</span>\n                        <span>Contributions</span>\n                    </a>\n                    {% endif %}\n'''
    text = replace_once(text, treasurer_old, treasurer_new, "secondary treasurer Primary Contributions link")

    leadership_old = '''                    <a href="{{ url_for('contributions_list') }}"\n                       class="nav-item {% if request.endpoint in [\n                           'contributions_list',\n                           'decide_contribution'\n                       ] %}active{% endif %}">\n                        <span>🏦</span>\n                        <span>Contributions</span>\n                    </a>\n'''
    leadership_new = '''                    {% if is_secondary %}\n                    <a href="{{ url_for('jointops.dashboard', _anchor='primary-contributions') }}"\n                       class="nav-item {% if request.endpoint and request.endpoint.startswith('jointops.') %}active{% endif %}">\n                        <span>🏦</span>\n                        <span>Primary Contributions</span>\n                    </a>\n                    {% else %}\n                    <a href="{{ url_for('contributions_list') }}"\n                       class="nav-item {% if request.endpoint in [\n                           'contributions_list',\n                           'decide_contribution'\n                       ] %}active{% endif %}">\n                        <span>🏦</span>\n                        <span>Contributions</span>\n                    </a>\n                    {% endif %}\n'''
    text = replace_once(text, leadership_old, leadership_new, "secondary chair Primary Contributions link")
    return write_if_changed(path, text)


def patch_dashboard():
    path = ROOT / "templates" / "dashboard.html"
    text = path.read_text(encoding="utf-8")
    old = '''            {% if is_admin %}<a href="{{ url_for('users_list') }}" class="dash-primary-btn">Manage Users &amp; Access</a>\n            {% elif is_chairperson and own_pending_finance > 0 %}<a href="{{ url_for('contributions_list') }}" class="dash-primary-btn">Review {{ own_pending_finance }} Pending Approvals</a>\n            {% elif is_treasurer %}<a href="{{ url_for('add_contribution') }}" class="dash-primary-btn">Record Money</a>\n'''
    new = '''            {% if is_admin %}<a href="{{ url_for('users_list') }}" class="dash-primary-btn">Manage Users &amp; Access</a>\n            {% elif is_secondary and is_chairperson %}<a href="{{ url_for('jointops.dashboard', _anchor='primary-contributions') }}" class="dash-primary-btn">Review Joint Finance</a>\n            {% elif is_chairperson and own_pending_finance > 0 %}<a href="{{ url_for('contributions_list') }}" class="dash-primary-btn">Review {{ own_pending_finance }} Pending Approvals</a>\n            {% elif is_secondary and is_treasurer %}<a href="{{ url_for('jointops.dashboard', _anchor='primary-contributions') }}" class="dash-primary-btn">Record Primary Contribution</a>\n            {% elif is_treasurer %}<a href="{{ url_for('add_contribution') }}" class="dash-primary-btn">Record Money</a>\n'''
    text = replace_once(text, old, new, "secondary contribution dashboard actions")
    return write_if_changed(path, text)


def patch_joint_dashboard():
    path = ROOT / "templates" / "joint_operations" / "dashboard.html"
    text = path.read_text(encoding="utf-8")
    old = '''    <section class="p7-card">\n        <div class="p7-card-head"><h2>Primary Cooperative Contributions to MFPSU</h2>'''
    new = '''    <section class="p7-card" id="primary-contributions">\n        <div class="p7-card-head"><h2>Primary Cooperative Contributions to MFPSU</h2>'''
    text = replace_once(text, old, new, "Primary contributions anchor")
    return write_if_changed(path, text)


def patch_joint_tests():
    path = ROOT / "joint_operations_regression_tests.py"
    text = path.read_text(encoding="utf-8")
    old = '''        cls._make_user("primary_chair", "Primary Chairperson", siy.id)\n'''
    new = old + '''        cls._make_user("primary_treasurer", "Primary Treasurer", siy.id)\n'''
    text = replace_once(text, old, new, "Primary Treasurer regression user")

    marker = '''    def test_treasurer_records_primary_contribution_and_chair_confirms(self):\n'''
    test = '''    def test_secondary_uses_cooperative_contributions_not_farmer_contributions(self):\n        self.login_as("sec_treasurer")\n        response = self.client.get("/contributions")\n        self.assertEqual(response.status_code, 302)\n        self.assertIn("/joint-operations", response.headers.get("Location", ""))\n        self.assertIn("#primary-contributions", response.headers.get("Location", ""))\n\n        response = self.client.get("/contributions/add")\n        self.assertEqual(response.status_code, 302)\n        self.assertIn("#primary-contributions", response.headers.get("Location", ""))\n\n        dashboard = self.client.get("/dashboard").get_data(as_text=True)\n        self.assertIn("Record Primary Contribution", dashboard)\n        self.assertNotIn('href="/contributions/add" class="dash-primary-btn">Record Money', dashboard)\n\n        self.login_as("primary_treasurer")\n        response = self.client.get("/contributions/add")\n        self.assertEqual(response.status_code, 200)\n        page = response.get_data(as_text=True)\n        self.assertIn("Member / Farmer", page)\n        self.assertNotIn("Primary Cooperative Contributions to MFPSU", page)\n\n'''
    if test not in text:
        if marker not in text:
            raise RuntimeError("Could not find joint contribution test marker")
        text = text.replace(marker, test + marker, 1)
    return write_if_changed(path, text)


def patch_regression_runner():
    path = ROOT / "run_regression_tests.py"
    text = path.read_text(encoding="utf-8")
    if '"joint_operations_regression_tests.py"' not in text:
        marker = '    "secondary_scope_regression_tests.py",\n'
        if marker not in text:
            marker = '    "phase7_regression_tests.py",\n'
        if marker not in text:
            raise RuntimeError("Could not find regression suite marker")
        text = text.replace(marker, marker + '    "joint_operations_regression_tests.py",\n', 1)
    return write_if_changed(path, text)


def patch_phase7():
    path = ROOT / "phase7.py"
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '    "Financial Document", "Membership Document", "Production Document", "General",\n',
        '    "Financial Document", "Membership Document", "Production Document", "Joint Operations Document", "General",\n',
        "joint document type",
    )

    helper_marker = '''def _year_bounds(year):\n    return date(year, 1, 1), date(year + 1, 1, 1)\n\n\n'''
    helper = helper_marker + '''def _confirmed_primary_cooperative_contributions(cooperative_id, start_date=None, through_date=None):\n    """Return confirmed Primary-to-Secondary contributions without using a fake farmer record."""\n    try:\n        from joint_operations import PrimaryContributionPayment\n    except (ImportError, AttributeError):\n        return 0.0\n    query = db.session.query(func.coalesce(func.sum(PrimaryContributionPayment.amount), 0)).filter(\n        PrimaryContributionPayment.secondary_cooperative_id == cooperative_id,\n        PrimaryContributionPayment.status == "Confirmed",\n    )\n    if start_date:\n        query = query.filter(PrimaryContributionPayment.payment_date >= start_date)\n    if through_date:\n        query = query.filter(PrimaryContributionPayment.payment_date <= through_date)\n    return float(query.scalar() or 0)\n\n\n'''
    text = replace_once(text, helper_marker, helper, "Primary cooperative contribution finance helper")

    old_balance = '    return float(contributions) + float(payments) - float(expenses)\n'
    new_balance = (
        '    primary_cooperative_contributions = _confirmed_primary_cooperative_contributions(\n'
        '        cooperative_id, through_date=through_date\n'
        '    )\n'
        '    return float(contributions) + primary_cooperative_contributions + float(payments) - float(expenses)\n'
    )
    text = replace_once(text, old_balance, new_balance, "book balance joint contributions")

    old_budget = '''    if budget.budget_type == "Contribution":\n        query = db.session.query(func.coalesce(func.sum(Contribution.amount), 0)).filter(\n            Contribution.cooperative_id == budget.cooperative_id,\n            Contribution.status.in_(CONFIRMED_CONTRIBUTION_STATUSES),\n            Contribution.contribution_date >= start,\n            Contribution.contribution_date < end,\n        )\n        if category and category.casefold() != "all":\n            query = query.filter(func.lower(Contribution.category) == category.lower())\n        return float(query.scalar() or 0)\n'''
    new_budget = '''    if budget.budget_type == "Contribution":\n        query = db.session.query(func.coalesce(func.sum(Contribution.amount), 0)).filter(\n            Contribution.cooperative_id == budget.cooperative_id,\n            Contribution.status.in_(CONFIRMED_CONTRIBUTION_STATUSES),\n            Contribution.contribution_date >= start,\n            Contribution.contribution_date < end,\n        )\n        if category and category.casefold() != "all":\n            query = query.filter(func.lower(Contribution.category) == category.lower())\n        legacy_total = float(query.scalar() or 0)\n        joint_total = _confirmed_primary_cooperative_contributions(\n            budget.cooperative_id, start_date=start, through_date=end - timedelta(days=1)\n        )\n        return legacy_total + joint_total\n'''
    text = replace_once(text, old_budget, new_budget, "budget actual joint contributions")

    old_report = '''        "month_contributions": float(db.session.query(func.coalesce(func.sum(Contribution.amount), 0)).filter(\n            Contribution.cooperative_id == coop_id, Contribution.contribution_date >= month_start,\n            Contribution.status.in_(CONFIRMED_CONTRIBUTION_STATUSES)).scalar() or 0),\n'''
    new_report = '''        "month_contributions": (\n            float(db.session.query(func.coalesce(func.sum(Contribution.amount), 0)).filter(\n                Contribution.cooperative_id == coop_id, Contribution.contribution_date >= month_start,\n                Contribution.status.in_(CONFIRMED_CONTRIBUTION_STATUSES)).scalar() or 0)\n            + _confirmed_primary_cooperative_contributions(coop_id, start_date=month_start)\n        ),\n'''
    text = replace_once(text, old_report, new_report, "reports joint contributions")
    return write_if_changed(path, text)


def patch_finance_copy():
    path = ROOT / "templates" / "phase7" / "finance_control.html"
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "Confirmed contributions + sale payments − confirmed expenses",
        "Confirmed member/Primary contributions + sale payments − confirmed expenses",
    )
    return write_if_changed(path, text)


def main():
    changed = []
    for name, fn in [
        ("app.py", patch_app),
        ("templates/base.html", patch_sidebar),
        ("templates/dashboard.html", patch_dashboard),
        ("templates/joint_operations/dashboard.html", patch_joint_dashboard),
        ("joint_operations_regression_tests.py", patch_joint_tests),
        ("run_regression_tests.py", patch_regression_runner),
        ("phase7.py", patch_phase7),
        ("templates/phase7/finance_control.html", patch_finance_copy),
    ]:
        if fn():
            changed.append(name)
    print("Joint operations integration applied.")
    if changed:
        print("Changed: " + ", ".join(changed))
    else:
        print("No changes required.")


if __name__ == "__main__":
    main()
