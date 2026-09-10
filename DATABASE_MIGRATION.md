# Database migration note

The Malenge CRM Alembic chain is now:

```text
83681c65734f  baseline current CRM schema
    -> 871d7c4ab3f9  security hardening + audit request metadata
    -> 9c4a1f6e2b70  Google Authenticator two-factor authentication
    -> b7e1f4a9c203  executive appointment history + active-position protection
    -> e4c2d8f7a105  Phase 5 membership lifecycle + history + fee linkage
    -> f1a6c9d2e508  legacy membership-fee contribution reconciliation
    -> a6b7c8d9e010  Phase 6 accountability + meeting evidence core
```

Use this for both a new database and an existing Malenge database:

```powershell
python upgrade_database.py
```

Phase 6 adds the following tables:

- `meeting`
- `meeting_document`
- `resolution`
- `task_update`
- `task_evidence`

It extends `task` with:

- `resolution_id`
- `assigned_role`
- `created_by_user_id`
- `progress_percentage`
- `started_at`
- `verified_by_user_id`
- `verified_at`
- `verification_notes`
- `updated_at`

The migration does **not** delete existing users, executives, members, farms, finance records, tasks or audit history. Existing Phase 5 tasks remain ordinary operational tasks and are not automatically converted into resolutions.

After upgrading:

```powershell
flask db current
```

Expected:

```text
a6b7c8d9e010 (head)
```

For Render:

```text
python upgrade_database.py && gunicorn app:app
```

Do not use `db.create_all()` as the normal production migration mechanism.
