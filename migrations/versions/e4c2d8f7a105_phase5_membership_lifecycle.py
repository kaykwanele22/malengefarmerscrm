"""Phase 5 membership lifecycle, history and fee linkage

Revision ID: e4c2d8f7a105
Revises: b7e1f4a9c203
Create Date: 2026-09-10
"""
from alembic import op
import sqlalchemy as sa

revision = "e4c2d8f7a105"
down_revision = "b7e1f4a9c203"
branch_labels = None
depends_on = None


def upgrade():
    # Timestamp for meaningful membership maintenance/history reporting.
    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.add_column(sa.Column("updated_at", sa.DateTime(), nullable=True))

    op.execute(sa.text("""
        UPDATE membership
        SET updated_at = COALESCE(created_at, CURRENT_TIMESTAMP)
        WHERE updated_at IS NULL
    """))

    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.alter_column("updated_at", existing_type=sa.DateTime(), nullable=False)

    # Link membership-fee contributions to the exact membership record.
    with op.batch_alter_table("contribution", schema=None) as batch_op:
        batch_op.add_column(sa.Column("membership_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_contribution_membership_id_membership",
            "membership",
            ["membership_id"],
            ["id"],
        )
        batch_op.create_index("ix_contribution_membership_id", ["membership_id"], unique=False)

    # Preserve linkage for historical membership-fee transactions where an exact
    # cooperative/farmer membership already exists.
    op.execute(sa.text("""
        UPDATE contribution
        SET membership_id = (
            SELECT m.id
            FROM membership m
            WHERE m.cooperative_id = contribution.cooperative_id
              AND m.farmer_id = contribution.farmer_id
            ORDER BY m.id ASC
            LIMIT 1
        )
        WHERE LOWER(COALESCE(category, '')) = 'membership fee'
          AND membership_id IS NULL
          AND EXISTS (
              SELECT 1
              FROM membership m2
              WHERE m2.cooperative_id = contribution.cooperative_id
                AND m2.farmer_id = contribution.farmer_id
          )
    """))

    op.create_table(
        "membership_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("membership_id", sa.Integer(), nullable=False),
        sa.Column("cooperative_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("from_status", sa.String(length=30), nullable=True),
        sa.Column("to_status", sa.String(length=30), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["cooperative_id"], ["cooperative.id"]),
        sa.ForeignKeyConstraint(["membership_id"], ["membership.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_membership_history_membership_id", "membership_history", ["membership_id"], unique=False)
    op.create_index("ix_membership_history_cooperative_id", "membership_history", ["cooperative_id"], unique=False)
    op.create_index("ix_membership_history_created_at", "membership_history", ["created_at"], unique=False)

    # Normalize the previous generic exit status to the explicit Phase 5 lifecycle.
    op.execute(sa.text("""
        UPDATE membership
        SET status = 'Resigned'
        WHERE LOWER(COALESCE(status, '')) = 'exited'
    """))

    # Create one starting history record for every existing assigned membership.
    op.execute(sa.text("""
        INSERT INTO membership_history (
            membership_id,
            cooperative_id,
            user_id,
            event_type,
            from_status,
            to_status,
            description,
            created_at
        )
        SELECT
            m.id,
            m.cooperative_id,
            NULL,
            'IMPORTED',
            NULL,
            m.status,
            'Existing membership imported into Phase 5 lifecycle history.',
            COALESCE(m.created_at, CURRENT_TIMESTAMP)
        FROM membership m
        WHERE m.cooperative_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM membership_history mh WHERE mh.membership_id = m.id
          )
    """))


def downgrade():
    op.drop_index("ix_membership_history_created_at", table_name="membership_history")
    op.drop_index("ix_membership_history_cooperative_id", table_name="membership_history")
    op.drop_index("ix_membership_history_membership_id", table_name="membership_history")
    op.drop_table("membership_history")

    with op.batch_alter_table("contribution", schema=None) as batch_op:
        batch_op.drop_index("ix_contribution_membership_id")
        batch_op.drop_constraint("fk_contribution_membership_id_membership", type_="foreignkey")
        batch_op.drop_column("membership_id")

    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.drop_column("updated_at")
