"""relational database integrity hardening

Revision ID: b8c9d0e1f222
Revises: a7b8c9d0e111
Create Date: 2026-09-13

This migration makes cooperative ownership part of key parent/child relationships,
adds conservative numeric checks, and blocks exact duplicate Farmer/Farm records.
Before adding constraints it refuses to continue if existing rows would violate the
new rules so legacy data is never silently rewritten or discarded.
"""
from alembic import op
import sqlalchemy as sa

revision = "b8c9d0e1f222"
down_revision = "a7b8c9d0e111"
branch_labels = None
depends_on = None


def _count(bind, sql):
    return int(bind.execute(sa.text(sql)).scalar() or 0)


def _preflight_integrity(bind):
    checks = [
        (
            "duplicate farmer identity rows",
            """
            SELECT COUNT(*) FROM (
                SELECT cooperative_id, fullname, phone
                FROM farmer
                WHERE cooperative_id IS NOT NULL
                GROUP BY cooperative_id, fullname, phone
                HAVING COUNT(*) > 1
            ) AS duplicate_rows
            """,
        ),
        (
            "duplicate farm identity rows",
            """
            SELECT COUNT(*) FROM (
                SELECT cooperative_id, farmer_id, name, location
                FROM farm
                WHERE cooperative_id IS NOT NULL
                GROUP BY cooperative_id, farmer_id, name, location
                HAVING COUNT(*) > 1
            ) AS duplicate_rows
            """,
        ),
        (
            "farm/farmer cooperative mismatches",
            """
            SELECT COUNT(*)
            FROM farm child JOIN farmer parent ON parent.id = child.farmer_id
            WHERE child.cooperative_id IS NOT NULL
              AND parent.cooperative_id IS NOT NULL
              AND child.cooperative_id <> parent.cooperative_id
            """,
        ),
        (
            "crop/farm cooperative mismatches",
            """
            SELECT COUNT(*)
            FROM crop child JOIN farm parent ON parent.id = child.farm_id
            WHERE child.cooperative_id IS NOT NULL
              AND parent.cooperative_id IS NOT NULL
              AND child.cooperative_id <> parent.cooperative_id
            """,
        ),
        (
            "harvest/crop cooperative mismatches",
            """
            SELECT COUNT(*)
            FROM harvest child JOIN crop parent ON parent.id = child.crop_id
            WHERE child.cooperative_id IS NOT NULL
              AND parent.cooperative_id IS NOT NULL
              AND child.cooperative_id <> parent.cooperative_id
            """,
        ),
        (
            "sale/harvest cooperative mismatches",
            """
            SELECT COUNT(*)
            FROM sale child JOIN harvest parent ON parent.id = child.harvest_id
            WHERE child.cooperative_id IS NOT NULL
              AND parent.cooperative_id IS NOT NULL
              AND child.cooperative_id <> parent.cooperative_id
            """,
        ),
        (
            "payment/sale cooperative mismatches",
            """
            SELECT COUNT(*)
            FROM payment child JOIN sale parent ON parent.id = child.sale_id
            WHERE child.cooperative_id IS NOT NULL
              AND parent.cooperative_id IS NOT NULL
              AND child.cooperative_id <> parent.cooperative_id
            """,
        ),
        (
            "expense/farm cooperative mismatches",
            """
            SELECT COUNT(*)
            FROM expense child JOIN farm parent ON parent.id = child.farm_id
            WHERE child.farm_id IS NOT NULL
              AND child.cooperative_id IS NOT NULL
              AND parent.cooperative_id IS NOT NULL
              AND child.cooperative_id <> parent.cooperative_id
            """,
        ),
        (
            "expense/supplier cooperative mismatches",
            """
            SELECT COUNT(*)
            FROM expense child JOIN supplier parent ON parent.id = child.supplier_id
            WHERE child.supplier_id IS NOT NULL
              AND child.cooperative_id IS NOT NULL
              AND parent.cooperative_id IS NOT NULL
              AND child.cooperative_id <> parent.cooperative_id
            """,
        ),
        (
            "membership/farmer cooperative mismatches",
            """
            SELECT COUNT(*)
            FROM membership child JOIN farmer parent ON parent.id = child.farmer_id
            WHERE child.cooperative_id <> parent.cooperative_id
            """,
        ),
        (
            "contribution/farmer cooperative mismatches",
            """
            SELECT COUNT(*)
            FROM contribution child JOIN farmer parent ON parent.id = child.farmer_id
            WHERE child.cooperative_id IS NOT NULL
              AND parent.cooperative_id IS NOT NULL
              AND child.cooperative_id <> parent.cooperative_id
            """,
        ),
        (
            "contribution/membership cooperative mismatches",
            """
            SELECT COUNT(*)
            FROM contribution child JOIN membership parent ON parent.id = child.membership_id
            WHERE child.membership_id IS NOT NULL
              AND child.cooperative_id IS NOT NULL
              AND child.cooperative_id <> parent.cooperative_id
            """,
        ),
        (
            "membership-history cooperative mismatches",
            """
            SELECT COUNT(*)
            FROM membership_history child JOIN membership parent ON parent.id = child.membership_id
            WHERE child.cooperative_id <> parent.cooperative_id
            """,
        ),
        ("negative legacy farmer farm sizes", "SELECT COUNT(*) FROM farmer WHERE farm_size < 0"),
        ("negative farm sizes", "SELECT COUNT(*) FROM farm WHERE size < 0"),
        ("negative crop areas", "SELECT COUNT(*) FROM crop WHERE area_planted < 0"),
        ("non-positive harvest quantities", "SELECT COUNT(*) FROM harvest WHERE quantity <= 0"),
        ("non-positive sale quantities", "SELECT COUNT(*) FROM sale WHERE quantity <= 0"),
        ("negative sale prices", "SELECT COUNT(*) FROM sale WHERE price_per_unit < 0"),
        ("negative sale totals", "SELECT COUNT(*) FROM sale WHERE total_amount < 0"),
        ("non-positive payment amounts", "SELECT COUNT(*) FROM payment WHERE amount <= 0"),
        ("non-positive expense amounts", "SELECT COUNT(*) FROM expense WHERE amount <= 0"),
        ("negative membership fees", "SELECT COUNT(*) FROM membership WHERE fee_amount < 0 OR fee_paid < 0"),
        ("non-positive contribution amounts", "SELECT COUNT(*) FROM contribution WHERE amount <= 0"),
    ]

    failures = []
    for label, sql in checks:
        count = _count(bind, sql)
        if count:
            failures.append(f"{label}: {count}")

    if failures:
        raise RuntimeError(
            "Database integrity preflight failed. Correct these records before upgrading: "
            + "; ".join(failures)
        )


