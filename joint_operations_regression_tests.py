import importlib
import os
import tempfile
import unittest
from pathlib import Path


class JointOperationsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory(prefix="malenge_joint_ops_test_")
        cls.db_path = Path(cls.tempdir.name) / "joint_ops.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{cls.db_path.as_posix()}"
        os.environ["SECRET_KEY"] = "malenge-joint-operations-secret"
        os.environ["APP_ENV"] = "development"

        cls.crm = importlib.import_module("app")
        cls.jo = importlib.import_module("joint_operations")
        cls.crm.app.config.update(TESTING=True, TWO_FACTOR_REQUIRED=False)

        with cls.crm.app.app_context():
            cls.crm.db.create_all()
            cls._seed_data()

    @classmethod
    def _seed_data(cls):
        c = cls.crm
        secondary = c.Cooperative(name="Malenge Secondary Joint Test", cooperative_type="Secondary", code="MFPSU", status="Active")
        siy = c.Cooperative(name="Siyaphumla Joint Test", cooperative_type="Primary", parent=secondary, code="SIYA", status="Active")
        vim = c.Cooperative(name="Vimba Joint Test", cooperative_type="Primary", parent=secondary, code="VIMBA", status="Active")
        c.db.session.add_all([secondary, siy, vim])
        c.db.session.flush()
        cls.secondary_id = secondary.id
        cls.siy_id = siy.id
        cls.vim_id = vim.id

        roles = {
            "sec_chair": ("Secondary Chairperson", secondary.id),
            "sec_vice": ("Secondary Vice Chairperson", secondary.id),
            "sec_secretary": ("Secondary Secretary", secondary.id),
            "sec_vice_secretary": ("Secondary Vice Secretary", secondary.id),
            "sec_treasurer": ("Secondary Treasurer", secondary.id),
            "primary_treasurer": ("Primary Treasurer", siy.id),
            "primary_chair": ("Primary Chairperson", siy.id),
        }
        cls.user_ids = {}
        for index, (key, (role, coop_id)) in enumerate(roles.items(), start=1):
            user = c.User(
                fullname=key.replace("_", " ").title(),
                phone=f"076{index:07d}",
                email=f"{key}@joint.local",
                farm_location="Malenge",
                password=c.generate_password_hash("Testing123!"),
            )
            c.db.session.add(user)
            c.db.session.flush()
            c.db.session.add(c.UserAccess(user_id=user.id, role=role, status="Active", cooperative_id=coop_id))
            cls.user_ids[key] = user.id

        farmer = c.Farmer(cooperative_id=siy.id, fullname="Joint Farmer", phone="0711111111", location="Malenge", status="Active")
        c.db.session.add(farmer)
        c.db.session.flush()
        farm = c.Farm(cooperative_id=siy.id, name="Joint Farm", farmer_id=farmer.id, location="Malenge", size=20, status="Active")
        c.db.session.add(farm)
        c.db.session.flush()
        crop = c.Crop(cooperative_id=siy.id, name="Potatoes", farm_id=farm.id, area_planted=10, status="Growing")
        c.db.session.add(crop)
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
        c = self.crm
        with c.app.app_context():
            self.jo.PrimaryContributionPayment.query.delete()
            self.jo.PrimaryContributionAccount.query.delete()
            self.jo.JointProcurement.query.delete()
            self.jo.JointProjectAllocation.query.delete()
            self.jo.JointProject.query.delete()
            c.AuditLog.query.delete()
            c.db.session.commit()
        self.client = c.app.test_client()

    def login_as(self, key):
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user_ids[key]
            sess["fullname"] = key

    def test_secondary_executive_can_open_joint_operations_but_primary_cannot(self):
        self.login_as("sec_secretary")
        self.assertEqual(self.client.get("/joint-operations").status_code, 200)
        self.login_as("primary_chair")
        self.assertEqual(self.client.get("/joint-operations").status_code, 403)

    def test_secretary_creates_project_and_allocates_only_child_primary(self):
        self.login_as("sec_secretary")
        response = self.client.post("/joint-operations/projects", data={
            "title": "Joint Potato Programme", "project_type": "Production Programme",
            "budget_amount": "500000", "status": "In Progress",
        })
        self.assertEqual(response.status_code, 302)
        with self.crm.app.app_context():
            project = self.jo.JointProject.query.one()
            project_id = project.id
        response = self.client.post(f"/joint-operations/projects/{project_id}/allocations", data={
            "primary_cooperative_id": str(self.siy_id), "allocated_amount": "180000", "allocated_area_hectares": "15",
            "progress_percentage": "70", "status": "In Progress",
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
        self.assertIn("Member with Outstanding Contribution", page)
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
            "method": "Bank Transfer", "reference": "S-JOINT-1",
        })
        self.assertEqual(response.status_code, 302)
        with self.crm.app.app_context():
            payment = self.jo.PrimaryContributionPayment.query.one()
            self.assertEqual(payment.status, "Pending Confirmation")
            payment_id = payment.id

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
            "title": "Joint seed purchase", "category": "Inputs", "quantity": "100", "unit": "bags",
            "estimated_cost": "75000",
        })
        self.assertEqual(response.status_code, 302)
        with self.crm.app.app_context():
            item = self.jo.JointProcurement.query.one()
            self.assertEqual(item.status, "Pending Approval")
            procurement_id = item.id

        self.login_as("sec_chair")
        response = self.client.post(f"/joint-operations/procurements/{procurement_id}/decision", data={"decision": "approve"})
        self.assertEqual(response.status_code, 302)
        with self.crm.app.app_context():
            item = self.crm.db.session.get(self.jo.JointProcurement, procurement_id)
            self.assertEqual(item.status, "Approved")

    def test_primary_summary_is_aggregate_only(self):
        self.login_as("sec_chair")
        response = self.client.get(f"/joint-operations/primaries/{self.siy_id}")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Joint Farmer", page)
        self.assertIn("Joint Farm", page)
        self.assertNotIn("/farmers/edit/", page)
        self.assertNotIn("/farms/edit/", page)


if __name__ == "__main__":
    unittest.main(verbosity=2)
