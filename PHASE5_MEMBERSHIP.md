# Phase 5 - Membership

## Purpose

Phase 5 turns the existing membership register into the operational Primary-cooperative membership system for Malenge Farmers CRM.

## Cooperative rule

Individual people are members of one of the two Primary cooperatives. The Secondary cooperative receives network-wide oversight through the existing access-scoping rules; individual Primary membership records are not created or edited at Secondary level.

## Membership lifecycle

Allowed statuses are:

- Active
- Pending
- Suspended
- Resigned
- Deceased
- Inactive

A reason is required when changing a member to Suspended, Resigned, Deceased or Inactive. The CRM stores each lifecycle event in `membership_history` rather than overwriting the historical story of the membership.

## Member numbers

New registrations automatically receive a number based on the Primary cooperative's `code` field. For example, cooperative code `SIYA` produces `SIYA-0001`, `SIYA-0002`, and so on. If no cooperative code exists, a safe Primary-ID prefix is used. Once registered, the member number is permanent.

## Finance separation

The Secretary records the expected membership fee only. The Treasurer records actual money as a `Membership Fee` contribution. The contribution remains Pending Confirmation until the Chairperson confirms it. Only then is `membership.fee_paid` increased.

Each membership-fee contribution is linked to the exact membership through `contribution.membership_id`. Overpayment beyond the remaining membership fee is rejected.

## History

Membership History records:

- registration
- administrative updates
- status changes and reasons
- membership-fee entries submitted by the Treasurer
- Chairperson fee confirmations/rejections
- removal of unconfirmed/rejected fee entries

System Audit Logs continue to record the corresponding CRM actions with user/request metadata.

## Reporting

The membership register supports search and filters by cooperative, status and fee position, plus a role-scoped CSV export. The Reports page now includes total/active members and confirmed/outstanding membership fees.

## Completion test

Phase 5 is considered complete when this flow passes:

```text
Primary Secretary registers member
-> CRM assigns member number
-> Membership History records registration
-> Primary Treasurer records Membership Fee
-> fee remains unconfirmed
-> Primary Chairperson confirms fee
-> membership balance updates
-> history and Audit Logs show the events
-> Secondary executive can view but cannot edit Primary membership
-> other Primary cooperative cannot access/modify the record
```

## Legacy `Membership` contribution compatibility

Phase 5 now treats the older contribution category `Membership` as the same financial event as `Membership Fee`. Migration `f1a6c9d2e508` links matching historical records to the member, reconciles confirmed amounts into the membership fee balance, and preserves an audit-style lifecycle event named `FEE_RECONCILED`.
