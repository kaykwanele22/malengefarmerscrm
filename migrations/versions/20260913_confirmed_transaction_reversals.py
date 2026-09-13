"""confirmed transaction reversals

Revision ID: f6a7b8c9d000
Revises: e5f6a7b8c999
Create Date: 2026-09-13
"""
from alembic import op
import sqlalchemy as sa

revision = "f6a7b8c9d000"
down_revision = "e5f6a7b8c999"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("ledger_transaction") as batch_op:
        batch_op.add_column(sa.Column("reversal_of_transaction_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_ledger_transaction_reversal_of",
            "ledger_transaction",
            ["reversal_of_transaction_id"],
            ["id"],
        )
        batch_op.create_unique_constraint(
            "uq_ledger_transaction_reversal_of",
            ["reversal_of_transaction_id"],
        )
        batch_op.create_index(
            "ix_ledger_transaction_reversal_of_transaction_id",
            ["reversal_of_transaction_id"],
            unique=False,
        )


def downgrade():
    with op.batch_alter_table("ledger_transaction") as batch_op:
        batch_op.drop_index("ix_ledger_transaction_reversal_of_transaction_id")
        batch_op.drop_constraint("uq_ledger_transaction_reversal_of", type_="unique")
        batch_op.drop_constraint("fk_ledger_transaction_reversal_of", type_="foreignkey")
        batch_op.drop_column("reversal_of_transaction_id")
