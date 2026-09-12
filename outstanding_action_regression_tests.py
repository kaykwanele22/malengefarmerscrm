import importlib
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path


class OutstandingActionRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory(prefix="malenge_outstanding_action_")
        cls.db_path = Path(cls.tempdir.name) / "outstanding.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{cls.db_path.as_posix()}"
        os.environ["SECRET_KEY"] = "malenge-outstanding-action-secret"
        os.environ["APP_ENV"] = "development"

        cls.crm = importlib.import_module("app")
        cls.pp = importlib.import_module("primary_production")
        cls.jo = importlib.import_module("joint_operations")
        cls.crm.app.config.update(TESTING=True, TWO_FACTOR_REQUIRED=False)

        with cls.crm.app.app_context():
            cls.crm.db.create_all()
            cls._seed_data()

    @classmethod
    def _seed_data(cls):
        c = cls.crm
        pp = cls.pp
        jo = cls.jo

        secondary = c.Cooperative(name="Malenge Action Secondary", cooperative_type="Secondary", code="MACT", status="Active")
        primary_a = c.Cooperative(name="Siyaphumla Action Primary", cooperative_type="Primary", parent=secondary, code="SACT", status="Active")
        primary_b = c.Cooperative(name="Vimba Action Primary", cooperative_type="Primary", parent=secondary, code="VACT", status="Active")
        c.db.session.add_all([secondary, primary_a, primary_b])
        c.db.session.flush()
        cls.secondary_id = secondary.id
        cls.primary_a_id = primary_a.id
        cls.primary_b_id = primary_b.id

        roles = {
            "primary_secretary": ("Primary Secretary", primary_a.id),
            "primary_treasurer": ("Primary Treasurer", primary_a.id),
            "primary_chair": ("Primary Chairperson", primary_a.id),
            "primary_vice": ("Primary Vice Chairperson", primary_a.id),
            "secondary_treasurer": ("Secondary Treasurer", secondary.id),
            "secondary_chair": ("Secondary Chairperson", secondary.id),
        }
        cls.user_ids = {}
        for index, (key, (role, coop_id)) in enumerate(roles.items(), start=1):
            user = c.User(
                fullname=key.replace("_", " ").title(),
                phone=f"079900{index:04d}",
                email=f"{key}@outstanding.local",
                farm_location="Malenge",
                password=c.generate_password_hash("Testing123!"),
            )
            c.db.session.add(user)
            c.db.session.flush()
            c.db.session.add(c.UserAccess(user_id=user.id, role=role, status="Active", cooperative_id=coop_id))
            cls.user_ids[key] = user.id

        due_farmer = c.Farmer(cooperative_id=primary_a.id, fullname="Due Member", phone="0710000001", location="Malenge", status="Active")
        paid_farmer = c.Farmer(cooperative_id=primary_a.id, fullname="Paid Member", phone="0710000002", location="Malenge", status="Active")
        new_farmer = c.Farmer(cooperative_id=primary_a.id, fullname="New Farmer", phone="0710000003", location="Malenge", status="Active")
        c.db.session.add_all([due_farmer, paid_farmer, new_farmer])
        c.db.session.flush()
        cls.due_farmer_id = due_farmer.id
        cls.paid_farmer_id = paid_farmer.id
        cls.new_farmer_id = new_farmer.id

        due_membership = c.Membership(
            cooperative_id=primary_a.id, farmer_id=due_farmer.id, member_number="SACT-0001",
            membership_type="Primary", join_date=date.today(), fee_amount=300, fee_paid=100, status="Active"
        )
        paid_membership = c.Membership(
            cooperative_id=primary_a.id, farmer_id=paid_farmer.id, member_number="SACT-0002",
            membership_type="Primary", join_date=date.today(), fee_amount=300, fee_paid=300, status="Active"
        )
        c.db.session.add_all([due_membership, paid_membership])
        c.db.session.flush()
        cls.due_membership_id = due_membership.id
        cls.paid_membership_id = paid_membership.id

        farm = c.Farm(cooperative_id=primary_a.id, name="Action Farm", farmer_id=due_farmer.id, location="Malenge", size=20, status="Active")
        c.db.session.add(farm)
        c.db.session.flush()
        cls.farm_id = farm.id

        active_crop = c.Crop(
            cooperative_id=primary_a.id, name="Action Potatoes", farm_id=farm.id,
            planting_date=date.today(), area_planted=10, status="Growing"
        )
        finished_crop = c.Crop(
            cooperative_id=primary_a.id, name="Finished Maize", farm_id=farm.id,
            planting_date=date.today(), area_planted=5, status="Harvested"
        )
        c.db.session.add_all([active_crop, finished_crop])
        c.db.session.flush()
        cls.active_crop_id = active_crop.id
        cls.finished_crop_id = finished_crop.id

        open_harvest = c.Harvest(
            cooperative_id=primary_a.id, crop_id=active_crop.id, harvest_date=date.today(),
            quantity=100, unit="kg", status="Available"
        )
        sold_harvest = c.Harvest(
            cooperative_id=primary_a.id, crop_id=finished_crop.id, harvest_date=date.today(),
            quantity=50, unit="kg", status="Sold"
        )
        c.db.session.add_all([open_harvest, sold_harvest])
        c.db.session.flush()
        cls.open_harvest_id = open_harvest.id
        cls.sold_harvest_id = sold_harvest.id

        sold_sale = c.Sale(
            cooperative_id=primary_a.id, harvest_id=sold_harvest.id, buyer_name="Sold Buyer",
            quantity=50, unit="kg", price_per_unit=2, total_amount=100,
            sale_date=date.today(), status="Completed"
        )
        unpaid_sale = c.Sale(
            cooperative_id=primary_a.id, harvest_id=open_harvest.id, buyer_name="Outstanding Buyer",
            quantity=20, unit="kg", price_per_unit=5, total_amount=100,
            sale_date=date.today(), status="Completed"
        )
        paid_sale = c.Sale(
            cooperative_id=primary_a.id, harvest_id=open_harvest.id, buyer_name="Paid Buyer",
            quantity=10, unit="kg", price_per_unit=5, total_amount=50,
            sale_date=date.today(), status="Completed"
        )
        c.db.session.add_all([sold_sale, unpaid_sale, paid_sale])
        c.db.session.flush()
        cls.unpaid_sale_id = unpaid_sale.id
        cls.paid_sale_id = paid_sale.id
        c.db.session.add(c.Payment(
            cooperative_id=primary_a.id, sale_id=paid_sale.id, amount=50,
            payment_date=date.today(), status="Received"
        ))

        equipment = c.Equipment(
            cooperative_id=primary_a.id, name="Action Tractor", equipment_type="Tractor",
            farm_id=farm.id, status="Available"
        )
        c.db.session.add(equipment)
        c.db.session.flush()
        cls.equipment_id = equipment.id

        completed_plan = pp.ProductionPlan(
            cooperative_id=primary_a.id, crop_id=finished_crop.id,
            target_yield_per_ha_kg=1000, approved_budget=10000,
            status="Completed", created_by_user_id=cls.user_ids["primary_vice"]
        )
        c.db.session.add(completed_plan)
        c.db.session.flush()
        cls.completed_plan_id = completed_plan.id

        full_account = jo.PrimaryContributionAccount(
            secondary_cooperative_id=secondary.id, primary_cooperative_id=primary_a.id,
            fiscal_year=date.today().year, expected_amount=1000,
            created_by_user_id=cls.user_ids["secondary_treasurer"]
        )
        due_account = jo.PrimaryContributionAccount(
            secondary_cooperative_id=secondary.id, primary_cooperative_id=primary_b.id,
            fiscal_year=date.today().year, expected_amount=1000,
            created_by_user_id=cls.user_ids["secondary_treasurer"]
        )
        c.db.session.add_all([full_account, due_account])
        c.db.session.flush()
        cls.full_account_id = full_account.id
        cls.due_account_id = due_account.id
        c.db.session.add(jo.PrimaryContributionPayment(
            account_id=full_account.id, secondary_cooperative_id=secondary.id,
            primary_cooperative_id=primary_a.id, amount=1000, payment_date=date.today(),
            status="Confirmed", recorded_by_user_id=cls.user_ids["secondary_treasurer"],
            decided_by_user_id=cls.user_ids["secondary_chair"]
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

    def test_membership_create_hides_people_already_registered(self):
        self.login_as("primary_secretary")
        html = self.client.get("/memberships/add").get_data(as_text=True)
        self.assertIn("New Farmer", html)
        self.assertNotIn("Due Member", html)
        self.assertNotIn("Paid Member", html)

    def test_record_contribution_hides_fully_settled_member(self):
        self.login_as("primary_treasurer")
        html = self.client.get("/contributions/add").get_data(as_text=True)
        self.assertIn("Due Member", html)
        self.assertNotIn("Paid Member", html)
        self.assertIn("Member with Outstanding Contribution", html)

    def test_harvest_create_hides_fully_harvested_crop(self):
        self.login_as("primary_chair")
        html = self.client.get("/harvests/add").get_data(as_text=True)
        self.assertIn("Action Potatoes", html)
        self.assertNotIn("Finished Maize", html)
        response = self.client.post("/harvests/add", data={
            "crop_id": str(self.finished_crop_id), "harvest_date": date.today().isoformat(),
            "quantity": "1", "unit": "kg", "status": "Available"
        })
        self.assertEqual(response.status_code, 303)

    def test_sale_create_hides_exhausted_harvest(self):
        self.login_as("primary_treasurer")
        html = self.client.get("/sales/add").get_data(as_text=True)
        self.assertIn("Action Potatoes", html)
        self.assertNotIn("Finished Maize", html)

    def test_payment_create_hides_fully_recorded_sale(self):
        self.login_as("primary_treasurer")
        html = self.client.get("/payments/add").get_data(as_text=True)
        self.assertIn("Outstanding Buyer", html)
        self.assertNotIn("Paid Buyer", html)

    def test_joint_contribution_completed_account_cannot_receive_more(self):
        self.login_as("secondary_treasurer")
        response = self.client.post(
            f"/joint-operations/contribution-accounts/{self.full_account_id}/payments",
            data={"amount": "1", "payment_date": date.today().isoformat()},
        )
        self.assertEqual(response.status_code, 303)
        html = self.client.get(f"/joint-operations?year={date.today().year}").get_data(as_text=True)
        self.assertIn("No action due", html)

    def test_closed_production_crop_and_plan_reject_new_actions(self):
        self.login_as("primary_vice")
        response = self.client.post("/production-control/plans", data={
            "crop_id": str(self.finished_crop_id), "target_yield_per_ha_kg": "1000", "approved_budget": "10000"
        })
        self.assertEqual(response.status_code, 303)
        response = self.client.post("/production-control/activities", data={
            "plan_id": str(self.completed_plan_id), "activity_type": "Planting", "title": "Late activity"
        })
        self.assertEqual(response.status_code, 303)
        response = self.client.post("/production-control/equipment-log", data={
            "crop_id": str(self.finished_crop_id), "equipment_id": str(self.equipment_id),
            "use_date": date.today().isoformat(), "purpose": "Late operation",
            "hours_used": "1", "fuel_litres": "1"
        })
        self.assertEqual(response.status_code, 303)


if __name__ == "__main__":
    unittest.main(verbosity=2)
