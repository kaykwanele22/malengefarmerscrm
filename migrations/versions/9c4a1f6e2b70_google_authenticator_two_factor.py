"""Google Authenticator two-factor authentication

Revision ID: 9c4a1f6e2b70
Revises: 871d7c4ab3f9
Create Date: 2026-09-10
"""
from alembic import op
import sqlalchemy as sa

revision = "9c4a1f6e2b70"
down_revision = "871d7c4ab3f9"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "two_factor_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(sa.Column("two_factor_secret", sa.String(length=512), nullable=True))
        batch_op.add_column(sa.Column("two_factor_recovery_codes", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("two_factor_confirmed_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("two_factor_last_counter", sa.BigInteger(), nullable=True))

    # Keep the application-level default but remove the migration-only server default.
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.alter_column("two_factor_enabled", server_default=None)


def downgrade():
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.drop_column("two_factor_last_counter")
        batch_op.drop_column("two_factor_confirmed_at")
        batch_op.drop_column("two_factor_recovery_codes")
        batch_op.drop_column("two_factor_secret")
        batch_op.drop_column("two_factor_enabled")
