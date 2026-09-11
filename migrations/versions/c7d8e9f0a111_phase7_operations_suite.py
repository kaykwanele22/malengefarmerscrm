"""Phase 7 cooperative operations suite

Revision ID: c7d8e9f0a111
Revises: a6b7c8d9e010
Create Date: 2026-09-11
"""
from alembic import op
import sqlalchemy as sa

revision = "c7d8e9f0a111"
down_revision = "a6b7c8d9e010"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "notification",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cooperative_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False, server_default="Info"),
        sa.Column("link", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="Unread"),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("source_type", sa.String(length=60), nullable=True),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["cooperative_id"], ["cooperative.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
    )
    op.create_index("ix_notification_cooperative_id", "notification", ["cooperative_id"])
    op.create_index("ix_notification_user_id", "notification", ["user_id"])
    op.create_index("ix_notification_category", "notification", ["category"])
    op.create_index("ix_notification_status", "notification", ["status"])
    op.create_index("ix_notification_created_at", "notification", ["created_at"])

    op.create_table(
        "cooperative_document",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cooperative_id", sa.Integer(), nullable=False),
        sa.Column("document_type", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("entity_type", sa.String(length=60), nullable=True),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("stored_name", sa.String(length=255), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["cooperative_id"], ["cooperative.id"]),
        sa.ForeignKeyConstraint(["uploaded_by_user_id"], ["user.id"]),
        sa.UniqueConstraint("stored_name"),
    )
    op.create_index("ix_cooperative_document_cooperative_id", "cooperative_document", ["cooperative_id"])
    op.create_index("ix_cooperative_document_document_type", "cooperative_document", ["document_type"])
    op.create_index("ix_cooperative_document_created_at", "cooperative_document", ["created_at"])

    op.create_table(
        "budget",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cooperative_id", sa.Integer(), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("budget_type", sa.String(length=30), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("planned_amount", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="Pending Approval"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("approved_by_user_id", sa.Integer(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["cooperative_id"], ["cooperative.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["user.id"]),
        sa.UniqueConstraint("cooperative_id", "fiscal_year", "budget_type", "category", name="uq_budget_scope"),
    )
    op.create_index("ix_budget_cooperative_id", "budget", ["cooperative_id"])
    op.create_index("ix_budget_fiscal_year", "budget", ["fiscal_year"])

    op.create_table(
        "bank_reconciliation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cooperative_id", sa.Integer(), nullable=False),
        sa.Column("statement_date", sa.Date(), nullable=False),
        sa.Column("statement_balance", sa.Float(), nullable=False),
        sa.Column("book_balance", sa.Float(), nullable=False),
        sa.Column("difference", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="Pending Review"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("prepared_by_user_id", sa.Integer(), nullable=False),
        sa.Column("reviewed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["cooperative_id"], ["cooperative.id"]),
        sa.ForeignKeyConstraint(["prepared_by_user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["user.id"]),
    )
    op.create_index("ix_bank_reconciliation_cooperative_id", "bank_reconciliation", ["cooperative_id"])
    op.create_index("ix_bank_reconciliation_statement_date", "bank_reconciliation", ["statement_date"])

    op.create_table(
        "meeting_agenda_item",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("meeting_id", sa.Integer(), nullable=False),
        sa.Column("cooperative_id", sa.Integer(), nullable=False),
        sa.Column("item_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="Open"),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["meeting_id"], ["meeting.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["cooperative_id"], ["cooperative.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["user.id"]),
        sa.UniqueConstraint("meeting_id", "item_number", name="uq_meeting_agenda_number"),
    )
    op.create_index("ix_meeting_agenda_item_meeting_id", "meeting_agenda_item", ["meeting_id"])
    op.create_index("ix_meeting_agenda_item_cooperative_id", "meeting_agenda_item", ["cooperative_id"])

    op.create_table(
        "meeting_attendance",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("meeting_id", sa.Integer(), nullable=False),
        sa.Column("cooperative_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("attendee_name", sa.String(length=150), nullable=False),
        sa.Column("role_or_capacity", sa.String(length=100), nullable=True),
        sa.Column("attendance_status", sa.String(length=30), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["meeting_id"], ["meeting.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["cooperative_id"], ["cooperative.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["user.id"]),
    )
    op.create_index("ix_meeting_attendance_meeting_id", "meeting_attendance", ["meeting_id"])
    op.create_index("ix_meeting_attendance_cooperative_id", "meeting_attendance", ["cooperative_id"])

    op.create_table(
        "production_input",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cooperative_id", sa.Integer(), nullable=False),
        sa.Column("crop_id", sa.Integer(), nullable=False),
        sa.Column("inventory_item_id", sa.Integer(), nullable=True),
        sa.Column("input_type", sa.String(length=80), nullable=False),
        sa.Column("description", sa.String(length=250), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("unit", sa.String(length=40), nullable=True),
        sa.Column("unit_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("total_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("activity_date", sa.Date(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["cooperative_id"], ["cooperative.id"]),
        sa.ForeignKeyConstraint(["crop_id"], ["crop.id"]),
        sa.ForeignKeyConstraint(["inventory_item_id"], ["inventory_item.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["user.id"]),
    )
    op.create_index("ix_production_input_cooperative_id", "production_input", ["cooperative_id"])
    op.create_index("ix_production_input_crop_id", "production_input", ["crop_id"])
    op.create_index("ix_production_input_activity_date", "production_input", ["activity_date"])

    op.create_table(
        "equipment_usage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cooperative_id", sa.Integer(), nullable=False),
        sa.Column("equipment_id", sa.Integer(), nullable=False),
        sa.Column("farm_id", sa.Integer(), nullable=False),
        sa.Column("crop_id", sa.Integer(), nullable=True),
        sa.Column("responsible_user_id", sa.Integer(), nullable=True),
        sa.Column("purpose", sa.String(length=220), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("fuel_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["cooperative_id"], ["cooperative.id"]),
        sa.ForeignKeyConstraint(["equipment_id"], ["equipment.id"]),
        sa.ForeignKeyConstraint(["farm_id"], ["farm.id"]),
        sa.ForeignKeyConstraint(["crop_id"], ["crop.id"]),
        sa.ForeignKeyConstraint(["responsible_user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["user.id"]),
    )
    op.create_index("ix_equipment_usage_cooperative_id", "equipment_usage", ["cooperative_id"])
    op.create_index("ix_equipment_usage_equipment_id", "equipment_usage", ["equipment_id"])

    op.create_table(
        "api_access_token",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_api_access_token_user_id", "api_access_token", ["user_id"])
    op.create_index("ix_api_access_token_token_hash", "api_access_token", ["token_hash"])


def downgrade():
    op.drop_index("ix_api_access_token_token_hash", table_name="api_access_token")
    op.drop_index("ix_api_access_token_user_id", table_name="api_access_token")
    op.drop_table("api_access_token")
    op.drop_index("ix_equipment_usage_equipment_id", table_name="equipment_usage")
    op.drop_index("ix_equipment_usage_cooperative_id", table_name="equipment_usage")
    op.drop_table("equipment_usage")
    op.drop_index("ix_production_input_activity_date", table_name="production_input")
    op.drop_index("ix_production_input_crop_id", table_name="production_input")
    op.drop_index("ix_production_input_cooperative_id", table_name="production_input")
    op.drop_table("production_input")
    op.drop_index("ix_meeting_attendance_cooperative_id", table_name="meeting_attendance")
    op.drop_index("ix_meeting_attendance_meeting_id", table_name="meeting_attendance")
    op.drop_table("meeting_attendance")
    op.drop_index("ix_meeting_agenda_item_cooperative_id", table_name="meeting_agenda_item")
    op.drop_index("ix_meeting_agenda_item_meeting_id", table_name="meeting_agenda_item")
    op.drop_table("meeting_agenda_item")
    op.drop_index("ix_bank_reconciliation_statement_date", table_name="bank_reconciliation")
    op.drop_index("ix_bank_reconciliation_cooperative_id", table_name="bank_reconciliation")
    op.drop_table("bank_reconciliation")
    op.drop_index("ix_budget_fiscal_year", table_name="budget")
    op.drop_index("ix_budget_cooperative_id", table_name="budget")
    op.drop_table("budget")
    op.drop_index("ix_cooperative_document_created_at", table_name="cooperative_document")
    op.drop_index("ix_cooperative_document_document_type", table_name="cooperative_document")
    op.drop_index("ix_cooperative_document_cooperative_id", table_name="cooperative_document")
    op.drop_table("cooperative_document")
    op.drop_index("ix_notification_created_at", table_name="notification")
    op.drop_index("ix_notification_status", table_name="notification")
    op.drop_index("ix_notification_category", table_name="notification")
    op.drop_index("ix_notification_user_id", table_name="notification")
    op.drop_index("ix_notification_cooperative_id", table_name="notification")
    op.drop_table("notification")
