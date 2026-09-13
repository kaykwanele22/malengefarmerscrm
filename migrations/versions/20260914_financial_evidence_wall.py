"""financial evidence wall metadata

Revision ID: c9d0e1f2a333
Revises: b8c9d0e1f222
Create Date: 2026-09-14
"""
from alembic import op
import sqlalchemy as sa

revision = "c9d0e1f2a333"
down_revision = "b8c9d0e1f222"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("ledger_transaction") as batch_op:
        batch_op.add_column(sa.Column("evidence_tier", sa.String(length=24), nullable=True))
        batch_op.add_column(sa.Column("evidence_bypass", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("evidence_bypass_reason", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("evidence_bypass_acknowledged_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("budget_justification", sa.Text(), nullable=True))
        batch_op.create_index("ix_ledger_transaction_evidence_tier", ["evidence_tier"], unique=False)


def downgrade():
    with op.batch_alter_table("ledger_transaction") as batch_op:
        batch_op.drop_index("ix_ledger_transaction_evidence_tier")
        batch_op.drop_column("budget_justification")
        batch_op.drop_column("evidence_bypass_acknowledged_at")
        batch_op.drop_column("evidence_bypass_reason")
        batch_op.drop_column("evidence_bypass")
        batch_op.drop_column("evidence_tier")