def upgrade():
    bind = op.get_bind()
    _preflight_integrity(bind)

    # Parent composite uniqueness lets child tables enforce both record identity
    # and cooperative ownership with one foreign-key relationship.
    with op.batch_alter_table("farmer") as batch_op:
        batch_op.create_unique_constraint("uq_farmer_id_coop", ["id", "cooperative_id"])
        batch_op.create_unique_constraint(
            "uq_farmer_exact_identity", ["cooperative_id", "fullname", "phone"]
        )
        batch_op.create_check_constraint(
            "ck_farmer_farm_size_nonnegative", "farm_size IS NULL OR farm_size >= 0"
        )

    with op.batch_alter_table("supplier") as batch_op:
        batch_op.create_unique_constraint("uq_supplier_id_coop", ["id", "cooperative_id"])

    with op.batch_alter_table("farm") as batch_op:
        batch_op.create_unique_constraint("uq_farm_id_coop", ["id", "cooperative_id"])
        batch_op.create_unique_constraint(
            "uq_farm_exact_identity", ["cooperative_id", "farmer_id", "name", "location"]
        )
        batch_op.create_check_constraint(
            "ck_farm_size_nonnegative", "size IS NULL OR size >= 0"
        )
        batch_op.create_foreign_key(
            "fk_farm_farmer_coop",
            "farmer",
            ["farmer_id", "cooperative_id"],
            ["id", "cooperative_id"],
        )

    with op.batch_alter_table("crop") as batch_op:
        batch_op.create_unique_constraint("uq_crop_id_coop", ["id", "cooperative_id"])
        batch_op.create_check_constraint(
            "ck_crop_area_nonnegative", "area_planted IS NULL OR area_planted >= 0"
        )
        batch_op.create_foreign_key(
            "fk_crop_farm_coop",
            "farm",
            ["farm_id", "cooperative_id"],
            ["id", "cooperative_id"],
        )

    with op.batch_alter_table("harvest") as batch_op:
        batch_op.create_unique_constraint("uq_harvest_id_coop", ["id", "cooperative_id"])
        batch_op.create_check_constraint("ck_harvest_quantity_positive", "quantity > 0")
        batch_op.create_foreign_key(
            "fk_harvest_crop_coop",
            "crop",
            ["crop_id", "cooperative_id"],
            ["id", "cooperative_id"],
        )

    with op.batch_alter_table("sale") as batch_op:
        batch_op.create_unique_constraint("uq_sale_id_coop", ["id", "cooperative_id"])
        batch_op.create_check_constraint("ck_sale_quantity_positive", "quantity > 0")
        batch_op.create_check_constraint("ck_sale_price_nonnegative", "price_per_unit >= 0")
        batch_op.create_check_constraint("ck_sale_total_nonnegative", "total_amount >= 0")
        batch_op.create_foreign_key(
            "fk_sale_harvest_coop",
            "harvest",
            ["harvest_id", "cooperative_id"],
            ["id", "cooperative_id"],
        )

    with op.batch_alter_table("payment") as batch_op:
        batch_op.create_check_constraint("ck_payment_amount_positive", "amount > 0")
        batch_op.create_foreign_key(
            "fk_payment_sale_coop",
            "sale",
            ["sale_id", "cooperative_id"],
            ["id", "cooperative_id"],
        )

    with op.batch_alter_table("expense") as batch_op:
        batch_op.create_check_constraint("ck_expense_amount_positive", "amount > 0")
        batch_op.create_foreign_key(
            "fk_expense_farm_coop",
            "farm",
            ["farm_id", "cooperative_id"],
            ["id", "cooperative_id"],
        )
        batch_op.create_foreign_key(
            "fk_expense_supplier_coop",
            "supplier",
            ["supplier_id", "cooperative_id"],
            ["id", "cooperative_id"],
        )

    with op.batch_alter_table("membership") as batch_op:
        batch_op.create_unique_constraint("uq_membership_id_coop", ["id", "cooperative_id"])
        batch_op.create_check_constraint("ck_membership_fee_nonnegative", "fee_amount >= 0")
        batch_op.create_check_constraint("ck_membership_fee_paid_nonnegative", "fee_paid >= 0")
        batch_op.create_foreign_key(
            "fk_membership_farmer_coop",
            "farmer",
            ["farmer_id", "cooperative_id"],
            ["id", "cooperative_id"],
        )

    with op.batch_alter_table("contribution") as batch_op:
        batch_op.create_check_constraint("ck_contribution_amount_positive", "amount > 0")
        batch_op.create_foreign_key(
            "fk_contribution_farmer_coop",
            "farmer",
            ["farmer_id", "cooperative_id"],
            ["id", "cooperative_id"],
        )
        batch_op.create_foreign_key(
            "fk_contribution_membership_coop",
            "membership",
            ["membership_id", "cooperative_id"],
            ["id", "cooperative_id"],
        )

    with op.batch_alter_table("membership_history") as batch_op:
        batch_op.create_foreign_key(
            "fk_membership_history_membership_coop",
            "membership",
            ["membership_id", "cooperative_id"],
            ["id", "cooperative_id"],
        )


