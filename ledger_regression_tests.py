import importlib
import os
import tempfile
import unittest
from pathlib import Path


class FinanceLedgerRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory(prefix="malenge_ledger_test_")
        cls.db_path = Path(cls.tempdir.name) / "ledger.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{cls.db_path.as_posix()}"
        os.environ["SECRET_KEY"] = "ledger-regression-secret"
        os.environ["APP_ENV"] = "development"
        os.environ["TWO_FACTOR_REQUIRED"] = "false"
        os.environ["DOCUMENT_UPLOAD_DIR"] = str(Path(cls.tempdir.name) / "documents")

        cls.crm = importlib.import_module("app")
        cls.ledger = importlib.import_module("account_ledger")
        cls.p7 = importlib.import_module("phase7")
        cls.crm.app.config.update(TESTING=True, TWO_FACTOR_REQUIRED=False)

        with cls.crm.app.app_context():
            cls.crm.db.create_all()
            cls._seed()

    @classmethod
    def _seed(cls):
        c = cls.crm
        coop_a = c.Cooperative(name="Ledger Siyaphumla", cooperative_type="Primary", code="LGA", status="Active")
        coop_b = c.Cooperative(name="Ledger Vimba", cooperative_type="Primary", code="LGB", status="Active")
        c.db.session.add_all([coop_a, coop_b])
        c.db.session.flush()
        cls.coop_a, cls.coop_b = coop_a.id, coop_b.id

        cls.users = {}
        for key, role, coop in [
            ("treasurer", "Primary Treasurer", coop_a.id),
            ("chair", "Primary Chairperson", coop_a.id),
            ("other_chair", "Primary Chairperson", coop_b.id),
        ]:
            user = c.User(
                fullname=key.replace("_", " ").title(),
                phone=f"07123{len(cls.users):05d}",
                email=f"{key}@ledger.local",
                farm_location="Malenge",
                password=c.generate_password_hash("Testing123!"),
            )
            c.db.session.add(user)
            c.db.session.flush()
            c.db.session.add(c.UserAccess(user_id=user.id, cooperative_id=coop, role=role, status="Active"))
            cls.users[key] = user.id

        farmer_a = c.Farmer(cooperative_id=coop_a.id, fullname="Farmer A", phone="0711111111", location="A", status="Active")
        farmer_b = c.Farmer(cooperative_id=coop_b.id, fullname="Farmer B", phone="0722222222", location="B", status="Active")
        c.db.session.add_all([farmer_a, farmer_b])
        c.db.session.flush()
        contribution_a = c.Contribution(
            cooperative_id=coop_a.id,
            farmer_id=farmer_a.id,
            amount=300,
            contribution_date=c.crm_today(),
            category="Membership Fee",
            method="Cash",
            reference="LEDGER-A-001",
            status="Confirmed",
        )
        contribution_b = c.Contribution(
            cooperative_id=coop_b.id,
            farmer_id=farmer_b.id,
            amount=300,
            contribution_date=c.crm_today(),
            category="Membership Fee",
            method="Cash",
            reference="LEDGER-B-001",
            status="Confirmed",
        )
        c.db.session.add_all([contribution_a, contribution_b])
        c.db.session.commit()
        cls.source_a, cls.source_b = contribution_a.id, contribution_b.id

    @classmethod
    def tearDownClass(cls):
        with cls.crm.app.app_context():
            cls.crm.db.session.remove()
            cls.crm.db.drop_all()
            cls.crm.db.engine.dispose()
        cls.tempdir.cleanup()

    def setUp(self):
        self.client = self.crm.app.test_client()

    def login_as(self, key):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess["user_id"] = self.users[key]
            sess["fullname"] = key.title()

    def test_ledger_separation_and_evidence_workflow(self):
        c, l, p = self.crm, self.ledger, self.p7
        with c.app.app_context():
            l.LedgerTransaction.query.delete()
            l.FinanceAccount.query.delete()
            p.CooperativeDocument.query.delete()
            c.db.session.commit()

        self.login_as("treasurer")
        response = self.client.post("/finance/accounts", data={
            "name": "Co-op Bank", "account_type": "Bank Account", "institution": "Test Bank",
            "account_last4": "1234", "opening_balance": "1000",
        })
        self.assertEqual(response.status_code, 302)
        with c.app.app_context():
            account = l.FinanceAccount.query.filter_by(cooperative_id=self.coop_a, name="Co-op Bank").one()
            account_id = account.id

        response = self.client.post("/finance/transactions", data={
            "transaction_type": "Income", "category": "Membership Fee", "amount": "300",
            "transaction_date": c.crm_today().isoformat(), "to_account_id": str(account_id),
            "source_type": "Contribution", "source_id": str(self.source_a),
        })
        self.assertEqual(response.status_code, 302)

        with c.app.app_context():
            tx = l.LedgerTransaction.query.filter_by(cooperative_id=self.coop_a, source_type="Contribution", source_id=self.source_a).one()
            tx_id = tx.id
            self.assertEqual(tx.status, "Pending Confirmation")

        # Recorder cannot approve own transaction.
        response = self.client.post(f"/finance/transactions/{tx_id}/decision", data={"decision": "approve"})
        self.assertEqual(response.status_code, 403)

        # Another cooperative's source record cannot be linked.
        response = self.client.post("/finance/transactions", data={
            "transaction_type": "Income", "category": "Membership Fee", "amount": "300",
            "transaction_date": c.crm_today().isoformat(), "to_account_id": str(account_id),
            "source_type": "Contribution", "source_id": str(self.source_b),
        })
        self.assertEqual(response.status_code, 400)

        self.login_as("chair")
        response = self.client.post(f"/finance/transactions/{tx_id}/decision", data={"decision": "approve"})
        self.assertEqual(response.status_code, 302)
        with c.app.app_context():
            tx = c.db.session.get(l.LedgerTransaction, tx_id)
            self.assertEqual(tx.status, "Confirmed")

        # The same source cannot post twice.
        self.login_as("treasurer")
        response = self.client.post("/finance/transactions", data={
            "transaction_type": "Income", "category": "Membership Fee", "amount": "300",
            "transaction_date": c.crm_today().isoformat(), "to_account_id": str(account_id),
            "source_type": "Contribution", "source_id": str(self.source_a),
        })
        self.assertEqual(response.status_code, 409)

        # Linked evidence must appear on the transaction detail page.
        with c.app.app_context():
            doc = p.CooperativeDocument(
                cooperative_id=self.coop_a,
                document_type="Receipt",
                title="Membership receipt",
                entity_type="LedgerTransaction",
                entity_id=tx_id,
                original_name="receipt.pdf",
                stored_name="ledger-test-receipt.pdf",
                file_sha256="0" * 64,
                uploaded_by_user_id=self.users["treasurer"],
            )
            c.db.session.add(doc)
            c.db.session.commit()

        response = self.client.get(f"/finance/transactions/{tx_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Membership receipt", response.data)
        self.assertIn(b"Attach Evidence", response.data)


if __name__ == "__main__":
    unittest.main()
