import os
import sys
import tempfile
import unittest
import importlib
from pathlib import Path
from datetime import date, timedelta


class FullRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory(prefix="malenge_full_test_")
        cls.db_path = Path(cls.tempdir.name) / "full_regression.db"

        os.environ["DATABASE_URL"] = f"sqlite:///{cls.db_path.as_posix()}"
        os.environ["SECRET_KEY"] = "malenge-full-regression-secret"

        # Import only after test DB settings are in place.
        cls.crm = importlib.import_module("app")
        cls.crm.app.config.update(TESTING=True)

        with cls.crm.app.app_context():
            cls.crm.db.create_all()
            cls._seed_base_data()

    @classmethod
    def tearDownClass(cls):
        with cls.crm.app.app_context():
            cls.crm.db.session.remove()
            cls.crm.db.drop_all()
            cls.crm.db.session.remove()
            cls.crm.db.engine.dispose()
        cls.tempdir.cleanup()

    @classmethod
    def _seed_base_data(cls):
        c = cls.crm

        secondary = c.Cooperative(
            name="Malenge Secondary Regression",
            cooperative_type="Secondary",
            status="Active",
        )
        primary = c.Cooperative(
            name="Siyaphumla Primary Regression",
            cooperative_type="Primary",
            status="Active",
            parent=secondary,
        )
        other_primary = c.Cooperative(
            name="Vimba Primary Regression",
            cooperative_type="Primary",
            status="Active",
            parent=secondary,
        )
        c.db.session.add_all([secondary, primary, other_primary])
        c.db.session.flush()

        cls.secondary_id = secondary.id
        cls.primary_id = primary.id
        cls.other_primary_id = other_primary.id

        cls.user_ids = {}

        roles = {
            "admin": ("Admin", None),
            "primary_secretary": ("Primary Secretary", primary.id),
            "primary_treasurer": ("Primary Treasurer", primary.id),
            "primary_chair": ("Primary Chairperson", primary.id),
            "primary_vice_chair": ("Primary Vice Chairperson", primary.id),
            "secondary_chair": ("Secondary Chairperson", secondary.id),
            "secondary_secretary": ("Secondary Secretary", secondary.id),
            "secondary_treasurer": ("Secondary Treasurer", secondary.id),
        }

        for key, (role, coop_id) in roles.items():
            user = c.User(
                fullname=key.replace("_", " ").title(),
                phone="0710000000",
                email=f"{key}@regression.local",
                farm_location="Regression Test",
                password=c.generate_password_hash("Testing123!"),
            )
            c.db.session.add(user)
            c.db.session.flush()
            c.db.session.add(
                c.UserAccess(
                    user_id=user.id,
                    role=role,
                    status="Active",
                    cooperative_id=coop_id,
                )
            )
            cls.user_ids[key] = user.id

        farmer = c.Farmer(
            cooperative_id=primary.id,
            fullname="Regression Farmer",
            phone="0720000000",
            email="farmer@regression.local",
            location="Regression Farm Area",
            status="Active",
        )
        foreign_farmer = c.Farmer(
            cooperative_id=other_primary.id,
            fullname="Foreign Regression Farmer",
            phone="0730000000",
            location="Other Area",
            status="Active",
        )
        c.db.session.add_all([farmer, foreign_farmer])
        c.db.session.commit()

        cls.farmer_id = farmer.id
        cls.foreign_farmer_id = foreign_farmer.id

    def setUp(self):
        self.client = self.crm.app.test_client()

    def login_session(self, key):
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user_ids[key]
            sess["fullname"] = key

    def assert_status(self, url, expected, method="get", data=None, follow_redirects=False):
        response = getattr(self.client, method)(
            url,
            data=data or {},
            follow_redirects=follow_redirects,
        )
        self.assertEqual(
            response.status_code,
            expected,
            msg=f"{method.upper()} {url}: expected {expected}, got {response.status_code}",
        )
        return response

    # =========================================================
    # PUBLIC / AUTHENTICATION
    # =========================================================
    def test_public_pages_render(self):
        self.assert_status("/", 200)
        self.assert_status("/login", 200)
        self.assert_status("/health", 200)

    def test_anonymous_dashboard_redirects_to_login(self):
        response = self.assert_status("/dashboard", 302)
        self.assertIn("/login", response.headers.get("Location", ""))

    def test_invalid_login_is_rejected_and_audited(self):
        before = None
        with self.crm.app.app_context():
            before = self.crm.AuditLog.query.filter_by(action="LOGIN_FAILED").count()

        response = self.assert_status(
            "/login",
            303,
            method="post",
            data={"email": "admin@regression.local", "password": "WrongPassword"},
        )

        with self.client.session_transaction() as sess:
            self.assertNotIn("user_id", sess)

        with self.crm.app.app_context():
            after = self.crm.AuditLog.query.filter_by(action="LOGIN_FAILED").count()
            self.assertEqual(after, before + 1)

    def test_valid_login_and_logout_flow(self):
        response = self.assert_status(
            "/login",
            302,
            method="post",
            data={"email": "primary_secretary@regression.local", "password": "Testing123!"},
        )
        self.assertIn("/dashboard", response.headers.get("Location", ""))

        self.assert_status("/dashboard", 200)

        response = self.assert_status("/logout", 302)
        self.assertIn("/login", response.headers.get("Location", ""))

        response = self.assert_status("/dashboard", 302)
        self.assertIn("/login", response.headers.get("Location", ""))

    # =========================================================
    # TEMPLATE / DASHBOARD SMOKE TESTS
    # =========================================================
    def test_all_core_role_dashboards_render(self):
        for key in [
            "admin",
            "primary_secretary",
            "primary_treasurer",
            "primary_chair",
            "primary_vice_chair",
            "secondary_chair",
            "secondary_secretary",
            "secondary_treasurer",
        ]:
            client = self.crm.app.test_client()
            with client.session_transaction() as sess:
                sess["user_id"] = self.user_ids[key]
                sess["fullname"] = key
            response = client.get("/dashboard")
            self.assertEqual(
                response.status_code,
                200,
                msg=f"Dashboard failed to render for {key}: {response.status_code}",
            )

    def test_primary_secretary_templates_render(self):
        self.login_session("primary_secretary")
        for url in [
            "/farmers",
            "/farmers/add",
            "/memberships",
            "/memberships/add",
            "/reports",
            "/settings",
        ]:
            self.assert_status(url, 200)

    def test_primary_chair_templates_render(self):
        self.login_session("primary_chair")
        for url in [
            "/farmers",
            "/farms",
            "/farms/add",
            "/crops",
            "/crops/add",
            "/harvests",
            "/harvests/add",
            "/sales",
            "/payments",
            "/contributions",
            "/expenses",
            "/reports",
            "/settings",
        ]:
            self.assert_status(url, 200)

    def test_primary_treasurer_templates_render(self):
        self.login_session("primary_treasurer")
        for url in [
            "/memberships",
            "/sales",
            "/sales/add",
            "/payments",
            "/payments/add",
            "/contributions",
            "/contributions/add",
            "/expenses",
            "/expenses/add",
            "/reports",
            "/settings",
        ]:
            self.assert_status(url, 200)

    def test_admin_templates_render(self):
        self.login_session("admin")
        for url in [
            "/dashboard",
            "/users",
            "/users/add",
            "/cooperatives",
            "/cooperatives/add",
            "/audit-logs",
            "/admin/security",
            "/admin/backup-restore",
            "/admin/system-health",
            "/admin/data-exports",
            "/admin/role-permissions",
            "/admin/system-settings",
        ]:
            self.assert_status(url, 200)

    # =========================================================
    # FARMER CRUD / VALIDATION / PERSISTENCE
    # =========================================================
    def test_farmer_create_update_delete_persistence(self):
        c = self.crm
        self.login_session("primary_secretary")

        response = self.assert_status(
            "/farmers/add",
            302,
            method="post",
            data={
                "fullname": "CRUD Farmer",
                "phone": "0741111111",
                "email": "crud.farmer@test.local",
                "location": "Old Location",
                "status": "Active",
            },
        )

        with c.app.app_context():
            farmer = c.Farmer.query.filter_by(email="crud.farmer@test.local").first()
            self.assertIsNotNone(farmer)
            self.assertEqual(farmer.cooperative_id, self.primary_id)
            farmer_id = farmer.id

        self.assert_status(
            f"/farmers/edit/{farmer_id}",
            302,
            method="post",
            data={
                "fullname": "CRUD Farmer Updated",
                "phone": "0741111111",
                "email": "crud.farmer@test.local",
                "location": "New Location",
                "status": "Active",
            },
        )

        with c.app.app_context():
            farmer = c.db.session.get(c.Farmer, farmer_id)
            self.assertEqual(farmer.fullname, "CRUD Farmer Updated")
            self.assertEqual(farmer.location, "New Location")

        self.assert_status(f"/farmers/delete/{farmer_id}", 302, method="post")

        with c.app.app_context():
            self.assertIsNone(c.db.session.get(c.Farmer, farmer_id))

    def test_farmer_required_field_validation(self):
        c = self.crm
        self.login_session("primary_secretary")

        with c.app.app_context():
            before = c.Farmer.query.count()

        self.assert_status(
            "/farmers/add",
            303,
            method="post",
            data={"fullname": "", "phone": "", "location": ""},
        )

        with c.app.app_context():
            after = c.Farmer.query.count()
            self.assertEqual(after, before)

    # =========================================================
    # FARM -> CROP -> HARVEST LIFECYCLE
    # =========================================================
    def test_farm_crop_harvest_lifecycle(self):
        c = self.crm
        self.login_session("primary_chair")

        self.assert_status(
            "/farms/add",
            302,
            method="post",
            data={
                "name": "Regression Farm",
                "farmer_id": str(self.farmer_id),
                "location": "Regression Valley",
                "size": "2.5",
                "farming_type": "Crop",
                "status": "Active",
            },
        )

        with c.app.app_context():
            farm = c.Farm.query.filter_by(name="Regression Farm").first()
            self.assertIsNotNone(farm)
            self.assertEqual(farm.cooperative_id, self.primary_id)
            farm_id = farm.id

        planting = date.today() - timedelta(days=90)
        expected = date.today() + timedelta(days=10)

        self.assert_status(
            "/crops/add",
            302,
            method="post",
            data={
                "name": "Potatoes Regression",
                "farm_id": str(farm_id),
                "variety": "Test Variety",
                "planting_date": planting.isoformat(),
                "expected_harvest_date": expected.isoformat(),
                "area_planted": "1.5",
                "status": "Growing",
                "notes": "Regression crop",
            },
        )

        with c.app.app_context():
            crop = c.Crop.query.filter_by(name="Potatoes Regression").first()
            self.assertIsNotNone(crop)
            crop_id = crop.id

        self.assert_status(
            "/harvests/add",
            302,
            method="post",
            data={
                "crop_id": str(crop_id),
                "harvest_date": date.today().isoformat(),
                "quantity": "500",
                "unit": "kg",
                "quality_grade": "A",
                "storage_location": "Store 1",
                "status": "Available",
                "notes": "Regression harvest",
                "final_harvest": "0",
            },
        )

        with c.app.app_context():
            harvest = c.Harvest.query.filter_by(crop_id=crop_id).first()
            self.assertIsNotNone(harvest)
            self.assertEqual(float(harvest.quantity), 500.0)

            crop = c.db.session.get(c.Crop, crop_id)
            self.assertEqual(crop.status, "Partially Harvested")

    def test_negative_farm_size_is_rejected(self):
        c = self.crm
        self.login_session("primary_chair")

        self.assert_status(
            "/farms/add",
            303,
            method="post",
            data={
                "name": "Bad Farm",
                "farmer_id": str(self.farmer_id),
                "location": "Bad",
                "size": "-1",
                "farming_type": "Crop",
                "status": "Active",
            },
        )

        with c.app.app_context():
            self.assertIsNone(c.Farm.query.filter_by(name="Bad Farm").first())

    def test_crop_expected_harvest_before_planting_is_rejected(self):
        c = self.crm
        self.login_session("primary_chair")

        with c.app.app_context():
            farm = c.Farm(
                cooperative_id=self.primary_id,
                farmer_id=self.farmer_id,
                name="Validation Farm",
                location="Validation",
                status="Active",
            )
            c.db.session.add(farm)
            c.db.session.commit()
            farm_id = farm.id

        self.assert_status(
            "/crops/add",
            303,
            method="post",
            data={
                "name": "Bad Dates Crop",
                "farm_id": str(farm_id),
                "planting_date": date.today().isoformat(),
                "expected_harvest_date": (date.today() - timedelta(days=1)).isoformat(),
                "area_planted": "1",
                "status": "Growing",
            },
        )

        with c.app.app_context():
            self.assertIsNone(c.Crop.query.filter_by(name="Bad Dates Crop").first())

    def test_zero_harvest_quantity_is_rejected(self):
        c = self.crm
        self.login_session("primary_chair")

        with c.app.app_context():
            farm = c.Farm(
                cooperative_id=self.primary_id,
                farmer_id=self.farmer_id,
                name="Harvest Validation Farm",
                location="Validation",
                status="Active",
            )
            c.db.session.add(farm)
            c.db.session.flush()
            crop = c.Crop(
                cooperative_id=self.primary_id,
                farm_id=farm.id,
                name="Harvest Validation Crop",
                planting_date=date.today() - timedelta(days=30),
                status="Growing",
            )
            c.db.session.add(crop)
            c.db.session.commit()
            crop_id = crop.id

        self.assert_status(
            "/harvests/add",
            303,
            method="post",
            data={
                "crop_id": str(crop_id),
                "harvest_date": date.today().isoformat(),
                "quantity": "0",
                "unit": "kg",
                "status": "Available",
            },
        )

        with c.app.app_context():
            self.assertIsNone(c.Harvest.query.filter_by(crop_id=crop_id).first())

    # =========================================================
    # MEMBERSHIP / FINANCE
    # =========================================================
    def test_membership_create_persists_in_own_coop(self):
        c = self.crm
        self.login_session("primary_secretary")

        self.assert_status(
            "/memberships/add",
            302,
            method="post",
            data={
                "farmer_id": str(self.farmer_id),
                "member_number": "MEM-REG-001",
                "membership_type": "Ordinary",
                "join_date": date.today().isoformat(),
                "fee_amount": "100",
                "status": "Active",
            },
        )

        with c.app.app_context():
            membership = c.Membership.query.filter_by(member_number="MEM-REG-001").first()
            self.assertIsNotNone(membership)
            self.assertEqual(membership.cooperative_id, self.primary_id)

    def test_treasurer_contribution_then_chair_approval(self):
        c = self.crm
        self.login_session("primary_treasurer")

        self.assert_status(
            "/contributions/add",
            302,
            method="post",
            data={
                "farmer_id": str(self.farmer_id),
                "amount": "125",
                "category": "General",
                "contribution_date": date.today().isoformat(),
                "method": "Cash",
                "reference": "FULL-REG-CONTRIB",
                "notes": "Full regression",
            },
        )

        with c.app.app_context():
            record = c.Contribution.query.filter_by(reference="FULL-REG-CONTRIB").first()
            self.assertIsNotNone(record)
            self.assertEqual(record.status, "Pending Confirmation")
            contribution_id = record.id

        self.client = c.app.test_client()
        self.login_session("primary_chair")

        self.assert_status(
            f"/contributions/{contribution_id}/decision",
            302,
            method="post",
            data={"decision": "approve"},
        )

        with c.app.app_context():
            record = c.db.session.get(c.Contribution, contribution_id)
            self.assertEqual(record.status, "Confirmed")

    def test_treasurer_expense_then_chair_rejection(self):
        c = self.crm
        self.login_session("primary_treasurer")

        self.assert_status(
            "/expenses/add",
            302,
            method="post",
            data={
                "category": "Fuel",
                "description": "Regression expense rejection",
                "amount": "80",
                "expense_date": date.today().isoformat(),
                "payment_method": "Cash",
                "reference": "FULL-REG-EXPENSE",
            },
        )

        with c.app.app_context():
            expense = c.Expense.query.filter_by(reference="FULL-REG-EXPENSE").first()
            self.assertIsNotNone(expense)
            self.assertEqual(expense.status, "Pending Confirmation")
            expense_id = expense.id

        self.client = c.app.test_client()
        self.login_session("primary_chair")

        self.assert_status(
            f"/expenses/{expense_id}/decision",
            302,
            method="post",
            data={"decision": "reject"},
        )

        with c.app.app_context():
            expense = c.db.session.get(c.Expense, expense_id)
            self.assertEqual(expense.status, "Rejected")

    def test_zero_contribution_is_rejected(self):
        c = self.crm
        self.login_session("primary_treasurer")

        with c.app.app_context():
            before = c.Contribution.query.count()

        self.assert_status(
            "/contributions/add",
            303,
            method="post",
            data={
                "farmer_id": str(self.farmer_id),
                "amount": "0",
                "category": "General",
                "contribution_date": date.today().isoformat(),
                "method": "Cash",
            },
        )

        with c.app.app_context():
            after = c.Contribution.query.count()
            self.assertEqual(after, before)

    # =========================================================
    # SETTINGS
    # =========================================================
    def test_profile_update_persists(self):
        c = self.crm
        self.login_session("primary_secretary")

        self.assert_status(
            "/settings",
            302,
            method="post",
            data={
                "fullname": "Primary Secretary Updated",
                "phone": "0799999999",
                "email": "primary_secretary@regression.local",
                "farm_location": "Updated Location",
            },
        )

        with c.app.app_context():
            user = c.db.session.get(c.User, self.user_ids["primary_secretary"])
            self.assertEqual(user.fullname, "Primary Secretary Updated")
            self.assertEqual(user.farm_location, "Updated Location")

    def test_password_change_validation(self):
        c = self.crm
        self.login_session("primary_secretary")

        with c.app.app_context():
            user = c.db.session.get(c.User, self.user_ids["primary_secretary"])
            original_hash = user.password

        self.assert_status(
            "/settings/password",
            303,
            method="post",
            data={
                "current_password": "WrongPassword",
                "new_password": "NewTesting123!",
                "confirm_password": "NewTesting123!",
            },
        )

        with c.app.app_context():
            user = c.db.session.get(c.User, self.user_ids["primary_secretary"])
            self.assertEqual(user.password, original_hash)
            self.assertTrue(c.check_password_hash(user.password, "Testing123!"))

    # =========================================================
    # CSV / ADMIN / ERROR HANDLING
    # =========================================================
    def test_role_csv_exports_return_csv(self):
        self.login_session("primary_chair")
        for url in [
            "/exports/farmers.csv",
            "/exports/farms.csv",
            "/exports/crops.csv",
            "/exports/harvests.csv",
            "/exports/sales.csv",
            "/exports/payments.csv",
            "/exports/expenses.csv",
        ]:
            response = self.assert_status(url, 200)
            self.assertIn("text/csv", response.content_type)

    def test_admin_csv_export_returns_csv(self):
        self.login_session("admin")
        response = self.assert_status("/admin/export/users.csv", 200)
        self.assertIn("text/csv", response.content_type)

    def test_unknown_admin_export_is_404(self):
        self.login_session("admin")
        self.assert_status("/admin/export/not-a-dataset.csv", 404)

    def test_unknown_route_is_404(self):
        self.assert_status("/this-route-does-not-exist", 404)

    def test_cross_cooperative_edit_is_not_possible(self):
        self.login_session("primary_secretary")
        response = self.client.get(f"/farmers/edit/{self.foreign_farmer_id}")
        self.assertIn(
            response.status_code,
            {403, 404},
            msg=f"Foreign farmer edit should be hidden or forbidden, got {response.status_code}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
