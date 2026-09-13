# Database integrity and PostgreSQL migration

This document defines the database rules for Malenge Farmers CRM and the supported path from a local SQLite database to PostgreSQL.

## Integrity rules introduced in H11

The database now enforces cooperative ownership across the core operational chain instead of relying only on route logic. A Farm cannot reference a Farmer from another cooperative; a Crop cannot reference a Farm from another cooperative; Harvest, Sale and Payment records remain in the same cooperative chain. Memberships and member contributions are tied to the same cooperative as their Farmer/Member records, and Expense links to Farm/Supplier records are cooperative-scoped.

Exact duplicate Farmer rows are blocked within one cooperative when cooperative, full name and phone are identical. Exact duplicate Farm rows are blocked when cooperative, farmer, farm name and location are identical. Shared family phone numbers are still allowed for different Farmer names.

The database also rejects negative farm/crop sizes and invalid financial/agricultural values such as non-positive harvest quantities, payments, expenses and contributions. Membership fee balances cannot be negative.

The H11 migration performs a read-only preflight before adding any constraint. If existing data would violate a new rule, the migration stops and reports the category and count of bad records. It does not delete, merge or silently rewrite legacy records.

## Development database

SQLite remains suitable for local development and automated regression tests. Application routes continue to validate ownership and required fields. Migration regression tests explicitly enable SQLite foreign-key checking when verifying the new relational constraints.

Use Flask-Migrate/Alembic as the schema source of truth. Avoid `db.create_all()` for upgrading an existing database because it does not apply migration history or later integrity constraints.

## Production database

PostgreSQL is the production target. The application already reads `DATABASE_URL`, production refuses to start without it, and the project includes the `psycopg` PostgreSQL driver.

Recommended connection format:

```text
postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE
```

Store the real value only in the deployment environment. Do not commit production credentials.

## SQLite to PostgreSQL migration procedure

1. Stop writes to the SQLite deployment and create a verified backup copy.
2. Upgrade the SQLite database to the latest Alembic revision first. If the H11 preflight reports integrity problems, correct those records deliberately before proceeding.
3. Create an empty PostgreSQL database and set `DATABASE_URL` to the PostgreSQL connection string.
4. Run `python -m flask --app app db upgrade` against PostgreSQL so Alembic creates the complete schema and all constraints.
5. Export application data from SQLite in dependency order and import it into PostgreSQL without recreating schema. Preserve primary-key values so relationships remain intact.
6. Reset PostgreSQL sequences after importing rows with explicit integer IDs.
7. Run integrity checks for orphaned foreign keys, cross-cooperative ownership, duplicates and invalid numeric values.
8. Run the complete CRM regression suite against a staging copy of PostgreSQL.
9. Point the production service at PostgreSQL, run `flask db current`, perform a login/role/finance smoke test, and only then reopen writes.
10. Keep the original SQLite backup read-only until the PostgreSQL deployment has been verified and backed up independently.

## Import order

Import parent tables before child tables. At minimum: Cooperative and User first; then UserAccess and security state; Farmer and Supplier; Farm; Crop; Harvest; Sale; Payment; Membership; Contribution; then governance, finance-ledger, accountability, production and other dependent module tables.

Do not disable PostgreSQL constraints to force through invalid records. If an import fails, fix the source data or the dependency order and retry from a clean PostgreSQL database.

## Deployment check

A deployment is database-ready when all of these are true: `flask db upgrade` succeeds on a fresh database, `flask db current` reports the latest revision, the database-integrity regression suite passes, the full CRM regression matrix passes, and no production credential appears in the repository.
