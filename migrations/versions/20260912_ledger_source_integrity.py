"""ledger source integrity

Revision ID: a1b2c3d4e555
Revises: f0a1b2c3d444
Create Date: 2026-09-12
"""
from alembic import op

revision = "a1b2c3d4e555"
down_revision = "f0a1b2c3d444"
branch_labels = None
depends_on = None


def upgrade():
    # Batch mode keeps this migration compatible with SQLite development/test
    # databases while PostgreSQL receives the same database-level guarantee.
    with op.batch_alter_table("ledger_transaction") as batch_op:
        batch_op.create_unique_constraint(
            "uq_ledger_source",
            ["cooperative_id", "source_type", "source_id"],
        )


def downgrade():
    with op.batch_alter_table("ledger_transaction") as batch_op:
        batch_op.drop_constraint("uq_ledger_source", type_="unique")
