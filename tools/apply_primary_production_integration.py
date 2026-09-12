from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def patch_once(path, old, new, marker):
    text = path.read_text(encoding="utf-8")
    if marker in text:
        return False
    if old not in text:
        raise RuntimeError(f"Expected integration anchor not found in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return True


def main():
    changed = []

    app_path = ROOT / "app.py"
    old_app = (
        "# Secondary/MFPSU joint operations are isolated from Primary individual records.\n"
        "from joint_operations import register_joint_operations\n"
        "register_joint_operations(app)\n\n\n"
    )
    new_app = old_app + (
        "# Primary production command centre separates field coordination from Chairperson oversight.\n"
        "from primary_production import register_primary_production\n"
        "register_primary_production(app)\n\n\n"
    )
    if patch_once(app_path, old_app, new_app, "register_primary_production(app)"):
        changed.append("app.py")

    phase7_path = ROOT / "phase7.py"
    phase7 = phase7_path.read_text(encoding="utf-8")
    if '@bp.route("/production-control/legacy")' not in phase7:
        anchor = '@bp.route("/production-control")\n@roles_required(*OPERATIONS_VIEW_ROLES)\ndef production_control():'
        replacement = '@bp.route("/production-control/legacy")\n@roles_required(*OPERATIONS_VIEW_ROLES)\ndef production_control():'
        if anchor not in phase7:
            raise RuntimeError("Phase 7 production-control route anchor not found")
        phase7_path.write_text(phase7.replace(anchor, replacement, 1), encoding="utf-8")
        changed.append("phase7.py")

    base_path = ROOT / "templates" / "base.html"
    base = base_path.read_text(encoding="utf-8")
    if "url_for('primaryprod.dashboard')" not in base:
        old_nav = (
            "                {% if is_leadership and not is_secondary %}\n"
            "                <a href=\"{{ url_for('phase7.production_control') }}\"\n"
            "                   class=\"nav-item {% if request.endpoint in ['phase7.production_control','phase7.production_input_add','phase7.equipment_usage_add'] %}active{% endif %}\">\n"
            "                    <span>🚜</span><span>Production Control</span>\n"
            "                </a>"
        )
        new_nav = (
            "                {% if is_leadership and not is_secondary %}\n"
            "                <a href=\"{{ url_for('primaryprod.dashboard') }}\"\n"
            "                   class=\"nav-item {% if request.endpoint and request.endpoint.startswith('primaryprod.') %}active{% endif %}\">\n"
            "                    <span>🚜</span><span>Production Control</span>\n"
            "                </a>"
        )
        if old_nav not in base:
            raise RuntimeError("Primary production navigation anchor not found")
        base_path.write_text(base.replace(old_nav, new_nav, 1), encoding="utf-8")
        changed.append("templates/base.html")

    print("Updated: " + (", ".join(changed) if changed else "nothing; already integrated"))


if __name__ == "__main__":
    main()
