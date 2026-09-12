"""account-level finance reconciliation

Revision ID: b2c3d4e5f666
Revises: a1b2c3d4e555
Create Date: 2026-09-12
"""
from alembic import op
import sqlalchemy as sa

revision = "b2c3d4e5f666"
down_revision = "a1b2c3d4e555"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "finance_reconciliation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cooperative_id", sa.Integer(), sa.ForeignKey("cooperative.id"), nullable=False),
        sa.Column("finance_account_id", sa.Integer(), sa.ForeignKey("finance_account.id"), nullable=False),
        sa.Column("statement_date", sa.Date(), nullable=False),
        sa.Column("statement_balance", sa.Float(), nullable=False),
        sa.Column("book_balance", sa.Float(), nullable=False),
        sa.Column("difference", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("prepared_by_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("reviewed_by_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "cooperative_id", "finance_account_id", "statement_date",
            name="uq_finance_reconciliation_scope",
        ),
    )
    op.create_index("ix_finance_reconciliation_cooperative_id", "finance_reconciliation", ["cooperative_id"])
    op.create_index("ix_finance_reconciliation_finance_account_id", "finance_reconciliation", ["finance_account_id"])
    op.create_index("ix_finance_reconciliation_statement_date", "finance_reconciliation", ["statement_date"])
    op.create_index("ix_finance_reconciliation_status", "finance_reconciliation", ["status"])


def downgrade():
    op.drop_index("ix_finance_reconciliation_status", table_name="finance_reconciliation")
    op.drop_index("ix_finance_reconciliation_statement_date", table_name="finance_reconciliation")
    op.drop_index("ix_finance_reconciliation_finance_account_id", table_name="finance_reconciliation")
    op.drop_index("ix_finance_reconciliation_cooperative_id", table_name="finance_reconciliation")
    op.drop_table("finance_reconciliation")
