import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile


class BackupRecoveryRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory(prefix="malenge_recovery_test_")
        cls.root = Path(cls.tempdir.name)
        cls.db_path = cls.root / "recovery.db"
        cls.accountability_path = cls.root / "accountability"
        cls.documents_path = cls.root / "documents"
        cls.bundle_path = cls.root / "bundles"
        cls.accountability_path.mkdir(parents=True, exist_ok=True)
        cls.documents_path.mkdir(parents=True, exist_ok=True)
        cls.bundle_path.mkdir(parents=True, exist_ok=True)

        os.environ["DATABASE_URL"] = f"sqlite:///{cls.db_path.as_posix()}"
        os.environ["SECRET_KEY"] = "backup-recovery-regression-secret"
        os.environ["APP_ENV"] = "development"
        os.environ["TWO_FACTOR_REQUIRED"] = "false"
        os.environ["ACCOUNTABILITY_UPLOAD_DIR"] = str(cls.accountability_path)
        os.environ["DOCUMENT_UPLOAD_DIR"] = str(cls.documents_path)
        os.environ["RECOVERY_BUNDLE_DIR"] = str(cls.bundle_path)
        os.environ["RECOVERY_BUNDLE_RETENTION"] = "7"

        cls.crm = importlib.import_module("app")
        cls.phase7 = importlib.import_module("phase7")
        cls.recovery = importlib.import_module("backup_recovery")
        cls.crm.app.config.update(TESTING=True, TWO_FACTOR_REQUIRED=False)
        cls.crm.ACCOUNTABILITY_UPLOAD_DIR = cls.accountability_path
        cls.phase7.DOCUMENT_UPLOAD_DIR = cls.documents_path

        cls.settings_path = cls.root / "system_settings.json"
        cls.settings_path.write_text(json.dumps({"brand_name": "Malenge Farmers"}), encoding="utf-8")
        cls.original_system_settings_path = cls.crm.system_settings_path
        cls.crm.system_settings_path = lambda: cls.settings_path

        cls.accountability_path.joinpath("signed-minutes.pdf").write_bytes(b"signed meeting evidence")
        cls.documents_path.joinpath("finance-receipt.pdf").write_bytes(b"finance receipt evidence")

        with cls.crm.app.app_context():
            cls.crm.db.create_all()
            cls._seed_users()

    @classmethod
    def _seed_users(cls):
        c = cls.crm
        cooperative = c.Cooperative(
            name="Recovery Test Primary",
            cooperative_type="Primary",
            status="Active",
        )
        c.db.session.add(cooperative)
        c.db.session.flush()

        admin = c.User(
            fullname="Recovery Admin",
            phone="0000000000",
            email="recovery-admin@test.local",
            farm_location="Test",
            password="not-used-in-session-test",
        )
        secretary = c.User(
            fullname="Recovery Secretary",
            phone="0000000001",
            email="recovery-secretary@test.local",
            farm_location="Test",
            password="not-used-in-session-test",
        )
        c.db.session.add_all([admin, secretary])
        c.db.session.flush()
        c.db.session.add_all([
            c.UserAccess(user_id=admin.id, role="Admin", status="Active", cooperative_id=None),
            c.UserAccess(
                user_id=secretary.id,
                role="Primary Secretary",
                status="Active",
                cooperative_id=cooperative.id,
            ),
        ])
        c.db.session.commit()
        cls.admin_id = admin.id
        cls.secretary_id = secretary.id

    @classmethod
    def tearDownClass(cls):
        cls.crm.system_settings_path = cls.original_system_settings_path
        with cls.crm.app.app_context():
            cls.crm.db.session.remove()
            cls.crm.db.drop_all()
            cls.crm.db.session.remove()
            cls.crm.db.engine.dispose()
        cls.tempdir.cleanup()

    def setUp(self):
        self.client = self.crm.app.test_client()
        for path in self.bundle_path.glob("*.zip"):
            path.unlink()
        os.environ["RECOVERY_BUNDLE_RETENTION"] = "7"

    def login_as(self, user_id):
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id
            sess["fullname"] = "Recovery Test User"

    def test_complete_sqlite_bundle_contains_database_evidence_settings_and_manifest(self):
        with self.crm.app.app_context():
            bundle = self.recovery.create_recovery_bundle()

        self.assertTrue(bundle.exists())
        verified, manifest = self.recovery.verify_recovery_bundle(bundle)
        self.assertTrue(verified, msg=manifest)
        self.assertEqual(manifest["database_backend"], "sqlite")
        self.assertEqual(manifest["database_format"], "sqlite")
        self.assertTrue(manifest["database_archive_path"].startswith("database/"))

        with ZipFile(bundle, "r") as archive:
            names = set(archive.namelist())
            self.assertIn("manifest.json", names)
            self.assertIn("evidence/accountability/signed-minutes.pdf", names)
            self.assertIn("evidence/documents/finance-receipt.pdf", names)
            self.assertIn("configuration/system_settings.json", names)
            self.assertIn(manifest["database_archive_path"], names)
            manifest_text = archive.read("manifest.json").decode("utf-8")
            self.assertNotIn("backup-recovery-regression-secret", manifest_text)

    def test_tampering_is_detected(self):
        with self.crm.app.app_context():
            bundle = self.recovery.create_recovery_bundle()

        with ZipFile(bundle, "a") as archive:
            archive.writestr("evidence/accountability/signed-minutes.pdf", b"tampered")

        verified, message = self.recovery.verify_recovery_bundle(bundle)
        self.assertFalse(verified)
        self.assertIn("duplicate", str(message).lower())

    def test_local_retention_prunes_old_bundles(self):
        os.environ["RECOVERY_BUNDLE_RETENTION"] = "2"
        with self.crm.app.app_context():
            for _ in range(4):
                self.recovery.create_recovery_bundle()
        self.assertEqual(len(list(self.bundle_path.glob("*.zip"))), 2)

    def test_admin_recovery_page_is_admin_only(self):
        response = self.client.get("/admin/recovery", follow_redirects=False)
        self.assertIn(response.status_code, {302, 401, 403})

        self.login_as(self.secretary_id)
        response = self.client.get("/admin/recovery", follow_redirects=False)
        self.assertEqual(response.status_code, 403)

        self.client = self.crm.app.test_client()
        self.login_as(self.admin_id)
        response = self.client.get("/admin/recovery", follow_redirects=False)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Disaster Recovery", response.data)

    def test_recovery_cli_commands_are_registered(self):
        self.assertIn("create-recovery-bundle", self.crm.app.cli.commands)
        self.assertIn("verify-recovery-bundle", self.crm.app.cli.commands)

    def test_postgres_bundle_refuses_to_claim_completeness_without_pg_dump(self):
        with patch.object(self.recovery, "_database_backend", return_value="postgresql"), \
             patch.object(self.recovery.shutil, "which", return_value=None):
            capabilities = self.recovery.recovery_capabilities()
        self.assertFalse(capabilities["can_create_complete_bundle"])
        self.assertFalse(capabilities["pg_dump_available"])


if __name__ == "__main__":
    unittest.main()