def downgrade():
    with op.batch_alter_table("membership_history") as batch_op:
        batch_op.drop_constraint("fk_membership_history_membership_coop", type_="foreignkey")

    with op.batch_alter_table("contribution") as batch_op:
        batch_op.drop_constraint("fk_contribution_membership_coop", type_="foreignkey")
        batch_op.drop_constraint("fk_contribution_farmer_coop", type_="foreignkey")
        batch_op.drop_constraint("ck_contribution_amount_positive", type_="check")

    with op.batch_alter_table("membership") as batch_op:
        batch_op.drop_constraint("fk_membership_farmer_coop", type_="foreignkey")
        batch_op.drop_constraint("ck_membership_fee_paid_nonnegative", type_="check")
        batch_op.drop_constraint("ck_membership_fee_nonnegative", type_="check")
        batch_op.drop_constraint("uq_membership_id_coop", type_="unique")

    with op.batch_alter_table("expense") as batch_op:
        batch_op.drop_constraint("fk_expense_supplier_coop", type_="foreignkey")
        batch_op.drop_constraint("fk_expense_farm_coop", type_="foreignkey")
        batch_op.drop_constraint("ck_expense_amount_positive", type_="check")

    with op.batch_alter_table("payment") as batch_op:
        batch_op.drop_constraint("fk_payment_sale_coop", type_="foreignkey")
        batch_op.drop_constraint("ck_payment_amount_positive", type_="check")

    with op.batch_alter_table("sale") as batch_op:
        batch_op.drop_constraint("fk_sale_harvest_coop", type_="foreignkey")
        batch_op.drop_constraint("ck_sale_total_nonnegative", type_="check")
        batch_op.drop_constraint("ck_sale_price_nonnegative", type_="check")
        batch_op.drop_constraint("ck_sale_quantity_positive", type_="check")
        batch_op.drop_constraint("uq_sale_id_coop", type_="unique")

    with op.batch_alter_table("harvest") as batch_op:
        batch_op.drop_constraint("fk_harvest_crop_coop", type_="foreignkey")
        batch_op.drop_constraint("ck_harvest_quantity_positive", type_="check")
        batch_op.drop_constraint("uq_harvest_id_coop", type_="unique")

    with op.batch_alter_table("crop") as batch_op:
        batch_op.drop_constraint("fk_crop_farm_coop", type_="foreignkey")
        batch_op.drop_constraint("ck_crop_area_nonnegative", type_="check")
        batch_op.drop_constraint("uq_crop_id_coop", type_="unique")

    with op.batch_alter_table("farm") as batch_op:
        batch_op.drop_constraint("fk_farm_farmer_coop", type_="foreignkey")
        batch_op.drop_constraint("ck_farm_size_nonnegative", type_="check")
        batch_op.drop_constraint("uq_farm_exact_identity", type_="unique")
        batch_op.drop_constraint("uq_farm_id_coop", type_="unique")

    with op.batch_alter_table("supplier") as batch_op:
        batch_op.drop_constraint("uq_supplier_id_coop", type_="unique")

    with op.batch_alter_table("farmer") as batch_op:
        batch_op.drop_constraint("ck_farmer_farm_size_nonnegative", type_="check")
        batch_op.drop_constraint("uq_farmer_exact_identity", type_="unique")
        batch_op.drop_constraint("uq_farmer_id_coop", type_="unique")
