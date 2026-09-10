"""Phase 6 accountability and evidence core

Revision ID: a6b7c8d9e010
Revises: f1a6c9d2e508
Create Date: 2026-09-10
"""
from alembic import op
import sqlalchemy as sa

revision = "a6b7c8d9e010"
down_revision = "f1a6c9d2e508"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "meeting",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cooperative_id", sa.Integer(), nullable=False),
        sa.Column("meeting_number", sa.String(length=80), nullable=False),
        sa.Column("meeting_type", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("meeting_date", sa.Date(), nullable=False),
        sa.Column("venue", sa.String(length=200), nullable=True),
        sa.Column("quorum_status", sa.String(length=30), nullable=False, server_default="Not Recorded"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="Draft"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("confirmed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["cooperative_id"], ["cooperative.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["confirmed_by_user_id"], ["user.id"]),
        sa.UniqueConstraint("meeting_number"),
    )
    op.create_index("ix_meeting_cooperative_id", "meeting", ["cooperative_id"])
    op.create_index("ix_meeting_meeting_number", "meeting", ["meeting_number"])
    op.create_index("ix_meeting_meeting_date", "meeting", ["meeting_date"])
    op.create_index("ix_meeting_status", "meeting", ["status"])

    op.create_table(
        "meeting_document",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("meeting_id", sa.Integer(), nullable=False),
        sa.Column("cooperative_id", sa.Integer(), nullable=False),
        sa.Column("document_type", sa.String(length=60), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("stored_name", sa.String(length=255), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["meeting_id"], ["meeting.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["cooperative_id"], ["cooperative.id"]),
        sa.ForeignKeyConstraint(["uploaded_by_user_id"], ["user.id"]),
        sa.UniqueConstraint("stored_name"),
    )
    op.create_index("ix_meeting_document_meeting_id", "meeting_document", ["meeting_id"])
    op.create_index("ix_meeting_document_cooperative_id", "meeting_document", ["cooperative_id"])

    op.create_table(
        "resolution",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cooperative_id", sa.Integer(), nullable=False),
        sa.Column("meeting_id", sa.Integer(), nullable=False),
        sa.Column("resolution_number", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("resolution_text", sa.Text(), nullable=False),
        sa.Column("responsible_role", sa.String(length=50), nullable=False),
        sa.Column("responsible_user_id", sa.Integer(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("priority", sa.String(length=30), nullable=False, server_default="Normal"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="Draft"),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("certified_by_user_id", sa.Integer(), nullable=True),
        sa.Column("certified_at", sa.DateTime(), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["cooperative_id"], ["cooperative.id"]),
        sa.ForeignKeyConstraint(["meeting_id"], ["meeting.id"]),
        sa.ForeignKeyConstraint(["responsible_user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["certified_by_user_id"], ["user.id"]),
        sa.UniqueConstraint("resolution_number"),
    )
    op.create_index("ix_resolution_cooperative_id", "resolution", ["cooperative_id"])
    op.create_index("ix_resolution_meeting_id", "resolution", ["meeting_id"])
    op.create_index("ix_resolution_resolution_number", "resolution", ["resolution_number"])
    op.create_index("ix_resolution_due_date", "resolution", ["due_date"])
    op.create_index("ix_resolution_status", "resolution", ["status"])

    with op.batch_alter_table("task") as batch_op:
        batch_op.add_column(sa.Column("resolution_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("assigned_role", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("created_by_user_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("progress_percentage", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("started_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("verified_by_user_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("verified_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("verification_notes", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("updated_at", sa.DateTime(), nullable=True))
        batch_op.create_foreign_key("fk_task_resolution_id", "resolution", ["resolution_id"], ["id"])
        batch_op.create_foreign_key("fk_task_created_by_user_id", "user", ["created_by_user_id"], ["id"])
        batch_op.create_foreign_key("fk_task_verified_by_user_id", "user", ["verified_by_user_id"], ["id"])
        batch_op.create_index("ix_task_resolution_id", ["resolution_id"])

    # Existing Phase 5 tasks receive safe defaults without changing their meaning.
    bind = op.get_bind()
    bind.execute(sa.text("UPDATE task SET progress_percentage = CASE WHEN status = 'Completed' THEN 100 ELSE 0 END WHERE progress_percentage IS NULL OR progress_percentage = 0"))
    bind.execute(sa.text("UPDATE task SET updated_at = COALESCE(created_at, CURRENT_TIMESTAMP) WHERE updated_at IS NULL"))

    op.create_table(
        "task_update",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("cooperative_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("progress_percentage", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["cooperative_id"], ["cooperative.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
    )
    op.create_index("ix_task_update_task_id", "task_update", ["task_id"])
    op.create_index("ix_task_update_cooperative_id", "task_update", ["cooperative_id"])
    op.create_index("ix_task_update_created_at", "task_update", ["created_at"])

    op.create_table(
        "task_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("cooperative_id", sa.Integer(), nullable=False),
        sa.Column("evidence_type", sa.String(length=60), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=True),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("stored_name", sa.String(length=255), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["cooperative_id"], ["cooperative.id"]),
        sa.ForeignKeyConstraint(["uploaded_by_user_id"], ["user.id"]),
        sa.UniqueConstraint("stored_name"),
    )
    op.create_index("ix_task_evidence_task_id", "task_evidence", ["task_id"])
    op.create_index("ix_task_evidence_cooperative_id", "task_evidence", ["cooperative_id"])


def downgrade():
    op.drop_index("ix_task_evidence_cooperative_id", table_name="task_evidence")
    op.drop_index("ix_task_evidence_task_id", table_name="task_evidence")
    op.drop_table("task_evidence")

    op.drop_index("ix_task_update_created_at", table_name="task_update")
    op.drop_index("ix_task_update_cooperative_id", table_name="task_update")
    op.drop_index("ix_task_update_task_id", table_name="task_update")
    op.drop_table("task_update")

    with op.batch_alter_table("task") as batch_op:
        batch_op.drop_index("ix_task_resolution_id")
        batch_op.drop_constraint("fk_task_verified_by_user_id", type_="foreignkey")
        batch_op.drop_constraint("fk_task_created_by_user_id", type_="foreignkey")
        batch_op.drop_constraint("fk_task_resolution_id", type_="foreignkey")
        batch_op.drop_column("updated_at")
        batch_op.drop_column("verification_notes")
        batch_op.drop_column("verified_at")
        batch_op.drop_column("verified_by_user_id")
        batch_op.drop_column("started_at")
        batch_op.drop_column("progress_percentage")
        batch_op.drop_column("created_by_user_id")
        batch_op.drop_column("assigned_role")
        batch_op.drop_column("resolution_id")

    op.drop_index("ix_resolution_status", table_name="resolution")
    op.drop_index("ix_resolution_due_date", table_name="resolution")
    op.drop_index("ix_resolution_resolution_number", table_name="resolution")
    op.drop_index("ix_resolution_meeting_id", table_name="resolution")
    op.drop_index("ix_resolution_cooperative_id", table_name="resolution")
    op.drop_table("resolution")

    op.drop_index("ix_meeting_document_cooperative_id", table_name="meeting_document")
    op.drop_index("ix_meeting_document_meeting_id", table_name="meeting_document")
    op.drop_table("meeting_document")

    op.drop_index("ix_meeting_status", table_name="meeting")
    op.drop_index("ix_meeting_meeting_date", table_name="meeting")
    op.drop_index("ix_meeting_meeting_number", table_name="meeting")
    op.drop_index("ix_meeting_cooperative_id", table_name="meeting")
    op.drop_table("meeting")
