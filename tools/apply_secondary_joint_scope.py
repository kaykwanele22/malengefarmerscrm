from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def write(path, text):
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(text, old, new, label):
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"Could not find patch target: {label}")
    return text.replace(old, new, 1)


def patch_app():
    path = "app.py"
    text = read(path)

    text = replace_once(
        text,
        'FARMER_VIEW_ROLES = MEMBERSHIP_MANAGEMENT_ROLES | MEMBERSHIP_OVERSIGHT_ROLES | LEADERSHIP_ROLES\nFARMER_RECORD_ROLES = MEMBERSHIP_MANAGEMENT_ROLES\n\nAGRICULTURE_VIEW_ROLES = LEADERSHIP_ROLES\n',
        'PRIMARY_LEADERSHIP_ROLES = {\n    "Primary Chairperson",\n    "Primary Vice Chairperson",\n}\n\n# Individual farmers, memberships and farm-production records belong to Primary\n# cooperatives. Secondary executives receive aggregate network summaries only.\nFARMER_VIEW_ROLES = MEMBERSHIP_MANAGEMENT_ROLES | PRIMARY_LEADERSHIP_ROLES\nFARMER_RECORD_ROLES = MEMBERSHIP_MANAGEMENT_ROLES\n\nAGRICULTURE_VIEW_ROLES = PRIMARY_LEADERSHIP_ROLES\n',
        "primary-only farmer/agriculture permissions",
    )

    text = replace_once(
        text,
        'MEMBERSHIP_VIEW_ROLES = COOPERATIVE_EXECUTIVE_ROLES\n',
        'MEMBERSHIP_VIEW_ROLES = PRIMARY_EXECUTIVE_ROLES\n',
        "primary-only membership register",
    )

    old_scope = '''    if access.role in SECONDARY_EXECUTIVE_ROLES and cooperative.cooperative_type == "Secondary":\n        child_ids = [\n            child.id\n            for child in cooperative.primary_cooperatives\n            if child.status == "Active"\n        ]\n        return [cooperative.id] + child_ids\n\n    return [cooperative.id]\n'''
    new_scope = '''    # Every executive works only with records owned by the cooperative assigned\n    # to that account. Secondary executives do not inherit raw Primary records.\n    # Cross-primary visibility is intentionally exposed only through explicit\n    # aggregate network summaries on the Secondary dashboard/reports.\n    return [cooperative.id]\n'''
    text = replace_once(text, old_scope, new_scope, "strict executive cooperative scope")

    old_primaries = '''    primary_cooperatives = accessible_cooperative_query().filter_by(\n        cooperative_type="Primary", status="Active"\n    ).order_by(Cooperative.name.asc()).all()\n'''
    new_primaries = '''    if is_secondary_dashboard and cooperative_now and cooperative_now.cooperative_type == "Secondary":\n        # Secondary dashboards may compare the two Primaries as aggregate units,\n        # without granting access to their individual records.\n        primary_cooperatives = Cooperative.query.filter_by(\n            parent_id=cooperative_now.id, cooperative_type="Primary", status="Active"\n        ).order_by(Cooperative.name.asc()).all()\n    else:\n        primary_cooperatives = accessible_cooperative_query().filter_by(\n            cooperative_type="Primary", status="Active"\n        ).order_by(Cooperative.name.asc()).all()\n'''
    text = replace_once(text, old_primaries, new_primaries, "secondary aggregate primary summaries")

    text = text.replace(
        '# Visible network / cooperative totals',
        '# Direct cooperative record totals (never inherited child records)',
        1,
    )

    write(path, text)


