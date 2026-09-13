import importlib
import io
import os
import tempfile
import unittest
from pathlib import Path


class Phase6AccountabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory(prefix="malenge_phase6_test_")
        cls.db_path = Path(cls.tempdir.name) / "phase6.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{cls.db_path.as_posix()}"
        os.environ["SECRET_KEY"] = "malenge-phase6-regression-secret"
        os.environ["APP_ENV"] = "development"

        cls.crm = importlib.import_module("app")
        cls.crm.app.config.update(TESTING=True, TWO_FACTOR_REQUIRED=False)
        cls.crm.ACCOUNTABILITY_UPLOAD_DIR = Path(cls.tempdir.name) / "uploads"
        cls.crm.ACCOUNTABILITY_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

        with cls.crm.app.app_context():
            cls.crm.db.create_all()
            cls._seed_data()

    @classmethod
    def _seed_data(cls):
        c = cls.crm
        coop = c.Cooperative(
            name="Siyaphumla Phase 6 Test",
            cooperative_type="Primary",
            code="SIY",
            status="Active",
        )
        c.db.session.add(coop)
        c.db.session.flush()
        cls.coop_id = coop.id

        roles = [
            ("chair", "Primary Chairperson"),
            ("vice", "Primary Vice Chairperson"),
            ("secretary", "Primary Secretary"),
            ("treasurer", "Primary Treasurer"),
        ]
        cls.users = {}
        for idx, (key, role) in enumerate(roles, start=1):
            user = c.User(
                fullname=f"{role} Test",
                phone=f"07123456{idx:02d}",
                email=f"{key}@phase6.local",
                farm_location="Malenge",
                password=c.generate_password_hash("Testing123!"),
            )
            c.db.session.add(user)
            c.db.session.flush()
            c.db.session.add(c.UserAccess(
                user_id=user.id,
                cooperative_id=coop.id,
                role=role,
                status="Active",
            ))
            cls.users[key] = user.id
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
        with self.crm.app.app_context():
            self.crm.TaskEvidence.query.delete()
            self.crm.TaskUpdate.query.delete()
            self.crm.Task.query.delete()
            self.crm.Resolution.query.delete()
            self.crm.MeetingDocument.query.delete()
            self.crm.Meeting.query.delete()
            self.crm.AuditLog.query.delete()
            self.crm.db.session.commit()
        for path in self.crm.ACCOUNTABILITY_UPLOAD_DIR.glob("*"):
            path.unlink()

    def login_as(self, key):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess["user_id"] = self.users[key]
            sess["fullname"] = key.title()

    def create_confirmed_meeting(self):
        self.login_as("secretary")
        response = self.client.post("/meetings/add", data={
            "meeting_type": "General Meeting",
            "title": "September General Meeting",
            "meeting_date": "2026-09-25",
            "venue": "Malenge FPSU",
            "quorum_status": "Met",
        })
        self.assertEqual(response.status_code, 302)
        with self.crm.app.app_context():
            meeting_id = self.crm.Meeting.query.one().id

        response = self.client.post(
            f"/meetings/{meeting_id}/upload",
            data={
                "document_type": "Meeting Minutes",
                "document": (io.BytesIO(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n"), "minutes.pdf"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 302)

        self.login_as("chair")
        response = self.client.post(f"/meetings/{meeting_id}/confirm", data={})
        self.assertEqual(response.status_code, 302)
        return meeting_id

    def test_secretary_uploads_handwritten_evidence_and_chair_locks_it(self):
        meeting_id = self.create_confirmed_meeting()
        with self.crm.app.app_context():
            meeting = self.crm.db.session.get(self.crm.Meeting, meeting_id)
            self.assertEqual(meeting.status, "Confirmed")
            self.assertEqual(len(meeting.documents), 1)
            self.assertEqual(meeting.confirmed_by_user_id, self.users["chair"])
            doc = meeting.documents[0]
            self.assertTrue((self.crm.ACCOUNTABILITY_UPLOAD_DIR / doc.stored_name).exists())
            self.assertEqual(len(doc.file_sha256), 64)
            self.assertIsNotNone(self.crm.AuditLog.query.filter_by(action="MEETING_CONFIRMED").first())

        self.login_as("secretary")
        response = self.client.post(
            f"/meetings/{meeting_id}/upload",
            data={
                "document_type": "Attendance Register",
                "document": (io.BytesIO(b"%PDF-1.4\n%%EOF\n"), "late-upload.pdf"),
            },
            content_type="multipart/form-data",
        )
        # Browser form validation uses POST/Redirect/GET, so rejected POSTs return 303.
        self.assertEqual(response.status_code, 303)
        with self.crm.app.app_context():
            self.assertEqual(self.crm.MeetingDocument.query.filter_by(meeting_id=meeting_id).count(), 1)
        self.assertEqual(len(list(self.crm.ACCOUNTABILITY_UPLOAD_DIR.glob("*"))), 1)

    def test_full_resolution_to_verified_closure_workflow(self):
        meeting_id = self.create_confirmed_meeting()

        self.login_as("secretary")
        response = self.client.post("/resolutions/add", data={
            "meeting_id": str(meeting_id),
            "title": "Potato harvesting commencement",
            "resolution_text": "The cooperative resolved that potato harvesting commence on 28 September 2026.",
            "responsible_user_id": str(self.users["vice"]),
            "due_date": "2026-09-28",
            "priority": "High",
        })
        self.assertEqual(response.status_code, 302)
        with self.crm.app.app_context():
            resolution = self.crm.Resolution.query.one()
            self.assertEqual(resolution.status, "Draft")
            resolution_id = resolution.id

        self.login_as("chair")
        response = self.client.post(f"/resolutions/{resolution_id}/certify", data={})
        self.assertEqual(response.status_code, 302)
        with self.crm.app.app_context():
            task = self.crm.Task.query.filter_by(resolution_id=resolution_id).one()
            task_id = task.id
            self.assertEqual(task.assigned_user_id, self.users["vice"])
            self.assertEqual(task.status, "Open")
            self.assertEqual(task.resolution.status, "Assigned")

        self.login_as("vice")
        response = self.client.post(f"/accountability/tasks/{task_id}/update", data={
            "status": "Completed",
            "progress_percentage": "100",
            "comment": "Harvesting was completed and the field report is attached.",
        })
        self.assertEqual(response.status_code, 302)
        response = self.client.post(
            f"/accountability/tasks/{task_id}/evidence",
            data={
                "evidence_type": "Report",
                "description": "Harvest completion report",
                "evidence": (io.BytesIO(b"%PDF-1.4\n%%EOF\n"), "harvest-report.pdf"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 302)

        # The responsible executive cannot close their own accountability loop.
        response = self.client.post(f"/accountability/tasks/{task_id}/verify", data={
            "decision": "approve",
            "verification_notes": "Trying to self verify",
        })
        self.assertEqual(response.status_code, 403)

        self.login_as("chair")
        response = self.client.post(f"/accountability/tasks/{task_id}/verify", data={
            "decision": "approve",
            "verification_notes": "Checked the uploaded harvest report against the meeting resolution.",
        })
        self.assertEqual(response.status_code, 302)

        with self.crm.app.app_context():
            task = self.crm.db.session.get(self.crm.Task, task_id)
            resolution = self.crm.db.session.get(self.crm.Resolution, resolution_id)
            self.assertEqual(task.status, "Verified")
            self.assertEqual(task.verified_by_user_id, self.users["chair"])
            self.assertEqual(resolution.status, "Closed")
            self.assertIsNotNone(resolution.closed_at)
            self.assertEqual(len(task.evidence_files), 1)
            self.assertGreaterEqual(len(task.progress_updates), 3)

    def test_accountability_register_surfaces_scoped_management_audit_actions(self):
        c = self.crm
        with c.app.app_context():
            c.add_audit_log(
                "MANAGEMENT_TEST_ACTION",
                "Resolution",
                77,
                "Management action visible to governance.",
                cooperative_id=self.coop_id,
                user_id=self.users["secretary"],
            )
            c.db.session.commit()

        self.login_as("chair")
        response = self.client.get("/accountability")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Recent Management Actions", page)
        self.assertIn("Management Test Action", page)
        self.assertIn("Management action visible to governance.", page)
        self.assertIn("Primary Secretary Test", page)

    def test_other_executives_can_view_but_treasurer_cannot_register_meeting(self):
        meeting_id = self.create_confirmed_meeting()
        self.login_as("treasurer")
        self.assertEqual(self.client.get("/accountability").status_code, 200)
        self.assertEqual(self.client.get(f"/meetings/{meeting_id}").status_code, 200)
        self.assertEqual(self.client.get("/meetings/add").status_code, 403)

    def test_invalid_file_signature_is_rejected(self):
        self.login_as("secretary")
        response = self.client.post("/meetings/add", data={
            "meeting_type": "General Meeting",
            "title": "Signature Test",
            "meeting_date": "2026-09-25",
            "quorum_status": "Met",
        })
        self.assertEqual(response.status_code, 302)
        with self.crm.app.app_context():
            meeting_id = self.crm.Meeting.query.one().id
        response = self.client.post(
            f"/meetings/{meeting_id}/upload",
            data={
                "document_type": "Meeting Minutes",
                "document": (io.BytesIO(b"<html>not really a pdf</html>"), "fake.pdf"),
            },
            content_type="multipart/form-data",
        )
        # Rejected browser uploads are redirected back with form feedback (PRG pattern).
        self.assertEqual(response.status_code, 303)
        with self.crm.app.app_context():
            self.assertEqual(self.crm.MeetingDocument.query.filter_by(meeting_id=meeting_id).count(), 0)
        self.assertEqual(list(self.crm.ACCOUNTABILITY_UPLOAD_DIR.glob("*")), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
