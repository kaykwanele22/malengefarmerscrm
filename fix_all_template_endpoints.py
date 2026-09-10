from pathlib import Path
from datetime import datetime
import shutil
import re
import sys

TEMPLATES_DIR = Path("templates")

ENDPOINT_MAP = {
    "cooperatives": "cooperatives_list",
    "farmers": "farmers_list",
    "farms": "farms_list",
    "crops": "crops_list",
    "harvests": "harvests_list",
    "sales": "sales_list",
    "payments": "payments_list",
    "users": "users_list",
}

if not TEMPLATES_DIR.exists():
    print("ERROR: templates folder not found. Run from project root.")
    sys.exit(1)

# Create backup
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup_dir = Path(f"templates_backup_before_endpoint_fix_{timestamp}")
backup_dir.mkdir(parents=True, exist_ok=True)

# Process templates
changed_files = []
total_replacements = 0

for template_path in sorted(TEMPLATES_DIR.glob("*.html")):
    original = template_path.read_text(encoding="utf-8")
    updated = original
    file_replacements = 0

    for old, new in ENDPOINT_MAP.items():
        # Both quote types
        for quote in ["'", '"']:
            pattern = rf"url_for\(\s*{quote}{re.escape(old)}{quote}"
            replacement = f"url_for({quote}{new}{quote}"
            updated, count = re.subn(pattern, replacement, updated)
            file_replacements += count

    if updated != original:
        shutil.copy2(template_path, backup_dir / template_path.name)
        template_path.write_text(updated, encoding="utf-8")
        changed_files.append((template_path.name, file_replacements))
        total_replacements += file_replacements

# Report
print("=" * 64)
print("MALENGE FARMERS CRM - TEMPLATE ENDPOINT FIX")
print("=" * 64)
print(f"Backup: {backup_dir}\n")

if changed_files:
    print("Updated files:")
    for filename, count in changed_files:
        print(f"  {filename}: {count} replacement(s)")
else:
    print("No old endpoint references found.")

print(f"\nTotal replacements: {total_replacements}\n")

# Validate endpoints
try:
    from app import app
except Exception as e:
    print(f"WARNING: Could not import app.py for validation:\n{e}")
    sys.exit(0)

valid = set(app.view_functions)
invalid = []

pattern = re.compile(r"url_for\(\s*['\"]([^'\"]+)['\"]")

for template_path in sorted(TEMPLATES_DIR.glob("*.html")):
    text = template_path.read_text(encoding="utf-8")
    for endpoint in pattern.findall(text):
        if endpoint not in valid:
            invalid.append((template_path.name, endpoint))

print("VALIDATION")
print("-" * 64)

if invalid:
    print("Invalid endpoint references found:")
    for filename, endpoint in sorted(set(invalid)):
        print(f"  {filename}: {endpoint}")
    print("\nDo not start Flask yet. Review the items above.")
    sys.exit(2)

print("All template url_for() endpoints match app.py.")
print("\nNext:")
print("  python -m py_compile app.py")
print("  python app.py")