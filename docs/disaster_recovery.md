# Malenge Farmers CRM disaster recovery

This runbook defines the minimum production backup and recovery process for the CRM.

## What must be protected

A complete recovery point contains all of the following:

- the application database;
- Phase 6 accountability evidence from `ACCOUNTABILITY_UPLOAD_DIR`;
- Phase 7 controlled documents from `DOCUMENT_UPLOAD_DIR`;
- non-secret system settings from the instance `system_settings.json` file when present;
- the application code and Alembic migration history from GitHub.

A database-only backup is not a complete CRM backup because uploaded governance and finance evidence is stored outside the database.

## Recovery bundles

The Admin **Disaster Recovery** screen creates a ZIP recovery bundle containing a consistent database snapshot plus the protected evidence stores. Every archived file is recorded in `manifest.json` with its size and SHA-256 digest.

SQLite uses Python's SQLite backup API to create a consistent snapshot. PostgreSQL bundles use `pg_dump` in custom format and deliberately avoid placing database passwords in the command-line arguments. If `pg_dump` is not installed, the CRM refuses to label a partial archive as a complete recovery bundle.

The bundle directory defaults to `instance/recovery_bundles`. In production, set `RECOVERY_BUNDLE_DIR` to persistent storage. `RECOVERY_BUNDLE_RETENTION` controls the number of local bundles retained and defaults to 7.

Local persistence is not off-site protection. Copy verified bundles to storage outside the application host/account after creation.

## Scheduled backup command

A scheduler or hosting cron job can run:

```text
python -m flask --app app create-recovery-bundle
```

The command prints the bundle filename on success and exits unsuccessfully if a complete database snapshot cannot be created.

Verify a stored bundle with:

```text
python -m flask --app app verify-recovery-bundle BUNDLE_NAME.zip
```

The Admin Disaster Recovery page can also verify bundles through the web interface.

## PostgreSQL provider snapshots

Managed PostgreSQL provider snapshots remain strongly recommended even when application recovery bundles are enabled. Provider snapshots and application recovery bundles protect against different failures: provider snapshots are efficient database recovery points, while application bundles preserve the database together with uploaded evidence and a cryptographic manifest.

If the application host does not include `pg_dump`, use the provider's database backup/snapshot system and keep evidence backups independently. Do not treat an evidence-only archive as a complete CRM recovery point.

## Restore procedure

Recovery is intentionally not exposed as a one-click production web action. A restore can replace official financial, membership and governance records and must be performed during a controlled maintenance window.

1. Stop application writes and place the service into maintenance/offline mode.
2. Preserve the failed/current environment before replacing anything.
3. Verify the selected recovery bundle. Do not proceed if verification fails.
4. Confirm the bundle's `schema_revision` is compatible with the application version being restored.
5. Restore the database:
   - SQLite: restore the bundled SQLite snapshot while the application is stopped.
   - PostgreSQL: restore the bundled custom-format dump with `pg_restore`, or restore the selected provider snapshot.
6. Restore `evidence/accountability` to `ACCOUNTABILITY_UPLOAD_DIR` and `evidence/documents` to `DOCUMENT_UPLOAD_DIR`.
7. Restore non-secret system settings if required.
8. Run `python -m flask --app app db current` and, if the deployed code is newer than the restored database, run `python -m flask --app app db upgrade` only after reviewing the migration path.
9. Start the application and require `/ready` to return HTTP 200.
10. Perform login, permissions, finance ledger, evidence-download and membership smoke tests.
11. Record the recovery event and preserve the recovery bundle used for the incident.

## Recovery drill

A backup is not considered proven until it has been restored successfully outside production. Perform a recovery drill periodically using a staging environment:

- select a recent verified bundle;
- restore database and evidence into staging;
- confirm the schema revision and `/ready` endpoint;
- sign in as an authorized test user;
- confirm representative finance, membership, production and evidence records;
- record the drill date, bundle name, result and any corrective action.

## Security rules

Recovery bundles contain sensitive cooperative information. Store them with access controls at least as strong as production, never commit them to Git, never place them under the application's static web directory, and do not send them through unsecured channels. Production database credentials remain environment secrets and are never written into the recovery manifest.
