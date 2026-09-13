import os
import unittest
from pathlib import Path

DB_PATH = "/tmp/malenge_secondary_scope_test.db"
try:
    Path(DB_PATH).unlink()
except FileNotFoundError:
    pass

os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ["SECRET_KEY"] = "secondary-scope-test-secret"
os.environ["APP_ENV"] = "development"
os.environ["TWO_FACTOR_REQUIRED"] = "false"
os.environ["ALLOW_BOOTSTRAP_REGISTRATION"] = "true"

import app as crm


class SecondaryJointScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        crm.app.config.update(TESTING=True)
        with crm.app.app_context():
            crm.db.drop_all()
            crm.db.create_all()

            secondary = crm.Cooperative(name="MFPSU", cooperative_type="Secondary", status="Active")
            crm.db.session.add(secondary)
            crm.db.session.flush()
            siyaphumla = crm.Cooperative(name="Siyaphumla", cooperative_type="Primary", parent_id=secondary.id, status="Active")
            vimba = crm.Cooperative(name="Vimba", cooperative_type="Primary", parent_id=secondary.id, status="Active")
            crm.db.session.add_all([siyaphumla, vimba])
            crm.db.session.flush()

            sec_chair = crm.User(fullname="Secondary Chair", phone="1", email="secchair@example.test", farm_location="Malenge", password="x")
            sec_secretary = crm.User(fullname="Secondary Secretary", phone="2", email="secsecretary@example.test", farm_location="Malenge", password="x")
            primary_chair = crm.User(fullname="Primary Chair", phone="3", email="primarychair@example.test", farm_location="Malenge", password="x")
            crm.db.session.add_all([sec_chair, sec_secretary, primary_chair])
            crm.db.session.flush()
            crm.db.session.add_all([
                crm.UserAccess(user_id=sec_chair.id, role="Secondary Chairperson", status="Active", cooperative_id=secondary.id),
                crm.UserAccess(user_id=sec_secretary.id, role="Secondary Secretary", status="Active", cooperative_id=secondary.id),
                crm.UserAccess(user_id=primary_chair.id, role="Primary Chairperson", status="Active", cooperative_id=siyaphumla.id),
            ])
            crm.db.session.add_all([
                crm.Farmer(cooperative_id=siyaphumla.id, fullname="Siyaphumla Farmer", phone="10", location="Siyaphumla", status="Active"),
                crm.Farmer(cooperative_id=vimba.id, fullname="Vimba Farmer", phone="11", location="Vimba", status="Active"),
            ])
            crm.db.session.commit()
            cls.secondary_id = secondary.id
            cls.siyaphumla_id = siyaphumla.id
            cls.vimba_id = vimba.id
            cls.sec_chair_id = sec_chair.id
            cls.sec_secretary_id = sec_secretary.id
            cls.primary_chair_id = primary_chair.id

    def setUp(self):
        self.client = crm.app.test_client()

    def login_as(self, user_id):
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id
            sess["fullname"] = "Test User"
            sess["two_factor_authenticated"] = True

    def test_secondary_raw_scope_is_secondary_only(self):
        with crm.app.app_context():
            self.assertEqual(crm.accessible_cooperative_ids(self.sec_chair_id), [self.secondary_id])
            self.assertFalse(crm.can_access_cooperative(self.siyaphumla_id, self.sec_chair_id))
            self.assertFalse(crm.can_access_cooperative(self.vimba_id, self.sec_chair_id))
            self.assertEqual(crm.scoped_model_query(crm.Farmer, user_id=self.sec_chair_id).count(), 0)

    def test_secondary_cannot_open_primary_individual_registers(self):
        self.login_as(self.sec_chair_id)
        self.assertEqual(self.client.get("/farmers").status_code, 403)
        self.assertEqual(self.client.get("/memberships").status_code, 403)
        self.assertEqual(self.client.get("/farms").status_code, 403)
        self.assertEqual(self.client.get("/crops").status_code, 403)
        self.assertEqual(self.client.get("/harvests").status_code, 403)

    def test_secondary_joint_governance_and_finance_remain_available(self):
        self.login_as(self.sec_chair_id)
        self.assertEqual(self.client.get("/meetings").status_code, 200)
        self.assertEqual(self.client.get("/accountability").status_code, 200)
        self.assertEqual(self.client.get("/finance-control").status_code, 200)

    def test_secondary_dashboard_keeps_aggregate_primary_summary_only(self):
        self.login_as(self.sec_chair_id)
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Siyaphumla", page)
        self.assertIn("Vimba", page)
        self.assertIn("Secondary portal rule", page)
        self.assertNotIn("Siyaphumla Farmer", page)
        self.assertNotIn("Vimba Farmer", page)
        self.assertNotIn('href="/farmers"', page)
        self.assertNotIn('href="/memberships"', page)
        self.assertNotIn('href="/farms"', page)
        self.assertNotIn('href="/crops"', page)
        self.assertNotIn('href="/harvests"', page)

    def test_legacy_secondary_dashboard_contains_no_primary_finance_columns(self):
        template_path = Path(__file__).parent / "templates" / "dashboard.html"
        template = template_path.read_text(encoding="utf-8")
        secondary_start = template.index('{% if is_secondary %}', template.index('Primary Cooperative Network'))
        secondary_end = template.index('{% endif %}', secondary_start)
        section = template[secondary_start:secondary_end]
        self.assertNotIn("Primary Financial Summary", section)
        self.assertNotIn("<th>Cash Position</th>", section)
        self.assertNotIn("<th>Pending Approval</th>", section)
        self.assertNotIn("item.cash_position", section)
        self.assertNotIn("item.pending_finance", section)

    def test_secondary_primary_summary_hides_internal_primary_finance(self):
        self.login_as(self.sec_chair_id)
        response = self.client.get(f"/joint-operations/primary/{self.siyaphumla_id}")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Primary → MFPSU", page)
        self.assertIn("MFPSU Joint Allocation", page)
        self.assertNotIn("Primary Book Position", page)
        self.assertNotIn("Confirmed Sale Payments", page)
        self.assertNotIn("Confirmed Member Contributions", page)
        self.assertIn("internal bank balances", page.lower())

    def test_secondary_secretary_is_not_a_primary_membership_manager(self):
        self.login_as(self.sec_secretary_id)
        self.assertEqual(self.client.get("/farmers").status_code, 403)
        self.assertEqual(self.client.get("/memberships").status_code, 403)
        dashboard = self.client.get("/dashboard").get_data(as_text=True)
        self.assertIn("Joint Governance &amp; Records", dashboard)
        self.assertNotIn("Register Member", dashboard)

    def test_primary_portal_keeps_primary_records(self):
        self.login_as(self.primary_chair_id)
        self.assertEqual(self.client.get("/farmers").status_code, 200)
        self.assertEqual(self.client.get("/memberships").status_code, 200)
        page = self.client.get("/farmers").get_data(as_text=True)
        self.assertIn("Siyaphumla Farmer", page)
        self.assertNotIn("Vimba Farmer", page)


if __name__ == "__main__":
    unittest.main(verbosity=2)
