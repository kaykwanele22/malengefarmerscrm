import importlib
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path


class MembershipRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory(prefix="malenge_membership_test_")
        cls.db_path = Path(cls.tempdir.name) / "membership.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{cls.db_path.as_posix()}"
        os.environ["SECRET_KEY"] = "malenge-membership-regression-secret"
        os.environ["APP_ENV"] = "development"

        cls.crm = importlib.import_module("app")
        cls.crm.app.config.update(TESTING=True, TWO_FACTOR_REQUIRED=False)

        with cls.crm.app.app_context():
            cls.crm.db.create_all()
            cls._seed_data()

    @classmethod
    def _seed_data(cls):
        c = cls.crm
        secondary = c.Cooperative(name="Malenge Secondary Membership Test", cooperative_type="Secondary", code="MFPSU", status="Active")
        primary_a = c.Cooperative(name="Siyaphumla Membership Test", cooperative_type="Primary", parent=secondary, code="SIYA", status="Active")
        primary_b = c.Cooperative(name="Vimba Membership Test", cooperative_type="Primary", parent=secondary, code="VIMBA", status="Active")
        c.db.session.add_all([secondary, primary_a, primary_b])
        c.db.session.flush()
        cls.secondary_id = secondary.id
        cls.primary_a_id = primary_a.id
        cls.primary_b_id = primary_b.id

        roles = {
            "primary_secretary": ("Primary Secretary", primary_a.id),
            "primary_treasurer": ("Primary Treasurer", primary_a.id),
            "primary_chair": ("Primary Chairperson", primary_a.id),
            "secondary_secretary": ("Secondary Secretary", secondary.id),
            "secondary_treasurer": ("Secondary Treasurer", secondary.id),
        }
        cls.user_ids = {}
        for key, (role, coop_id) in roles.items():
            user = c.User(
                fullname=key.replace("_", " ").title(),
                phone=f"07{len(cls.user_ids)+1:08d}",
                email=f"{key}@membership.local",
                farm_location="Malenge",
                password=c.generate_password_hash("Testing123!"),
            )
            c.db.session.add(user)
            c.db.session.flush()
            c.db.session.add(c.UserAccess(user_id=user.id, role=role, status="Active", cooperative_id=coop_id))
            cls.user_ids[key] = user.id

        farmer_a = c.Farmer(cooperative_id=primary_a.id, fullname="Member One", phone="0711111111", location="Siyaphumla", status="Active")
        farmer_b = c.Farmer(cooperative_id=primary_b.id, fullname="Member Two", phone="0722222222", location="Vimba", status="Active")
        farmer_secondary = c.Farmer(cooperative_id=secondary.id, fullname="Secondary Person", phone="0733333333", location="Malenge", status="Active")
        c.db.session.add_all([farmer_a, farmer_b, farmer_secondary])
        c.db.session.commit()
        cls.farmer_a_id = farmer_a.id
        cls.farmer_b_id = farmer_b.id
        cls.farmer_secondary_id = farmer_secondary.id

    @classmethod
    def tearDownClass(cls):
        with cls.crm.app.app_context():
            cls.crm.db.session.remove()
            cls.crm.db.drop_all()
            cls.crm.db.session.remove()
            cls.crm.db.engine.dispose()
        cls.tempdir.cleanup()

    def setUp(self):
        c = self.crm
        with c.app.app_context():
            import phase7
            phase7.Notification.query.delete()
            c.Contribution.query.delete()
            c.MembershipHistory.query.delete()
            c.Membership.query.delete()
            c.AuditLog.query.delete()
            c.db.session.commit()
        self.client = c.app.test_client()

    def login_as(self, key):
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user_ids[key]
            sess["fullname"] = key

    def register_member(self, status="Active", fee="300", member_number=""):
        self.login_as("primary_secretary")
        data = {
            "farmer_id": str(self.farmer_a_id),
            "join_date": date.today().isoformat(),
            "fee_amount": fee,
            "status": status,
            "notes": "Phase 5 test",
        }
        if member_number:
            data["member_number"] = member_number
        return self.client.post("/memberships/add", data=data, follow_redirects=False)

    def test_auto_member_number_and_registration_history(self):
        response = self.register_member()
        self.assertEqual(response.status_code, 302)
        with self.crm.app.app_context():
            membership = self.crm.Membership.query.one()
            self.assertEqual(membership.member_number, "SIYA-0001")
            self.assertEqual(membership.cooperative_id, self.primary_a_id)
            self.assertEqual(membership.membership_type, "Primary")
            history = self.crm.MembershipHistory.query.filter_by(membership_id=membership.id).one()
            self.assertEqual(history.event_type, "REGISTERED")
            self.assertEqual(history.to_status, "Active")
            self.assertIsNotNone(self.crm.AuditLog.query.filter_by(action="MEMBER_REGISTERED").first())

    def test_member_numbers_increment(self):
        c = self.crm
        with c.app.app_context():
            farmer_extra = c.Farmer(cooperative_id=self.primary_a_id, fullname="Member Three", phone="0744444444", location="Siyaphumla", status="Active")
            c.db.session.add(farmer_extra)
            c.db.session.commit()
            farmer_extra_id = farmer_extra.id
        self.register_member()
        self.client = c.app.test_client()
        self.login_as("primary_secretary")
        response = self.client.post("/memberships/add", data={
            "farmer_id": str(farmer_extra_id), "join_date": date.today().isoformat(), "fee_amount": "300", "status": "Active"
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        with c.app.app_context():
            numbers = [m.member_number for m in c.Membership.query.order_by(c.Membership.id.asc()).all()]
            self.assertEqual(numbers, ["SIYA-0001", "SIYA-0002"])

    def test_membership_fee_cannot_be_finance_scale_amount(self):
        response = self.register_member(fee="3000000")
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"exceeds the allowed maximum", response.data)
        with self.crm.app.app_context():
            self.assertEqual(self.crm.Membership.query.count(), 0)

    def test_existing_invalid_membership_fee_is_repaired_without_deleting_record(self):
        c = self.crm
        with c.app.app_context():
            membership = c.Membership(
                cooperative_id=self.primary_a_id,
                farmer_id=self.farmer_a_id,
                member_number="SIYA-LEGACY-BAD-FEE",
                membership_type="Primary",
                join_date=date.today(),
                fee_amount=3000000,
                fee_paid=0,
                status="Active",
            )
            c.db.session.add(membership)
            c.db.session.commit()
            membership_id = membership.id

            repaired = c.repair_existing_membership_fee_integrity()
            self.assertEqual(repaired, 1)

            membership = c.db.session.get(c.Membership, membership_id)
            self.assertAlmostEqual(membership.fee_amount, 300.0)
            self.assertAlmostEqual(membership.fee_outstanding, 300.0)
            history = c.MembershipHistory.query.filter_by(
                membership_id=membership_id,
                event_type="FEE_INTEGRITY_REPAIR",
            ).one()
            self.assertIn("R3000000.00", history.description.replace(",", ""))
            self.assertIsNotNone(c.AuditLog.query.filter_by(
                entity_type="Membership",
                entity_id=membership_id,
                action="MEMBERSHIP_FEE_INTEGRITY_REPAIR",
            ).first())

    def test_secondary_secretary_uses_aggregate_oversight_not_primary_member_register(self):
        self.login_as("secondary_secretary")
        self.assertEqual(self.client.get("/memberships").status_code, 403)
        self.assertEqual(self.client.get("/memberships/add").status_code, 403)
        response = self.client.post("/memberships/add", data={
            "farmer_id": str(self.farmer_secondary_id), "fee_amount": "300", "status": "Active"
        })
        self.assertEqual(response.status_code, 403)

    def test_foreign_primary_member_cannot_be_registered(self):
        self.login_as("primary_secretary")
        response = self.client.post("/memberships/add", data={
            "farmer_id": str(self.farmer_b_id), "join_date": date.today().isoformat(), "fee_amount": "300", "status": "Active"
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        with self.crm.app.app_context():
            self.assertEqual(self.crm.Membership.query.count(), 0)

    def test_status_change_requires_reason_and_records_history(self):
        self.register_member()
        with self.crm.app.app_context():
            membership_id = self.crm.Membership.query.one().id
        response = self.client.post(f"/memberships/edit/{membership_id}", data={
            "farmer_id": str(self.farmer_a_id), "member_number": "SIYA-0001", "join_date": date.today().isoformat(),
            "fee_amount": "300", "status": "Suspended", "notes": "",
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        with self.crm.app.app_context():
            self.assertEqual(self.crm.db.session.get(self.crm.Membership, membership_id).status, "Active")

        response = self.client.post(f"/memberships/edit/{membership_id}", data={
            "farmer_id": str(self.farmer_a_id), "member_number": "SIYA-0001", "join_date": date.today().isoformat(),
            "fee_amount": "300", "status": "Suspended", "status_reason": "Membership documents under review.", "notes": "",
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        with self.crm.app.app_context():
            membership = self.crm.db.session.get(self.crm.Membership, membership_id)
            self.assertEqual(membership.status, "Suspended")
            event = self.crm.MembershipHistory.query.filter_by(membership_id=membership_id, event_type="STATUS_CHANGED").one()
            self.assertEqual(event.from_status, "Active")
            self.assertEqual(event.to_status, "Suspended")
            self.assertIn("documents", event.description)

    def test_member_number_cannot_be_changed_after_registration(self):
        self.register_member()
        with self.crm.app.app_context():
            membership_id = self.crm.Membership.query.one().id
        response = self.client.post(f"/memberships/edit/{membership_id}", data={
            "farmer_id": str(self.farmer_a_id), "member_number": "CHANGED-9999", "join_date": date.today().isoformat(),
            "fee_amount": "300", "status": "Active",
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        with self.crm.app.app_context():
            self.assertEqual(self.crm.db.session.get(self.crm.Membership, membership_id).member_number, "SIYA-0001")

    def test_treasurer_fee_then_chair_confirmation_updates_membership(self):
        self.register_member(fee="300")
        c = self.crm
        with c.app.app_context():
            membership_id = c.Membership.query.one().id
        self.client = c.app.test_client()
        self.login_as("primary_treasurer")
        response = self.client.post("/contributions/add", data={
            "membership_id": str(membership_id), "farmer_id": str(self.farmer_a_id), "amount": "125",
            "category": "Membership Fee", "contribution_date": date.today().isoformat(), "method": "Cash", "reference": "MEMFEE-001"
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        with c.app.app_context():
            contribution = c.Contribution.query.filter_by(reference="MEMFEE-001").one()
            self.assertEqual(contribution.membership_id, membership_id)
            membership = c.db.session.get(c.Membership, membership_id)
            self.assertEqual(membership.fee_paid, 0)
            self.assertAlmostEqual(membership.fee_pending, 125.0)
            self.assertAlmostEqual(membership.fee_outstanding, 175.0)
            self.assertEqual(membership.fee_status, "Partially Paid")
            contribution_id = contribution.id

        self.client = c.app.test_client()
        self.login_as("primary_chair")
        response = self.client.post(f"/contributions/{contribution_id}/decision", data={"decision": "approve"}, follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        with c.app.app_context():
            membership = c.db.session.get(c.Membership, membership_id)
            self.assertAlmostEqual(membership.fee_paid, 125.0)
            self.assertAlmostEqual(membership.fee_pending, 0.0)
            self.assertAlmostEqual(membership.fee_outstanding, 175.0)
            self.assertEqual(membership.fee_status, "Partially Paid")
            self.assertIsNotNone(c.MembershipHistory.query.filter_by(membership_id=membership_id, event_type="FEE_CONFIRMED").first())


    def test_legacy_membership_category_is_normalized_and_linked(self):
        self.register_member(fee="300")
        c = self.crm
        with c.app.app_context():
            membership_id = c.Membership.query.one().id

        self.client = c.app.test_client()
        self.login_as("primary_treasurer")
        response = self.client.post("/contributions/add", data={
            "membership_id": str(membership_id),
            "farmer_id": str(self.farmer_a_id),
            "amount": "150",
            "category": "Membership",
            "contribution_date": date.today().isoformat(),
            "method": "Cash",
            "reference": "LEGACY-MEMBERSHIP-150",
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 302)

        with c.app.app_context():
            contribution = c.Contribution.query.filter_by(reference="LEGACY-MEMBERSHIP-150").one()
            self.assertEqual(contribution.category, "Membership Fee")
            self.assertEqual(contribution.membership_id, membership_id)
            membership = c.db.session.get(c.Membership, membership_id)
            self.assertAlmostEqual(membership.fee_pending, 150.0)
            self.assertAlmostEqual(membership.fee_outstanding, 150.0)

    def test_partial_membership_fee_immediately_reduces_still_to_pay_balance(self):
        self.register_member(fee="300")
        c = self.crm
        with c.app.app_context():
            membership_id = c.Membership.query.one().id

        self.client = c.app.test_client()
        self.login_as("primary_treasurer")
        response = self.client.post("/contributions/add", data={
            "membership_id": str(membership_id),
            "farmer_id": str(self.farmer_a_id),
            "amount": "150",
            "category": "Membership Fee",
            "contribution_date": date.today().isoformat(),
            "method": "Cash",
            "reference": "PARTIAL-150",
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 302)

        with c.app.app_context():
            membership = c.db.session.get(c.Membership, membership_id)
            self.assertAlmostEqual(membership.fee_paid, 0.0)
            self.assertAlmostEqual(membership.fee_pending, 150.0)
            self.assertAlmostEqual(membership.fee_outstanding, 150.0)
            self.assertEqual(membership.fee_status, "Partially Paid")

        page = self.client.get("/memberships")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Pending", page.data)
        self.assertIn(b"150.00", page.data)

    def test_full_pending_fee_is_awaiting_confirmation_not_paid(self):
        self.register_member(fee="300")
        c = self.crm
        with c.app.app_context():
            membership_id = c.Membership.query.one().id

        self.client = c.app.test_client()
        self.login_as("primary_treasurer")
        response = self.client.post("/contributions/add", data={
            "membership_id": str(membership_id),
            "farmer_id": str(self.farmer_a_id),
            "amount": "300",
            "category": "Membership Fee",
            "contribution_date": date.today().isoformat(),
            "method": "Cash",
            "reference": "FULL-PENDING",
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 302)

        with c.app.app_context():
            membership = c.db.session.get(c.Membership, membership_id)
            self.assertAlmostEqual(membership.fee_paid, 0.0)
            self.assertAlmostEqual(membership.fee_pending, 300.0)
            self.assertAlmostEqual(membership.fee_outstanding, 0.0)
            self.assertEqual(membership.fee_status, "Awaiting Confirmation")

    def test_membership_fee_overpayment_becomes_member_credit(self):
        self.register_member(fee="100")
        with self.crm.app.app_context():
            membership_id = self.crm.Membership.query.one().id
        self.client = self.crm.app.test_client()
        self.login_as("primary_treasurer")
        response = self.client.post("/contributions/add", data={
            "membership_id": str(membership_id), "farmer_id": str(self.farmer_a_id), "amount": "150",
            "category": "Membership Fee", "contribution_date": date.today().isoformat(), "method": "Cash",
            "reference": "OVERPAY-150",
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        with self.crm.app.app_context():
            membership = self.crm.db.session.get(self.crm.Membership, membership_id)
            entries = self.crm.Contribution.query.filter_by(membership_id=membership_id).order_by(self.crm.Contribution.id.asc()).all()
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0].category, "Membership Fee")
            self.assertAlmostEqual(entries[0].amount, 100.0)
            self.assertEqual(entries[1].category, "Member Credit")
            self.assertAlmostEqual(entries[1].amount, 50.0)
            self.assertAlmostEqual(membership.fee_pending, 100.0)
            self.assertAlmostEqual(membership.fee_credit_pending, 50.0)
            self.assertAlmostEqual(membership.fee_outstanding, 0.0)
            import phase7
            chair_notice = phase7.Notification.query.filter_by(
                user_id=self.user_ids["primary_chair"],
                source_type="MembershipPaymentApproval",
            ).one()
            self.assertIn("R150.00", chair_notice.message)
            self.assertEqual(chair_notice.link, "/contributions")
            entry_ids = [entry.id for entry in entries]

        self.client = self.crm.app.test_client()
        self.login_as("primary_chair")
        for entry_id in entry_ids:
            response = self.client.post(
                f"/contributions/{entry_id}/decision",
                data={"decision": "approve"},
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 302)

        with self.crm.app.app_context():
            membership = self.crm.db.session.get(self.crm.Membership, membership_id)
            entries = self.crm.Contribution.query.filter_by(membership_id=membership_id).all()
            self.assertTrue(all(entry.status == "Confirmed" for entry in entries))
            self.assertAlmostEqual(membership.fee_paid_applied, 100.0)
            self.assertAlmostEqual(membership.fee_credit_confirmed, 50.0)
            self.assertAlmostEqual(membership.fee_outstanding, 0.0)
            import phase7
            treasurer_notices = phase7.Notification.query.filter_by(
                user_id=self.user_ids["primary_treasurer"],
                source_type="MembershipPaymentDecision",
            ).all()
            self.assertEqual(len(treasurer_notices), 2)
            self.assertTrue(all("approved" in notice.message for notice in treasurer_notices))

    def test_secondary_secretary_cannot_open_primary_membership_history_or_export(self):
        self.register_member()
        with self.crm.app.app_context():
            membership_id = self.crm.Membership.query.one().id
        self.client = self.crm.app.test_client()
        self.login_as("secondary_secretary")
        history = self.client.get(f"/memberships/{membership_id}/history")
        self.assertEqual(history.status_code, 403)
        export = self.client.get("/exports/memberships.csv")
        self.assertEqual(export.status_code, 403)

    def test_membership_filters_and_reports_render(self):
        self.register_member(status="Pending")
        response = self.client.get("/memberships?status=Pending&fee=due")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"SIYA-0001", response.data)
        report = self.client.get("/reports")
        self.assertEqual(report.status_code, 200)
        self.assertIn(b"Membership Summary", report.data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
