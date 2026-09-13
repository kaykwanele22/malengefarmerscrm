import importlib
import os
import tempfile
import unittest
from pathlib import Path


class FinanceControlSourceTruthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory(prefix="malenge_finance_truth_test_")
        cls.db_path = Path(cls.tempdir.name) / "finance_truth.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{cls.db_path.as_posix()}"
        os.environ["SECRET_KEY"] = "finance-source-truth-secret"
        os.environ["APP_ENV"] = "development"
        os.environ["TWO_FACTOR_REQUIRED"] = "false"
        os.environ["DOCUMENT_UPLOAD_DIR"] = str(Path(cls.tempdir.name) / "documents")

        cls.crm = importlib.import_module("app")
        cls.p7 = importlib.import_module("phase7")
        cls.ledger = importlib.import_module("account_ledger")
        cls.crm.app.config.update(TESTING=True, TWO_FACTOR_REQUIRED=False)

        with cls.crm.app.app_context():
            cls.crm.db.create_all()
            cls._seed()

    @classmethod
    def _seed(cls):
        c = cls.crm
        coop = c.Cooperative(
            name="Finance Truth Primary",
            cooperative_type="Primary",
            code="FTP",
            status="Active",
        )
        c.db.session.add(coop)
        c.db.session.flush()
        cls.coop_id = coop.id

        treasurer = c.User(
            fullname="Finance Truth Treasurer",
            phone="0731000001",
            email="treasurer@finance-truth.local",
            farm_location="Malenge",
            password=c.generate_password_hash("Testing123!"),
        )
        chair = c.User(
            fullname="Finance Truth Chairperson",
            phone="0731000002",
            email="chair@finance-truth.local",
            farm_location="Malenge",
            password=c.generate_password_hash("Testing123!"),
        )
        c.db.session.add_all([treasurer, chair])
        c.db.session.flush()
        cls.treasurer_id = treasurer.id
        cls.chair_id = chair.id
        c.db.session.add_all([
            c.UserAccess(user_id=treasurer.id, cooperative_id=coop.id, role="Primary Treasurer", status="Active"),
            c.UserAccess(user_id=chair.id, cooperative_id=coop.id, role="Primary Chairperson", status="Active"),
        ])

        farmer = c.Farmer(
            cooperative_id=coop.id,
            fullname="Finance Truth Member",
            phone="0731000003",
            location="Malenge",
            status="Active",
        )
        c.db.session.add(farmer)
        c.db.session.flush()
        cls.farmer_id = farmer.id
        c.db.session.commit()

    @classmethod
    def tearDownClass(cls):
        with cls.crm.app.app_context():
            cls.crm.db.session.remove()
            cls.crm.db.drop_all()
            cls.crm.db.engine.dispose()
        cls.tempdir.cleanup()

    def setUp(self):
        c, p, l = self.crm, self.p7, self.ledger
        self.client = c.app.test_client()
        with c.app.app_context():
            l.LedgerTransactionRevision.query.delete()
            l.FinanceReconciliation.query.delete()
            l.LedgerTransaction.query.delete()
            l.FinanceAccount.query.delete()
            p.BankReconciliation.query.delete()
            p.Budget.query.delete()
            p.CooperativeDocument.query.delete()
            c.Expense.query.delete()
            c.Contribution.query.delete()
            c.AuditLog.query.delete()
            c.db.session.commit()

    def login_treasurer(self):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess["user_id"] = self.treasurer_id
            sess["fullname"] = "Finance Truth Treasurer"

    def test_finance_control_identifies_account_ledger_as_balance_authority(self):
        c, p = self.crm, self.p7
        today = c.crm_today()
        with c.app.app_context():
            c.db.session.add_all([
                c.Contribution(
                    cooperative_id=self.coop_id,
                    farmer_id=self.farmer_id,
                    amount=100,
                    contribution_date=today,
                    category="General",
                    status="Confirmed",
                ),
                c.Expense(
                    cooperative_id=self.coop_id,
                    category="Fuel",
                    description="Operational source expense",
                    amount=20,
                    expense_date=today,
                    status="Confirmed",
                ),
                p.BankReconciliation(
                    cooperative_id=self.coop_id,
                    statement_date=today,
                    statement_balance=80,
                    book_balance=80,
                    difference=0,
                    status="Reviewed",
                    prepared_by_user_id=self.treasurer_id,
                    reviewed_by_user_id=self.chair_id,
                    reviewed_at=c.utc_now(),
                ),
            ])
            c.db.session.commit()

        self.login_treasurer()
        response = self.client.get("/finance-control")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Financial Source of Truth", response.data)
        self.assertIn(b"Account Ledger", response.data)
        self.assertIn(b"Confirmed Cash &amp; Bank Balance", response.data)
        self.assertIn(b"Open Authoritative Ledger", response.data)
        self.assertIn(b"Operational Source Net", response.data)
        self.assertIn(b"R 80.00", response.data)
        self.assertIn(b"Reference only", response.data)
        self.assertIn(b"not a bank or cash account balance", response.data)
        self.assertIn(b"Legacy Reconciliation History", response.data)
        self.assertIn(b"Historical records only", response.data)
        self.assertIn(b"preserved for audit continuity only", response.data)

        # The retired operational-book reconciliation form must not be exposed in the UI.
        self.assertNotIn(b'name="statement_balance"', response.data)
        self.assertNotIn(b'action="/finance-control/reconciliation"', response.data)
        self.assertIn(b"/finance/reconciliations", response.data)

        reconciliation_page = self.client.get("/finance/reconciliations")
        self.assertEqual(reconciliation_page.status_code, 200)

    def test_legacy_reconciliation_route_remains_backward_compatible_but_not_primary_ui(self):
        c, p = self.crm, self.p7
        today = c.crm_today()
        self.login_treasurer()

        # Existing integrations may still post to the old endpoint. Preserve compatibility
        # while the user interface directs all new work to account-level reconciliation.
        response = self.client.post("/finance-control/reconciliation", data={
            "statement_date": today.isoformat(),
            "statement_balance": "0",
            "notes": "Legacy compatibility test",
        })
        self.assertEqual(response.status_code, 302)
        with c.app.app_context():
            self.assertEqual(p.BankReconciliation.query.filter_by(cooperative_id=self.coop_id).count(), 1)

        page = self.client.get("/finance-control")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Legacy Reconciliation History", page.data)
        self.assertNotIn(b'action="/finance-control/reconciliation"', page.data)
        self.assertIn(b"New reconciliations are recorded per financial account", page.data)


if __name__ == "__main__":
    unittest.main()
