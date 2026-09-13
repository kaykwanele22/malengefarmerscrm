# Admin Global 2FA Toggle

For testing, the System Admin can temporarily pause Google Authenticator enforcement for every CRM login and reactivate it later.

## Where

Open **System Administration → Security**.

- **Disable 2FA for Testing** skips the Google Authenticator challenge for all users while keeping password login, rate limiting, role permissions, CSRF protection and audit logging active.
- Existing Google Authenticator secrets and recovery codes are **not deleted**.
- **Reactivate 2FA for All** restores mandatory Google Authenticator enforcement. Existing enrolled users resume using their current authenticator; unenrolled users are sent to setup.

Every global policy change is written to Audit Logs as `TWO_FACTOR_GLOBAL_DISABLED` or `TWO_FACTOR_GLOBAL_ENABLED`.

The setting is stored durably in the CRM database, so application updates, restarts, and redeployments do **not** switch 2FA back on. `instance/system_settings.json` is only a compatibility mirror. Once Admin disables 2FA, it remains disabled until an Admin explicitly selects **Reactivate 2FA for All**. The environment setting `TWO_FACTOR_REQUIRED=true` must remain enabled if Admin should be able to reactivate 2FA from the CRM.
