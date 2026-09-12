import importlib
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path


class ActionableOptionsRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory(prefix="malenge_actionable_options_")
        cls.db_path = Path(cls.tempdir.name) / "actionable.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{cls.db_path.as_posix()}"
        os.environ["SECRET_KEY"] = "malenge-actionable-options-secret"
        os.environ["APP_ENV"] = "development"
        os.environ["TWO_FACTOR_REQUIRED"] = "false"

        cls.crm = importlib.import_module("app")
        cls.jo = importlib.import_module("joint_operations")
        cls.pp = importlib.import_module("primary_production")
        cls.crm.app.config.update(TESTING=True, TWO_FACTOR_REQUIRED=False)

        with cls.crm.app.app_context():
            cls.crm.db.create_all()
            cls._seed()

    @classmethod
    def _seed(cls):
        c = cls.crm
        secondary = c.Cooperative(name="MFPSU Actionable Test", cooperative_type="Secondary", status="Active")
        primary = c.Cooperative(name="Siyaphumla Actionable Test", cooperative_type="Primary", parent=secondary, status="Active")
        other_primary = c.Cooperative(name="Vimba Actionable Test", cooperative_type="Primary", parent=secondary, status="Active")
        c.db.session.add_all([secondary, primary, other_primary])
        c.db.session.flush()
        cls.secondary_id = secondary.id
        cls.primary_id = primary.id
        cls.other_primary_id = other_primary.id

        roles = {
            "primary_treasurer": ("Primary Treasurer", primary.id),
            "primary_vice": ("Primary Vice Chairperson", primary.id),
            "primary_chair": ("Primary Chairperson", primary.id),
            "secondary_treasurer": ("Secondary Treasurer", secondary.id),
            "secondary_chair": ("Secondary Chairperson", secondary.id),
        }
        cls.user_ids = {}
        for key, (role, coop_id) in roles.items():
            user = c.User(
                fullname=key.replace("_", " ").title(),
                phone=f"07{len(cls.user_ids)+1:08d}",
                email=f"{key}@actionable.local",
                farm_location="Malenge",
                password=c.generate_password_hash("Testing123!"),
            )
            c.db.session.add(user)
            c.db.session.flush()
            c.db.session.add(c.UserAccess(user_id=user.id, role=role, status="Active", cooperative_id=coop_id))
            cls.user_ids[key] = user.id

        due = c.Farmer(cooperative_id=primary.id, fullname="Due Member", phone="0711111111", location="Malenge", status="Active")
        done = c.Farmer(cooperative_id=primary.id, fullname="Done Member", phone="0722222222", location="Malenge", status="Active")
        pending = c.Farmer(cooperative_id=primary.id, fullname="Pending Complete Member", phone="0733333333", location="Malenge", status="Active")
        c.db.session.add_all([due, done, pending])
        c.db.session.flush()
        cls.due_farmer_id, cls.done_farmer_id, cls.pending_farmer_id = due.id, done.id, pending.id

        due_m = c.Membership(cooperative_id=primary.id, farmer_id=due.id, member_number="SIYA-ACT-1", join_date=date.today(), fee_amount=300, fee_paid=100, status="Active")
        done_m = c.Membership(cooperative_id=primary.id, farmer_id=done.id, member_number="SIYA-ACT-2", join_date=date.today(), fee_amount=300, fee_paid=300, status="Active")
        pending_m = c.Membership(cooperative_id=primary.id, farmer_id=pending.id, member_number="SIYA-ACT-3", join_date=date.today(), fee_amount=300, fee_paid=0, status="Active")
        c.db.session.add_all([due_m, done_m, pending_m])
        c.db.session.flush()
        c.db.session.add(c.Contribution(
            cooperative_id=primary.id, farmer_id=pending.id, membership_id=pending_m.id,
            amount=300, contribution_date=date.today(), category="Membership Fee",
            status="Pending Confirmation",
        ))

        farm = c.Farm(cooperative_id=primary.id, name="Action Farm", farmer_id=due.id, location="Malenge", size=20, status="Active")
        c.db.session.add(farm)
        c.db.session.flush()
        cls.farm_id = farm.id
        active_crop = c.Crop(cooperative_id=primary.id, farm_id=farm.id, name="Active Potatoes", area_planted=10, status="Growing", planting_date=date.today())
        harvested_crop = c.Crop(cooperative_id=primary.id, farm_id=farm.id, name="Finished Maize", area_planted=4, status="Harvested", planting_date=date.today())
        planned_crop = c.Crop(cooperative_id=primary.id, farm_id=farm.id, name="Completed Plan Beans", area_planted=3, status="Growing", planting_date=date.today())
        c.db.session.add_all([active_crop, harvested_crop, planned_crop])
        c.db.session.flush()
        cls.active_crop_id, cls.harvested_crop_id, cls.planned_crop_id = active_crop.id, harvested_crop.id, planned_crop.id

        full_harvest = c.Harvest(cooperative_id=primary.id, crop_id=active_crop.id, harvest_date=date.today(), quantity=100, unit="kg", status="Available")
        open_harvest = c.Harvest(cooperative_id=primary.id, crop_id=active_crop.id, harvest_date=date.today(), quantity=80, unit="kg", status="Available")
        c.db.session.add_all([full_harvest, open_harvest])
        c.db.session.flush()
        cls.full_harvest_id, cls.open_harvest_id = full_harvest.id, open_harvest.id
        full_sale = c.Sale(cooperative_id=primary.id, harvest_id=full_harvest.id, buyer_name="Full Buyer", quantity=100, unit="kg", price_per_unit=10, total_amount=1000, sale_date=date.today(), status="Completed")
        open_sale = c.Sale(cooperative_id=primary.id, harvest_id=open_harvest.id, buyer_name="Open Buyer", quantity=20, unit="kg", price_per_unit=10, total_amount=200, sale_date=date.today(), status="Pending")
        c.db.session.add_all([full_sale, open_sale])
        c.db.session.flush()
        cls.full_sale_id, cls.open_sale_id = full_sale.id, open_sale.id
        c.db.session.add(c.Payment(cooperative_id=primary.id, sale_id=full_sale.id, amount=1000, payment_date=date.today(), status="Received"))

        completed_plan = cls.pp.ProductionPlan(
            cooperative_id=primary.id, crop_id=planned_crop.id, target_yield_per_ha_kg=1000,
            approved_budget=1000, status="Completed", created_by_user_id=cls.user_ids["primary_vice"],
        )
        c.db.session.add(completed_plan)

        account_done = cls.jo.PrimaryContributionAccount(
            secondary_cooperative_id=secondary.id, primary_cooperative_id=primary.id,
            fiscal_year=date.today().year, expected_amount=1000,
            created_by_user_id=cls.user_ids["secondary_treasurer"],
        )
        account_open = cls.jo.PrimaryContributionAccount(
            secondary_cooperative_id=secondary.id, primary_cooperative_id=other_primary.id,
            fiscal_year=date.today().year, expected_amount=1000,
            created_by_user_id=cls.user_ids["secondary_treasurer"],
        )
        c.db.session.add_all([account_done, account_open])
        c.db.session.flush()
        cls.account_done_id, cls.account_open_id = account_done.id, account_open.id
        c.db.session.add(cls.jo.PrimaryContributionPayment(
            account_id=account_done.id, secondary_cooperative_id=secondary.id,
            primary_cooperative_id=primary.id, amount=1000, payment_date=date.today(),
            status="Pending Confirmation", recorded_by_user_id=cls.user_ids["secondary_treasurer"],
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
            sess.clear()
            sess["user_id"] = self.user_ids[key]
            sess["fullname"] = key
            sess["two_factor_authenticated"] = True

    def test_contribution_list_only_shows_members_with_amount_left(self):
        self.login_as("primary_treasurer")
        page = self.client.get("/contributions/add").get_data(as_text=True)
        self.assertIn("Due Member", page)
        self.assertNotIn("Done Member", page)
        self.assertNotIn("Pending Complete Member", page)

    def test_completed_harvest_crop_is_not_selectable_for_new_harvest(self):
        self.login_as("primary_vice")
        page = self.client.get("/harvests/add").get_data(as_text=True)
        self.assertIn(f'value="{self.active_crop_id}"', page)
        self.assertNotIn(f'value="{self.harvested_crop_id}"', page)

    def test_exhausted_harvest_is_not_selectable_for_new_sale(self):
        self.login_as("primary_treasurer")
        page = self.client.get("/sales/add").get_data(as_text=True)
        self.assertNotIn(f'value="{self.full_harvest_id}"', page)
        self.assertIn(f'value="{self.open_harvest_id}"', page)

    def test_fully_paid_sale_is_not_selectable_for_new_payment(self):
        self.login_as("primary_treasurer")
        page = self.client.get("/payments/add").get_data(as_text=True)
        self.assertNotIn(f'value="{self.full_sale_id}"', page)
        self.assertIn(f'value="{self.open_sale_id}"', page)

    def test_pending_secondary_contribution_removes_record_action(self):
        self.login_as("secondary_treasurer")
        with self.crm.app.app_context():
            account = self.crm.db.session.get(self.jo.PrimaryContributionAccount, self.account_done_id)
            self.assertEqual(account.recordable_amount, 0)
        response = self.client.post(
            f"/joint-operations/contribution-accounts/{self.account_done_id}/payments",
            data={"amount": "1", "payment_date": date.today().isoformat()},
        )
        self.assertEqual(response.status_code, 400)

    def test_completed_production_items_are_not_actionable_options(self):
        self.login_as("primary_vice")
        page = self.client.get("/production-control").get_data(as_text=True)
        self.assertIn(f'<option value="{self.active_crop_id}">Active Potatoes', page)
        self.assertNotIn(f'<option value="{self.harvested_crop_id}">Finished Maize', page)
        self.assertNotIn(f'<option value="{self.planned_crop_id}">Completed Plan Beans', page)


if __name__ == "__main__":
    unittest.main(verbosity=2)
