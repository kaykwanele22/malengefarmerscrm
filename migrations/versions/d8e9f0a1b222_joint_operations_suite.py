"""MFPSU joint operations suite

Revision ID: d8e9f0a1b222
Revises: c7d8e9f0a111
Create Date: 2026-09-12
"""
from alembic import op
import sqlalchemy as sa

revision = "d8e9f0a1b222"
down_revision = "c7d8e9f0a111"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "joint_project",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("secondary_cooperative_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("project_type", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("budget_amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="Planned"),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["secondary_cooperative_id"], ["cooperative.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["user.id"]),
    )
    op.create_index("ix_joint_project_secondary_cooperative_id", "joint_project", ["secondary_cooperative_id"])
    op.create_index("ix_joint_project_status", "joint_project", ["status"])

    op.create_table(
        "joint_project_allocation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("secondary_cooperative_id", sa.Integer(), nullable=False),
        sa.Column("primary_cooperative_id", sa.Integer(), nullable=False),
        sa.Column("allocated_amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("hectares", sa.Float(), nullable=False, server_default="0"),
        sa.Column("progress_percentage", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["joint_project.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["secondary_cooperative_id"], ["cooperative.id"]),
        sa.ForeignKeyConstraint(["primary_cooperative_id"], ["cooperative.id"]),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["user.id"]),
        sa.UniqueConstraint("project_id", "primary_cooperative_id", name="uq_joint_project_primary"),
    )
    op.create_index("ix_joint_project_allocation_project_id", "joint_project_allocation", ["project_id"])
    op.create_index("ix_joint_project_allocation_secondary_cooperative_id", "joint_project_allocation", ["secondary_cooperative_id"])
    op.create_index("ix_joint_project_allocation_primary_cooperative_id", "joint_project_allocation", ["primary_cooperative_id"])

    op.create_table(
        "shared_asset",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("secondary_cooperative_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("identifier", sa.String(length=120), nullable=True),
        sa.Column("acquisition_date", sa.Date(), nullable=True),
        sa.Column("acquisition_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("location", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="Available"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["secondary_cooperative_id"], ["cooperative.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["user.id"]),
    )
    op.create_index("ix_shared_asset_secondary_cooperative_id", "shared_asset", ["secondary_cooperative_id"])
    op.create_index("ix_shared_asset_status", "shared_asset", ["status"])

    op.create_table(
        "shared_asset_usage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("secondary_cooperative_id", sa.Integer(), nullable=False),
        sa.Column("primary_cooperative_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(length=220), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("estimated_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("actual_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="Scheduled"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["shared_asset.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["secondary_cooperative_id"], ["cooperative.id"]),
        sa.ForeignKeyConstraint(["primary_cooperative_id"], ["cooperative.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["user.id"]),
    )
    op.create_index("ix_shared_asset_usage_asset_id", "shared_asset_usage", ["asset_id"])
    op.create_index("ix_shared_asset_usage_secondary_cooperative_id", "shared_asset_usage", ["secondary_cooperative_id"])
    op.create_index("ix_shared_asset_usage_primary_cooperative_id", "shared_asset_usage", ["primary_cooperative_id"])
    op.create_index("ix_shared_asset_usage_status", "shared_asset_usage", ["status"])

    op.create_table(
        "joint_procurement",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("secondary_cooperative_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("unit", sa.String(length=40), nullable=True),
        sa.Column("supplier_name", sa.String(length=180), nullable=True),
        sa.Column("estimated_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("actual_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("order_date", sa.Date(), nullable=True),
        sa.Column("delivery_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="Pending Approval"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("requested_by_user_id", sa.Integer(), nullable=False),
        sa.Column("approved_by_user_id", sa.Integer(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["secondary_cooperative_id"], ["cooperative.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["joint_project.id"]),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["user.id"]),
    )
    op.create_index("ix_joint_procurement_secondary_cooperative_id", "joint_procurement", ["secondary_cooperative_id"])
    op.create_index("ix_joint_procurement_project_id", "joint_procurement", ["project_id"])
    op.create_index("ix_joint_procurement_status", "joint_procurement", ["status"])

    op.create_table(
        "primary_contribution_account",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("secondary_cooperative_id", sa.Integer(), nullable=False),
        sa.Column("primary_cooperative_id", sa.Integer(), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("expected_amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["secondary_cooperative_id"], ["cooperative.id"]),
        sa.ForeignKeyConstraint(["primary_cooperative_id"], ["cooperative.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["user.id"]),
        sa.UniqueConstraint(
            "secondary_cooperative_id", "primary_cooperative_id", "fiscal_year",
            name="uq_primary_contribution_account",
        ),
    )
    op.create_index("ix_primary_contribution_account_secondary_cooperative_id", "primary_contribution_account", ["secondary_cooperative_id"])
    op.create_index("ix_primary_contribution_account_primary_cooperative_id", "primary_contribution_account", ["primary_cooperative_id"])
    op.create_index("ix_primary_contribution_account_fiscal_year", "primary_contribution_account", ["fiscal_year"])

    op.create_table(
        "primary_contribution_payment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("secondary_cooperative_id", sa.Integer(), nullable=False),
        sa.Column("primary_cooperative_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("method", sa.String(length=60), nullable=True),
        sa.Column("reference", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="Pending Confirmation"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("recorded_by_user_id", sa.Integer(), nullable=False),
        sa.Column("decided_by_user_id", sa.Integer(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["primary_contribution_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["secondary_cooperative_id"], ["cooperative.id"]),
        sa.ForeignKeyConstraint(["primary_cooperative_id"], ["cooperative.id"]),
        sa.ForeignKeyConstraint(["recorded_by_user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["decided_by_user_id"], ["user.id"]),
    )
    op.create_index("ix_primary_contribution_payment_account_id", "primary_contribution_payment", ["account_id"])
    op.create_index("ix_primary_contribution_payment_secondary_cooperative_id", "primary_contribution_payment", ["secondary_cooperative_id"])
    op.create_index("ix_primary_contribution_payment_primary_cooperative_id", "primary_contribution_payment", ["primary_cooperative_id"])
    op.create_index("ix_primary_contribution_payment_payment_date", "primary_contribution_payment", ["payment_date"])
    op.create_index("ix_primary_contribution_payment_status", "primary_contribution_payment", ["status"])

    op.create_table(
        "joint_market_contract",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("secondary_cooperative_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("buyer_name", sa.String(length=180), nullable=False),
        sa.Column("product", sa.String(length=120), nullable=False),
        sa.Column("target_quantity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("unit", sa.String(length=40), nullable=True),
        sa.Column("contract_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("delivery_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="Planned"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["secondary_cooperative_id"], ["cooperative.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["joint_project.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["user.id"]),
    )
    op.create_index("ix_joint_market_contract_secondary_cooperative_id", "joint_market_contract", ["secondary_cooperative_id"])
    op.create_index("ix_joint_market_contract_project_id", "joint_market_contract", ["project_id"])
    op.create_index("ix_joint_market_contract_status", "joint_market_contract", ["status"])


def downgrade():
    op.drop_index("ix_joint_market_contract_status", table_name="joint_market_contract")
    op.drop_index("ix_joint_market_contract_project_id", table_name="joint_market_contract")
    op.drop_index("ix_joint_market_contract_secondary_cooperative_id", table_name="joint_market_contract")
    op.drop_table("joint_market_contract")

    op.drop_index("ix_primary_contribution_payment_status", table_name="primary_contribution_payment")
    op.drop_index("ix_primary_contribution_payment_payment_date", table_name="primary_contribution_payment")
    op.drop_index("ix_primary_contribution_payment_primary_cooperative_id", table_name="primary_contribution_payment")
    op.drop_index("ix_primary_contribution_payment_secondary_cooperative_id", table_name="primary_contribution_payment")
    op.drop_index("ix_primary_contribution_payment_account_id", table_name="primary_contribution_payment")
    op.drop_table("primary_contribution_payment")

    op.drop_index("ix_primary_contribution_account_fiscal_year", table_name="primary_contribution_account")
    op.drop_index("ix_primary_contribution_account_primary_cooperative_id", table_name="primary_contribution_account")
    op.drop_index("ix_primary_contribution_account_secondary_cooperative_id", table_name="primary_contribution_account")
    op.drop_table("primary_contribution_account")

    op.drop_index("ix_joint_procurement_status", table_name="joint_procurement")
    op.drop_index("ix_joint_procurement_project_id", table_name="joint_procurement")
    op.drop_index("ix_joint_procurement_secondary_cooperative_id", table_name="joint_procurement")
    op.drop_table("joint_procurement")

    op.drop_index("ix_shared_asset_usage_status", table_name="shared_asset_usage")
    op.drop_index("ix_shared_asset_usage_primary_cooperative_id", table_name="shared_asset_usage")
    op.drop_index("ix_shared_asset_usage_secondary_cooperative_id", table_name="shared_asset_usage")
    op.drop_index("ix_shared_asset_usage_asset_id", table_name="shared_asset_usage")
    op.drop_table("shared_asset_usage")

    op.drop_index("ix_shared_asset_status", table_name="shared_asset")
    op.drop_index("ix_shared_asset_secondary_cooperative_id", table_name="shared_asset")
    op.drop_table("shared_asset")

    op.drop_index("ix_joint_project_allocation_primary_cooperative_id", table_name="joint_project_allocation")
    op.drop_index("ix_joint_project_allocation_secondary_cooperative_id", table_name="joint_project_allocation")
    op.drop_index("ix_joint_project_allocation_project_id", table_name="joint_project_allocation")
    op.drop_table("joint_project_allocation")

    op.drop_index("ix_joint_project_status", table_name="joint_project")
    op.drop_index("ix_joint_project_secondary_cooperative_id", table_name="joint_project")
    op.drop_table("joint_project")
