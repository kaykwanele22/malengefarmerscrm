import importlib
import os
import tempfile
import unittest
from pathlib import Path


class PrimaryProductionCommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory(prefix="malenge_primaryprod_")
        db_path = Path(cls.tempdir.name) / "primaryprod.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
        os.environ["SECRET_KEY"] = "primary-production-test-secret"
        os.environ["APP_ENV"] = "development"
        os.environ["TWO_FACTOR_REQUIRED"] = "false"
        os.environ["ALLOW_BOOTSTRAP_REGISTRATION"] = "true"

        cls.crm = importlib.import_module("app")
        cls.pp = importlib.import_module("primary_production")
        cls.crm.app.config.update(TESTING=True, TWO_FACTOR_REQUIRED=False)
        with cls.crm.app.app_context():
            cls.crm.db.drop_all()
            cls.crm.db.create_all()
            cls._seed()

    @classmethod
    def _user(cls, key, role, cooperative_id):
        c = cls.crm
        user = c.User(
            fullname=key.replace("_", " ").title(), phone=f"071{len(cls.users)+1:07d}",
            email=f"{key}@primaryprod.test", farm_location="Malenge", password="x",
        )
        c.db.session.add(user)
        c.db.session.flush()
        c.db.session.add(c.UserAccess(user_id=user.id, role=role, status="Active", cooperative_id=cooperative_id))
        cls.users[key] = user.id
        return user

    @classmethod
    def _seed(cls):
        c = cls.crm
        secondary = c.Cooperative(name="MFPSU Production Test", cooperative_type="Secondary", status="Active")
        c.db.session.add(secondary)
        c.db.session.flush()
        primary = c.Cooperative(name="Siyaphumla Production Test", cooperative_type="Primary", parent_id=secondary.id, status="Active")
        c.db.session.add(primary)
        c.db.session.flush()
        cls.secondary_id, cls.primary_id = secondary.id, primary.id
        cls.users = {}
        cls._user("primary_chair", "Primary Chairperson", primary.id)
        cls._user("primary_vice", "Primary Vice Chairperson", primary.id)
        cls._user("primary_treasurer", "Primary Treasurer", primary.id)
        cls._user("secondary_chair", "Secondary Chairperson", secondary.id)

        farmer = c.Farmer(cooperative_id=primary.id, fullname="Test Farmer", phone="0711111111", location="Malenge", status="Active")
        c.db.session.add(farmer)
        c.db.session.flush()
        farm = c.Farm(cooperative_id=primary.id, name="Test Farm", farmer_id=farmer.id, location="Malenge", size=20, status="Active")
        c.db.session.add(farm)
        c.db.session.flush()
        crop = c.Crop(
            cooperative_id=primary.id, name="Potatoes", farm_id=farm.id,
            area_planted=10, status="Growing",
        )
        c.db.session.add(crop)
        c.db.session.flush()
        inventory = c.InventoryItem(
            cooperative_id=primary.id, name="Potato Seed", category="Seed", unit="bags",
            quantity_on_hand=100, reorder_level=10, unit_cost=500, status="Active",
        )
        equipment = c.Equipment(
            cooperative_id=primary.id, name="Primary Tractor", equipment_type="Tractor",
            farm_id=farm.id, status="Available",
        )
        c.db.session.add_all([inventory, equipment])
        c.db.session.commit()
        cls.crop_id, cls.inventory_id, cls.equipment_id = crop.id, inventory.id, equipment.id

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

    def test_primary_leadership_access_only(self):
        self.login_as("primary_chair")
        response = self.client.get("/production-control")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Production Command Centre", page)
        self.assertIn("Chairperson oversight mode", page)

        self.login_as("primary_vice")
        response = self.client.get("/production-control")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Vice Chairperson coordination mode", response.get_data(as_text=True))

        self.login_as("primary_treasurer")
        self.assertEqual(self.client.get("/production-control").status_code, 403)
        self.login_as("secondary_chair")
        self.assertEqual(self.client.get("/production-control").status_code, 403)

    def test_vice_submits_plan_and_chair_approves(self):
        with self.crm.app.app_context():
            existing = self.pp.ProductionPlan.query.filter_by(crop_id=self.crop_id).first()
            if existing:
                self.crm.db.session.delete(existing)
                self.crm.db.session.commit()

        self.login_as("primary_vice")
        response = self.client.post("/production-control/plans", data={
            "crop_id": str(self.crop_id), "target_yield_per_ha_kg": "45000",
            "approved_budget": "300000", "notes": "Potato production plan",
        })
        self.assertIn(response.status_code, {302, 303})
        with self.crm.app.app_context():
            plan = self.pp.ProductionPlan.query.filter_by(crop_id=self.crop_id).one()
            self.assertEqual(plan.status, "Pending Approval")
            plan_id = plan.id

        self.login_as("primary_chair")
        response = self.client.post(f"/production-control/plans/{plan_id}/decision", data={"decision": "approve"})
        self.assertIn(response.status_code, {302, 303})
        with self.crm.app.app_context():
            plan = self.crm.db.session.get(self.pp.ProductionPlan, plan_id)
            self.assertEqual(plan.status, "Approved")
            self.assertEqual(plan.target_total_kg, 450000)

    def test_chair_cannot_do_routine_coordination(self):
        self.login_as("primary_chair")
        response = self.client.post("/production-control/input-usage", data={
            "crop_id": str(self.crop_id), "input_type": "Seed", "description": "Seed",
            "quantity": "1", "activity_date": self.crm.crm_today().isoformat(),
        })
        self.assertEqual(response.status_code, 403)

    def test_inventory_issue_decrements_stock_and_creates_out_transaction(self):
        self.login_as("primary_vice")
        with self.crm.app.app_context():
            before = self.crm.db.session.get(self.crm.InventoryItem, self.inventory_id).quantity_on_hand
        response = self.client.post("/production-control/input-usage", data={
            "crop_id": str(self.crop_id), "inventory_item_id": str(self.inventory_id),
            "input_type": "Seed", "description": "Seed issued to potatoes",
            "quantity": "12", "unit": "bags", "unit_cost": "0",
            "activity_date": self.crm.crm_today().isoformat(),
        })
        self.assertIn(response.status_code, {302, 303})
        with self.crm.app.app_context():
            item = self.crm.db.session.get(self.crm.InventoryItem, self.inventory_id)
            self.assertEqual(item.quantity_on_hand, before - 12)
            tx = self.crm.InventoryTransaction.query.filter_by(inventory_item_id=self.inventory_id).order_by(self.crm.InventoryTransaction.id.desc()).first()
            self.assertIsNotNone(tx)
            self.assertEqual(tx.transaction_type, "OUT")
            self.assertEqual(tx.quantity, 12)
            production_input = self.crm.db.session.query(self.pp.ProductionInput).filter_by(crop_id=self.crop_id).order_by(self.pp.ProductionInput.id.desc()).first()
            self.assertEqual(production_input.unit_cost, 500)
            self.assertEqual(production_input.total_cost, 6000)

    def test_activity_completion_requires_chair_verification(self):
        with self.crm.app.app_context():
            plan = self.pp.ProductionPlan.query.filter_by(crop_id=self.crop_id).first()
            if not plan:
                plan = self.pp.ProductionPlan(
                    cooperative_id=self.primary_id, crop_id=self.crop_id,
                    target_yield_per_ha_kg=45000, approved_budget=300000,
                    status="Approved", created_by_user_id=self.users["primary_vice"],
                    approved_by_user_id=self.users["primary_chair"], approved_at=self.crm.utc_now(),
                )
                self.crm.db.session.add(plan)
                self.crm.db.session.commit()
            elif plan.status != "Approved":
                plan.status = "Approved"
                plan.approved_by_user_id = self.users["primary_chair"]
                plan.approved_at = self.crm.utc_now()
                self.crm.db.session.commit()
            plan_id = plan.id

        self.login_as("primary_vice")
        response = self.client.post("/production-control/activities", data={
            "plan_id": str(plan_id), "activity_type": "Fertilizer",
            "title": "First fertilizer application",
            "responsible_user_id": str(self.users["primary_vice"]),
            "due_date": self.crm.crm_today().isoformat(),
        })
        self.assertIn(response.status_code, {302, 303})
        with self.crm.app.app_context():
            activity = self.pp.ProductionActivity.query.filter_by(title="First fertilizer application").one()
            activity_id = activity.id
        response = self.client.post(f"/production-control/activities/{activity_id}/progress", data={
            "status": "Completed", "evidence_reference": "FIELD-PHOTO-001",
        })
        self.assertIn(response.status_code, {302, 303})
        with self.crm.app.app_context():
            self.assertEqual(self.crm.db.session.get(self.pp.ProductionActivity, activity_id).status, "Completed")

        self.login_as("primary_chair")
        response = self.client.post(f"/production-control/activities/{activity_id}/verify", data={})
        self.assertIn(response.status_code, {302, 303})
        with self.crm.app.app_context():
            activity = self.crm.db.session.get(self.pp.ProductionActivity, activity_id)
            self.assertEqual(activity.status, "Verified")
            self.assertEqual(activity.verified_by_user_id, self.users["primary_chair"])

    def test_equipment_log_tracks_usage_not_finance_expense(self):
        self.login_as("primary_vice")
        with self.crm.app.app_context():
            expenses_before = self.crm.Expense.query.count()
        response = self.client.post("/production-control/equipment-log", data={
            "crop_id": str(self.crop_id), "equipment_id": str(self.equipment_id),
            "use_date": self.crm.crm_today().isoformat(), "purpose": "Ploughing",
            "hours_used": "6.5", "fuel_litres": "28",
            "responsible_user_id": str(self.users["primary_vice"]),
        })
        self.assertIn(response.status_code, {302, 303})
        with self.crm.app.app_context():
            log = self.pp.ProductionEquipmentLog.query.filter_by(crop_id=self.crop_id).order_by(self.pp.ProductionEquipmentLog.id.desc()).first()
            self.assertEqual(log.hours_used, 6.5)
            self.assertEqual(log.fuel_litres, 28)
            self.assertEqual(self.crm.Expense.query.count(), expenses_before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
