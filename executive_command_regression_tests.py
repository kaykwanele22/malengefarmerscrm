import importlib
import os
import tempfile
import unittest
from pathlib import Path


class ExecutiveCommandRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory(prefix="malenge_exec_command_")
        cls.db_path = Path(cls.tempdir.name) / "executive_command.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{cls.db_path.as_posix()}"
        os.environ["SECRET_KEY"] = "executive-command-regression-secret"
        os.environ["APP_ENV"] = "development"
        os.environ["TWO_FACTOR_REQUIRED"] = "false"
        os.environ["DOCUMENT_UPLOAD_DIR"] = str(Path(cls.tempdir.name) / "documents")
        os.environ["ACCOUNTABILITY_UPLOAD_DIR"] = str(Path(cls.tempdir.name) / "accountability")
        os.environ["RECOVERY_BUNDLE_DIR"] = str(Path(cls.tempdir.name) / "recovery")

        cls.crm = importlib.import_module("app")
        cls.ledger = importlib.import_module("account_ledger")
        cls.phase7 = importlib.import_module("phase7")
        cls.crm.app.config.update(TESTING=True, TWO_FACTOR_REQUIRED=False)

        with cls.crm.app.app_context():
            cls.crm.db.create_all()
            cls._seed()

    @classmethod
    def _seed(cls):
        c = cls.crm
        secondary = c.Cooperative(name="Executive Secondary", cooperative_type="Secondary", status="Active")
        primary = c.Cooperative(name="Executive Primary", cooperative_type="Primary", parent=secondary, status="Active")
        c.db.session.add_all([secondary, primary])
        c.db.session.flush()
        cls.secondary_id = secondary.id
        cls.primary_id = primary.id

        users = {
            "admin": ("Admin", None),
            "chair": ("Primary Chairperson", primary.id),
            "secretary": ("Primary Secretary", primary.id),
            "treasurer": ("Primary Treasurer", primary.id),
            "secondary_chair": ("Secondary Chairperson", secondary.id),
            "secondary_secretary": ("Secondary Secretary", secondary.id),
        }
        cls.user_ids = {}
        for key, (role, cooperative_id) in users.items():
            user = c.User(
                fullname=key.replace("_", " ").title(),
                phone="0700000000",
                email=f"{key}@exec-command.local",
                farm_location="Malenge",
                password=c.generate_password_hash("Testing123!"),
            )
            c.db.session.add(user)
            c.db.session.flush()
            c.db.session.add(c.UserAccess(
                user_id=user.id,
                role=role,
                status="Active",
                cooperative_id=cooperative_id,
            ))
            cls.user_ids[key] = user.id

        farmer = c.Farmer(
            cooperative_id=primary.id,
            fullname="Command Farmer",
            phone="0711111111",
            location="Malenge",
            status="Active",
        )
        c.db.session.add(farmer)
        c.db.session.flush()
        c.db.session.add(c.Membership(
            cooperative_id=primary.id,
            farmer_id=farmer.id,
            member_number="CMD-001",
            membership_type="Primary",
            fee_amount=300,
            fee_paid=0,
            status="Active",
        ))
        c.db.session.flush()

        account = cls.ledger.FinanceAccount(
            cooperative_id=primary.id,
            name="Main Bank",
            account_type="Bank Account",
            opening_balance=1000,
            opening_balance_date=c.crm_today(),
            status="Active",
            created_by_user_id=cls.user_ids["treasurer"],
        )
        c.db.session.add(account)
        c.db.session.flush()
        c.db.session.add_all([
            cls.ledger.LedgerTransaction(
                cooperative_id=primary.id, transaction_type="Income", category="Loan", amount=3000000,
                transaction_date=c.crm_today(), to_account_id=account.id, status="Confirmed",
                recorded_by_user_id=cls.user_ids["treasurer"], decided_by_user_id=cls.user_ids["chair"],
            ),
            cls.ledger.LedgerTransaction(
                cooperative_id=primary.id, transaction_type="Income", category="Product Sale", amount=25000,
                transaction_date=c.crm_today(), to_account_id=account.id, status="Confirmed",
                recorded_by_user_id=cls.user_ids["treasurer"], decided_by_user_id=cls.user_ids["chair"],
            ),
            cls.ledger.LedgerTransaction(
                cooperative_id=primary.id, transaction_type="Expense", category="Farm Inputs", amount=5000,
                transaction_date=c.crm_today(), from_account_id=account.id, status="Confirmed",
                recorded_by_user_id=cls.user_ids["treasurer"], decided_by_user_id=cls.user_ids["chair"],
            ),
            cls.ledger.LedgerTransaction(
                cooperative_id=primary.id, transaction_type="Expense", category="Transport", amount=7500,
                transaction_date=c.crm_today(), from_account_id=account.id, status="Pending Confirmation",
                recorded_by_user_id=cls.user_ids["treasurer"],
            ),
            cls.ledger.LedgerTransaction(
                cooperative_id=primary.id, transaction_type="Expense", category="Packaging", amount=2500,
                transaction_date=c.crm_today(), from_account_id=account.id, status="Rejected",
                recorded_by_user_id=cls.user_ids["treasurer"], decided_by_user_id=cls.user_ids["chair"],
                decision_note="Correct the supporting reference.",
            ),
        ])
        c.db.session.add(cls.phase7.Budget(
            cooperative_id=primary.id, fiscal_year=c.crm_today().year, budget_type="Expense",
            category="Farm Inputs", planned_amount=120000, status="Pending Approval",
            created_by_user_id=cls.user_ids["treasurer"],
        ))
        c.db.session.add(cls.phase7.BankReconciliation(
            cooperative_id=primary.id, statement_date=c.crm_today(), statement_balance=3021000,
            book_balance=3021000, difference=0, status="Pending Review",
            prepared_by_user_id=cls.user_ids["treasurer"],
        ))
        c.db.session.commit()

    @classmethod
    def tearDownClass(cls):
        with cls.crm.app.app_context():
            cls.crm.db.session.remove()
            cls.crm.db.drop_all()
            cls.crm.db.session.remove()
            cls.crm.db.engine.dispose()
        cls.tempdir.cleanup()

    def setUp(self):
        self.client = self.crm.app.test_client()

    def login_as(self, key):
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user_ids[key]
            sess["fullname"] = key

    def test_primary_chair_dashboard_uses_command_centre(self):
        self.login_as("chair")
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Executive Command Centre", response.data)
        self.assertIn(b"Governance Pulse", response.data)
        self.assertIn(b"Finance Pulse", response.data)
        self.assertIn(b"Membership &amp; production snapshot", response.data)

    def test_primary_chair_gets_decision_centre_and_financial_composition(self):
        self.login_as("chair")
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Chairperson Decision Centre", page)
        self.assertIn("R 7,500.00 awaiting confirmation", page)
        self.assertIn("R 120,000.00 awaiting approval", page)
        self.assertIn("Reconciliations", page)
        self.assertIn("Financial Composition", page)
        self.assertIn("R 3,000,000.00", page)
        self.assertIn("R 25,000.00", page)
        self.assertIn("R 5,000.00", page)

    def test_treasurer_does_not_get_chairperson_decision_centre(self):
        self.login_as("treasurer")
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"Chairperson Decision Centre", response.data)
        self.assertNotIn(b"Financial Composition", response.data)

    def test_primary_secretary_does_not_receive_finance_ledger_snapshot(self):
        self.login_as("secretary")
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Executive Command Centre", response.data)
        self.assertIn(b"Membership &amp; production snapshot", response.data)
        self.assertNotIn(b"Finance Pulse", response.data)
        self.assertNotIn(b"Confirmed Balance", response.data)

    def test_primary_treasurer_sees_ledger_source_of_truth(self):
        self.login_as("treasurer")
        response = self.client.get("/executive-command-centre")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Finance Pulse", response.data)
        self.assertIn(b"Source of truth", response.data)

    def test_membership_fee_anomaly_is_excluded_from_treasurer_receivables(self):
        c = self.crm
        with c.app.app_context():
            farmer = c.Farmer(
                cooperative_id=self.primary_id,
                fullname="Bad Fee Member",
                phone="0799999999",
                location="Malenge",
                status="Active",
            )
            c.db.session.add(farmer)
            c.db.session.flush()
            c.db.session.add(c.Membership(
                cooperative_id=self.primary_id,
                farmer_id=farmer.id,
                member_number="CMD-BAD-FEE",
                membership_type="Primary",
                fee_amount=3000000,
                fee_paid=0,
                status="Active",
            ))
            c.db.session.commit()

        self.login_as("treasurer")
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Membership fee data needs review", page)
        self.assertIn("R 300.00", page)

        with c.app.app_context():
            c.Membership.query.filter_by(member_number="CMD-BAD-FEE").delete()
            c.Farmer.query.filter_by(fullname="Bad Fee Member").delete()
            c.db.session.commit()

    def test_primary_treasurer_gets_work_centre_without_approval_authority(self):
        self.login_as("treasurer")
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Treasurer Work Centre", page)
        self.assertIn("R 7,500.00 recorded and awaiting independent confirmation", page)
        self.assertIn("R 2,500.00 requires Treasurer correction", page)
        self.assertIn("1 budget line", page)
        self.assertIn("1 reconciliation", page)
        self.assertIn("Evidence Missing", page)
        self.assertIn(">4<", page)
        self.assertNotIn("Decisions requiring your authority", page)


    def test_secondary_secretary_sees_network_summary_without_finance(self):
        self.login_as("secondary_secretary")
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Primary governance &amp; reporting status", response.data)
        self.assertIn(b"Executive Primary", response.data)
        self.assertIn(b"Secondary portal rule", response.data)
        self.assertNotIn(b"Confirmed Balance", response.data)

    def test_secondary_chair_cannot_see_primary_internal_financial_position(self):
        self.login_as("secondary_chair")
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Primary governance &amp; reporting status", page)
        self.assertIn("Primary → Secondary Contribution", page)
        self.assertIn("Joint Allocation", page)
        self.assertNotIn("R 3,000,000.00", page)
        self.assertNotIn("R 25,000.00", page)
        self.assertNotIn("Primary Book Position", page)
        self.assertNotIn("Confirmed Sale Payments", page)
        self.assertNotIn("Confirmed Member Contributions", page)

    def test_admin_keeps_system_administration_dashboard(self):
        self.login_as("admin")
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"CRM Administration Dashboard", response.data)
        self.assertNotIn(b"Executive Command Centre", response.data)

    def test_admin_cannot_open_executive_command_centre_directly(self):
        self.login_as("admin")
        response = self.client.get("/executive-command-centre")
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main(verbosity=2)
