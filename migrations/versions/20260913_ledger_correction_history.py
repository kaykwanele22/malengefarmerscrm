"""ledger correction history

Revision ID: e5f6a7b8c999
Revises: d4e5f6a7b888
Create Date: 2026-09-13
"""
from alembic import op
import sqlalchemy as sa

revision = "e5f6a7b8c999"
down_revision = "d4e5f6a7b888"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("ledger_transaction") as batch_op:
        batch_op.add_column(sa.Column("decision_note", sa.Text(), nullable=True))

    op.create_table(
        "ledger_transaction_revision",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("transaction_id", sa.Integer(), nullable=False),
        sa.Column("cooperative_id", sa.Integer(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=250), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("changed_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["transaction_id"], ["ledger_transaction.id"]),
        sa.ForeignKeyConstraint(["cooperative_id"], ["cooperative.id"]),
        sa.ForeignKeyConstraint(["changed_by_user_id"], ["user.id"]),
        sa.UniqueConstraint("transaction_id", "revision_number", name="uq_ledger_transaction_revision_number"),
    )
    op.create_index("ix_ledger_transaction_revision_transaction_id", "ledger_transaction_revision", ["transaction_id"])
    op.create_index("ix_ledger_transaction_revision_cooperative_id", "ledger_transaction_revision", ["cooperative_id"])


def downgrade():
    op.drop_index("ix_ledger_transaction_revision_cooperative_id", table_name="ledger_transaction_revision")
    op.drop_index("ix_ledger_transaction_revision_transaction_id", table_name="ledger_transaction_revision")
    op.drop_table("ledger_transaction_revision")
    with op.batch_alter_table("ledger_transaction") as batch_op:
        batch_op.drop_column("decision_note")
