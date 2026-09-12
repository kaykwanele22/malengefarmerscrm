"""Update legacy permission regressions for the MFPSU joint contribution model."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "permission_regression_tests.py"

text = PATH.read_text(encoding="utf-8")

import_marker = '        cls.crm = importlib.import_module("app")\n'
import_replacement = (
    '        cls.crm = importlib.import_module("app")\n'
    '        cls.jo = importlib.import_module("joint_operations")\n'
)
if 'cls.jo = importlib.import_module("joint_operations")' not in text:
    if import_marker not in text:
        raise RuntimeError("Could not find permission-test import marker")
    text = text.replace(import_marker, import_replacement, 1)

start_marker = '    def test_secondary_treasurer_surface(self):\n'
end_marker = '    # ---------------------------------------------------------\n    # ACCOUNT STATUS / LOGIN SECURITY\n'

new_block = '''    def test_secondary_treasurer_surface(self):
        self.login_as("secondary_treasurer")

        for url in [
            "/sales", "/payments", "/expenses", "/reports", "/settings", "/joint-operations"
        ]:
            self.assert_status(url, 200)

        contribution_redirect = self.assert_status("/contributions", 302)
        self.assertIn("/joint-operations", contribution_redirect.headers.get("Location", ""))
        self.assertIn("#primary-contributions", contribution_redirect.headers.get("Location", ""))

        add_redirect = self.assert_status("/contributions/add", 302)
        self.assertIn("#primary-contributions", add_redirect.headers.get("Location", ""))

        for url in ["/memberships", "/farmers", "/farms", "/crops", "/harvests"]:
            self.assert_status(url, 403)

    def test_secondary_treasurer_records_primary_cooperative_contribution_only(self):
        self.login_as("secondary_treasurer")
        year = date.today().year

        response = self.client.post(
            "/joint-operations/contribution-accounts",
            data={
                "primary_cooperative_id": str(self.primary_a_id),
                "fiscal_year": str(year),
                "expected_amount": "1000",
                "notes": "Primary cooperative annual contribution",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        with self.crm.app.app_context():
            account = self.jo.PrimaryContributionAccount.query.filter_by(
                secondary_cooperative_id=self.secondary_id,
                primary_cooperative_id=self.primary_a_id,
                fiscal_year=year,
            ).one()
            account_id = account.id

        response = self.client.post(
            f"/joint-operations/contribution-accounts/{account_id}/payments",
            data={
                "amount": "40",
                "payment_date": date.today().isoformat(),
                "method": "Bank Transfer",
                "reference": "SECONDARY-CONTRIB-001",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        with self.crm.app.app_context():
            payment = self.jo.PrimaryContributionPayment.query.filter_by(
                reference="SECONDARY-CONTRIB-001"
            ).one()
            self.assertEqual(payment.secondary_cooperative_id, self.secondary_id)
            self.assertEqual(payment.primary_cooperative_id, self.primary_a_id)
            self.assertEqual(payment.status, "Pending Confirmation")
            self.assertIsNone(
                self.crm.Contribution.query.filter_by(reference="SECONDARY-CONTRIB-001").first(),
                "Secondary cooperative money must not be stored as a farmer contribution.",
            )

    def test_secondary_treasurer_cannot_use_legacy_primary_contribution_form(self):
        self.login_as("secondary_treasurer")

        response = self.client.post(
            "/contributions/add",
            data={
                "farmer_id": str(self.farmer_a_id),
                "amount": "40",
                "category": "General",
                "contribution_date": date.today().isoformat(),
                "method": "Cash",
                "reference": "SECONDARY-FOREIGN-001",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/joint-operations", response.headers.get("Location", ""))
        self.assertIn("#primary-contributions", response.headers.get("Location", ""))

        with self.crm.app.app_context():
            record = self.crm.Contribution.query.filter_by(
                reference="SECONDARY-FOREIGN-001"
            ).first()
            self.assertIsNone(record)

    def test_secondary_chair_can_approve_secondary_finance(self):
        c = self.crm
        year = date.today().year + 1
        with c.app.app_context():
            account = self.jo.PrimaryContributionAccount(
                secondary_cooperative_id=self.secondary_id,
                primary_cooperative_id=self.primary_b_id,
                fiscal_year=year,
                expected_amount=30.0,
                created_by_user_id=self.user_ids["secondary_treasurer"],
            )
            c.db.session.add(account)
            c.db.session.flush()
            payment = self.jo.PrimaryContributionPayment(
                account_id=account.id,
                secondary_cooperative_id=self.secondary_id,
                primary_cooperative_id=self.primary_b_id,
                amount=30.0,
                payment_date=date.today(),
                method="Bank Transfer",
                reference="SECONDARY-CHAIR-APPROVE",
                status="Pending Confirmation",
                recorded_by_user_id=self.user_ids["secondary_treasurer"],
            )
            c.db.session.add(payment)
            c.db.session.commit()
            payment_id = payment.id

        self.login_as("secondary_chair")
        self.assert_status(
            f"/joint-operations/contribution-payments/{payment_id}/decision",
            302,
            method="post",
            data={"decision": "approve"},
        )

        with c.app.app_context():
            payment = c.db.session.get(self.jo.PrimaryContributionPayment, payment_id)
            self.assertEqual(payment.status, "Confirmed")

    def test_secondary_chair_cannot_approve_primary_finance(self):
        c = self.crm
        with c.app.app_context():
            record = c.Contribution(
                cooperative_id=self.primary_a_id,
                farmer_id=self.farmer_a_id,
                amount=30.0,
                contribution_date=date.today(),
                category="General",
                method="Cash",
                reference="SECONDARY-CHAIR-FOREIGN",
                status="Pending Confirmation",
            )
            c.db.session.add(record)
            c.db.session.commit()
            record_id = record.id

        self.login_as("secondary_chair")
        self.assert_status(
            f"/contributions/{record_id}/decision",
            403,
            method="post",
            data={"decision": "approve"},
        )

'''

if 'def test_secondary_treasurer_records_primary_cooperative_contribution_only' not in text:
    if start_marker not in text or end_marker not in text:
        raise RuntimeError("Could not find Secondary finance permission-test block")
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    text = text[:start] + new_block + text[end:]

PATH.write_text(text, encoding="utf-8")
print("Joint Operations permission regressions updated.")
