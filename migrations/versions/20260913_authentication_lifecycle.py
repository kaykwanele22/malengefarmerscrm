"""authentication lifecycle state

Revision ID: a7b8c9d0e111
Revises: f6a7b8c9d000
Create Date: 2026-09-13
"""
from alembic import op
import sqlalchemy as sa

revision = "a7b8c9d0e111"
down_revision = "f6a7b8c9d000"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_security",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(), nullable=True),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.Column("last_login_ip", sa.String(length=64), nullable=True),
        sa.Column("last_login_user_agent", sa.String(length=255), nullable=True),
        sa.Column("password_changed_at", sa.DateTime(), nullable=True),
        sa.Column("auth_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", name="uq_user_security_user_id"),
    )
    op.create_index("ix_user_security_user_id", "user_security", ["user_id"], unique=True)
    op.create_index("ix_user_security_locked_until", "user_security", ["locked_until"], unique=False)
    op.create_index("ix_user_security_last_login_at", "user_security", ["last_login_at"], unique=False)

    # Existing accounts remain usable after deployment. New Admin-created accounts
    # are marked for mandatory password rotation by the application lifecycle hook.
    op.execute(sa.text(
        'INSERT INTO user_security '
        '(user_id, must_change_password, failed_login_count, auth_version, created_at, updated_at) '
        'SELECT id, false, 0, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP FROM "user"'
    ))


def downgrade():
    op.drop_index("ix_user_security_last_login_at", table_name="user_security")
    op.drop_index("ix_user_security_locked_until", table_name="user_security")
    op.drop_index("ix_user_security_user_id", table_name="user_security")
    op.drop_table("user_security")
