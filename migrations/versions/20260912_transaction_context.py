"""transaction payment and project context

Revision ID: d4e5f6a7b888
Revises: c3d4e5f6a777
Create Date: 2026-09-12
"""
from alembic import op
import sqlalchemy as sa

revision = "d4e5f6a7b888"
down_revision = "c3d4e5f6a777"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("ledger_transaction") as batch_op:
        batch_op.add_column(sa.Column("payment_method", sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column("project_reference", sa.String(length=140), nullable=True))
        batch_op.create_index("ix_ledger_transaction_payment_method", ["payment_method"])
        batch_op.create_index("ix_ledger_transaction_project_reference", ["project_reference"])


def downgrade():
    with op.batch_alter_table("ledger_transaction") as batch_op:
        batch_op.drop_index("ix_ledger_transaction_project_reference")
        batch_op.drop_index("ix_ledger_transaction_payment_method")
        batch_op.drop_column("project_reference")
        batch_op.drop_column("payment_method")
