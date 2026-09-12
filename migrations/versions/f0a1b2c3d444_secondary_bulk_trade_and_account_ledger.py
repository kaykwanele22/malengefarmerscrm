"""Secondary bulk trade and cooperative account ledger

Revision ID: f0a1b2c3d444
Revises: e9f0a1b2c333
Create Date: 2026-09-12
"""
from alembic import op
import sqlalchemy as sa

revision="f0a1b2c3d444"
down_revision="e9f0a1b2c333"
branch_labels=None
depends_on=None


def upgrade():
    op.create_table("bulk_purchase",
        sa.Column("id",sa.Integer(),primary_key=True),sa.Column("secondary_cooperative_id",sa.Integer(),nullable=False),
        sa.Column("title",sa.String(180),nullable=False),sa.Column("product",sa.String(120),nullable=False),
        sa.Column("supplier_name",sa.String(180),nullable=False),sa.Column("quantity",sa.Float(),nullable=False,server_default="0"),
        sa.Column("unit",sa.String(40),nullable=False),sa.Column("estimated_cost",sa.Float(),nullable=False,server_default="0"),
        sa.Column("actual_cost",sa.Float(),nullable=False,server_default="0"),sa.Column("order_date",sa.Date()),
        sa.Column("expected_delivery_date",sa.Date()),sa.Column("status",sa.String(40),nullable=False,server_default="Pending Approval"),
        sa.Column("notes",sa.Text()),sa.Column("created_by_user_id",sa.Integer(),nullable=False),
        sa.Column("approved_by_user_id",sa.Integer()),sa.Column("approved_at",sa.DateTime()),sa.Column("created_at",sa.DateTime(),nullable=False),
        sa.ForeignKeyConstraint(["secondary_cooperative_id"],["cooperative.id"]),sa.ForeignKeyConstraint(["created_by_user_id"],["user.id"]),
        sa.ForeignKeyConstraint(["approved_by_user_id"],["user.id"]))
    op.create_index("ix_bulk_purchase_secondary","bulk_purchase",["secondary_cooperative_id"]);op.create_index("ix_bulk_purchase_status","bulk_purchase",["status"])
    op.create_table("bulk_purchase_allocation",
        sa.Column("id",sa.Integer(),primary_key=True),sa.Column("purchase_id",sa.Integer(),nullable=False),
        sa.Column("secondary_cooperative_id",sa.Integer(),nullable=False),sa.Column("primary_cooperative_id",sa.Integer(),nullable=False),
        sa.Column("requested_quantity",sa.Float(),nullable=False,server_default="0"),sa.Column("allocated_quantity",sa.Float(),nullable=False,server_default="0"),
        sa.Column("received_quantity",sa.Float(),nullable=False,server_default="0"),sa.Column("amount_due",sa.Float(),nullable=False,server_default="0"),
        sa.Column("status",sa.String(40),nullable=False,server_default="Planned"),sa.Column("notes",sa.Text()),
        sa.Column("updated_by_user_id",sa.Integer(),nullable=False),sa.Column("updated_at",sa.DateTime(),nullable=False),
        sa.ForeignKeyConstraint(["purchase_id"],["bulk_purchase.id"],ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["secondary_cooperative_id"],["cooperative.id"]),sa.ForeignKeyConstraint(["primary_cooperative_id"],["cooperative.id"]),
        sa.ForeignKeyConstraint(["updated_by_user_id"],["user.id"]),sa.UniqueConstraint("purchase_id","primary_cooperative_id",name="uq_bulk_purchase_primary"))
    op.create_index("ix_bulk_purchase_allocation_purchase","bulk_purchase_allocation",["purchase_id"])
    op.create_table("bulk_sale",
        sa.Column("id",sa.Integer(),primary_key=True),sa.Column("secondary_cooperative_id",sa.Integer(),nullable=False),
        sa.Column("title",sa.String(180),nullable=False),sa.Column("buyer_name",sa.String(180),nullable=False),
        sa.Column("product",sa.String(120),nullable=False),sa.Column("target_quantity",sa.Float(),nullable=False,server_default="0"),
        sa.Column("unit",sa.String(40),nullable=False),sa.Column("contract_value",sa.Float(),nullable=False,server_default="0"),
        sa.Column("delivery_date",sa.Date()),sa.Column("status",sa.String(40),nullable=False,server_default="Pending Approval"),
        sa.Column("notes",sa.Text()),sa.Column("created_by_user_id",sa.Integer(),nullable=False),sa.Column("approved_by_user_id",sa.Integer()),
        sa.Column("approved_at",sa.DateTime()),sa.Column("created_at",sa.DateTime(),nullable=False),
        sa.ForeignKeyConstraint(["secondary_cooperative_id"],["cooperative.id"]),sa.ForeignKeyConstraint(["created_by_user_id"],["user.id"]),
        sa.ForeignKeyConstraint(["approved_by_user_id"],["user.id"]))
    op.create_index("ix_bulk_sale_secondary","bulk_sale",["secondary_cooperative_id"]);op.create_index("ix_bulk_sale_status","bulk_sale",["status"])
    op.create_table("bulk_sale_commitment",
        sa.Column("id",sa.Integer(),primary_key=True),sa.Column("sale_id",sa.Integer(),nullable=False),
        sa.Column("secondary_cooperative_id",sa.Integer(),nullable=False),sa.Column("primary_cooperative_id",sa.Integer(),nullable=False),
        sa.Column("committed_quantity",sa.Float(),nullable=False,server_default="0"),sa.Column("accepted_quantity",sa.Float(),nullable=False,server_default="0"),
        sa.Column("quality_grade",sa.String(80)),sa.Column("status",sa.String(40),nullable=False,server_default="Committed"),
        sa.Column("notes",sa.Text()),sa.Column("updated_by_user_id",sa.Integer(),nullable=False),sa.Column("updated_at",sa.DateTime(),nullable=False),
        sa.ForeignKeyConstraint(["sale_id"],["bulk_sale.id"],ondelete="CASCADE"),sa.ForeignKeyConstraint(["secondary_cooperative_id"],["cooperative.id"]),
        sa.ForeignKeyConstraint(["primary_cooperative_id"],["cooperative.id"]),sa.ForeignKeyConstraint(["updated_by_user_id"],["user.id"]),
        sa.UniqueConstraint("sale_id","primary_cooperative_id",name="uq_bulk_sale_primary"))
    op.create_table("bulk_sale_receipt",
        sa.Column("id",sa.Integer(),primary_key=True),sa.Column("sale_id",sa.Integer(),nullable=False),
        sa.Column("secondary_cooperative_id",sa.Integer(),nullable=False),sa.Column("amount",sa.Float(),nullable=False),
        sa.Column("payment_date",sa.Date(),nullable=False),sa.Column("method",sa.String(60)),sa.Column("reference",sa.String(120)),
        sa.Column("status",sa.String(40),nullable=False,server_default="Pending Confirmation"),sa.Column("recorded_by_user_id",sa.Integer(),nullable=False),
        sa.Column("decided_by_user_id",sa.Integer()),sa.Column("decided_at",sa.DateTime()),sa.Column("notes",sa.Text()),sa.Column("created_at",sa.DateTime(),nullable=False),
        sa.ForeignKeyConstraint(["sale_id"],["bulk_sale.id"],ondelete="CASCADE"),sa.ForeignKeyConstraint(["secondary_cooperative_id"],["cooperative.id"]),
        sa.ForeignKeyConstraint(["recorded_by_user_id"],["user.id"]),sa.ForeignKeyConstraint(["decided_by_user_id"],["user.id"]))
    op.create_table("bulk_sale_distribution",
        sa.Column("id",sa.Integer(),primary_key=True),sa.Column("sale_id",sa.Integer(),nullable=False),
        sa.Column("secondary_cooperative_id",sa.Integer(),nullable=False),sa.Column("primary_cooperative_id",sa.Integer(),nullable=False),
        sa.Column("gross_share",sa.Float(),nullable=False,server_default="0"),sa.Column("deductions",sa.Float(),nullable=False,server_default="0"),
        sa.Column("net_amount",sa.Float(),nullable=False,server_default="0"),sa.Column("status",sa.String(40),nullable=False,server_default="Pending Approval"),
        sa.Column("notes",sa.Text()),sa.Column("prepared_by_user_id",sa.Integer(),nullable=False),sa.Column("approved_by_user_id",sa.Integer()),
        sa.Column("approved_at",sa.DateTime()),sa.Column("created_at",sa.DateTime(),nullable=False),
        sa.ForeignKeyConstraint(["sale_id"],["bulk_sale.id"],ondelete="CASCADE"),sa.ForeignKeyConstraint(["secondary_cooperative_id"],["cooperative.id"]),
        sa.ForeignKeyConstraint(["primary_cooperative_id"],["cooperative.id"]),sa.ForeignKeyConstraint(["prepared_by_user_id"],["user.id"]),
        sa.ForeignKeyConstraint(["approved_by_user_id"],["user.id"]),sa.UniqueConstraint("sale_id","primary_cooperative_id",name="uq_bulk_distribution_primary"))
    op.create_table("finance_account",
        sa.Column("id",sa.Integer(),primary_key=True),sa.Column("cooperative_id",sa.Integer(),nullable=False),
        sa.Column("name",sa.String(120),nullable=False),sa.Column("account_type",sa.String(40),nullable=False),
        sa.Column("institution",sa.String(120)),sa.Column("account_last4",sa.String(4)),sa.Column("opening_balance",sa.Float(),nullable=False,server_default="0"),
        sa.Column("status",sa.String(20),nullable=False,server_default="Active"),sa.Column("notes",sa.Text()),
        sa.Column("created_by_user_id",sa.Integer(),nullable=False),sa.Column("created_at",sa.DateTime(),nullable=False),
        sa.ForeignKeyConstraint(["cooperative_id"],["cooperative.id"]),sa.ForeignKeyConstraint(["created_by_user_id"],["user.id"]),
        sa.UniqueConstraint("cooperative_id","name",name="uq_finance_account_name"))
    op.create_index("ix_finance_account_cooperative","finance_account",["cooperative_id"])
    op.create_table("ledger_transaction",
        sa.Column("id",sa.Integer(),primary_key=True),sa.Column("cooperative_id",sa.Integer(),nullable=False),
        sa.Column("transaction_type",sa.String(30),nullable=False),sa.Column("category",sa.String(100),nullable=False),
        sa.Column("amount",sa.Float(),nullable=False),sa.Column("transaction_date",sa.Date(),nullable=False),
        sa.Column("from_account_id",sa.Integer()),sa.Column("to_account_id",sa.Integer()),sa.Column("counterparty",sa.String(180)),
        sa.Column("reference",sa.String(120)),sa.Column("source_type",sa.String(60)),sa.Column("source_id",sa.Integer()),
        sa.Column("status",sa.String(40),nullable=False,server_default="Pending Confirmation"),sa.Column("notes",sa.Text()),
        sa.Column("recorded_by_user_id",sa.Integer(),nullable=False),sa.Column("decided_by_user_id",sa.Integer()),
        sa.Column("decided_at",sa.DateTime()),sa.Column("created_at",sa.DateTime(),nullable=False),
        sa.ForeignKeyConstraint(["cooperative_id"],["cooperative.id"]),sa.ForeignKeyConstraint(["from_account_id"],["finance_account.id"]),
        sa.ForeignKeyConstraint(["to_account_id"],["finance_account.id"]),sa.ForeignKeyConstraint(["recorded_by_user_id"],["user.id"]),
        sa.ForeignKeyConstraint(["decided_by_user_id"],["user.id"]))
    op.create_index("ix_ledger_transaction_cooperative","ledger_transaction",["cooperative_id"])
    op.create_index("ix_ledger_transaction_date","ledger_transaction",["transaction_date"])
    op.create_index("ix_ledger_transaction_status","ledger_transaction",["status"])


def downgrade():
    for table in ("ledger_transaction","finance_account","bulk_sale_distribution","bulk_sale_receipt",
                  "bulk_sale_commitment","bulk_sale","bulk_purchase_allocation","bulk_purchase"):
        op.drop_table(table)
