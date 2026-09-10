# Malenge Farmers CRM — Phase 6 Accountability Core

Date: 10 September 2026
Migration head: `a6b7c8d9e010`

## Principle

Phase 6 treats the CRM as an **accountability and evidence system**, not a meeting word processor.

Official handwritten, printed or signed meeting pages remain the source evidence. The CRM records the minimum structured information needed to answer:

- What was decided?
- Which official meeting supports the decision?
- Who is responsible?
- What is the deadline?
- What progress has been reported?
- What proof was uploaded?
- Who independently verified completion?
- Is the matter open, at risk, overdue, awaiting verification or closed?

## Workflow

`Meeting evidence -> Chairperson confirmation -> Resolution -> Chairperson certification -> Accountability task -> Responsible executive progress -> Evidence -> Independent verification -> Closed`

### Meeting evidence

Secretary / Vice Secretary:

1. Registers the meeting index (type, date, title, venue, quorum).
2. Uploads PDF/image evidence such as handwritten minutes, attendance registers and signed resolutions.
3. May correct draft meeting metadata before confirmation.

Chairperson:

4. Reviews the uploaded evidence.
5. Confirms and locks the meeting evidence.

Confirmed meeting evidence has no delete/replace route. Each stored file is fingerprinted with SHA-256 and checked again when viewed.

A meeting recorded as **Quorum Not Met** can still be preserved as evidence, but action resolutions cannot be created/certified from it.

### Resolution accountability

Secretary / Vice Secretary:

1. Selects a confirmed source meeting.
2. Captures only the actionable decision, not the whole set of minutes.
3. Assigns an active executive, deadline and priority.
4. May correct the resolution while it remains Draft.

Chairperson:

5. Certifies the resolution against the meeting evidence.
6. Certification automatically creates the accountability task.

### Execution and proof

The executive who was assigned responsibility is the only person allowed to report progress or upload proof for that task.

Progress states:

- Open
- In Progress
- Completed -> automatically becomes Awaiting Verification

Evidence may include PDF/images of:

- photographs
- quotations
- receipts
- delivery notes
- reports
- signed documents
- other supporting evidence

### Independent verification

A completed task cannot close itself.

An authorised Chairperson, Vice Chairperson or Secretary may verify the work only when they are **not the responsible executive** for that task.

Verification also requires at least one evidence file.

- Approve -> Task becomes Verified and Resolution becomes Closed.
- Return -> Task goes back to In Progress with the verifier's reason in permanent progress history.

## New database objects

- `meeting`
- `meeting_document`
- `resolution`
- `task_update`
- `task_evidence`

The existing `task` table is extended with resolution linkage, role responsibility, progress, timestamps and verification fields.

## New main screens

- `/accountability` — central Accountability Register
- `/meetings` — meeting/evidence register
- `/meetings/<id>` — source evidence and resolution list
- `/resolutions/<id>` — structured decision record
- `/accountability/tasks/<id>` — implementation, proof and verification history

All cooperative executives can view their **own cooperative's** governance/accountability records. Admin remains a technical system role and does not become a cooperative executive.

## Evidence storage

Uploads are saved by default under:

`instance/accountability_uploads/`

The location can be overridden with the `ACCOUNTABILITY_UPLOAD_DIR` environment variable. In production, point it to persistent storage; do not rely on an ephemeral deployment filesystem for official evidence.

They are deliberately stored outside `/static`, so files cannot be viewed without going through CRM authorization.

Allowed evidence formats:

- PDF
- PNG
- JPG/JPEG
- WEBP

Filename extensions are not trusted by themselves. Phase 6 checks basic file signatures before accepting an upload.

**Backup note:** the existing Phase 5 built-in database backup creates an SQLite `.db` backup only. Until the backup module is upgraded to a full evidence archive, server backups must also include `instance/accountability_uploads/` together with the database. Do not treat the `.db` file alone as a complete Phase 6 evidence backup.

## Recommended next build

The next Phase 6 layer should add:

1. formal amendment records for already-confirmed meeting evidence;
2. executive delegation / Acting Chairperson authority;
3. executive handover checklists;
4. Treasurer evidence attachments and explicit recorder/approver fields;
5. accountability exports/reports;
6. full evidence-aware backup/restore archives;
7. MFPSU cross-primary accountability oversight without giving the Secondary executive edit authority over Primary records.
