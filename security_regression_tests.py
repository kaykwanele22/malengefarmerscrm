import csv
import importlib
import io
import os
import tempfile
import unittest
from pathlib import Path


class SecurityRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory(prefix="malenge_security_test_")
        cls.db_path = Path(cls.tempdir.name) / "security.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{cls.db_path.as_posix()}"
        os.environ["SECRET_KEY"] = "malenge-security-regression-secret"
        os.environ["APP_ENV"] = "development"

        cls.crm = importlib.import_module("app")
        cls.crm.app.config.update(TESTING=True)

        with cls.crm.app.app_context():
            cls.crm.db.create_all()
            cls._seed_data()

    @classmethod
    def _seed_data(cls):
        c = cls.crm
        secondary = c.Cooperative(
            name="Malenge Secondary Security",
            cooperative_type="Secondary",
            status="Active",
        )
        primary_a = c.Cooperative(
            name="Security Primary A",
            cooperative_type="Primary",
            status="Active",
            parent=secondary,
        )
        primary_b = c.Cooperative(
            name="Security Primary B",
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
        users = {
            "admin": ("Admin", None),
            "chair": ("Primary Chairperson", primary_a.id),
            "secretary": ("Primary Secretary", primary_a.id),
            "treasurer": ("Primary Treasurer", primary_a.id),
        }
        for key, (role, cooperative_id) in users.items():
            user = c.User(
                fullname=key.title(),
                phone="0710000000",
                email=f"{key}@security.local",
                farm_location="Security Test",
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

        farmer_a = c.Farmer(
            cooperative_id=primary_a.id,
            fullname="Security Farmer A",
            phone="0720000000",
            location="Primary A",
            status="Active",
        )
        farmer_b = c.Farmer(
            cooperative_id=primary_b.id,
            fullname="Security Farmer B",
            phone="0730000000",
            location="Primary B",
            status="Active",
        )
        c.db.session.add_all([farmer_a, farmer_b])
        c.db.session.commit()
        cls.farmer_a_id = farmer_a.id
        cls.farmer_b_id = farmer_b.id

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
        self.crm.app.config["TESTING"] = True
        self.crm.app.config["TEST_TWO_FACTOR"] = False
        self.crm.app.config["TWO_FACTOR_REQUIRED"] = True
        with self.crm._LOGIN_FAILURE_LOCK:
            self.crm._LOGIN_FAILURES.clear()

    def login_session(self, key):
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user_ids[key]
            sess["fullname"] = key

    def test_all_state_changing_forms_have_csrf_tokens(self):
        import re
        form_re = re.compile(r'<form\b[^>]*method\s*=\s*["\']?post["\']?[^>]*>', re.I | re.S)
        missing = []
        for path in Path("templates").glob("*.html"):
            text = path.read_text(encoding="utf-8")
            for index, match in enumerate(form_re.finditer(text), start=1):
                end = text.find("</form>", match.end())
                body = text[match.start():end + 7 if end >= 0 else len(text)]
                if 'name="csrf_token"' not in body and "name='csrf_token'" not in body:
                    missing.append(f"{path.name} form #{index}")
        self.assertEqual(missing, [])

    def test_csrf_rejects_missing_token(self):
        self.crm.app.config["TESTING"] = False
        self.crm.app.config["TWO_FACTOR_REQUIRED"] = False
        response = self.client.post(
            "/login",
            data={"email": "admin@security.local", "password": "Testing123!"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"security token", response.data.lower())

    def test_csrf_allows_valid_token(self):
        self.crm.app.config["TESTING"] = False
        self.crm.app.config["TWO_FACTOR_REQUIRED"] = False
        get_response = self.client.get("/login")
        self.assertEqual(get_response.status_code, 200)
        with self.client.session_transaction() as sess:
            token = sess.get("_csrf_token")
        self.assertTrue(token)
        response = self.client.post(
            "/login",
            data={
                "email": "admin@security.local",
                "password": "Testing123!",
                "csrf_token": token,
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/dashboard", response.headers.get("Location", ""))

    def test_security_headers_are_present(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(response.headers.get("X-Frame-Options"), "DENY")
        self.assertIn("default-src 'self'", response.headers.get("Content-Security-Policy", ""))
        self.assertTrue(response.headers.get("X-Request-ID"))

    def test_admin_cannot_direct_access_cooperative_extended_modules(self):
        self.login_session("admin")
        for url in ("/customers", "/suppliers", "/inventory", "/equipment", "/tasks", "/interactions"):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 403)

    def test_duplicate_active_executive_position_is_rejected(self):
        c = self.crm
        with c.app.app_context():
            cooperative, error = c.validate_admin_user_assignment(
                "Primary Chairperson",
                "Active",
                self.primary_a_id,
            )
            self.assertIsNone(cooperative)
            self.assertIsNotNone(error)
            self.assertIn("already actively assigned", error)

    def test_malenge_structure_limits_are_enforced(self):
        c = self.crm
        with c.app.app_context():
            _, secondary_error = c.validate_cooperative_configuration(
                "Secondary", None, "Active"
            )
            _, primary_error = c.validate_cooperative_configuration(
                "Primary", self.secondary_id, "Active"
            )
            self.assertIsNotNone(secondary_error)
            self.assertIsNotNone(primary_error)

    def test_audit_log_captures_request_metadata(self):
        self.login_session("secretary")
        response = self.client.get(
            "/logout",
            headers={"User-Agent": "MalengeSecurityTest/1.0"},
        )
        self.assertEqual(response.status_code, 302)
        with self.crm.app.app_context():
            log = self.crm.AuditLog.query.filter_by(
                user_id=self.user_ids["secretary"], action="LOGOUT"
            ).order_by(self.crm.AuditLog.id.desc()).first()
            self.assertIsNotNone(log)
            self.assertEqual(log.request_method, "GET")
            self.assertEqual(log.request_path, "/logout")
            self.assertTrue(log.request_id)
            self.assertEqual(log.user_agent, "MalengeSecurityTest/1.0")

    def test_csv_cells_are_formula_safe(self):
        self.assertEqual(self.crm.csv_safe_cell("=2+2"), "'=2+2")
        self.assertEqual(self.crm.csv_safe_cell("+cmd"), "'+cmd")
        self.assertEqual(self.crm.csv_safe_cell("normal"), "normal")
        self.assertEqual(self.crm.csv_safe_cell(42), 42)

    def test_login_throttling_blocks_repeated_failures(self):
        c = self.crm
        c.app.config["TESTING"] = False
        old_account = c.LOGIN_MAX_FAILURES_PER_ACCOUNT
        old_ip = c.LOGIN_MAX_FAILURES_PER_IP
        try:
            c.LOGIN_MAX_FAILURES_PER_ACCOUNT = 2
            c.LOGIN_MAX_FAILURES_PER_IP = 50
            self.client.get("/login")
            with self.client.session_transaction() as sess:
                token = sess.get("_csrf_token")

            payload = {
                "email": "admin@security.local",
                "password": "wrong-password",
                "csrf_token": token,
            }
            first = self.client.post("/login", data=payload, follow_redirects=False)
            self.assertEqual(first.status_code, 303)

            # The 303 validation redirect stores form feedback in the session but does not
            # rotate the CSRF token, so the same token remains valid for this test sequence.
            second = self.client.post("/login", data=payload, follow_redirects=False)
            self.assertEqual(second.status_code, 303)
            third = self.client.post("/login", data=payload, follow_redirects=False)
            self.assertEqual(third.status_code, 429)
        finally:
            c.LOGIN_MAX_FAILURES_PER_ACCOUNT = old_account
            c.LOGIN_MAX_FAILURES_PER_IP = old_ip
            with c._LOGIN_FAILURE_LOCK:
                c._LOGIN_FAILURES.clear()

    def test_cross_cooperative_extended_link_is_rejected(self):
        c = self.crm
        with c.app.app_context():
            # Give the Primary Chairperson an own-coop farm and prepare a foreign farm ID.
            own_farm = c.Farm(
                cooperative_id=self.primary_a_id,
                farmer_id=self.farmer_a_id,
                name="Own Security Farm",
                location="A",
                status="Active",
            )
            foreign_farm = c.Farm(
                cooperative_id=self.primary_b_id,
                farmer_id=self.farmer_b_id,
                name="Foreign Security Farm",
                location="B",
                status="Active",
            )
            c.db.session.add_all([own_farm, foreign_farm])
            c.db.session.commit()
            foreign_farm_id = foreign_farm.id

        self.login_session("chair")
        response = self.client.post(
            "/equipment/add",
            data={
                "name": "Tampered Tractor",
                "farm_id": str(foreign_farm_id),
                "status": "Available",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        with c.app.app_context():
            self.assertIsNone(c.Equipment.query.filter_by(name="Tampered Tractor").first())

    def test_totp_matches_rfc6238_sha1_vector(self):
        # RFC 6238 SHA-1 test secret: ASCII "12345678901234567890".
        secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
        # RFC vector at Unix time 59 is 94287082 for 8 digits.
        self.assertEqual(
            self.crm.totp_code_for_counter(secret, 59 // 30, digits=8),
            "94287082",
        )

    def test_google_authenticator_enrollment_and_login_flow(self):
        c = self.crm
        c.app.config["TEST_TWO_FACTOR"] = True

        # Password login for an unenrolled account must go to Google Authenticator setup.
        response = self.client.post(
            "/login",
            data={"email": "admin@security.local", "password": "Testing123!"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/2fa/setup", response.headers.get("Location", ""))

        setup_page = self.client.get("/2fa/setup")
        self.assertEqual(setup_page.status_code, 200)
        self.assertIn(b"Google Authenticator", setup_page.data)

        with c.app.app_context():
            user = c.db.session.get(c.User, self.user_ids["admin"])
            secret = c.decrypt_two_factor_secret(user.two_factor_secret)
            setup_counter = int(c.time.time()) // 30
            code = c.totp_code_for_counter(secret, setup_counter)

        response = self.client.post(
            "/2fa/setup",
            data={"code": code},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"now enabled", response.data)

        with c.app.app_context():
            user = c.db.session.get(c.User, self.user_ids["admin"])
            self.assertTrue(user.two_factor_enabled)
            self.assertEqual(c.recovery_code_count(user), 8)
            self.assertIsNotNone(user.two_factor_confirmed_at)

        # A new password login must now stop at the 2FA verification page.
        self.client.get("/logout")
        response = self.client.post(
            "/login",
            data={"email": "admin@security.local", "password": "Testing123!"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/2fa/verify", response.headers.get("Location", ""))

        with c.app.app_context():
            user = c.db.session.get(c.User, self.user_ids["admin"])
            secret = c.decrypt_two_factor_secret(user.two_factor_secret)
            # Use the next window; valid_window=1 accepts it while replay protection
            # prevents reuse of the setup counter.
            verify_code = c.totp_code_for_counter(secret, (int(c.time.time()) // 30) + 1)

        response = self.client.post(
            "/2fa/verify",
            data={"code": verify_code},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/dashboard", response.headers.get("Location", ""))

    def test_recovery_code_is_one_time(self):
        c = self.crm
        with c.app.app_context():
            user = c.db.session.get(c.User, self.user_ids["secretary"])
            codes = c.generate_recovery_codes(2)
            c.set_recovery_codes(user, codes)
            c.db.session.commit()
            first = codes[0]
            self.assertTrue(c.consume_recovery_code(user, first))
            self.assertFalse(c.consume_recovery_code(user, first))
            self.assertEqual(c.recovery_code_count(user), 1)



if __name__ == "__main__":
    unittest.main(verbosity=2)
