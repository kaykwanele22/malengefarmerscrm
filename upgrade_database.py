"""Safely initialize or migrate the Malenge Farmers CRM database.

Use this instead of db.create_all() for normal startup:
    python upgrade_database.py

It handles the one-time transition from databases that were originally created
with db.create_all() before the Alembic history was repaired, including the later
security, Google Authenticator and Executive Management schema upgrades.
"""
from sqlalchemy import inspect
from flask_migrate import stamp, upgrade

from app import app, db

BASELINE_REVISION = "83681c65734f"
HARDENING_REVISION = "871d7c4ab3f9"
TWO_FACTOR_REVISION = "9c4a1f6e2b70"
EXECUTIVE_REVISION = "b7e1f4a9c203"
PHASE5_SCHEMA_REVISION = "e4c2d8f7a105"
PHASE5_HEAD_REVISION = "f1a6c9d2e508"
HEAD_REVISION = "a6b7c8d9e010"

REQUIRED_BASELINE_TABLES = {
    "user", "user_access", "cooperative", "audit_log", "farmer", "farm",
    "crop", "harvest", "sale", "payment", "customer", "supplier", "expense",
    "inventory_item", "inventory_transaction", "equipment", "task",
    "farmer_interaction", "membership", "contribution",
}

HARDENED_AUDIT_COLUMNS = {
    "ip_address", "request_method", "request_path", "request_id", "user_agent"
}

TWO_FACTOR_COLUMNS = {
    "two_factor_enabled", "two_factor_secret", "two_factor_recovery_codes",
    "two_factor_confirmed_at", "two_factor_last_counter",
}

PHASE5_MEMBERSHIP_COLUMNS = {"updated_at"}
PHASE5_CONTRIBUTION_COLUMNS = {"membership_id"}


def _column_names(inspector, table_name):
    return {column["name"] for column in inspector.get_columns(table_name)}


def main():
    with app.app_context():
        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())

        if not tables:
            print("Empty database detected. Applying all migrations...")
            upgrade()
            print(f"Database upgraded to {HEAD_REVISION}.")
            return

        if "alembic_version" not in tables:
            missing = REQUIRED_BASELINE_TABLES - tables
            if missing:
                raise RuntimeError(
                    "Database has tables but does not match the repaired CRM baseline. "
                    "Missing: " + ", ".join(sorted(missing))
                )

            audit_columns = _column_names(inspector, "audit_log")
            user_columns = _column_names(inspector, "user")

            present_hardening = HARDENED_AUDIT_COLUMNS & audit_columns
            present_two_factor = TWO_FACTOR_COLUMNS & user_columns

            if present_hardening and present_hardening != HARDENED_AUDIT_COLUMNS:
                raise RuntimeError(
                    "Database has a partially applied audit hardening schema. "
                    "Do not stamp it automatically; inspect the schema first."
                )

            if present_two_factor and present_two_factor != TWO_FACTOR_COLUMNS:
                raise RuntimeError(
                    "Database has a partially applied Google Authenticator schema. "
                    "Do not stamp it automatically; inspect the schema first."
                )

            membership_columns = _column_names(inspector, "membership")
            contribution_columns = _column_names(inspector, "contribution")

            if "membership_history" in tables:
                if not PHASE5_MEMBERSHIP_COLUMNS.issubset(membership_columns):
                    raise RuntimeError("Phase 5 membership history exists but membership columns are incomplete.")
                if not PHASE5_CONTRIBUTION_COLUMNS.issubset(contribution_columns):
                    raise RuntimeError("Phase 5 membership history exists but contribution linkage is incomplete.")
                if "executive_appointment" not in tables:
                    raise RuntimeError("Phase 5 schema exists but Executive Management schema is missing.")
                print("Existing Phase 5 Membership schema detected. Stamping Phase 5 head...")
                stamp(revision=PHASE5_SCHEMA_REVISION)
                print(f"Database stamped at {PHASE5_SCHEMA_REVISION}; applying Phase 5 reconciliation and Phase 6 migration...")
                upgrade()
                print(f"Database upgraded to {HEAD_REVISION}.")
                return

            if "executive_appointment" in tables:
                if not HARDENED_AUDIT_COLUMNS.issubset(audit_columns):
                    raise RuntimeError("Executive schema exists but audit hardening columns are incomplete.")
                if not TWO_FACTOR_COLUMNS.issubset(user_columns):
                    raise RuntimeError("Executive schema exists but Google Authenticator columns are incomplete.")
                print("Existing Phase 4 schema detected. Stamping Executive Management revision...")
                stamp(revision=EXECUTIVE_REVISION)

            elif TWO_FACTOR_COLUMNS.issubset(user_columns):
                if not HARDENED_AUDIT_COLUMNS.issubset(audit_columns):
                    raise RuntimeError("Google Authenticator schema exists but audit hardening columns are incomplete.")
                print("Existing Google Authenticator schema detected. Stamping its revision...")
                stamp(revision=TWO_FACTOR_REVISION)

            elif HARDENED_AUDIT_COLUMNS.issubset(audit_columns):
                print("Existing hardened audit schema detected. Stamping hardening revision...")
                stamp(revision=HARDENING_REVISION)

            else:
                print("Existing db.create_all() baseline detected. Stamping repaired baseline...")
                stamp(revision=BASELINE_REVISION)

        print("Applying pending migrations...")
        upgrade()
        print(f"Database upgraded to {HEAD_REVISION}.")


if __name__ == "__main__":
    main()