def wrap_secondary_hidden_links(text, targets):
    for target in targets:
        pattern = re.compile(
            r'(?P<indent>^[ \t]*)<a href="\{\{ url_for\(\'' + re.escape(target) + r'\'\) \}\}"(?P<body>.*?)</a>',
            re.MULTILINE | re.DOTALL,
        )
        pos = 0
        out = []
        changed = False
        while True:
            match = pattern.search(text, pos)
            if not match:
                out.append(text[pos:])
                break
            # Avoid double-wrapping on idempotent reruns.
            prefix = text[max(0, match.start() - 80):match.start()]
            if '{% if not is_secondary %}' in prefix and prefix.rstrip().endswith('{% if not is_secondary %}'):
                out.append(text[pos:match.end()])
                pos = match.end()
                continue
            out.append(text[pos:match.start()])
            indent = match.group('indent')
            link = match.group(0)
            out.append(f"{indent}{{% if not is_secondary %}}\n{link}\n{indent}{{% endif %}}")
            pos = match.end()
            changed = True
        text = ''.join(out)
    return text


def patch_base():
    path = "templates/base.html"
    text = read(path)

    text = replace_once(
        text,
        "    {% set is_admin = role == 'Admin' %}\n",
        "    {% set is_admin = role == 'Admin' %}\n    {% set is_secondary = role.startswith('Secondary') %}\n    {% set is_primary = role.startswith('Primary') %}\n",
        "base secondary role flags",
    )

    text = replace_once(
        text,
        '''                {% if is_leadership %}\n                <a href="{{ url_for('phase7.production_control') }}"\n                   class="nav-item {% if request.endpoint in ['phase7.production_control','phase7.production_input_add','phase7.equipment_usage_add'] %}active{% endif %}">\n                    <span>🚜</span><span>Production Control</span>\n                </a>\n                {% endif %}\n''',
        '''                {% if is_leadership and not is_secondary %}\n                <a href="{{ url_for('phase7.production_control') }}"\n                   class="nav-item {% if request.endpoint in ['phase7.production_control','phase7.production_input_add','phase7.equipment_usage_add'] %}active{% endif %}">\n                    <span>🚜</span><span>Production Control</span>\n                </a>\n                {% endif %}\n''',
        "hide primary production control from secondary",
    )

    # These registers contain individual Primary-cooperative records. Keep them out
    # of all Secondary navigation while preserving them unchanged for Primary roles.
    text = wrap_secondary_hidden_links(
        text,
        ["farmers_list", "memberships_list", "farms_list", "crops_list", "harvests_list"],
    )

    text = text.replace(
        '                    <p class="nav-title">MEMBERSHIP</p>',
        '                    {% if not is_secondary %}<p class="nav-title">MEMBERSHIP</p>{% endif %}',
        1,
    )
    text = text.replace(
        '                    <p class="nav-title">OPERATIONS</p>',
        '                    <p class="nav-title">{% if is_secondary %}JOINT FINANCE{% else %}OPERATIONS{% endif %}</p>',
        1,
    )

    write(path, text)


