import importlib
import io
import os
import re
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path


class Phase7OperationsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory(prefix="malenge_phase7_test_")
        cls.db_path = Path(cls.tempdir.name) / "phase7.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{cls.db_path.as_posix()}"
        os.environ["SECRET_KEY"] = "malenge-phase7-regression-secret"
        os.environ["APP_ENV"] = "development"
        os.environ["TWO_FACTOR_REQUIRED"] = "false"
        os.environ["DOCUMENT_UPLOAD_DIR"] = str(Path(cls.tempdir.name) / "documents")

        cls.crm = importlib.import_module("app")
        cls.p7 = importlib.import_module("phase7")
        cls.crm.app.config.update(TESTING=True, TWO_FACTOR_REQUIRED=False)
        cls.p7.DOCUMENT_UPLOAD_DIR = Path(cls.tempdir.name) / "documents"
        cls.p7.DOCUMENT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

        with cls.crm.app.app_context():
            cls.crm.db.create_all()
            cls._seed_baseline()

    @classmethod
    def _user(cls, key, fullname, role, cooperative_id=None):
        c = cls.crm
        user = c.User(
            fullname=fullname,
            phone=f"071000{len(cls.users)+1:04d}",
            email=f"{key}@phase7.local",
            farm_location="Malenge",
            password=c.generate_password_hash("Testing123!"),
        )
        c.db.session.add(user)
        c.db.session.flush()
        c.db.session.add(c.UserAccess(
            user_id=user.id,
            cooperative_id=cooperative_id,
            role=role,
            status="Active",
        ))
        cls.users[key] = user.id
        return user

    @classmethod
    def _seed_baseline(cls):
        c = cls.crm
        secondary = c.Cooperative(name="Phase7 MFPSU", cooperative_type="Secondary", code="P7S", status="Active")
        c.db.session.add(secondary)
        c.db.session.flush()
        primary_a = c.Cooperative(name="Phase7 Siyaphumla", cooperative_type="Primary", code="P7A", parent_id=secondary.id, status="Active")
        primary_b = c.Cooperative(name="Phase7 Vimba", cooperative_type="Primary", code="P7B", parent_id=secondary.id, status="Active")
        c.db.session.add_all([primary_a, primary_b])
        c.db.session.flush()
        cls.secondary_id = secondary.id
        cls.coop_a = primary_a.id
        cls.coop_b = primary_b.id

        cls.users = {}
        cls._user("admin", "Phase 7 Admin", "Admin", None)
        cls._user("chair_a", "A Chairperson", "Primary Chairperson", primary_a.id)
        cls._user("vice_a", "A Vice Chairperson", "Primary Vice Chairperson", primary_a.id)
        cls._user("secretary_a", "A Secretary", "Primary Secretary", primary_a.id)
        cls._user("treasurer_a", "A Treasurer", "Primary Treasurer", primary_a.id)
        cls._user("chair_b", "B Chairperson", "Primary Chairperson", primary_b.id)

        farmer_a = c.Farmer(cooperative_id=primary_a.id, fullname="Visible Farmer A", phone="0711111111", location="Malenge A", status="Active")
        farmer_b = c.Farmer(cooperative_id=primary_b.id, fullname="Hidden Farmer B", phone="0722222222", location="Malenge B", status="Active")
        c.db.session.add_all([farmer_a, farmer_b])
        c.db.session.flush()
        cls.farmer_a = farmer_a.id
        cls.farmer_b = farmer_b.id

        farm_a = c.Farm(cooperative_id=primary_a.id, name="Visible Farm A", farmer_id=farmer_a.id, location="Malenge A", size=2.0, farming_type="Crop", status="Active")
        farm_b = c.Farm(cooperative_id=primary_b.id, name="Hidden Farm B", farmer_id=farmer_b.id, location="Malenge B", size=3.0, farming_type="Crop", status="Active")
        c.db.session.add_all([farm_a, farm_b])
        c.db.session.flush()
        cls.farm_a = farm_a.id
        cls.farm_b = farm_b.id

        today = c.crm_today()
        crop_a = c.Crop(cooperative_id=primary_a.id, name="Potatoes A", farm_id=farm_a.id, variety="Mondial", planting_date=today - timedelta(days=30), area_planted=1.0, status="Growing")
        crop_b = c.Crop(cooperative_id=primary_b.id, name="Potatoes B", farm_id=farm_b.id, variety="Sifra", planting_date=today - timedelta(days=25), area_planted=1.5, status="Growing")
        c.db.session.add_all([crop_a, crop_b])
        c.db.session.flush()
        cls.crop_a = crop_a.id
        cls.crop_b = crop_b.id

        membership = c.Membership(
            cooperative_id=primary_a.id, farmer_id=farmer_a.id, member_number="P7-A-001",
            membership_type="Primary", join_date=today - timedelta(days=100), fee_amount=300, fee_paid=100,
            status="Active",
        )
        c.db.session.add(membership)
        c.db.session.flush()
        cls.membership_a = membership.id

        inventory = c.InventoryItem(
            cooperative_id=primary_a.id, name="Potato Seed", category="Seed", unit="bags",
            quantity_on_hand=2, reorder_level=5, unit_cost=500, status="Active",
        )
        equipment = c.Equipment(
            cooperative_id=primary_a.id, name="Test Tractor", equipment_type="Tractor", farm_id=farm_a.id,
            next_service_date=today + timedelta(days=5), status="Available",
        )
        c.db.session.add_all([inventory, equipment])
        c.db.session.flush()
        cls.inventory_a = inventory.id
        cls.equipment_a = equipment.id
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
        c, p = self.crm, self.p7
        with c.app.app_context():
            p.ApiAccessToken.query.delete()
            p.EquipmentUsage.query.delete()
            p.ProductionInput.query.delete()
            p.MeetingAttendance.query.delete()
            p.MeetingAgendaItem.query.delete()
            p.BankReconciliation.query.delete()
            p.Budget.query.delete()
            p.CooperativeDocument.query.delete()
            p.Notification.query.delete()
            c.TaskEvidence.query.delete()
            c.TaskUpdate.query.delete()
            c.Task.query.delete()
            c.Resolution.query.delete()
            c.MeetingDocument.query.delete()
            c.Meeting.query.delete()
            c.Payment.query.delete()
            c.Sale.query.delete()
            c.Harvest.query.delete()
            c.Expense.query.delete()
            c.Contribution.query.delete()
            c.AuditLog.query.delete()
            c.db.session.commit()
        for path in self.p7.DOCUMENT_UPLOAD_DIR.glob("*"):
            path.unlink()

    def login_as(self, key):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess["user_id"] = self.users[key]
            sess["fullname"] = key.replace("_", " ").title()

    def create_meeting_a(self):
        c = self.crm
        with c.app.app_context():
            meeting = c.Meeting(
                cooperative_id=self.coop_a,
                meeting_number=f"P7-MTG-{c.Meeting.query.count()+1:03d}",
                meeting_type="General Meeting",
                title="Phase 7 Working Meeting",
                meeting_date=c.crm_today() + timedelta(days=3),
                venue="Malenge Hall",
                quorum_status="Met",
                status="Draft",
                created_by_user_id=self.users["secretary_a"],
            )
            c.db.session.add(meeting)
            c.db.session.commit()
            return meeting.id

    def test_role_workspaces_render_and_permissions_hold(self):
        self.login_as("chair_a")
        for url in [
            "/work", "/notifications", "/documents", "/finance-control",
            "/production-control", "/reports/command-centre", "/search",
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get("/api/tokens").status_code, 403)

        self.login_as("treasurer_a")
        self.assertEqual(self.client.get("/finance-control").status_code, 200)
        self.assertEqual(self.client.get("/production-control").status_code, 403)
        self.assertEqual(self.client.get("/api/tokens").status_code, 403)

        self.login_as("admin")
        self.assertEqual(self.client.get("/reports/command-centre").status_code, 200)
        self.assertEqual(self.client.get("/finance-control").status_code, 403)
        self.assertEqual(self.client.get("/api/tokens").status_code, 200)

    def test_meeting_agenda_attendance_and_cross_cooperative_user_block(self):
        c, p = self.crm, self.p7
        meeting_id = self.create_meeting_a()
        self.login_as("secretary_a")
        response = self.client.post(f"/meetings/{meeting_id}/agenda", data={
            "item_number": "1", "title": "Potato harvesting", "status": "Open", "notes": "Harvest readiness",
        })
        self.assertEqual(response.status_code, 302)
        response = self.client.post(f"/meetings/{meeting_id}/attendance", data={
            "attendee_name": "A Chairperson", "attendance_status": "Present",
            "role_or_capacity": "Chairperson", "user_id": str(self.users["chair_a"]),
        })
        self.assertEqual(response.status_code, 302)
        response = self.client.post(f"/meetings/{meeting_id}/attendance", data={
            "attendee_name": "B Chairperson", "attendance_status": "Present",
            "role_or_capacity": "Guest", "user_id": str(self.users["chair_b"]),
        })
        self.assertEqual(response.status_code, 303)
        with c.app.app_context():
            self.assertEqual(p.MeetingAgendaItem.query.filter_by(meeting_id=meeting_id).count(), 1)
            self.assertEqual(p.MeetingAttendance.query.filter_by(meeting_id=meeting_id).count(), 1)

    def test_budget_and_statement_date_bank_reconciliation(self):
        c, p = self.crm, self.p7
        today = c.crm_today()
        with c.app.app_context():
            c.db.session.add_all([
                c.Contribution(cooperative_id=self.coop_a, farmer_id=self.farmer_a, amount=100,
                               contribution_date=today - timedelta(days=20), category="General", status="Confirmed"),
                c.Contribution(cooperative_id=self.coop_a, farmer_id=self.farmer_a, amount=50,
                               contribution_date=today + timedelta(days=5), category="General", status="Confirmed"),
                c.Expense(cooperative_id=self.coop_a, category="Fuel", description="Early expense", amount=20,
                          expense_date=today - timedelta(days=15), status="Confirmed"),
                c.Expense(cooperative_id=self.coop_a, category="Fuel", description="Later expense", amount=10,
                          expense_date=today + timedelta(days=4), status="Confirmed"),
            ])
            c.db.session.commit()

        self.login_as("treasurer_a")
        response = self.client.post("/finance-control/budgets", data={
            "fiscal_year": str(today.year), "budget_type": "Expense", "category": "Fuel",
            "planned_amount": "5000", "notes": "Fuel plan",
        })
        self.assertEqual(response.status_code, 302)
        with c.app.app_context():
            budget_id = p.Budget.query.one().id
            self.assertEqual(p.Budget.query.one().status, "Pending Approval")

        self.login_as("chair_a")
        response = self.client.post(f"/finance-control/budgets/{budget_id}/decision", data={"decision": "approve"})
        self.assertEqual(response.status_code, 302)
        with c.app.app_context():
            self.assertEqual(c.db.session.get(p.Budget, budget_id).status, "Approved")

        statement_date = today - timedelta(days=10)
        self.login_as("treasurer_a")
        response = self.client.post("/finance-control/reconciliation", data={
            "statement_date": statement_date.isoformat(), "statement_balance": "80.00", "notes": "Balanced statement",
        })
        self.assertEqual(response.status_code, 302)
        with c.app.app_context():
            recon = p.BankReconciliation.query.one()
            self.assertAlmostEqual(recon.book_balance, 80.0)
            self.assertAlmostEqual(recon.difference, 0.0)
            recon_id = recon.id

        self.login_as("chair_a")
        self.assertEqual(self.client.post(f"/finance-control/reconciliation/{recon_id}/review").status_code, 302)
        with c.app.app_context():
            self.assertEqual(c.db.session.get(p.BankReconciliation, recon_id).status, "Reviewed")

    def test_rejected_budget_can_be_corrected_and_resubmitted(self):
        c, p = self.crm, self.p7
        today = c.crm_today()

        self.login_as("treasurer_a")
        response = self.client.post("/finance-control/budgets", data={
            "fiscal_year": str(today.year), "budget_type": "Expense", "category": "Fuel",
            "planned_amount": "5000", "notes": "Initial fuel plan",
        })
        self.assertEqual(response.status_code, 302)
        with c.app.app_context():
            budget_id = p.Budget.query.one().id

        self.login_as("chair_a")
        response = self.client.post(f"/finance-control/budgets/{budget_id}/decision", data={"decision": "reject"})
        self.assertEqual(response.status_code, 302)
        with c.app.app_context():
            rejected = c.db.session.get(p.Budget, budget_id)
            self.assertEqual(rejected.status, "Rejected")
            self.assertIsNotNone(rejected.approved_by_user_id)

        self.login_as("treasurer_a")
        page = self.client.get(f"/finance-control?year={today.year}")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Edit &amp; Resubmit", page.data)
        response = self.client.post(f"/finance-control/budgets/{budget_id}/resubmit", data={
            "fiscal_year": str(today.year), "budget_type": "Expense", "category": "Fuel",
            "planned_amount": "6500", "notes": "Corrected fuel plan",
        })
        self.assertEqual(response.status_code, 302)
        with c.app.app_context():
            corrected = c.db.session.get(p.Budget, budget_id)
            self.assertEqual(corrected.status, "Pending Approval")
            self.assertAlmostEqual(corrected.planned_amount, 6500.0)
            self.assertEqual(corrected.notes, "Corrected fuel plan")
            self.assertIsNone(corrected.approved_by_user_id)
            self.assertIsNone(corrected.approved_at)
            self.assertIsNotNone(c.AuditLog.query.filter_by(action="BUDGET_RESUBMITTED", entity_id=budget_id).first())

        self.login_as("chair_a")
        self.assertEqual(self.client.post(f"/finance-control/budgets/{budget_id}/resubmit", data={
            "fiscal_year": str(today.year), "budget_type": "Expense", "category": "Fuel",
            "planned_amount": "7000",
        }).status_code, 403)
        self.assertEqual(self.client.post(f"/finance-control/budgets/{budget_id}/decision", data={"decision": "approve"}).status_code, 302)
        with c.app.app_context():
            self.assertEqual(c.db.session.get(p.Budget, budget_id).status, "Approved")

    def test_document_fingerprint_and_cooperative_scope(self):
        c, p = self.crm, self.p7
        self.login_as("chair_a")
        response = self.client.post(
            "/documents/upload",
            data={
                "title": "Phase 7 Receipt", "document_type": "Receipt", "notes": "Test receipt",
                "file": (io.BytesIO(b"receipt evidence for cooperative A"), "receipt.txt"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 302)
        with c.app.app_context():
            doc = p.CooperativeDocument.query.one()
            self.assertEqual(doc.cooperative_id, self.coop_a)
            self.assertEqual(len(doc.file_sha256), 64)
            self.assertTrue((p.DOCUMENT_UPLOAD_DIR / doc.stored_name).exists())
            doc_id = doc.id

        self.login_as("chair_b")
        self.assertEqual(self.client.get(f"/documents/{doc_id}/download").status_code, 404)
        self.login_as("chair_a")
        self.assertEqual(self.client.get(f"/documents/{doc_id}/download").status_code, 200)

    def test_production_costing_and_equipment_responsibility_scope(self):
        c, p = self.crm, self.p7
        today = c.crm_today()
        with c.app.app_context():
            c.db.session.add(c.Harvest(
                cooperative_id=self.coop_a, crop_id=self.crop_a, harvest_date=today,
                quantity=1000, unit="kg", status="Available",
            ))
            c.db.session.commit()

        self.login_as("chair_a")
        response = self.client.post("/production-control/input", data={
            "crop_id": str(self.crop_a), "input_type": "Seed", "description": "Potato seed",
            "inventory_item_id": str(self.inventory_a), "activity_date": today.isoformat(),
            "quantity": "10", "unit": "bags", "unit_cost": "50",
        })
        self.assertEqual(response.status_code, 302)

        bad = self.client.post("/production-control/equipment-usage", data={
            "equipment_id": str(self.equipment_a), "farm_id": str(self.farm_a), "crop_id": str(self.crop_a),
            "responsible_user_id": str(self.users["chair_b"]), "purpose": "Ploughing",
            "start_date": today.isoformat(), "fuel_cost": "100",
        })
        self.assertEqual(bad.status_code, 303)
        good = self.client.post("/production-control/equipment-usage", data={
            "equipment_id": str(self.equipment_a), "farm_id": str(self.farm_a), "crop_id": str(self.crop_a),
            "responsible_user_id": str(self.users["vice_a"]), "purpose": "Ploughing",
            "start_date": today.isoformat(), "fuel_cost": "100",
        })
        self.assertEqual(good.status_code, 302)
        with c.app.app_context():
            self.assertEqual(p.ProductionInput.query.count(), 1)
            self.assertAlmostEqual(p.ProductionInput.query.one().total_cost, 500.0)
            self.assertEqual(p.EquipmentUsage.query.count(), 1)
        page = self.client.get("/production-control")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Potatoes A", page.data)

    def test_api_access_is_admin_only(self):
        self.login_as("chair_a")
        self.assertEqual(
            self.client.post("/api/tokens", data={"name": "Blocked Executive", "expires_days": "30"}).status_code,
            403,
        )
        self.assertEqual(self.client.get("/api/v1/farmers").status_code, 401)

        self.login_as("treasurer_a")
        self.assertEqual(
            self.client.post("/api/tokens", data={"name": "Blocked Treasurer", "expires_days": "30"}).status_code,
            403,
        )
        self.assertEqual(self.client.get("/api/v1/farmers").status_code, 401)

        self.login_as("admin")
        response = self.client.post("/api/tokens", data={"name": "Admin Integration", "expires_days": "30"})
        self.assertEqual(response.status_code, 200)
        match = re.search(rb"mfg_[A-Za-z0-9_-]+", response.data)
        self.assertIsNotNone(match)
        raw_token = match.group(0).decode("utf-8")

        with self.client.session_transaction() as sess:
            sess.clear()
        response = self.client.get("/api/v1/farmers", headers={"Authorization": f"Bearer {raw_token}"})
        self.assertEqual(response.status_code, 200)
        rows = response.get_json()
        ids = {row["id"] for row in rows}
        self.assertIn(self.farmer_a, ids)
        self.assertIn(self.farmer_b, ids)

    def test_notifications_search_and_certificate(self):
        c, p = self.crm, self.p7
        today = c.crm_today()
        with c.app.app_context():
            c.db.session.add(c.Task(
                cooperative_id=self.coop_a, title="Overdue Phase 7 task", assigned_user_id=self.users["chair_a"],
                assigned_role="Primary Chairperson", due_date=today - timedelta(days=1), status="Open",
                created_by_user_id=self.users["secretary_a"],
            ))
            c.db.session.add(c.Meeting(
                cooperative_id=self.coop_a, meeting_number="P7-NOTIFY-001", meeting_type="Special Meeting",
                title="Upcoming Phase 7 Meeting", meeting_date=today + timedelta(days=2), venue="Malenge Hall",
                status="Draft", created_by_user_id=self.users["secretary_a"],
            ))
            c.db.session.commit()

        self.login_as("chair_a")
        self.assertEqual(self.client.get("/notifications").status_code, 200)
        with c.app.app_context():
            categories = {n.category for n in p.Notification.query.filter_by(user_id=self.users["chair_a"], status="Unread").all()}
            self.assertIn("Accountability", categories)
            self.assertIn("Meeting", categories)
            self.assertIn("Operations", categories)

        visible = self.client.get("/search?q=Visible+Farmer+A")
        hidden = self.client.get("/search?q=Hidden+Farmer+B")
        self.assertIn(b"Visible Farmer A", visible.data)
        self.assertIn(b"No matching records found.", hidden.data)

        self.login_as("secretary_a")
        cert = self.client.get(f"/memberships/{self.membership_a}/certificate")
        self.assertEqual(cert.status_code, 200)
        self.assertIn(b"P7-A-001", cert.data)
        self.assertIn(b"Visible Farmer A", cert.data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
