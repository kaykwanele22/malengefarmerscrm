import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class OperationalReadinessRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory(prefix="malenge_readiness_test_")
        root = Path(cls.tempdir.name)
        cls.db_path = root / "readiness.db"
        cls.evidence_path = root / "evidence"
        cls.evidence_path.mkdir(parents=True, exist_ok=True)

        os.environ["DATABASE_URL"] = f"sqlite:///{cls.db_path.as_posix()}"
        os.environ["SECRET_KEY"] = "malenge-readiness-regression-secret"
        os.environ["APP_ENV"] = "development"
        os.environ["TWO_FACTOR_REQUIRED"] = "false"
        os.environ["ACCOUNTABILITY_UPLOAD_DIR"] = str(cls.evidence_path)

        cls.crm = importlib.import_module("app")
        cls.ops = importlib.import_module("operational_readiness")
        cls.crm.app.config.update(TESTING=True, TWO_FACTOR_REQUIRED=False)

        with cls.crm.app.app_context():
            cls.crm.db.create_all()

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

    def test_liveness_probe_is_dependency_free(self):
        with patch.object(self.ops, "_database_ready", side_effect=AssertionError("must not run")):
            response = self.client.get("/live")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "alive")

    def test_readiness_probe_confirms_database_and_evidence_storage(self):
        response = self.client.get("/ready")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["checks"]["database"], "ok")
        self.assertEqual(payload["checks"]["evidence_storage"], "ok")
        self.assertEqual(response.headers.get("Cache-Control"), "no-store, private, max-age=0")

    def test_readiness_returns_503_when_database_is_unavailable(self):
        with patch.object(self.ops, "_database_ready", return_value=False):
            response = self.client.get("/ready")
        self.assertEqual(response.status_code, 503)
        payload = response.get_json()
        self.assertEqual(payload["status"], "unavailable")
        self.assertEqual(payload["checks"]["database"], "unavailable")
        self.assertEqual(response.headers.get("Retry-After"), "5")
        self.assertNotIn("exception", response.get_data(as_text=True).lower())
        self.assertNotIn("database_url", response.get_data(as_text=True).lower())

    def test_readiness_returns_503_when_evidence_storage_is_unavailable(self):
        with patch.object(self.ops, "_evidence_storage_ready", return_value=False):
            response = self.client.get("/ready")
        self.assertEqual(response.status_code, 503)
        payload = response.get_json()
        self.assertEqual(payload["status"], "unavailable")
        self.assertEqual(payload["checks"]["evidence_storage"], "unavailable")
        self.assertEqual(response.headers.get("Retry-After"), "5")


if __name__ == "__main__":
    unittest.main()
