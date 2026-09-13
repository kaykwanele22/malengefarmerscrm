import importlib
import os
import tempfile
import unittest
from pathlib import Path


class AuthenticationLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory(prefix="malenge_auth_lifecycle_")
        cls.db_path = Path(cls.tempdir.name) / "auth.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{cls.db_path.as_posix()}"
        os.environ["SECRET_KEY"] = "auth-lifecycle-regression-secret"
        os.environ["APP_ENV"] = "development"
        os.environ["TWO_FACTOR_REQUIRED"] = "false"

        cls.crm = importlib.import_module("app")
        cls.auth = importlib.import_module("auth_hardening")
        cls.crm.app.config.update(TESTING=True, TWO_FACTOR_REQUIRED=False)
        cls.auth.ACCOUNT_LOCK_FAILURES = 3
        cls.auth.ACCOUNT_LOCK_MINUTES = 15

        with cls.crm.app.app_context():
            cls.crm.db.create_all()
            cls._seed()

    @classmethod
    def _seed(cls):
        c = cls.crm
        coop = c.Cooperative(
            name="Auth Lifecycle Primary",
            cooperative_type="Primary",
            code="AUTH-P",
            status="Active",
        )
        c.db.session.add(coop)
        c.db.session.flush()
        cls.coop_id = coop.id

        admin = c.User(
            fullname="Lifecycle Admin",
            phone="0718000001",
            email="admin@auth-lifecycle.local",
            farm_location="Malenge",
            password=c.generate_password_hash("Testing123!"),
        )
        treasurer = c.User(
            fullname="Lifecycle Treasurer",
            phone="0718000002",
            email="treasurer@auth-lifecycle.local",
            farm_location="Malenge",
            password=c.generate_password_hash("Testing123!"),
        )
        c.db.session.add_all([admin, treasurer])
        c.db.session.flush()
        cls.admin_id = admin.id
        cls.treasurer_id = treasurer.id
        c.db.session.add_all([
            c.UserAccess(user_id=admin.id, cooperative_id=None, role="Admin", status="Active"),
            c.UserAccess(user_id=treasurer.id, cooperative_id=coop.id, role="Primary Treasurer", status="Active"),
            cls.auth.UserSecurity(user_id=admin.id, password_changed_at=c.utc_now()),
            cls.auth.UserSecurity(user_id=treasurer.id, password_changed_at=c.utc_now()),
        ])
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
        with self.crm.app.app_context():
            for security in self.auth.UserSecurity.query.all():
                security.failed_login_count = 0
                security.locked_until = None
                security.must_change_password = False
                security.auth_version = 1
                security.last_login_at = None
                security.last_login_ip = None
                security.last_login_user_agent = None
            self.crm.AuditLog.query.delete()
            extra_ids = [u.id for u in self.crm.User.query.filter(~self.crm.User.id.in_([self.admin_id, self.treasurer_id])).all()]
            if extra_ids:
                self.auth.UserSecurity.query.filter(self.auth.UserSecurity.user_id.in_(extra_ids)).delete(synchronize_session=False)
                self.crm.UserAccess.query.filter(self.crm.UserAccess.user_id.in_(extra_ids)).delete(synchronize_session=False)
                self.crm.User.query.filter(self.crm.User.id.in_(extra_ids)).delete(synchronize_session=False)
            self.crm.db.session.commit()

    def login_session_as(self, user_id, fullname="Test User"):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess["user_id"] = user_id
            sess["fullname"] = fullname
            sess["two_factor_authenticated"] = True
            sess["two_factor_bypassed"] = True
            sess["auth_version"] = 1

    def test_persistent_account_lock_and_admin_unlock(self):
        for _ in range(3):
            self.client.post("/login", data={
                "email": "treasurer@auth-lifecycle.local",
                "password": "WrongPassword1!",
            }, follow_redirects=False)

        with self.crm.app.app_context():
            security = self.auth.UserSecurity.query.filter_by(user_id=self.treasurer_id).one()
            self.assertGreaterEqual(security.failed_login_count, 3)
            self.assertIsNotNone(security.locked_until)
            self.assertIsNotNone(self.crm.AuditLog.query.filter_by(action="ACCOUNT_LOCKED", entity_id=self.treasurer_id).first())

        blocked = self.client.post("/login", data={
            "email": "treasurer@auth-lifecycle.local",
            "password": "Testing123!",
        }, follow_redirects=False)
        self.assertIn(blocked.status_code, {303, 429})
        with self.client.session_transaction() as sess:
            self.assertFalse(bool(sess.get("user_id")))

        self.login_session_as(self.admin_id, "Lifecycle Admin")
        response = self.client.post(f"/users/{self.treasurer_id}/unlock", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        with self.crm.app.app_context():
            security = self.auth.UserSecurity.query.filter_by(user_id=self.treasurer_id).one()
            self.assertEqual(security.failed_login_count, 0)
            self.assertIsNone(security.locked_until)
            self.assertIsNotNone(self.crm.AuditLog.query.filter_by(action="ACCOUNT_UNLOCKED", entity_id=self.treasurer_id).first())

    def test_admin_created_user_must_replace_temporary_password(self):
        self.login_session_as(self.admin_id, "Lifecycle Admin")
        response = self.client.post("/users/add", data={
            "fullname": "Temporary Secretary",
            "phone": "0718000099",
            "email": "temporary@auth-lifecycle.local",
            "farm_location": "Malenge",
            "password": "Temporary1!",
            "confirm_password": "Temporary1!",
            "role": "Primary Secretary",
            "cooperative_id": str(self.coop_id),
            "status": "Active",
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 302)

        with self.crm.app.app_context():
            user = self.crm.User.query.filter_by(email="temporary@auth-lifecycle.local").one()
            user_id = user.id
            security = self.auth.UserSecurity.query.filter_by(user_id=user.id).one()
            self.assertTrue(security.must_change_password)
            self.assertIsNone(security.password_changed_at)

        with self.client.session_transaction() as sess:
            sess.clear()
        response = self.client.post("/login", data={
            "email": "temporary@auth-lifecycle.local",
            "password": "Temporary1!",
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/password/change-required", response.headers.get("Location", ""))

        page = self.client.get("/password/change-required")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Choose your own password", page.data)

        weak = self.client.post("/password/change-required", data={
            "current_password": "Temporary1!",
            "new_password": "short",
            "confirm_password": "short",
        }, follow_redirects=False)
        self.assertIn(weak.status_code, {303, 400})

        response = self.client.post("/password/change-required", data={
            "current_password": "Temporary1!",
            "new_password": "Permanent2!",
            "confirm_password": "Permanent2!",
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 302)

        with self.crm.app.app_context():
            user = self.crm.db.session.get(self.crm.User, user_id)
            security = self.auth.UserSecurity.query.filter_by(user_id=user_id).one()
            self.assertTrue(self.crm.check_password_hash(user.password, "Permanent2!"))
            self.assertFalse(security.must_change_password)
            self.assertIsNotNone(security.password_changed_at)
            self.assertGreater(security.auth_version, 1)
            self.assertIsNotNone(self.crm.AuditLog.query.filter_by(action="PASSWORD_ROTATED_REQUIRED", entity_id=user_id).first())

    def test_successful_login_tracks_activity(self):
        response = self.client.post("/login", data={
            "email": "treasurer@auth-lifecycle.local",
            "password": "Testing123!",
        }, headers={"User-Agent": "AuthLifecycleRegression/1.0"}, follow_redirects=False)
        self.assertIn(response.status_code, {302, 303})
        dashboard = self.client.get(
            "/dashboard",
            headers={"User-Agent": "AuthLifecycleRegression/1.0"},
            follow_redirects=False,
        )
        # Role-aware dashboards may redirect an authenticated user to a more specific
        # workspace. The security hook must still record the successful login before
        # that redirect, and the request must never bounce back to the login page.
        self.assertIn(dashboard.status_code, {200, 302, 303})
        self.assertNotIn("/login", dashboard.headers.get("Location", ""))
        with self.crm.app.app_context():
            security = self.auth.UserSecurity.query.filter_by(user_id=self.treasurer_id).one()
            self.assertIsNotNone(security.last_login_at)
            self.assertEqual(security.failed_login_count, 0)
            self.assertIn("AuthLifecycleRegression", security.last_login_user_agent or "")

    def test_admin_password_reset_revokes_existing_session_and_requires_rotation(self):
        user_client = self.crm.app.test_client()
        response = user_client.post("/login", data={
            "email": "treasurer@auth-lifecycle.local",
            "password": "Testing123!",
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        authenticated = user_client.get("/dashboard", follow_redirects=False)
        self.assertIn(authenticated.status_code, {200, 302, 303})
        self.assertNotIn("/login", authenticated.headers.get("Location", ""))

        self.login_session_as(self.admin_id, "Lifecycle Admin")
        response = self.client.post(f"/users/reset-password/{self.treasurer_id}", data={
            "new_password": "ResetSecure3!",
            "confirm_password": "ResetSecure3!",
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 302)

        with self.crm.app.app_context():
            security = self.auth.UserSecurity.query.filter_by(user_id=self.treasurer_id).one()
            self.assertTrue(security.must_change_password)
            self.assertGreater(security.auth_version, 1)

        revoked = user_client.get("/dashboard", follow_redirects=False)
        self.assertEqual(revoked.status_code, 302)
        self.assertIn("/login", revoked.headers.get("Location", ""))

    def test_admin_security_history_is_admin_only(self):
        self.login_session_as(self.treasurer_id, "Lifecycle Treasurer")
        self.assertEqual(self.client.get(f"/users/{self.treasurer_id}/security").status_code, 403)

        self.login_session_as(self.admin_id, "Lifecycle Admin")
        response = self.client.get(f"/users/{self.treasurer_id}/security")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Security &amp; Access Activity", response.data)
        self.assertIn(b"Lifecycle Treasurer", response.data)


if __name__ == "__main__":
    unittest.main()
