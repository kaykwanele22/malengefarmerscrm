import importlib
import os
import tempfile
import unittest
from pathlib import Path

from sqlalchemy.exc import IntegrityError, SQLAlchemyError


class ErrorFeedbackRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory(prefix="malenge_error_feedback_")
        cls.db_path = Path(cls.tempdir.name) / "errors.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{cls.db_path.as_posix()}"
        os.environ["SECRET_KEY"] = "malenge-error-feedback-regression-secret"
        os.environ["APP_ENV"] = "development"
        os.environ["TWO_FACTOR_REQUIRED"] = "false"

        cls.crm = importlib.import_module("app")
        cls.crm.app.config.update(
            TESTING=True,
            PROPAGATE_EXCEPTIONS=False,
            TWO_FACTOR_REQUIRED=False,
        )

        def validation_route():
            if cls.crm.request.method == "POST":
                return "Title is required.", 400
            return """
                <!DOCTYPE html>
                <html><body>
                    <form method="POST" action="/__error_feedback__/validation">
                        <input name="title" value="">
                        <input name="password" type="password" value="">
                        <button type="submit">Save</button>
                    </form>
                </body></html>
            """

        def crash_route():
            raise RuntimeError("secret internal diagnostic")

        def integrity_route():
            raise IntegrityError("INSERT INTO hidden_table", {"secret": "value"}, RuntimeError("duplicate secret"))

        def database_route():
            raise SQLAlchemyError("private database diagnostic")

        def api_get_only():
            return {"ok": True}

        cls.crm.app.add_url_rule(
            "/__error_feedback__/validation",
            endpoint="error_feedback_validation",
            view_func=validation_route,
            methods=["GET", "POST"],
        )
        cls.crm.app.add_url_rule(
            "/__error_feedback__/crash",
            endpoint="error_feedback_crash",
            view_func=crash_route,
            methods=["GET"],
        )
        cls.crm.app.add_url_rule(
            "/__error_feedback__/integrity",
            endpoint="error_feedback_integrity",
            view_func=integrity_route,
            methods=["GET"],
        )
        cls.crm.app.add_url_rule(
            "/__error_feedback__/database",
            endpoint="error_feedback_database",
            view_func=database_route,
            methods=["GET"],
        )
        cls.crm.app.add_url_rule(
            "/api/v1/__error_feedback__/get-only",
            endpoint="error_feedback_api_get_only",
            view_func=api_get_only,
            methods=["GET"],
        )

    @classmethod
    def tearDownClass(cls):
        with cls.crm.app.app_context():
            cls.crm.db.session.remove()
            cls.crm.db.engine.dispose()
        cls.tempdir.cleanup()

    def setUp(self):
        self.client = self.crm.app.test_client()
        self.crm.app.config.update(
            TESTING=True,
            PROPAGATE_EXCEPTIONS=False,
            TWO_FACTOR_REQUIRED=False,
        )

    def test_html_404_is_branded_and_has_support_reference(self):
        request_id = "error-feedback-404-reference"
        response = self.client.get(
            "/this-route-does-not-exist",
            headers={"X-Request-ID": request_id},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.headers.get("X-Request-ID"), request_id)
        self.assertIn(b"Page not found", response.data)
        self.assertIn(request_id.encode("utf-8"), response.data)
        self.assertIn(b"Share this reference", response.data)

    def test_api_404_uses_consistent_json_envelope(self):
        request_id = "api-error-reference"
        response = self.client.get(
            "/api/v1/does-not-exist",
            headers={"X-Request-ID": request_id},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.mimetype, "application/json")
        payload = response.get_json()
        self.assertEqual(payload["error"]["status"], 404)
        self.assertEqual(payload["error"]["title"], "Page not found")
        self.assertEqual(payload["error"]["request_id"], request_id)

    def test_api_method_not_allowed_is_json_not_framework_html(self):
        response = self.client.post("/api/v1/__error_feedback__/get-only")
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.mimetype, "application/json")
        payload = response.get_json()
        self.assertEqual(payload["error"]["status"], 405)
        self.assertEqual(payload["error"]["title"], "Action not allowed")
        self.assertTrue(payload["error"]["request_id"])

    def test_form_validation_redirects_back_and_restores_safe_values(self):
        response = self.client.post(
            "/__error_feedback__/validation",
            data={"title": "Saved title", "password": "NeverStoreThisPassword!"},
            headers={"Referer": "http://localhost/__error_feedback__/validation"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["Location"].endswith("/__error_feedback__/validation"))

        page = self.client.get(response.headers["Location"])
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Please check this form", page.data)
        self.assertIn(b"Title is required.", page.data)
        self.assertIn(b"Saved title", page.data)
        self.assertNotIn(b"NeverStoreThisPassword!", page.data)

    def test_integrity_error_rolls_back_and_returns_safe_conflict(self):
        response = self.client.get("/__error_feedback__/integrity")
        self.assertEqual(response.status_code, 409)
        self.assertIn(b"Record conflict", response.data)
        self.assertNotIn(b"hidden_table", response.data)
        self.assertNotIn(b"duplicate secret", response.data)
        self.assertNotIn(b"secret", response.data.lower())

    def test_database_error_returns_safe_service_unavailable(self):
        response = self.client.get("/__error_feedback__/database")
        self.assertEqual(response.status_code, 503)
        self.assertIn(b"Service temporarily unavailable", response.data)
        self.assertNotIn(b"private database diagnostic", response.data)

    def test_unhandled_exception_returns_safe_500_with_reference(self):
        request_id = "error-feedback-500-reference"
        response = self.client.get(
            "/__error_feedback__/crash",
            headers={"X-Request-ID": request_id},
        )
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.headers.get("X-Request-ID"), request_id)
        self.assertIn(b"Something went wrong", response.data)
        self.assertIn(request_id.encode("utf-8"), response.data)
        self.assertNotIn(b"secret internal diagnostic", response.data)

    def test_accept_json_gets_json_error_outside_api_namespace(self):
        response = self.client.get(
            "/another-missing-route",
            headers={"Accept": "application/json"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.mimetype, "application/json")
        self.assertEqual(response.get_json()["error"]["status"], 404)


if __name__ == "__main__":
    unittest.main()
