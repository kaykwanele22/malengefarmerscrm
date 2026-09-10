"""Executive appointment history and active-position protection

Revision ID: b7e1f4a9c203
Revises: 9c4a1f6e2b70
Create Date: 2026-09-10
"""
from alembic import op
import sqlalchemy as sa

revision = "b7e1f4a9c203"
down_revision = "9c4a1f6e2b70"
branch_labels = None
depends_on = None

EXECUTIVE_ROLES_SQL = """
'Secondary Chairperson',
'Secondary Vice Chairperson',
'Secondary Secretary',
'Secondary Vice Secretary',
'Secondary Treasurer',
'Primary Chairperson',
'Primary Vice Chairperson',
'Primary Secretary',
'Primary Vice Secretary',
'Primary Treasurer'
"""


def upgrade():
    op.create_table(
        "executive_appointment",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cooperative_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=30), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("appointed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("ended_by_user_id", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["appointed_by_user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["cooperative_id"], ["cooperative.id"]),
        sa.ForeignKeyConstraint(["ended_by_user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "uq_active_executive_appointment_position",
        "executive_appointment",
        ["cooperative_id", "role"],
        unique=True,
        postgresql_where=sa.text("status = 'Active'"),
        sqlite_where=sa.text("status = 'Active'"),
    )
    op.create_index(
        "uq_active_executive_appointment_user",
        "executive_appointment",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'Active'"),
        sqlite_where=sa.text("status = 'Active'"),
    )

    # Preserve any executive assignments that already existed in UserAccess.
    # Their original appointment date was not historically stored, so CURRENT_DATE
    # is used as the beginning of the imported appointment record.
    op.execute(sa.text(f"""
        INSERT INTO executive_appointment (
            cooperative_id,
            user_id,
            role,
            start_date,
            end_date,
            status,
            appointed_by_user_id,
            ended_by_user_id,
            notes,
            created_at,
            updated_at
        )
        SELECT
            ua.cooperative_id,
            ua.user_id,
            ua.role,
            CURRENT_DATE,
            NULL,
            'Active',
            NULL,
            NULL,
            'Imported from active CRM access during Phase 4 migration.',
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        FROM user_access ua
        WHERE ua.status = 'Active'
          AND ua.cooperative_id IS NOT NULL
          AND ua.role IN ({EXECUTIVE_ROLES_SQL})
          AND NOT EXISTS (
              SELECT 1
              FROM executive_appointment ea
              WHERE ea.user_id = ua.user_id
                AND ea.status = 'Active'
          )
    """))


def downgrade():
    op.drop_index("uq_active_executive_appointment_user", table_name="executive_appointment")
    op.drop_index("uq_active_executive_appointment_position", table_name="executive_appointment")
    op.drop_table("executive_appointment")