def patch_dashboard():
    path = "templates/dashboard.html"
    text = read(path)

    text = text.replace(
        'Secondary Leadership &amp; Network Oversight',
        'Secondary Joint Governance &amp; Network Summary',
    ).replace(
        'Secondary Leadership Support &amp; Network Oversight',
        'Secondary Joint Governance Support &amp; Network Summary',
    ).replace(
        'Secondary Finance &amp; Network Oversight',
        'Secondary Joint Finance &amp; Network Summary',
    ).replace(
        'Secondary Secretariat &amp; Membership Oversight',
        'Secondary Joint Secretariat &amp; Network Summary',
    )

    text = replace_once(
        text,
        '''            {% elif is_treasurer %}<a href="{{ url_for('add_contribution') }}" class="dash-primary-btn">Record Money</a>\n            {% elif is_secretariat %}<a href="{{ url_for('add_membership') }}" class="dash-primary-btn">Register Member</a>\n            {% else %}<a href="{{ url_for('reports') }}" class="dash-primary-btn">Open Reports</a>{% endif %}\n''',
        '''            {% elif is_treasurer %}<a href="{{ url_for('add_contribution') }}" class="dash-primary-btn">Record Money</a>\n            {% elif is_secondary and is_secretariat %}<a href="{{ url_for('meetings_list') }}" class="dash-primary-btn">Open Joint Meetings</a>\n            {% elif is_secretariat %}<a href="{{ url_for('add_membership') }}" class="dash-primary-btn">Register Member</a>\n            {% else %}<a href="{{ url_for('reports') }}" class="dash-primary-btn">Open Reports</a>{% endif %}\n''',
        "secondary secretariat dashboard action",
    )

    old_governance_stats = '''        <div class="dash-section-body"><div class="dash-stat-grid" style="margin-bottom:16px"><div class="dash-stat good"><span>Executive Positions Filled</span><strong>{{ own_positions_filled }}/5</strong><small>Active assigned offices</small></div><div class="dash-stat {% if own_positions_vacant > 0 %}attention{% endif %}"><span>Vacant Positions</span><strong>{{ own_positions_vacant }}</strong><small>Out of five executive offices</small></div><div class="dash-stat"><span>Members</span><strong>{{ own_member_count }}</strong><small>{{ own_active_member_count }} active</small></div><div class="dash-stat"><span>Farmers</span><strong>{{ own_farmer_count }}</strong><small>Own cooperative records</small></div></div>\n'''
    new_governance_stats = '''        <div class="dash-section-body"><div class="dash-stat-grid" style="margin-bottom:16px"><div class="dash-stat good"><span>Executive Positions Filled</span><strong>{{ own_positions_filled }}/5</strong><small>Active assigned offices</small></div><div class="dash-stat {% if own_positions_vacant > 0 %}attention{% endif %}"><span>Vacant Positions</span><strong>{{ own_positions_vacant }}</strong><small>Out of five executive offices</small></div>{% if is_secondary %}<div class="dash-stat"><span>Linked Primary Cooperatives</span><strong>{{ primary_cooperatives|length }}</strong><small>Constituent cooperatives represented in the Secondary</small></div><div class="dash-stat"><span>Joint Responsibilities</span><strong>{{ accountability_open_count }}</strong><small>Secondary resolutions still requiring action</small></div>{% else %}<div class="dash-stat"><span>Members</span><strong>{{ own_member_count }}</strong><small>{{ own_active_member_count }} active</small></div><div class="dash-stat"><span>Farmers</span><strong>{{ own_farmer_count }}</strong><small>Own cooperative records</small></div>{% endif %}</div>\n'''
    text = replace_once(text, old_governance_stats, new_governance_stats, "secondary governance summary stats")

    # Primary-only record links must never appear in a Secondary dashboard.
    text = wrap_secondary_hidden_links(
        text,
        ["add_membership", "memberships_list", "farmers_list", "farms_list", "crops_list", "harvests_list"],
    )

    old_secretariat_stats = '''            <div class="dash-stat-grid">\n                <div class="dash-stat"><span>Total Members</span><strong>{{ own_member_count }}</strong><small>Membership records</small></div>\n                <div class="dash-stat good"><span>Active Members</span><strong>{{ own_active_member_count }}</strong><small>Currently active members</small></div>\n                <div class="dash-stat {% if own_membership_fee_due > 0 %}attention{% endif %}"><span>Membership Fees Due</span><strong>R {{ "{:,.0f}".format(own_membership_fee_due|float) }}</strong><small>Expected membership money not yet fully covered</small></div>\n                <div class="dash-stat {% if upcoming_meetings|length > 0 %}attention{% endif %}"><span>Upcoming Meetings</span><strong>{{ upcoming_meetings|length }}</strong><small>Registered future meetings</small></div>\n            </div>\n'''
    new_secretariat_stats = '''            <div class="dash-stat-grid">\n                {% if is_secondary %}\n                <div class="dash-stat"><span>Linked Primaries</span><strong>{{ primary_cooperatives|length }}</strong><small>Primary cooperatives represented in the Secondary</small></div>\n                <div class="dash-stat {% if upcoming_meetings|length > 0 %}attention{% endif %}"><span>Joint Meetings</span><strong>{{ upcoming_meetings|length }}</strong><small>Upcoming Secondary meetings and evidence records</small></div>\n                <div class="dash-stat"><span>Open Joint Responsibilities</span><strong>{{ accountability_open_count }}</strong><small>Secondary resolutions still requiring action</small></div>\n                <div class="dash-stat {% if accountability_awaiting_verification_count > 0 %}attention{% endif %}"><span>Awaiting Verification</span><strong>{{ accountability_awaiting_verification_count }}</strong><small>Secondary work awaiting independent review</small></div>\n                {% else %}\n                <div class="dash-stat"><span>Total Members</span><strong>{{ own_member_count }}</strong><small>Membership records</small></div>\n                <div class="dash-stat good"><span>Active Members</span><strong>{{ own_active_member_count }}</strong><small>Currently active members</small></div>\n                <div class="dash-stat {% if own_membership_fee_due > 0 %}attention{% endif %}"><span>Membership Fees Due</span><strong>R {{ "{:,.0f}".format(own_membership_fee_due|float) }}</strong><small>Expected membership money not yet fully covered</small></div>\n                <div class="dash-stat {% if upcoming_meetings|length > 0 %}attention{% endif %}"><span>Upcoming Meetings</span><strong>{{ upcoming_meetings|length }}</strong><small>Registered future meetings</small></div>\n                {% endif %}\n            </div>\n'''
    text = replace_once(text, old_secretariat_stats, new_secretariat_stats, "secondary secretariat stats")

    text = text.replace(
        '<h2>Governance, Membership &amp; Records</h2>',
        '<h2>{% if is_secondary %}Joint Governance &amp; Records{% else %}Governance, Membership &amp; Records{% endif %}</h2>',
        1,
    )

    old_secretary_note = '''            {% if is_secretary %}<div class="dash-note" style="margin-top:16px"><strong>Secretary responsibility:</strong> maintain official membership and meeting records, upload evidence and capture resolutions. Chairperson confirmation and independent verification remain separate controls.</div>{% else %}<div class="dash-note" style="margin-top:16px"><strong>Vice Secretary responsibility:</strong> support continuity of records, meetings, evidence and membership administration without replacing Chairperson confirmation or financial duties.</div>{% endif %}\n'''
    new_secretary_note = '''            {% if is_secondary %}<div class="dash-note" style="margin-top:16px"><strong>Secondary secretariat boundary:</strong> maintain joint Secondary meetings, evidence, resolutions and shared records. Individual farmer and membership records remain inside Siyaphumla and Vimba.</div>{% elif is_secretary %}<div class="dash-note" style="margin-top:16px"><strong>Secretary responsibility:</strong> maintain official membership and meeting records, upload evidence and capture resolutions. Chairperson confirmation and independent verification remain separate controls.</div>{% else %}<div class="dash-note" style="margin-top:16px"><strong>Vice Secretary responsibility:</strong> support continuity of records, meetings, evidence and membership administration without replacing Chairperson confirmation or financial duties.</div>{% endif %}\n'''
    text = replace_once(text, old_secretary_note, new_secretary_note, "secondary secretariat boundary note")

    text = text.replace(
        '    {% if is_secretariat %}\n    <section class="dash-two"><div class="dash-section"><div class="dash-section-head"><div><p class="eyebrow">Membership</p>',
        '    {% if is_secretariat and not is_secondary %}\n    <section class="dash-two"><div class="dash-section"><div class="dash-section-head"><div><p class="eyebrow">Membership</p>',
        1,
    )

    text = text.replace(
        '    {% if is_chairperson or is_vice_chairperson %}\n    <section class="dash-two"><div class="dash-section"><div class="dash-section-head"><div><p class="eyebrow">Operations</p>',
        '    {% if (is_chairperson or is_vice_chairperson) and not is_secondary %}\n    <section class="dash-two"><div class="dash-section"><div class="dash-section-head"><div><p class="eyebrow">Operations</p>',
        1,
    )

    text = text.replace(
        '<strong>Secondary Chairperson scope:</strong> lead and approve governance and finance for {{ current_cooperative.name }}; Primary figures are oversight only.',
        '<strong>Secondary Chairperson scope:</strong> lead joint governance and finance for {{ current_cooperative.name }}. Primary figures are aggregate summaries only; individual Primary records remain in their own portals.',
        1,
    )
    text = text.replace(
        '<strong>Secondary Vice Chairperson:</strong> supports Secondary leadership and network oversight. Primary cooperative actions remain with the responsible Primary offices.',
        '<strong>Secondary Vice Chairperson:</strong> supports joint Secondary governance and accountability. Primary-level farmers, farms, membership and production remain with the responsible Primary offices.',
        1,
    )

    text = text.replace(
        '{% if is_secretariat %}Membership &amp; Operations Comparison{% elif is_treasurer %}Financial Oversight Comparison{% else %}Primary Cooperative Performance{% endif %}',
        '{% if is_treasurer %}Primary Financial Summary{% else %}Primary Cooperative Summary{% endif %}',
        1,
    )

    # Add a visible rule beneath the Primary aggregate table for every Secondary role.
    needle = '''        {% if is_chairperson %}<div class="dash-note" style="margin:14px 20px 20px">Primary Cooperative pending finance is shown for oversight only. A Secondary Chairperson cannot approve a Primary Cooperative Treasurer's transaction.</div>{% elif is_treasurer %}<div class="dash-note" style="margin:14px 20px 20px">Primary Cooperative finance is view-only oversight. The Secondary Treasurer records money only for the Secondary Cooperative.</div>{% endif %}\n'''
    replacement = '''        <div class="dash-note" style="margin:14px 20px 20px"><strong>Secondary portal rule:</strong> this table is an aggregate comparison of the constituent Primary cooperatives. Individual members, farmers, farms, crops and Primary-only transactions remain inside their own Primary portals.{% if is_chairperson %} Primary pending finance is summary information only; Secondary approval authority does not extend into a Primary cooperative.{% elif is_treasurer %} The Secondary Treasurer records only Secondary/joint finance.{% endif %}</div>\n'''
    text = replace_once(text, needle, replacement, "secondary aggregate-only note")

    write(path, text)


