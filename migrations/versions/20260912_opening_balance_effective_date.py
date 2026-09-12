"""opening balance effective date

Revision ID: c3d4e5f6a777
Revises: b2c3d4e5f666
Create Date: 2026-09-12
"""
from alembic import op
import sqlalchemy as sa

revision = "c3d4e5f6a777"
down_revision = "b2c3d4e5f666"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("finance_account") as batch_op:
        batch_op.add_column(sa.Column("opening_balance_date", sa.Date(), nullable=True))
        batch_op.create_index("ix_finance_account_opening_balance_date", ["opening_balance_date"])


def downgrade():
    with op.batch_alter_table("finance_account") as batch_op:
        batch_op.drop_index("ix_finance_account_opening_balance_date")
        batch_op.drop_column("opening_balance_date")
