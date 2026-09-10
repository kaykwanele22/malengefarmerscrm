# Phase 5 Partial Membership Fee Fix

Membership fee balances now separate three values:

- **Confirmed** — amount approved by the Chairperson.
- **Pending** — amount recorded by the Treasurer and awaiting Chairperson confirmation.
- **Still to Pay** — expected fee minus confirmed and pending amounts.

Example: expected R300, Treasurer records R150:

- Confirmed: R0
- Pending: R150
- Still to Pay: R150
- Status: Partially Paid

After Chairperson confirmation:

- Confirmed: R150
- Pending: R0
- Still to Pay: R150
- Status: Partially Paid

If the pending R150 is rejected, Still to Pay returns to R300.

This fix does not change the database schema and requires no new migration.
