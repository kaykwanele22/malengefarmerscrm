# Phase 4 — Executives & Permissions

This build adds a governance-aware Executive Management module for Malenge's three cooperatives.

## Executive structure

Each cooperative has exactly five office positions:

- Chairperson
- Vice Chairperson
- Secretary
- Vice Secretary
- Treasurer

With one Secondary Cooperative and two Primary Cooperatives, the Executive dashboard therefore manages 15 positions.

## What the module does

- Shows all 15 executive slots and whether each is filled or vacant.
- Assigns an existing CRM user to a vacant position.
- Restricts Secondary roles to the Secondary Cooperative and Primary roles to Primary Cooperatives.
- Prevents two active holders of the same position in one cooperative.
- Prevents one CRM user from holding two active executive appointments at the same time.
- Replaces an executive without deleting the outgoing appointment.
- Deactivates an executive while retaining historical dates and notes.
- Synchronizes the active appointment with `UserAccess`, so the office holder receives the correct CRM permissions.
- Records `EXECUTIVE_ASSIGNED`, `EXECUTIVE_ROLE_CHANGED`, `EXECUTIVE_DEACTIVATED`, and `EXECUTIVE_REPLACED` activity in Audit Logs.
- Exports full executive appointment history as CSV.

## Admin workflow

1. Open **System Administration → Executives**.
2. Choose a vacant position and click **Assign**.
3. Select an existing CRM user, confirm the cooperative/role and appointment date.
4. The user's active CRM access changes to the executive role.
5. If leadership changes, use **Replace** rather than deleting the old record.
6. Use **Executive History** for current/former office-holder records.

Executive login accounts remain protected by Google Authenticator 2FA.