def write_regression_test():
    path = ROOT / "secondary_scope_regression_tests.py"
    path.write_text(r'''import os
import unittest
from pathlib import Path

DB_PATH = "/tmp/malenge_secondary_scope_test.db"
try:
    Path(DB_PATH).unlink()
except FileNotFoundError:
    pass

os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ["SECRET_KEY"] = "secondary-scope-test-secret"
os.environ["APP_ENV"] = "development"
os.environ["TWO_FACTOR_REQUIRED"] = "false"
os.environ["ALLOW_BOOTSTRAP_REGISTRATION"] = "true"

import app as crm


class SecondaryJointScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        crm.app.config.update(TESTING=True)
        with crm.app.app_context():
            crm.db.drop_all()
            crm.db.create_all()

            secondary = crm.Cooperative(name="MFPSU", cooperative_type="Secondary", status="Active")
            crm.db.session.add(secondary)
            crm.db.session.flush()
            siyaphumla = crm.Cooperative(name="Siyaphumla", cooperative_type="Primary", parent_id=secondary.id, status="Active")
            vimba = crm.Cooperative(name="Vimba", cooperative_type="Primary", parent_id=secondary.id, status="Active")
            crm.db.session.add_all([siyaphumla, vimba])
            crm.db.session.flush()

            sec_chair = crm.User(fullname="Secondary Chair", phone="1", email="secchair@example.test", farm_location="Malenge", password="x")
            sec_secretary = crm.User(fullname="Secondary Secretary", phone="2", email="secsecretary@example.test", farm_location="Malenge", password="x")
            primary_chair = crm.User(fullname="Primary Chair", phone="3", email="primarychair@example.test", farm_location="Malenge", password="x")
            crm.db.session.add_all([sec_chair, sec_secretary, primary_chair])
            crm.db.session.flush()
            crm.db.session.add_all([
                crm.UserAccess(user_id=sec_chair.id, role="Secondary Chairperson", status="Active", cooperative_id=secondary.id),
                crm.UserAccess(user_id=sec_secretary.id, role="Secondary Secretary", status="Active", cooperative_id=secondary.id),
                crm.UserAccess(user_id=primary_chair.id, role="Primary Chairperson", status="Active", cooperative_id=siyaphumla.id),
            ])
            crm.db.session.add_all([
                crm.Farmer(cooperative_id=siyaphumla.id, fullname="Siyaphumla Farmer", phone="10", location="Siyaphumla", status="Active"),
                crm.Farmer(cooperative_id=vimba.id, fullname="Vimba Farmer", phone="11", location="Vimba", status="Active"),
            ])
            crm.db.session.commit()
            cls.secondary_id = secondary.id
            cls.siyaphumla_id = siyaphumla.id
            cls.vimba_id = vimba.id
            cls.sec_chair_id = sec_chair.id
            cls.sec_secretary_id = sec_secretary.id
            cls.primary_chair_id = primary_chair.id

    def setUp(self):
        self.client = crm.app.test_client()

    def login_as(self, user_id):
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id
            sess["fullname"] = "Test User"
            sess["two_factor_authenticated"] = True

    def test_secondary_raw_scope_is_secondary_only(self):
        with crm.app.app_context():
            self.assertEqual(crm.accessible_cooperative_ids(self.sec_chair_id), [self.secondary_id])
            self.assertFalse(crm.can_access_cooperative(self.siyaphumla_id, self.sec_chair_id))
            self.assertFalse(crm.can_access_cooperative(self.vimba_id, self.sec_chair_id))
            self.assertEqual(crm.scoped_model_query(crm.Farmer, user_id=self.sec_chair_id).count(), 0)

    def test_secondary_cannot_open_primary_individual_registers(self):
        self.login_as(self.sec_chair_id)
        self.assertEqual(self.client.get("/farmers").status_code, 403)
        self.assertEqual(self.client.get("/memberships").status_code, 403)
        self.assertEqual(self.client.get("/farms").status_code, 403)
        self.assertEqual(self.client.get("/crops").status_code, 403)
        self.assertEqual(self.client.get("/harvests").status_code, 403)

    def test_secondary_joint_governance_and_finance_remain_available(self):
        self.login_as(self.sec_chair_id)
        self.assertEqual(self.client.get("/meetings").status_code, 200)
        self.assertEqual(self.client.get("/accountability").status_code, 200)
        self.assertEqual(self.client.get("/finance-control").status_code, 200)

    def test_secondary_dashboard_keeps_aggregate_primary_summary_only(self):
        self.login_as(self.sec_chair_id)
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Siyaphumla", page)
        self.assertIn("Vimba", page)
        self.assertIn("Secondary portal rule", page)
        self.assertNotIn("Siyaphumla Farmer", page)
        self.assertNotIn("Vimba Farmer", page)
        self.assertNotIn('href="/farmers"', page)
        self.assertNotIn('href="/memberships"', page)
        self.assertNotIn('href="/farms"', page)
        self.assertNotIn('href="/crops"', page)
        self.assertNotIn('href="/harvests"', page)

    def test_secondary_secretary_is_not_a_primary_membership_manager(self):
        self.login_as(self.sec_secretary_id)
        self.assertEqual(self.client.get("/farmers").status_code, 403)
        self.assertEqual(self.client.get("/memberships").status_code, 403)
        dashboard = self.client.get("/dashboard").get_data(as_text=True)
        self.assertIn("Joint Governance &amp; Records", dashboard)
        self.assertNotIn("Register Member", dashboard)

    def test_primary_portal_keeps_primary_records(self):
        self.login_as(self.primary_chair_id)
        self.assertEqual(self.client.get("/farmers").status_code, 200)
        self.assertEqual(self.client.get("/memberships").status_code, 200)
        page = self.client.get("/farmers").get_data(as_text=True)
        self.assertIn("Siyaphumla Farmer", page)
        self.assertNotIn("Vimba Farmer", page)


if __name__ == "__main__":
    unittest.main(verbosity=2)
''', encoding="utf-8")


def main():
    patch_app()
    patch_base()
    patch_dashboard()
    write_regression_test()
    print("Secondary joint-scope patch applied.")


if __name__ == "__main__":
    main()
