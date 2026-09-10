"""Link legacy Membership contributions to Phase 5 membership fees

Revision ID: f1a6c9d2e508
Revises: e4c2d8f7a105
Create Date: 2026-09-10
"""
from alembic import op
import sqlalchemy as sa

revision = "f1a6c9d2e508"
down_revision = "e4c2d8f7a105"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    # Older screens used the category label "Membership" while Phase 5 uses
    # "Membership Fee". Normalize both labels so old and new transactions use
    # one canonical category.
    bind.execute(sa.text("""
        UPDATE contribution
        SET category = 'Membership Fee'
        WHERE LOWER(TRIM(COALESCE(category, ''))) IN ('membership', 'membership fee')
    """))

    # Attach previously-created membership contributions to the exact member
    # record where cooperative + farmer identifies a membership.
    legacy_rows = bind.execute(sa.text("""
        SELECT c.id AS contribution_id,
               c.cooperative_id,
               c.farmer_id
        FROM contribution c
        WHERE LOWER(TRIM(COALESCE(c.category, ''))) = 'membership fee'
          AND c.membership_id IS NULL
    """)).mappings().all()

    for row in legacy_rows:
        membership_id = bind.execute(sa.text("""
            SELECT m.id
            FROM membership m
            WHERE m.cooperative_id = :cooperative_id
              AND m.farmer_id = :farmer_id
            ORDER BY m.id ASC
            LIMIT 1
        """), {
            "cooperative_id": row["cooperative_id"],
            "farmer_id": row["farmer_id"],
        }).scalar()

        if membership_id:
            bind.execute(sa.text("""
                UPDATE contribution
                SET membership_id = :membership_id
                WHERE id = :contribution_id
            """), {
                "membership_id": membership_id,
                "contribution_id": row["contribution_id"],
            })

    # Reconcile confirmed membership money. Never reduce an existing fee_paid;
    # only raise it when confirmed/received linked transactions prove that more
    # money has already been paid.
    totals = bind.execute(sa.text("""
        SELECT membership_id, COALESCE(SUM(amount), 0) AS confirmed_total
        FROM contribution
        WHERE membership_id IS NOT NULL
          AND LOWER(TRIM(COALESCE(category, ''))) = 'membership fee'
          AND status IN ('Received', 'Confirmed')
        GROUP BY membership_id
    """)).mappings().all()

    for row in totals:
        current_paid = bind.execute(sa.text("""
            SELECT COALESCE(fee_paid, 0)
            FROM membership
            WHERE id = :membership_id
        """), {"membership_id": row["membership_id"]}).scalar()

        confirmed_total = float(row["confirmed_total"] or 0)
        current_paid = float(current_paid or 0)
        if confirmed_total > current_paid + 1e-9:
            bind.execute(sa.text("""
                UPDATE membership
                SET fee_paid = :confirmed_total,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :membership_id
            """), {
                "confirmed_total": confirmed_total,
                "membership_id": row["membership_id"],
            })

            bind.execute(sa.text("""
                INSERT INTO membership_history (
                    membership_id, cooperative_id, user_id, event_type,
                    from_status, to_status, description, created_at
                )
                SELECT m.id, m.cooperative_id, NULL, 'FEE_RECONCILED',
                       m.status, m.status, :description, CURRENT_TIMESTAMP
                FROM membership m
                WHERE m.id = :membership_id
            """), {
                "membership_id": row["membership_id"],
                "description": (
                    f"Legacy confirmed membership contribution(s) reconciled. "
                    f"Confirmed membership fee total: R{confirmed_total:.2f}."
                ),
            })


def downgrade():
    # Data reconciliation is intentionally not reversed. Removing the migration
    # marker must not detach or erase legitimate historical payment evidence.
    pass
