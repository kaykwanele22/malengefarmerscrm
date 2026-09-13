import importlib
import os
import tempfile
import unittest
from pathlib import Path


class LedgerReversalRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory(prefix="malenge_reversal_test_")
        cls.db_path = Path(cls.tempdir.name) / "reversal.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{cls.db_path.as_posix()}"
        os.environ["SECRET_KEY"] = "ledger-reversal-regression-secret"
        os.environ["APP_ENV"] = "development"
        os.environ["TWO_FACTOR_REQUIRED"] = "false"
        os.environ["DOCUMENT_UPLOAD_DIR"] = str(Path(cls.tempdir.name) / "documents")

        cls.crm = importlib.import_module("app")
        cls.ledger = importlib.import_module("account_ledger")
        cls.crm.app.config.update(TESTING=True, TWO_FACTOR_REQUIRED=False)

        with cls.crm.app.app_context():
            cls.crm.db.create_all()
            cls._seed()

    @classmethod
    def _seed(cls):
        c = cls.crm
        coop_a = c.Cooperative(name="Reversal Primary A", cooperative_type="Primary", code="RVA", status="Active")
        coop_b = c.Cooperative(name="Reversal Primary B", cooperative_type="Primary", code="RVB", status="Active")
        c.db.session.add_all([coop_a, coop_b])
        c.db.session.flush()
        cls.coop_a, cls.coop_b = coop_a.id, coop_b.id

        cls.users = {}
        for key, role, coop_id in [
            ("treasurer", "Primary Treasurer", coop_a.id),
            ("chair", "Primary Chairperson", coop_a.id),
            ("other_chair", "Primary Chairperson", coop_b.id),
        ]:
            user = c.User(
                fullname=key.replace("_", " ").title(),
                phone=f"07355{len(cls.users):05d}",
                email=f"{key}@reversal.local",
                farm_location="Malenge",
                password=c.generate_password_hash("Testing123!"),
            )
            c.db.session.add(user)
            c.db.session.flush()
            c.db.session.add(c.UserAccess(user_id=user.id, cooperative_id=coop_id, role=role, status="Active"))
            cls.users[key] = user.id
        c.db.session.commit()

    @classmethod
    def tearDownClass(cls):
        with cls.crm.app.app_context():
            cls.crm.db.session.remove()
            cls.crm.db.drop_all()
            cls.crm.db.engine.dispose()
        cls.tempdir.cleanup()

    def setUp(self):
        c, l = self.crm, self.ledger
        self.client = c.app.test_client()
        with c.app.app_context():
            l.LedgerTransactionRevision.query.delete()
            l.FinanceReconciliation.query.delete()
            l.LedgerTransaction.query.delete()
            l.FinanceAccount.query.delete()
            c.db.session.commit()

    def login_as(self, key):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess["user_id"] = self.users[key]
            sess["fullname"] = key.replace("_", " ").title()

    def create_account(self, name, opening):
        c, l = self.crm, self.ledger
        self.login_as("treasurer")
        response = self.client.post("/finance/accounts", data={
            "name": name,
            "account_type": "Bank Account",
            "opening_balance": str(opening),
            "opening_balance_date": c.crm_today().isoformat() if opening else "",
        })
        self.assertEqual(response.status_code, 302)
        with c.app.app_context():
            return l.FinanceAccount.query.filter_by(cooperative_id=self.coop_a, name=name).one().id

    def create_and_confirm_income(self, account_id, amount=300):
        c, l = self.crm, self.ledger
        self.login_as("treasurer")
        response = self.client.post("/finance/transactions", data={
            "transaction_type": "Income",
            "category": "Membership Fee",
            "amount": str(amount),
            "transaction_date": c.crm_today().isoformat(),
            "to_account_id": str(account_id),
            "counterparty": "Member A",
            "reference": "MEMBER-INCOME-001",
            "payment_method": "Cash",
            "project_reference": "Membership",
        })
        self.assertEqual(response.status_code, 302)
        with c.app.app_context():
            original = l.LedgerTransaction.query.filter_by(
                cooperative_id=self.coop_a,
                reference="MEMBER-INCOME-001",
            ).one()
            original_id = original.id
        self.login_as("chair")
        response = self.client.post(
            f"/finance/transactions/{original_id}/decision",
            data={"decision": "approve", "decision_note": "Income verified."},
        )
        self.assertEqual(response.status_code, 302)
        return original_id

    def create_reversal(self, original_id, reason="Confirmed entry needs reversal"):
        c, l = self.crm, self.ledger
        self.login_as("treasurer")
        response = self.client.post(f"/finance/transactions/{original_id}/reverse", data={
            "reversal_date": c.crm_today().isoformat(),
            "reversal_reason": reason,
            "reference": "REV-001",
            "payment_method": "EFT / Bank Transfer",
            "counterparty": "Member A",
            "project_reference": "Membership",
        })
        self.assertEqual(response.status_code, 302)
        with c.app.app_context():
            reversal = l.LedgerTransaction.query.filter_by(
                cooperative_id=self.coop_a,
                reversal_of_transaction_id=original_id,
            ).one()
            return reversal.id

    def test_confirmed_income_reversal_restores_balance_and_nets_category_reporting(self):
        c, l = self.crm, self.ledger
        account_id = self.create_account("Main Bank", 1000)
        original_id = self.create_and_confirm_income(account_id, 300)

        with c.app.app_context():
            account = c.db.session.get(l.FinanceAccount, account_id)
            original = c.db.session.get(l.LedgerTransaction, original_id)
            self.assertEqual(original.status, "Confirmed")
            self.assertAlmostEqual(account.confirmed_balance, 1300.0)

        reversal_id = self.create_reversal(original_id, "Membership payment was refunded.")
        with c.app.app_context():
            reversal = c.db.session.get(l.LedgerTransaction, reversal_id)
            original = c.db.session.get(l.LedgerTransaction, original_id)
            account = c.db.session.get(l.FinanceAccount, account_id)
            self.assertEqual(reversal.transaction_type, "Reversal")
            self.assertEqual(reversal.status, "Pending Confirmation")
            self.assertEqual(reversal.category, original.category)
            self.assertAlmostEqual(reversal.amount, original.amount)
            self.assertEqual(reversal.from_account_id, account_id)
            self.assertIsNone(reversal.to_account_id)
            self.assertIsNone(reversal.source_type)
            self.assertIsNone(reversal.source_id)
            self.assertEqual(original.status, "Confirmed")
            self.assertAlmostEqual(account.confirmed_balance, 1300.0)

        self.login_as("other_chair")
        self.assertEqual(self.client.get(f"/finance/transactions/{reversal_id}").status_code, 404)

        self.login_as("treasurer")
        duplicate = self.client.post(f"/finance/transactions/{original_id}/reverse", data={
            "reversal_date": c.crm_today().isoformat(),
            "reversal_reason": "Duplicate reversal must not be created.",
        })
        self.assertIn(duplicate.status_code, (303, 409))
        with c.app.app_context():
            self.assertEqual(l.LedgerTransaction.query.filter_by(reversal_of_transaction_id=original_id).count(), 1)

        self.login_as("chair")
        approved = self.client.post(
            f"/finance/transactions/{reversal_id}/decision",
            data={"decision": "approve", "decision_note": "Refund evidence verified."},
        )
        self.assertEqual(approved.status_code, 302)

        with c.app.app_context():
            account = c.db.session.get(l.FinanceAccount, account_id)
            original = c.db.session.get(l.LedgerTransaction, original_id)
            reversal = c.db.session.get(l.LedgerTransaction, reversal_id)
            self.assertEqual(original.status, "Confirmed")
            self.assertEqual(reversal.status, "Confirmed")
            self.assertAlmostEqual(account.confirmed_balance, 1000.0)
            rows = l.LedgerTransaction.query.filter(
                l.LedgerTransaction.cooperative_id == self.coop_a,
                l.LedgerTransaction.status == "Confirmed",
                l.LedgerTransaction.category == "Membership Fee",
            ).all()
            self.assertAlmostEqual(sum(l._category_reporting_amount(row) for row in rows), 0.0)

        self.login_as("treasurer")
        reconciliation = self.client.post("/finance/reconciliations", data={
            "finance_account_id": str(account_id),
            "statement_date": c.crm_today().isoformat(),
            "statement_balance": "1000",
            "notes": "Balance after approved reversal",
        })
        self.assertEqual(reconciliation.status_code, 302)
        with c.app.app_context():
            row = l.FinanceReconciliation.query.filter_by(
                cooperative_id=self.coop_a,
                finance_account_id=account_id,
            ).one()
            self.assertAlmostEqual(row.book_balance, 1000.0)
            self.assertAlmostEqual(row.difference, 0.0)

        original_detail = self.client.get(f"/finance/transactions/{original_id}")
        self.assertEqual(original_detail.status_code, 200)
        self.assertIn(f"View Reversal #{reversal_id}".encode(), original_detail.data)
        reversal_detail = self.client.get(f"/finance/transactions/{reversal_id}")
        self.assertEqual(reversal_detail.status_code, 200)
        self.assertIn(f"reverses confirmed transaction".encode(), reversal_detail.data)
        self.assertIn(f"#{original_id}".encode(), reversal_detail.data)

    def test_rejected_reversal_resubmission_cannot_change_accounting_effect(self):
        c, l = self.crm, self.ledger
        account_id = self.create_account("Correction Bank", 1000)
        original_id = self.create_and_confirm_income(account_id, 250)
        reversal_id = self.create_reversal(original_id, "Refund initially requested.")

        self.login_as("chair")
        rejected = self.client.post(
            f"/finance/transactions/{reversal_id}/decision",
            data={"decision": "reject", "decision_note": "Use the bank credit reference before approval."},
        )
        self.assertEqual(rejected.status_code, 302)

        self.login_as("treasurer")
        resubmitted = self.client.post(f"/finance/transactions/{reversal_id}/resubmit", data={
            "transaction_date": c.crm_today().isoformat(),
            "payment_method": "EFT / Bank Transfer",
            "counterparty": "Member A",
            "reference": "BANK-CREDIT-250",
            "project_reference": "Membership",
            "notes": "Bank credit reference added.",
            "correction_reason": "Added the bank credit reference requested by the Chairperson.",
            # Malicious/accidental accounting changes must be ignored for reversal rows.
            "transaction_type": "Income",
            "category": "Grant",
            "amount": "1",
            "from_account_id": "",
            "to_account_id": str(account_id),
        })
        self.assertEqual(resubmitted.status_code, 302)

        with c.app.app_context():
            reversal = c.db.session.get(l.LedgerTransaction, reversal_id)
            self.assertEqual(reversal.status, "Pending Confirmation")
            self.assertEqual(reversal.transaction_type, "Reversal")
            self.assertEqual(reversal.category, "Membership Fee")
            self.assertAlmostEqual(reversal.amount, 250.0)
            self.assertEqual(reversal.from_account_id, account_id)
            self.assertIsNone(reversal.to_account_id)
            self.assertEqual(reversal.reference, "BANK-CREDIT-250")
            self.assertIsNone(reversal.decided_by_user_id)
            self.assertIsNone(reversal.decision_note)
            revision = l.LedgerTransactionRevision.query.filter_by(transaction_id=reversal_id).one()
            self.assertEqual(revision.snapshot.get("status"), "Rejected")
            self.assertEqual(revision.snapshot.get("transaction_type"), "Reversal")
            self.assertEqual(revision.snapshot.get("reversal_of_transaction_id"), original_id)
            self.assertAlmostEqual(revision.snapshot.get("amount"), 250.0)
            self.assertIn("bank credit reference", revision.reason.lower())

        self.login_as("chair")
        approved = self.client.post(
            f"/finance/transactions/{reversal_id}/decision",
            data={"decision": "approve", "decision_note": "Bank credit verified."},
        )
        self.assertEqual(approved.status_code, 302)
        with c.app.app_context():
            account = c.db.session.get(l.FinanceAccount, account_id)
            self.assertAlmostEqual(account.confirmed_balance, 1000.0)

    def test_transfer_reversal_restores_both_accounts(self):
        c, l = self.crm, self.ledger
        account_a = self.create_account("Operating", 1000)
        account_b = self.create_account("Savings", 0)

        self.login_as("treasurer")
        created = self.client.post("/finance/transactions", data={
            "transaction_type": "Transfer",
            "category": "Transfer",
            "amount": "400",
            "transaction_date": c.crm_today().isoformat(),
            "from_account_id": str(account_a),
            "to_account_id": str(account_b),
            "reference": "MOVE-400",
        })
        self.assertEqual(created.status_code, 302)
        with c.app.app_context():
            original = l.LedgerTransaction.query.filter_by(cooperative_id=self.coop_a, reference="MOVE-400").one()
            original_id = original.id

        self.login_as("chair")
        self.assertEqual(
            self.client.post(f"/finance/transactions/{original_id}/decision", data={"decision": "approve"}).status_code,
            302,
        )
        with c.app.app_context():
            self.assertAlmostEqual(c.db.session.get(l.FinanceAccount, account_a).confirmed_balance, 600.0)
            self.assertAlmostEqual(c.db.session.get(l.FinanceAccount, account_b).confirmed_balance, 400.0)

        reversal_id = self.create_reversal(original_id, "Transfer was sent to the wrong internal account.")
        with c.app.app_context():
            reversal = c.db.session.get(l.LedgerTransaction, reversal_id)
            self.assertEqual(reversal.from_account_id, account_b)
            self.assertEqual(reversal.to_account_id, account_a)
            self.assertAlmostEqual(reversal.amount, 400.0)

        self.login_as("chair")
        self.assertEqual(
            self.client.post(f"/finance/transactions/{reversal_id}/decision", data={"decision": "approve"}).status_code,
            302,
        )
        with c.app.app_context():
            self.assertAlmostEqual(c.db.session.get(l.FinanceAccount, account_a).confirmed_balance, 1000.0)
            self.assertAlmostEqual(c.db.session.get(l.FinanceAccount, account_b).confirmed_balance, 0.0)

        self.login_as("treasurer")
        cannot_reverse_reversal = self.client.post(f"/finance/transactions/{reversal_id}/reverse", data={
            "reversal_date": c.crm_today().isoformat(),
            "reversal_reason": "No reversal-of-reversal allowed.",
        })
        self.assertIn(cannot_reverse_reversal.status_code, (303, 400))
        with c.app.app_context():
            self.assertEqual(l.LedgerTransaction.query.filter_by(cooperative_id=self.coop_a).count(), 2)


if __name__ == "__main__":
    unittest.main()
