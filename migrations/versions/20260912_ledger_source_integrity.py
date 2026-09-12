"""ledger source integrity

Revision ID: 20260912_ledger_source_integrity
Revises: 20260912_finance_hardening
"""
from alembic import op

revision = "20260912_ledger_source_integrity"
down_revision = "20260912_finance_hardening"
branch_labels = None
depends_on = None


def upgrade():
    # One operational source record may post to the cooperative ledger only once.
    # PostgreSQL and SQLite both permit multiple NULL values, so manual ledger
    # entries without a source remain valid.
    op.create_unique_constraint(
        "uq_ledger_source",
        "ledger_transaction",
        ["cooperative_id", "source_type", "source_id"],
    )


def downgrade():
    op.drop_constraint("uq_ledger_source", "ledger_transaction", type_="unique")
