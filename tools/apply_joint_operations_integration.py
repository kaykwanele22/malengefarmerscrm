"""Apply the small integration edits required by joint_operations.py.

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
    return write_if_changed(path, text)


def patch_sidebar():
    path = ROOT / "templates" / "base.html"
    text = path.read_text(encoding="utf-8")
    old = '''                {% if is_leadership or is_treasurer %}\n                <a href="{{ url_for('phase7.finance_control') }}"\n                   class="nav-item {% if request.endpoint and request.endpoint.startswith('phase7.') and request.endpoint in ['phase7.finance_control','phase7.budget_create','phase7.budget_decision','phase7.reconciliation_create','phase7.reconciliation_review'] %}active{% endif %}">\n                    <span>🏦</span><span>Finance Control</span>\n                </a>\n                {% endif %}\n'''
    new = old + '''\n                {% if is_secondary %}\n                <a href="{{ url_for('jointops.dashboard') }}"\n                   class="nav-item {% if request.endpoint and request.endpoint.startswith('jointops.') %}active{% endif %}">\n                    <span>🤝</span><span>Joint Operations</span>\n                </a>\n                {% endif %}\n'''
    text = replace_once(text, old, new, "secondary Joint Operations sidebar link")
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
