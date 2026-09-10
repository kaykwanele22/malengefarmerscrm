from pathlib import Path
import re
import shutil
import sys

APP_FILE = Path("app.py")

TABLE_MAP = {
    "users": "user",
    "farmers": "farmer",
    "farms": "farm",
    "crops": "crop",
    "harvests": "harvest",
    "sales": "sale",
    "payments": "payment",
    "customers": "customer",
    "suppliers": "supplier",
    "expenses": "expense",
    "inventory_items": "inventory_item",
    "inventory_transactions": "inventory_transaction",
    "tasks": "task",
    "farmer_interactions": "farmer_interaction",
    "memberships": "membership",
    "contributions": "contribution",
    "audit_logs": "audit_log",
}

if not APP_FILE.exists():
    print("ERROR: app.py not found. Place this script in the same folder as app.py.")
    sys.exit(1)

# Create backup
backup = APP_FILE.with_name("app_backup_before_table_fix.py")
shutil.copy2(APP_FILE, backup)

# Read file
text = APP_FILE.read_text(encoding="utf-8")
changes = []

# Fix __tablename__ and ForeignKey references
for old, new in TABLE_MAP.items():
    # Fix __tablename__
    for quote in ['"', "'"]:
        old_pattern = f'__tablename__ = {quote}{old}{quote}'
        new_pattern = f'__tablename__ = {quote}{new}{quote}'
        count = text.count(old_pattern)
        if count:
            text = text.replace(old_pattern, new_pattern)
            changes.append((old_pattern, new_pattern, count))

    # Fix ForeignKey references
    for prefix in ['', 'db.']:
        for quote in ['"', "'"]:
            old_pattern = f'{prefix}ForeignKey({quote}{old}.id{quote})'
            new_pattern = f'{prefix}ForeignKey({quote}{new}.id{quote})'
            count = text.count(old_pattern)
            if count:
                text = text.replace(old_pattern, new_pattern)
                changes.append((old_pattern, new_pattern, count))

# Write updated file
APP_FILE.write_text(text, encoding="utf-8")

print(f"Backup: {backup}")
print(f"Updated: {APP_FILE}")

if changes:
    print("\nChanges made:")
    for old, new, count in changes:
        print(f"  {count}x {old} -> {new}")
else:
    print("\nNo changes made.")

# Check for remaining references
remaining = []
for old in TABLE_MAP:
    patterns = [
        rf'__tablename__\s*=\s*["\']{re.escape(old)}["\']',
        rf'ForeignKey\(\s*["\']{re.escape(old)}\.id["\']\s*\)',
    ]
    for pattern in patterns:
        if re.search(pattern, text):
            remaining.append(old)
            break

if remaining:
    print(f"\nWARNING: Review these manually: {', '.join(sorted(set(remaining)))}")
    sys.exit(2)
else:
    print("\nTable-name fix completed successfully.")