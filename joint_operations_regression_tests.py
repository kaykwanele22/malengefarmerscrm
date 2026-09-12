import importlib
import os
import tempfile
import unittest
from pathlib import Path


class JointOperationsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory(prefix="malenge_jointops_")
        db_path = Path(cls.tempdir.name) / "jointops.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
        os.environ["SECRET_KEY"] = "joint-operations-test-secret"
        os.environ["APP_ENV"] = "development"
        os.environ["TWO_FACTOR_REQUIRED"] = "false"
        os.environ["ALLOW_BOOTSTRAP_REGISTRATION"] = "true"

        cls.crm = importlib.import_module("app")
        cls.jo = importlib.import_module("joint_operations")
        cls.crm.app.config.update(TESTING=True, TWO_FACTOR_REQUIRED=False)
        with cls.crm.app.app_context():
            cls.crm.db.drop_all()
            cls.crm.db.create_all()
            cls._seed()

    @classmethod
    def _make_user(cls, key, role, coop_id):
        c = cls.crm
        user = c.User(
            fullname=key.replace("_", " ").title(), phone=f"070{len(cls.users)+1:07d}",
            email=f"{key}@jointops.test", farm_location="Malenge", password="x",
        )
        c.db.session.add(user)
        c.db.session.flush()
        c.db.session.add(c.UserAccess(user_id=user.id, role=role, status="Active", cooperative_id=coop_id))
        cls.users[key] = user.id

    @classmethod
    def _seed(cls):
        c = cls.crm
        secondary = c.Cooperative(name="MFPSU Joint Test", cooperative_type="Secondary", status="Active")
        c.db.session.add(secondary)
        c.db.session.flush()
        siy = c.Cooperative(name="Siyaphumla Joint Test", cooperative_type="Primary", parent_id=secondary.id, status="Active")
        vim = c.Cooperative(name="Vimba Joint Test", cooperative_type="Primary", parent_id=secondary.id, status="Active")
        c.db.session.add_all([siy, vim])
        c.db.session.flush()
        cls.secondary_id, cls.siy_id, cls.vim_id = secondary.id, siy.id, vim.id
        cls.users = {}
        cls._make_user("sec_chair", "Secondary Chairperson", secondary.id)
        cls._make_user("sec_secretary", "Secondary Secretary", secondary.id)
        cls._make_user("sec_treasurer", "Secondary Treasurer", secondary.id)
        cls._make_user("primary_chair", "Primary Chairperson", siy.id)
        cls._make_user("primary_treasurer", "Primary Treasurer", siy.id)
        farmer = c.Farmer(cooperative_id=siy.id, fullname="Private Primary Farmer", phone="0711111111", location="Malenge", status="Active")
        c.db.session.add(farmer)
        c.db.session.commit()

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
            sess["fullname"] = key
            sess["two_factor_authenticated"] = True

    def test_secondary_executive_can_open_joint_operations_but_primary_cannot(self):
        self.login_as("sec_chair")
        response = self.client.get("/joint-operations")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Joint Operations", page)
        self.assertIn("Siyaphumla Joint Test", page)
        self.assertIn("Vimba Joint Test", page)
        self.assertNotIn("Private Primary Farmer", page)

        self.login_as("primary_chair")
        self.assertEqual(self.client.get("/joint-operations").status_code, 403)

    def test_secretary_creates_project_and_allocates_only_child_primary(self):
        self.login_as("sec_secretary")
        response = self.client.post("/joint-operations/projects", data={
            "title": "Joint Potato Programme", "project_type": "Production Programme",
            "budget_amount": "500000", "status": "Planned",
        })
        self.assertEqual(response.status_code, 302)
        with self.crm.app.app_context():
            project = self.jo.JointProject.query.filter_by(title="Joint Potato Programme").one()
            project_id = project.id
        response = self.client.post(f"/joint-operations/projects/{project_id}/allocation", data={
            "primary_cooperative_id": str(self.siy_id), "allocated_amount": "180000",
            "hectares": "15", "progress_percentage": "70",
        })
        self.assertEqual(response.status_code, 302)
        with self.crm.app.app_context():
            allocation = self.jo.JointProjectAllocation.query.filter_by(project_id=project_id, primary_cooperative_id=self.siy_id).one()
            self.assertEqual(allocation.progress_percentage, 70)
            self.assertEqual(allocation.allocated_amount, 180000)

    def test_secondary_uses_cooperative_contributions_not_farmer_contributions(self):
        self.login_as("sec_treasurer")
        response = self.client.get("/contributions")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/joint-operations", response.headers.get("Location", ""))
        self.assertIn("#primary-contributions", response.headers.get("Location", ""))

        response = self.client.get("/contributions/add")
        self.assertEqual(response.status_code, 302)
        self.assertIn("#primary-contributions", response.headers.get("Location", ""))

        dashboard = self.client.get("/dashboard").get_data(as_text=True)
        self.assertIn("Record Primary Contribution", dashboard)
        self.assertNotIn('href="/contributions/add" class="dash-primary-btn">Record Money', dashboard)

        self.login_as("primary_treasurer")
        response = self.client.get("/contributions/add")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Member / Farmer", page)
        self.assertNotIn("Primary Cooperative Contributions to MFPSU", page)

    def test_treasurer_records_primary_contribution_and_chair_confirms(self):
        year = self.crm.crm_today().year
        self.login_as("sec_treasurer")
        response = self.client.post("/joint-operations/contribution-accounts", data={
            "primary_cooperative_id": str(self.siy_id), "fiscal_year": str(year),
            "expected_amount": "1000",
        })
        self.assertEqual(response.status_code, 302)
        with self.crm.app.app_context():
            account = self.jo.PrimaryContributionAccount.query.filter_by(primary_cooperative_id=self.siy_id, fiscal_year=year).one()
            account_id = account.id
        response = self.client.post(f"/joint-operations/contribution-accounts/{account_id}/payments", data={
            "amount": "1000", "payment_date": self.crm.crm_today().isoformat(),
            "method": "Bank", "reference": "SYP-001",
        })
        self.assertEqual(response.status_code, 302)
        with self.crm.app.app_context():
            payment = self.jo.PrimaryContributionPayment.query.filter_by(account_id=account_id).one()
            payment_id = payment.id
            self.assertEqual(payment.status, "Pending Confirmation")

        self.login_as("sec_chair")
        response = self.client.post(f"/joint-operations/contribution-payments/{payment_id}/decision", data={"decision": "approve"})
        self.assertEqual(response.status_code, 302)
        with self.crm.app.app_context():
            payment = self.crm.db.session.get(self.jo.PrimaryContributionPayment, payment_id)
            self.assertEqual(payment.status, "Confirmed")
            account = self.crm.db.session.get(self.jo.PrimaryContributionAccount, account_id)
            self.assertEqual(account.outstanding_amount, 0)

    def test_treasurer_submits_procurement_and_chair_approves(self):
        self.login_as("sec_treasurer")
        response = self.client.post("/joint-operations/procurements", data={
            "title": "Bulk Seed", "category": "Seed", "quantity": "100",
            "unit": "bags", "estimated_cost": "50000",
        })
        self.assertEqual(response.status_code, 302)
        with self.crm.app.app_context():
            item = self.jo.JointProcurement.query.filter_by(title="Bulk Seed").one()
            item_id = item.id
            self.assertEqual(item.status, "Pending Approval")
        self.login_as("sec_chair")
        response = self.client.post(f"/joint-operations/procurements/{item_id}/decision", data={"decision": "approve"})
        self.assertEqual(response.status_code, 302)
        with self.crm.app.app_context():
            self.assertEqual(self.crm.db.session.get(self.jo.JointProcurement, item_id).status, "Approved")

    def test_primary_summary_is_aggregate_only(self):
        self.login_as("sec_chair")
        response = self.client.get(f"/joint-operations/primary/{self.siy_id}")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Aggregate Only", page)
        self.assertIn("Siyaphumla Joint Test", page)
        self.assertNotIn("Private Primary Farmer", page)


if __name__ == "__main__":
    unittest.main(verbosity=2)
