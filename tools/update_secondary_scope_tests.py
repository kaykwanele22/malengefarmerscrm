from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace(path, old, new, label):
    file_path = ROOT / path
    text = file_path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"Could not find test patch target: {label}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main():
    replace(
        "permission_regression_tests.py",
        '''        for url in ["/farmers", "/memberships", "/reports", "/settings"]:\n            self.assert_status(url, 200)\n\n        for url in [\n            "/farms", "/crops", "/harvests",\n            "/sales", "/payments", "/contributions", "/expenses"\n        ]:\n            self.assert_status(url, 403)\n''',
        '''        for url in ["/reports", "/settings"]:\n            self.assert_status(url, 200)\n\n        for url in [\n            "/farmers", "/memberships", "/farms", "/crops", "/harvests",\n            "/sales", "/payments", "/contributions", "/expenses"\n        ]:\n            self.assert_status(url, 403)\n''',
        "secondary secretary surface",
    )
    replace(
        "permission_regression_tests.py",
        '''        for url in [\n            "/memberships", "/sales", "/payments",\n            "/contributions", "/expenses", "/reports", "/settings"\n        ]:\n            self.assert_status(url, 200)\n\n        for url in ["/farmers", "/farms", "/crops", "/harvests"]:\n            self.assert_status(url, 403)\n''',
        '''        for url in [\n            "/sales", "/payments", "/contributions", "/expenses", "/reports", "/settings"\n        ]:\n            self.assert_status(url, 200)\n\n        for url in ["/memberships", "/farmers", "/farms", "/crops", "/harvests"]:\n            self.assert_status(url, 403)\n''',
        "secondary treasurer surface",
    )
    replace(
        "permission_regression_tests.py",
        '''        self.assert_status(\n            f"/contributions/{record_id}/decision",\n            403,\n            method="post",\n            data={"decision": "approve"},\n        )\n''',
        '''        self.assert_status(\n            f"/contributions/{record_id}/decision",\n            404,\n            method="post",\n            data={"decision": "approve"},\n        )\n''',
        "secondary chair primary finance is not visible",
    )

    replace(
        "membership_regression_tests.py",
        '''    def test_secondary_secretary_has_oversight_but_cannot_register_individual_member(self):\n        self.login_as("secondary_secretary")\n        self.assertEqual(self.client.get("/memberships").status_code, 200)\n        self.assertEqual(self.client.get("/memberships/add").status_code, 403)\n''',
        '''    def test_secondary_secretary_uses_aggregate_oversight_not_primary_member_register(self):\n        self.login_as("secondary_secretary")\n        self.assertEqual(self.client.get("/memberships").status_code, 403)\n        self.assertEqual(self.client.get("/memberships/add").status_code, 403)\n''',
        "secondary secretary membership boundary",
    )
    replace(
        "membership_regression_tests.py",
        '''    def test_membership_history_page_and_csv_export_render(self):\n        self.register_member()\n        with self.crm.app.app_context():\n            membership_id = self.crm.Membership.query.one().id\n        self.client = self.crm.app.test_client()\n        self.login_as("secondary_secretary")\n        history = self.client.get(f"/memberships/{membership_id}/history")\n        self.assertEqual(history.status_code, 200)\n        self.assertIn(b"SIYA-0001", history.data)\n        export = self.client.get("/exports/memberships.csv")\n        self.assertEqual(export.status_code, 200)\n        self.assertIn(b"Member Number", export.data)\n        self.assertIn(b"SIYA-0001", export.data)\n''',
        '''    def test_secondary_secretary_cannot_open_primary_membership_history_or_export(self):\n        self.register_member()\n        with self.crm.app.app_context():\n            membership_id = self.crm.Membership.query.one().id\n        self.client = self.crm.app.test_client()\n        self.login_as("secondary_secretary")\n        history = self.client.get(f"/memberships/{membership_id}/history")\n        self.assertEqual(history.status_code, 403)\n        export = self.client.get("/exports/memberships.csv")\n        self.assertEqual(export.status_code, 403)\n''',
        "secondary membership history/export boundary",
    )

    replace(
        "phase7_regression_tests.py",
        '        self.assertEqual(response.status_code, 400)\n        with c.app.app_context():\n            self.assertEqual(p.MeetingAgendaItem.query.filter_by(meeting_id=meeting_id).count(), 1)\n',
        '        self.assertEqual(response.status_code, 303)\n        with c.app.app_context():\n            self.assertEqual(p.MeetingAgendaItem.query.filter_by(meeting_id=meeting_id).count(), 1)\n',
        "browser validation redirect for foreign attendance",
    )
    replace(
        "phase7_regression_tests.py",
        '        self.assertEqual(bad.status_code, 400)\n        good = self.client.post("/production-control/equipment-usage", data={\n',
        '        self.assertEqual(bad.status_code, 303)\n        good = self.client.post("/production-control/equipment-usage", data={\n',
        "browser validation redirect for foreign equipment responsibility",
    )
    replace(
        "phase7_regression_tests.py",
        '''        self.assertIn(b"Visible Farmer A", visible.data)\n        self.assertNotIn(b"Hidden Farmer B", hidden.data)\n''',
        '''        self.assertIn(b"Visible Farmer A", visible.data)\n        self.assertIn(b"No matching records found.", hidden.data)\n''',
        "search result scope assertion",
    )

    print("Secondary scope regression expectations updated.")


if __name__ == "__main__":
    main()
