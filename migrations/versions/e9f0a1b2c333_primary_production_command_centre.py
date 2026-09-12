"""Primary production command centre

Revision ID: e9f0a1b2c333
Revises: d8e9f0a1b222
Create Date: 2026-09-12
"""
from alembic import op
import sqlalchemy as sa

revision = "e9f0a1b2c333"
down_revision = "d8e9f0a1b222"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "production_plan",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cooperative_id", sa.Integer(), nullable=False),
        sa.Column("crop_id", sa.Integer(), nullable=False),
        sa.Column("target_yield_per_ha_kg", sa.Float(), nullable=False, server_default="0"),
        sa.Column("approved_budget", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="Pending Approval"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("approved_by_user_id", sa.Integer(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["cooperative_id"], ["cooperative.id"]),
        sa.ForeignKeyConstraint(["crop_id"], ["crop.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["user.id"]),
        sa.UniqueConstraint("crop_id", name="uq_production_plan_crop"),
    )
    op.create_index("ix_production_plan_cooperative_id", "production_plan", ["cooperative_id"])
    op.create_index("ix_production_plan_crop_id", "production_plan", ["crop_id"])
    op.create_index("ix_production_plan_status", "production_plan", ["status"])

    op.create_table(
        "production_activity",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cooperative_id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("activity_type", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("planned_date", sa.Date(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="Planned"),
        sa.Column("responsible_user_id", sa.Integer(), nullable=True),
        sa.Column("evidence_reference", sa.String(length=250), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("verified_by_user_id", sa.Integer(), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["cooperative_id"], ["cooperative.id"]),
        sa.ForeignKeyConstraint(["plan_id"], ["production_plan.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["responsible_user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["verified_by_user_id"], ["user.id"]),
    )
    op.create_index("ix_production_activity_cooperative_id", "production_activity", ["cooperative_id"])
    op.create_index("ix_production_activity_plan_id", "production_activity", ["plan_id"])
    op.create_index("ix_production_activity_due_date", "production_activity", ["due_date"])
    op.create_index("ix_production_activity_status", "production_activity", ["status"])

    op.create_table(
        "production_equipment_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cooperative_id", sa.Integer(), nullable=False),
        sa.Column("crop_id", sa.Integer(), nullable=False),
        sa.Column("equipment_id", sa.Integer(), nullable=False),
        sa.Column("farm_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(length=220), nullable=False),
        sa.Column("use_date", sa.Date(), nullable=False),
        sa.Column("hours_used", sa.Float(), nullable=False, server_default="0"),
        sa.Column("fuel_litres", sa.Float(), nullable=False, server_default="0"),
        sa.Column("responsible_user_id", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["cooperative_id"], ["cooperative.id"]),
        sa.ForeignKeyConstraint(["crop_id"], ["crop.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["equipment_id"], ["equipment.id"]),
        sa.ForeignKeyConstraint(["farm_id"], ["farm.id"]),
        sa.ForeignKeyConstraint(["responsible_user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["user.id"]),
    )
    op.create_index("ix_production_equipment_log_cooperative_id", "production_equipment_log", ["cooperative_id"])
    op.create_index("ix_production_equipment_log_crop_id", "production_equipment_log", ["crop_id"])
    op.create_index("ix_production_equipment_log_equipment_id", "production_equipment_log", ["equipment_id"])
    op.create_index("ix_production_equipment_log_farm_id", "production_equipment_log", ["farm_id"])
    op.create_index("ix_production_equipment_log_use_date", "production_equipment_log", ["use_date"])


def downgrade():
    op.drop_index("ix_production_equipment_log_use_date", table_name="production_equipment_log")
    op.drop_index("ix_production_equipment_log_farm_id", table_name="production_equipment_log")
    op.drop_index("ix_production_equipment_log_equipment_id", table_name="production_equipment_log")
    op.drop_index("ix_production_equipment_log_crop_id", table_name="production_equipment_log")
    op.drop_index("ix_production_equipment_log_cooperative_id", table_name="production_equipment_log")
    op.drop_table("production_equipment_log")
    op.drop_index("ix_production_activity_status", table_name="production_activity")
    op.drop_index("ix_production_activity_due_date", table_name="production_activity")
    op.drop_index("ix_production_activity_plan_id", table_name="production_activity")
    op.drop_index("ix_production_activity_cooperative_id", table_name="production_activity")
    op.drop_table("production_activity")
    op.drop_index("ix_production_plan_status", table_name="production_plan")
    op.drop_index("ix_production_plan_crop_id", table_name="production_plan")
    op.drop_index("ix_production_plan_cooperative_id", table_name="production_plan")
    op.drop_table("production_plan")
