import os
import sys
import tempfile
import unittest
import importlib
from pathlib import Path
from datetime import date


class PermissionRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory(prefix="malenge_perm_test_")
        cls.db_path = Path(cls.tempdir.name) / "permissions_test.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{cls.db_path.as_posix()}"
        os.environ["SECRET_KEY"] = "malenge-test-secret"

        # Import app only after the test database URL is configured.
        cls.crm = importlib.import_module("app")
        cls.jo = importlib.import_module("joint_operations")
        cls.crm.app.config.update(TESTING=True)

        # Backend permission tests do not need HTML rendering. This also makes
        # the suite independent from cosmetic template changes.
        cls.crm.render_template = lambda *args, **kwargs: "OK"
        cls.crm.render_optional_template = lambda *args, **kwargs: "OK"

        with cls.crm.app.app_context():
            cls.crm.db.create_all()
            cls._seed_data()

    @classmethod
    def tearDownClass(cls):
        with cls.crm.app.app_context():
            cls.crm.db.session.remove()
            cls.crm.db.drop_all()
            cls.crm.db.session.remove()
            cls.crm.db.engine.dispose()
        cls.tempdir.cleanup()

    @classmethod
    def _seed_data(cls):
        c = cls.crm
        secondary = c.Cooperative(
            name="Malenge Secondary Test",
            cooperative_type="Secondary",
            status="Active",
        )
        primary_a = c.Cooperative(
            name="Siyaphumla Primary Test",
            cooperative_type="Primary",
            status="Active",
            parent=secondary,
        )
        primary_b = c.Cooperative(
            name="Vimba Primary Test",
            cooperative_type="Primary",
            status="Active",
            parent=secondary,
        )
        c.db.session.add_all([secondary, primary_a, primary_b])
        c.db.session.flush()

        cls.secondary_id = secondary.id
        cls.primary_a_id = primary_a.id
        cls.primary_b_id = primary_b.id

        cls.user_ids = {}
        roles = {
            "primary_secretary": ("Primary Secretary", primary_a.id),
            "primary_vice_secretary": ("Primary Vice Secretary", primary_a.id),
            "primary_treasurer": ("Primary Treasurer", primary_a.id),
            "primary_chair": ("Primary Chairperson", primary_a.id),
            "primary_vice_chair": ("Primary Vice Chairperson", primary_a.id),
            "secondary_secretary": ("Secondary Secretary", secondary.id),
            "secondary_treasurer": ("Secondary Treasurer", secondary.id),
            "secondary_chair": ("Secondary Chairperson", secondary.id),
            "admin": ("Admin", None),
        }

        for key, (role, cooperative_id) in roles.items():
            user = c.User(
                fullname=key.replace("_", " ").title(),
                phone="0000000000",
                email=f"{key}@test.local",
                farm_location="Test",
                password="not-used-in-session-tests",
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

        farmer_a = c.Farmer(
            cooperative_id=primary_a.id,
            fullname="Farmer A",
            phone="111",
            location="A",
            status="Active",
        )
        farmer_b = c.Farmer(
            cooperative_id=primary_b.id,
            fullname="Farmer B",
            phone="222",
            location="B",
            status="Active",
        )
        farmer_secondary = c.Farmer(
            cooperative_id=secondary.id,
            fullname="Secondary Farmer",
            phone="333",
            location="Secondary",
            status="Active",
        )

        c.db.session.add_all([farmer_a, farmer_b, farmer_secondary])
        c.db.session.commit()
        cls.farmer_a_id = farmer_a.id
        cls.farmer_b_id = farmer_b.id
        cls.farmer_secondary_id = farmer_secondary.id

    def setUp(self):
        self.client = self.crm.app.test_client()

    def login_as(self, key):
        user_id = self.user_ids[key]
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id
            sess["fullname"] = key

    def assert_status(self, url, expected, method="get", data=None):
        response = getattr(self.client, method)(url, data=data or {}, follow_redirects=False)
        self.assertEqual(
            response.status_code,
            expected,
            msg=f"{method.upper()} {url}: expected {expected}, got {response.status_code}",
        )
        return response

    # ---------------------------------------------------------
    # PRIMARY SECRETARY
    # ---------------------------------------------------------
    def test_primary_secretary_surface(self):
        self.login_as("primary_secretary")
        for url in ["/farmers", "/memberships", "/reports", "/settings"]:
            self.assert_status(url, 200)
        for url in ["/farms", "/crops", "/harvests", "/sales", "/payments", "/contributions", "/expenses"]:
            self.assert_status(url, 403)

    def test_primary_secretary_can_add_own_farmer(self):
        self.login_as("primary_secretary")
        response = self.client.post("/farmers/add", data={
            "fullname": "Secretary Added Farmer",
            "phone": "333",
            "email": "",
            "location": "Own Coop",
            "status": "Active",
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        with self.crm.app.app_context():
            farmer = self.crm.Farmer.query.filter_by(fullname="Secretary Added Farmer").first()
            self.assertIsNotNone(farmer)
            self.assertEqual(farmer.cooperative_id, self.primary_a_id)

    def test_primary_secretary_cannot_register_foreign_membership(self):
        self.login_as("primary_secretary")
        response = self.client.post(
            "/memberships/add",
            data={
                "farmer_id": str(self.farmer_b_id),
                "member_number": "FOREIGN-001",
                "membership_type": "Ordinary",
                "join_date": date.today().isoformat(),
                "fee_amount": "100",
                "status": "Active",
            },
            follow_redirects=False,
        )

        # The CRM intentionally converts plain POST validation errors (400/401)
        # into a 303 redirect so the form can show the validation message.
        self.assertEqual(response.status_code, 303)

        with self.crm.app.app_context():
            foreign = self.crm.Membership.query.filter_by(
                member_number="FOREIGN-001"
            ).first()
            self.assertIsNone(
                foreign,
                "Primary Secretary was able to create a membership for another cooperative.",
            )

    # ---------------------------------------------------------
    # PRIMARY TREASURER
    # ---------------------------------------------------------
    def test_primary_treasurer_surface(self):
        self.login_as("primary_treasurer")
        for url in ["/memberships", "/sales", "/payments", "/contributions", "/expenses", "/reports", "/settings"]:
            self.assert_status(url, 200)
        for url in ["/farmers", "/farms", "/crops", "/harvests"]:
            self.assert_status(url, 403)

    def test_primary_treasurer_can_record_own_contribution(self):
        self.login_as("primary_treasurer")
        response = self.client.post("/contributions/add", data={
            "farmer_id": str(self.farmer_a_id),
            "amount": "10",
            "category": "General",
            "contribution_date": date.today().isoformat(),
            "method": "Cash",
            "reference": "TEST-10",
            "notes": "permission regression test",
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        with self.crm.app.app_context():
            record = self.crm.Contribution.query.filter_by(reference="TEST-10").first()
            self.assertIsNotNone(record)
            self.assertEqual(record.cooperative_id, self.primary_a_id)
            self.assertEqual(record.status, "Pending Confirmation")
            self.__class__.pending_contribution_id = record.id

    def test_primary_treasurer_cannot_record_foreign_contribution(self):
        self.login_as("primary_treasurer")
        response = self.client.post(
            "/contributions/add",
            data={
                "farmer_id": str(self.farmer_b_id),
                "amount": "10",
                "category": "General",
                "contribution_date": date.today().isoformat(),
                "method": "Cash",
                "reference": "FOREIGN-CONTRIB-001",
            },
            follow_redirects=False,
        )

        # The CRM intentionally converts plain POST validation errors (400/401)
        # into a 303 redirect so the form can show the validation message.
        self.assertEqual(response.status_code, 303)

        with self.crm.app.app_context():
            foreign = self.crm.Contribution.query.filter_by(
                reference="FOREIGN-CONTRIB-001"
            ).first()
            self.assertIsNone(
                foreign,
                "Primary Treasurer was able to record money for another cooperative.",
            )

    def test_primary_treasurer_cannot_approve_finance(self):
        self.login_as("primary_treasurer")
        self.assert_status("/contributions/999999/decision", 403, method="post", data={"decision": "approve"})
        self.assert_status("/expenses/999999/decision", 403, method="post", data={"decision": "approve"})

    # ---------------------------------------------------------
    # PRIMARY CHAIR / VICE CHAIR
    # ---------------------------------------------------------
    def test_primary_chair_surface(self):
        self.login_as("primary_chair")
        for url in ["/farmers", "/memberships", "/farms", "/crops", "/harvests", "/sales", "/payments", "/contributions", "/expenses", "/reports", "/settings"]:
            self.assert_status(url, 200)
        self.assert_status("/farmers/add", 403)
        self.assert_status("/crops/add", 403)
        self.assert_status("/harvests/add", 403)
        self.assert_status("/sales/add", 403)
        self.assert_status("/contributions/add", 403)
        self.assert_status("/expenses/add", 403)

    def test_primary_vice_chair_owns_production_recording_but_not_finance(self):
        self.login_as("primary_vice_chair")
        for url in ["/crops", "/harvests", "/crops/add", "/harvests/add"]:
            self.assert_status(url, 200)
        for url in ["/sales", "/payments", "/contributions", "/expenses"]:
            self.assert_status(url, 403)

    def test_primary_vice_chair_cannot_approve_finance(self):
        self.login_as("primary_vice_chair")
        self.assert_status("/contributions/999999/decision", 403, method="post", data={"decision": "approve"})
        self.assert_status("/expenses/999999/decision", 403, method="post", data={"decision": "approve"})

    def test_primary_chair_can_approve_own_pending_contribution(self):
        c = self.crm
        with c.app.app_context():
            record = c.Contribution(
                cooperative_id=self.primary_a_id,
                farmer_id=self.farmer_a_id,
                amount=25.0,
                contribution_date=date.today(),
                category="General",
                method="Cash",
                reference="CHAIR-APPROVE",
                status="Pending Confirmation",
            )
            c.db.session.add(record)
            c.db.session.commit()
            record_id = record.id

        self.login_as("primary_chair")
        self.assert_status(
            f"/contributions/{record_id}/decision",
            302,
            method="post",
            data={"decision": "approve"},
        )
        with c.app.app_context():
            record = c.db.session.get(c.Contribution, record_id)
            self.assertEqual(record.status, "Confirmed")

    def test_primary_chair_cannot_approve_other_coop_finance(self):
        c = self.crm
        with c.app.app_context():
            record = c.Contribution(
                cooperative_id=self.primary_b_id,
                farmer_id=self.farmer_b_id,
                amount=25.0,
                contribution_date=date.today(),
                category="General",
                method="Cash",
                reference="FOREIGN-CHAIR",
                status="Pending Confirmation",
            )
            c.db.session.add(record)
            c.db.session.commit()
            record_id = record.id

        self.login_as("primary_chair")
        self.assert_status(
            f"/contributions/{record_id}/decision",
            404,
            method="post",
            data={"decision": "approve"},
        )

    # ---------------------------------------------------------
    # EXPENSE WORKFLOW
    # ---------------------------------------------------------
    def test_primary_treasurer_can_record_expense(self):
        self.login_as("primary_treasurer")
        response = self.client.post(
            "/expenses/add",
            data={
                "category": "Fuel",
                "description": "Regression test fuel",
                "amount": "75.50",
                "expense_date": date.today().isoformat(),
                "payment_method": "Cash",
                "reference": "EXP-REG-001",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        with self.crm.app.app_context():
            expense = self.crm.Expense.query.filter_by(
                reference="EXP-REG-001"
            ).first()
            self.assertIsNotNone(expense)
            self.assertEqual(expense.cooperative_id, self.primary_a_id)
            self.assertEqual(expense.status, "Pending Confirmation")

    def test_primary_chair_can_approve_own_pending_expense(self):
        c = self.crm
        with c.app.app_context():
            expense = c.Expense(
                cooperative_id=self.primary_a_id,
                category="Seed",
                description="Chair expense approval test",
                amount=50.0,
                expense_date=date.today(),
                payment_method="Cash",
                reference="EXP-CHAIR-APPROVE",
                status="Pending Confirmation",
            )
            c.db.session.add(expense)
            c.db.session.commit()
            expense_id = expense.id

        self.login_as("primary_chair")
        self.assert_status(
            f"/expenses/{expense_id}/decision",
            302,
            method="post",
            data={"decision": "approve"},
        )

        with c.app.app_context():
            expense = c.db.session.get(c.Expense, expense_id)
            self.assertEqual(expense.status, "Confirmed")

    def test_primary_chair_cannot_approve_other_coop_expense(self):
        c = self.crm
        with c.app.app_context():
            expense = c.Expense(
                cooperative_id=self.primary_b_id,
                category="Fuel",
                description="Foreign expense",
                amount=20.0,
                expense_date=date.today(),
                payment_method="Cash",
                reference="EXP-FOREIGN-CHAIR",
                status="Pending Confirmation",
            )
            c.db.session.add(expense)
            c.db.session.commit()
            expense_id = expense.id

        self.login_as("primary_chair")
        self.assert_status(
            f"/expenses/{expense_id}/decision",
            404,
            method="post",
            data={"decision": "approve"},
        )

    # ---------------------------------------------------------
    # SECONDARY EXECUTIVES
    # ---------------------------------------------------------
    def test_secondary_secretary_surface(self):
        self.login_as("secondary_secretary")

        for url in ["/reports", "/settings"]:
            self.assert_status(url, 200)

        for url in [
            "/farmers", "/memberships", "/farms", "/crops", "/harvests",
            "/sales", "/payments", "/contributions", "/expenses"
        ]:
            self.assert_status(url, 403)

    def test_secondary_treasurer_surface(self):
        self.login_as("secondary_treasurer")

        for url in [
            "/sales", "/payments", "/expenses", "/reports", "/settings", "/joint-operations"
        ]:
            self.assert_status(url, 200)

        contribution_redirect = self.assert_status("/contributions", 302)
        self.assertIn("/joint-operations", contribution_redirect.headers.get("Location", ""))
        self.assertIn("#primary-contributions", contribution_redirect.headers.get("Location", ""))

        add_redirect = self.assert_status("/contributions/add", 302)
        self.assertIn("#primary-contributions", add_redirect.headers.get("Location", ""))

        for url in ["/memberships", "/farmers", "/farms", "/crops", "/harvests"]:
            self.assert_status(url, 403)

    def test_secondary_treasurer_records_primary_cooperative_contribution_only(self):
        self.login_as("secondary_treasurer")
        year = date.today().year

        response = self.client.post(
            "/joint-operations/contribution-accounts",
            data={
                "primary_cooperative_id": str(self.primary_a_id),
                "fiscal_year": str(year),
                "expected_amount": "1000",
                "notes": "Primary cooperative annual contribution",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        with self.crm.app.app_context():
            account = self.jo.PrimaryContributionAccount.query.filter_by(
                secondary_cooperative_id=self.secondary_id,
                primary_cooperative_id=self.primary_a_id,
                fiscal_year=year,
            ).one()
            account_id = account.id

        response = self.client.post(
            f"/joint-operations/contribution-accounts/{account_id}/payments",
            data={
                "amount": "40",
                "payment_date": date.today().isoformat(),
                "method": "Bank Transfer",
                "reference": "SECONDARY-CONTRIB-001",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        with self.crm.app.app_context():
            payment = self.jo.PrimaryContributionPayment.query.filter_by(
                reference="SECONDARY-CONTRIB-001"
            ).one()
            self.assertEqual(payment.secondary_cooperative_id, self.secondary_id)
            self.assertEqual(payment.primary_cooperative_id, self.primary_a_id)
            self.assertEqual(payment.status, "Pending Confirmation")
            self.assertIsNone(
                self.crm.Contribution.query.filter_by(reference="SECONDARY-CONTRIB-001").first(),
                "Secondary cooperative money must not be stored as a farmer contribution.",
            )

    def test_secondary_treasurer_cannot_use_legacy_primary_contribution_form(self):
        self.login_as("secondary_treasurer")

        response = self.client.post(
            "/contributions/add",
            data={
                "farmer_id": str(self.farmer_a_id),
                "amount": "40",
                "category": "General",
                "contribution_date": date.today().isoformat(),
                "method": "Cash",
                "reference": "SECONDARY-FOREIGN-001",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/joint-operations", response.headers.get("Location", ""))
        self.assertIn("#primary-contributions", response.headers.get("Location", ""))

        with self.crm.app.app_context():
            record = self.crm.Contribution.query.filter_by(
                reference="SECONDARY-FOREIGN-001"
            ).first()
            self.assertIsNone(record)

    def test_secondary_chair_can_approve_secondary_finance(self):
        c = self.crm
        year = date.today().year + 1
        with c.app.app_context():
            account = self.jo.PrimaryContributionAccount(
                secondary_cooperative_id=self.secondary_id,
                primary_cooperative_id=self.primary_b_id,
                fiscal_year=year,
                expected_amount=30.0,
                created_by_user_id=self.user_ids["secondary_treasurer"],
            )
            c.db.session.add(account)
            c.db.session.flush()
            payment = self.jo.PrimaryContributionPayment(
                account_id=account.id,
                secondary_cooperative_id=self.secondary_id,
                primary_cooperative_id=self.primary_b_id,
                amount=30.0,
                payment_date=date.today(),
                method="Bank Transfer",
                reference="SECONDARY-CHAIR-APPROVE",
                status="Pending Confirmation",
                recorded_by_user_id=self.user_ids["secondary_treasurer"],
            )
            c.db.session.add(payment)
            c.db.session.commit()
            payment_id = payment.id

        self.login_as("secondary_chair")
        self.assert_status(
            f"/joint-operations/contribution-payments/{payment_id}/decision",
            302,
            method="post",
            data={"decision": "approve"},
        )

        with c.app.app_context():
            payment = c.db.session.get(self.jo.PrimaryContributionPayment, payment_id)
            self.assertEqual(payment.status, "Confirmed")

    def test_secondary_chair_cannot_approve_primary_finance(self):
        c = self.crm
        with c.app.app_context():
            record = c.Contribution(
                cooperative_id=self.primary_a_id,
                farmer_id=self.farmer_a_id,
                amount=30.0,
                contribution_date=date.today(),
                category="General",
                method="Cash",
                reference="SECONDARY-CHAIR-FOREIGN",
                status="Pending Confirmation",
            )
            c.db.session.add(record)
            c.db.session.commit()
            record_id = record.id

        self.login_as("secondary_chair")
        self.assert_status(
            f"/contributions/{record_id}/decision",
            403,
            method="post",
            data={"decision": "approve"},
        )

    # ---------------------------------------------------------
    # ACCOUNT STATUS / LOGIN SECURITY
    # ---------------------------------------------------------
    def test_inactive_account_login_is_denied(self):
        c = self.crm

        with c.app.app_context():
            user = c.User(
                fullname="Inactive Login User",
                phone="444",
                email="inactive.login@test.local",
                farm_location="Test",
                password=c.generate_password_hash("Testing123!"),
            )
            c.db.session.add(user)
            c.db.session.flush()
            c.db.session.add(c.UserAccess(
                user_id=user.id,
                role="Primary Secretary",
                status="Inactive",
                cooperative_id=self.primary_a_id,
            ))
            c.db.session.commit()

        response = self.client.post(
            "/login",
            data={
                "email": "inactive.login@test.local",
                "password": "Testing123!",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 403)

    def test_pending_account_login_is_denied(self):
        c = self.crm

        with c.app.app_context():
            user = c.User(
                fullname="Pending Login User",
                phone="555",
                email="pending.login@test.local",
                farm_location="Test",
                password=c.generate_password_hash("Testing123!"),
            )
            c.db.session.add(user)
            c.db.session.flush()
            c.db.session.add(c.UserAccess(
                user_id=user.id,
                role="Primary Secretary",
                status="Pending",
                cooperative_id=self.primary_a_id,
            ))
            c.db.session.commit()

        response = self.client.post(
            "/login",
            data={
                "email": "pending.login@test.local",
                "password": "Testing123!",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 403)

    # ---------------------------------------------------------
    # ADMIN
    # ---------------------------------------------------------
    def test_admin_is_blocked_from_cooperative_operations(self):
        self.login_as("admin")
        for url in ["/farmers", "/memberships", "/farms", "/crops", "/harvests", "/sales", "/payments", "/contributions", "/expenses"]:
            self.assert_status(url, 403)

    def test_admin_system_pages_are_available(self):
        self.login_as("admin")
        for url in [
            "/users",
            "/cooperatives",
            "/audit-logs",
            "/admin/security",
            "/admin/backup-restore",
            "/admin/system-health",
            "/admin/data-exports",
            "/admin/role-permissions",
            "/admin/system-settings",
        ]:
            self.assert_status(url, 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
