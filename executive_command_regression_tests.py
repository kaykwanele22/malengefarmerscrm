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

        c.db.session.add(cls.ledger.FinanceAccount(
            cooperative_id=primary.id,
            name="Main Bank",
            account_type="Bank Account",
            opening_balance=1000,
            opening_balance_date=c.crm_today(),
            status="Active",
            created_by_user_id=cls.user_ids["treasurer"],
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
        self.assertIn(b"R 1,000.00", response.data)
        self.assertIn(b"Source of truth", response.data)

    def test_secondary_secretary_sees_network_summary_without_finance(self):
        self.login_as("secondary_secretary")
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Primary cooperative summary", response.data)
        self.assertIn(b"Executive Primary", response.data)
        self.assertIn(b"Entity boundary", response.data)
        self.assertNotIn(b"Confirmed Balance", response.data)

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
