import importlib
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path


class ExecutiveRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory(prefix="malenge_exec_test_")
        cls.db_path = Path(cls.tempdir.name) / "executives.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{cls.db_path.as_posix()}"
        os.environ["SECRET_KEY"] = "malenge-executive-regression-secret"
        os.environ["APP_ENV"] = "development"

        cls.crm = importlib.import_module("app")
        cls.crm.app.config.update(TESTING=True, TWO_FACTOR_REQUIRED=False)

        with cls.crm.app.app_context():
            cls.crm.db.create_all()
            cls._seed_data()

    @classmethod
    def _seed_data(cls):
        c = cls.crm
        secondary = c.Cooperative(
            name="Malenge Secondary Exec Test",
            cooperative_type="Secondary",
            status="Active",
        )
        primary_a = c.Cooperative(
            name="Siyaphumla Exec Test",
            cooperative_type="Primary",
            parent=secondary,
            status="Active",
        )
        primary_b = c.Cooperative(
            name="Vimba Exec Test",
            cooperative_type="Primary",
            parent=secondary,
            status="Active",
        )
        c.db.session.add_all([secondary, primary_a, primary_b])
        c.db.session.flush()
        cls.secondary_id = secondary.id
        cls.primary_a_id = primary_a.id
        cls.primary_b_id = primary_b.id

        admin = c.User(
            fullname="System Admin",
            phone="0700000000",
            email="admin@exec.local",
            farm_location="Malenge",
            password=c.generate_password_hash("Testing123!"),
        )
        c.db.session.add(admin)
        c.db.session.flush()
        c.db.session.add(c.UserAccess(
            user_id=admin.id,
            role="Admin",
            status="Active",
            cooperative_id=None,
        ))
        cls.admin_id = admin.id

        cls.user_ids = []
        for index in range(1, 4):
            user = c.User(
                fullname=f"Executive Candidate {index}",
                phone=f"071000000{index}",
                email=f"candidate{index}@exec.local",
                farm_location="Malenge",
                password=c.generate_password_hash("Testing123!"),
            )
            c.db.session.add(user)
            c.db.session.flush()
            c.db.session.add(c.UserAccess(
                user_id=user.id,
                role="Primary Secretary",
                status="Inactive",
                cooperative_id=primary_a.id,
            ))
            cls.user_ids.append(user.id)

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
            self.crm.ExecutiveAppointment.query.delete()
            self.crm.AuditLog.query.delete()
            for user_id in self.user_ids:
                access = self.crm.UserAccess.query.filter_by(user_id=user_id).first()
                access.role = "Primary Secretary"
                access.status = "Inactive"
                access.cooperative_id = self.primary_a_id
            self.crm.db.session.commit()
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.admin_id
            sess["fullname"] = "System Admin"

    def test_executive_dashboard_has_fifteen_positions(self):
        response = self.client.get("/executives")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Total Executive Positions", response.data)
        self.assertIn(b">15<", response.data)

    def test_assign_executive_updates_access_and_history(self):
        response = self.client.post(
            "/executives/assign",
            data={
                "user_id": str(self.user_ids[0]),
                "cooperative_id": str(self.primary_a_id),
                "role": "Primary Chairperson",
                "start_date": "2026-09-10",
                "notes": "Board appointment",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        with self.crm.app.app_context():
            appointment = self.crm.ExecutiveAppointment.query.filter_by(
                user_id=self.user_ids[0], status="Active"
            ).one()
            self.assertEqual(appointment.role, "Primary Chairperson")
            self.assertEqual(appointment.cooperative_id, self.primary_a_id)
            self.assertEqual(appointment.start_date, date(2026, 9, 10))
            access = self.crm.UserAccess.query.filter_by(user_id=self.user_ids[0]).one()
            self.assertEqual(access.role, "Primary Chairperson")
            self.assertEqual(access.status, "Active")
            self.assertEqual(access.cooperative_id, self.primary_a_id)
            self.assertIsNotNone(self.crm.AuditLog.query.filter_by(action="EXECUTIVE_ASSIGNED").first())

    def test_duplicate_active_position_is_rejected(self):
        self.test_assign_executive_updates_access_and_history()
        response = self.client.post(
            "/executives/assign",
            data={
                "user_id": str(self.user_ids[1]),
                "cooperative_id": str(self.primary_a_id),
                "role": "Primary Chairperson",
                "start_date": "2026-09-10",
            },
        )
        self.assertEqual(response.status_code, 303)
        with self.crm.app.app_context():
            self.assertEqual(
                self.crm.ExecutiveAppointment.query.filter_by(
                    cooperative_id=self.primary_a_id,
                    role="Primary Chairperson",
                    status="Active",
                ).count(),
                1,
            )

    def test_one_user_cannot_hold_two_active_positions(self):
        self.test_assign_executive_updates_access_and_history()
        response = self.client.post(
            "/executives/assign",
            data={
                "user_id": str(self.user_ids[0]),
                "cooperative_id": str(self.primary_a_id),
                "role": "Primary Vice Chairperson",
                "start_date": "2026-09-10",
            },
        )
        self.assertEqual(response.status_code, 303)
        with self.crm.app.app_context():
            self.assertEqual(
                self.crm.ExecutiveAppointment.query.filter_by(
                    user_id=self.user_ids[0], status="Active"
                ).count(),
                1,
            )

    def test_secondary_role_cannot_be_assigned_to_primary(self):
        response = self.client.post(
            "/executives/assign",
            data={
                "user_id": str(self.user_ids[0]),
                "cooperative_id": str(self.primary_a_id),
                "role": "Secondary Secretary",
                "start_date": "2026-09-10",
            },
        )
        self.assertEqual(response.status_code, 303)
        with self.crm.app.app_context():
            self.assertEqual(self.crm.ExecutiveAppointment.query.count(), 0)

    def test_replace_executive_preserves_old_history(self):
        self.test_assign_executive_updates_access_and_history()
        with self.crm.app.app_context():
            old_id = self.crm.ExecutiveAppointment.query.filter_by(status="Active").one().id

        response = self.client.post(
            f"/executives/replace/{old_id}",
            data={
                "user_id": str(self.user_ids[1]),
                "effective_date": "2026-09-15",
                "notes": "Replacement resolution",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        with self.crm.app.app_context():
            appointments = self.crm.ExecutiveAppointment.query.order_by(
                self.crm.ExecutiveAppointment.id.asc()
            ).all()
            self.assertEqual(len(appointments), 2)
            self.assertEqual(appointments[0].status, "Inactive")
            self.assertEqual(appointments[0].end_date, date(2026, 9, 15))
            self.assertEqual(appointments[1].status, "Active")
            self.assertEqual(appointments[1].user_id, self.user_ids[1])
            old_access = self.crm.UserAccess.query.filter_by(user_id=self.user_ids[0]).one()
            new_access = self.crm.UserAccess.query.filter_by(user_id=self.user_ids[1]).one()
            self.assertEqual(old_access.status, "Inactive")
            self.assertEqual(new_access.status, "Active")
            self.assertIsNotNone(self.crm.AuditLog.query.filter_by(action="EXECUTIVE_REPLACED").first())

    def test_deactivate_executive_retains_history(self):
        self.test_assign_executive_updates_access_and_history()
        with self.crm.app.app_context():
            appointment_id = self.crm.ExecutiveAppointment.query.filter_by(status="Active").one().id

        response = self.client.post(
            f"/executives/deactivate/{appointment_id}",
            data={"end_date": "2026-09-20"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        with self.crm.app.app_context():
            appointment = self.crm.db.session.get(self.crm.ExecutiveAppointment, appointment_id)
            self.assertEqual(appointment.status, "Inactive")
            self.assertEqual(appointment.end_date, date(2026, 9, 20))
            access = self.crm.UserAccess.query.filter_by(user_id=self.user_ids[0]).one()
            self.assertEqual(access.status, "Inactive")
            self.assertIsNotNone(self.crm.AuditLog.query.filter_by(action="EXECUTIVE_DEACTIVATED").first())

    def test_history_page_keeps_inactive_appointments(self):
        self.test_deactivate_executive_retains_history()
        response = self.client.get("/executives/history")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Executive Candidate 1", response.data)
        self.assertIn(b"Inactive", response.data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
