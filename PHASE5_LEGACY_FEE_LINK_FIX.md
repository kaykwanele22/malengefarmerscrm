# Phase 5 legacy membership-fee linkage fix

This patch fixes confirmed contributions created with the older category label `Membership`.

The CRM now treats both `Membership` and `Membership Fee` as membership-fee transactions, normalizes new entries to `Membership Fee`, links existing matching contributions to the member record, and reconciles confirmed totals into `membership.fee_paid` without reducing any existing paid amount.

Example after migration for a R300 fee with a confirmed R150 legacy contribution:

- Expected: R300.00
- Confirmed: R150.00
- Pending: R0.00
- Still to pay: R150.00
- Fee status: Partially Paid

Migration head: `f1a6c9d2e508`.
