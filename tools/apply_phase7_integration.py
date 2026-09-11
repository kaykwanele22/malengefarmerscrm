"""One-time source integration for Phase 7.

This script is intentionally idempotent. It wires the Phase 7 blueprint into the
large monolithic app without rewriting unrelated application code, adds the new
workspace navigation, and exposes Phase 7 links from existing meeting/member pages.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write_if_changed(path, new_text):
    old = path.read_text(encoding="utf-8")
    if old != new_text:
        path.write_text(new_text, encoding="utf-8")
        print(f"updated {path.relative_to(ROOT)}")
    else:
        print(f"unchanged {path.relative_to(ROOT)}")


def patch_app():
    path = ROOT / "app.py"
    text = path.read_text(encoding="utf-8")
    if "register_phase7(app)" in text:
        return write_if_changed(path, text)
    marker = "# =========================================================\n# RUN APPLICATION\n# =========================================================\n"
    if marker not in text:
        raise RuntimeError("Could not find app.py RUN APPLICATION marker")
    integration = (
        "# =========================================================\n"
        "# PHASE 7 COOPERATIVE OPERATIONS SUITE\n"
        "# =========================================================\n"
        "# Imported after the core models/helpers/routes are defined so Phase 7 can\n"
        "# extend the CRM without creating circular initialization problems.\n"
        "from phase7 import register_phase7\n"
        "register_phase7(app)\n\n\n"
    )
    text = text.replace(marker, integration + marker, 1)
    write_if_changed(path, text)


def patch_base():
    path = ROOT / "templates" / "base.html"
    text = path.read_text(encoding="utf-8")
    if "url_for('phase7.my_work')" in text:
        return write_if_changed(path, text)
    needle = """                </a>\n\n                {% if can_view_governance and not is_admin %}"""
    if needle not in text:
        raise RuntimeError("Could not find Dashboard/navigation insertion point in base.html")
    workspace = """                </a>\n\n                {% if current_access %}\n                <p class=\"nav-title\">WORKSPACE</p>\n\n                <a href=\"{{ url_for('phase7.my_work') }}\"\n                   class=\"nav-item {% if request.endpoint == 'phase7.my_work' %}active{% endif %}\">\n                    <span>📥</span><span>My Work</span>\n                </a>\n\n                <a href=\"{{ url_for('phase7.notifications') }}\"\n                   class=\"nav-item {% if request.endpoint in ['phase7.notifications','phase7.notification_read','phase7.notification_read_all'] %}active{% endif %}\">\n                    <span>🔔</span><span>Notifications</span>\n                </a>\n\n                <a href=\"{{ url_for('phase7.global_search') }}\"\n                   class=\"nav-item {% if request.endpoint == 'phase7.global_search' %}active{% endif %}\">\n                    <span>🔎</span><span>Search CRM</span>\n                </a>\n\n                <a href=\"{{ url_for('phase7.documents') }}\"\n                   class=\"nav-item {% if request.endpoint in ['phase7.documents','phase7.document_upload','phase7.document_download'] %}active{% endif %}\">\n                    <span>📁</span><span>Documents</span>\n                </a>\n\n                <a href=\"{{ url_for('phase7.reports_command_centre') }}\"\n                   class=\"nav-item {% if request.endpoint == 'phase7.reports_command_centre' %}active{% endif %}\">\n                    <span>📊</span><span>Reports Centre</span>\n                </a>\n\n                {% if is_leadership or is_treasurer %}\n                <a href=\"{{ url_for('phase7.finance_control') }}\"\n                   class=\"nav-item {% if request.endpoint and request.endpoint.startswith('phase7.') and request.endpoint in ['phase7.finance_control','phase7.budget_create','phase7.budget_decision','phase7.reconciliation_create','phase7.reconciliation_review'] %}active{% endif %}\">\n                    <span>🏦</span><span>Finance Control</span>\n                </a>\n                {% endif %}\n\n                {% if is_leadership %}\n                <a href=\"{{ url_for('phase7.production_control') }}\"\n                   class=\"nav-item {% if request.endpoint in ['phase7.production_control','phase7.production_input_add','phase7.equipment_usage_add'] %}active{% endif %}\">\n                    <span>🚜</span><span>Production Control</span>\n                </a>\n                {% endif %}\n\n                <a href=\"{{ url_for('phase7.api_tokens') }}\"\n                   class=\"nav-item {% if request.endpoint in ['phase7.api_tokens','phase7.api_token_revoke'] %}active{% endif %}\">\n                    <span>🔌</span><span>API Access</span>\n                </a>\n                {% endif %}\n\n                {% if can_view_governance and not is_admin %}"""
    text = text.replace(needle, workspace, 1)
    write_if_changed(path, text)


def patch_meeting_detail():
    path = ROOT / "templates" / "meeting_detail.html"
    text = path.read_text(encoding="utf-8")
    if "phase7.meeting_manage" in text:
        return write_if_changed(path, text)
    needle = "<a class=\"acc-btn\" href=\"{{ url_for('meetings_list') }}\">← Meetings</a>"
    if needle not in text:
        raise RuntimeError("Could not find Meetings button in meeting_detail.html")
    replacement = needle + "<a class=\"acc-btn\" href=\"{{ url_for('phase7.meeting_manage', meeting_id=meeting.id) }}\">Agenda &amp; Attendance</a>"
    text = text.replace(needle, replacement, 1)
    write_if_changed(path, text)


def patch_memberships():
    path = ROOT / "templates" / "memberships.html"
    text = path.read_text(encoding="utf-8")
    if "phase7.membership_certificate" in text:
        return write_if_changed(path, text)
    needle = "<a class=\"history-action\" href=\"{{ url_for('membership_history', membership_id=membership.id) }}\">History</a>"
    if needle not in text:
        raise RuntimeError("Could not find Membership History action")
    replacement = needle + "\n                            <a class=\"history-action\" href=\"{{ url_for('phase7.membership_certificate', membership_id=membership.id) }}\">Certificate</a>"
    text = text.replace(needle, replacement, 1)
    write_if_changed(path, text)


def patch_upgrade_database():
    path = ROOT / "upgrade_database.py"
    text = path.read_text(encoding="utf-8")
    old = 'HEAD_REVISION = "a6b7c8d9e010"'
    new = 'HEAD_REVISION = "c7d8e9f0a111"'
    if old in text:
        text = text.replace(old, new, 1)
    elif new not in text:
        raise RuntimeError("Could not find known HEAD_REVISION in upgrade_database.py")
    write_if_changed(path, text)


def main():
    patch_app()
    patch_base()
    patch_meeting_detail()
    patch_memberships()
    patch_upgrade_database()
    print("Phase 7 integration complete")


if __name__ == "__main__":
    main()
