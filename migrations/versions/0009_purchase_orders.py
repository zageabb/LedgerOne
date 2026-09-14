"""Add purchase order support.

Revision ID: 0009_purchase_orders
Revises: 0008_sales_quotes
Create Date: 2026-09-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0009_purchase_orders"
down_revision: Union[str, None] = "0008_sales_quotes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("supplier_id", sa.String(length=36), nullable=False),
        sa.Column("order_number", sa.String(length=120), nullable=False),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column("expected_date", sa.Date(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("subtotal", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("tax_total", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("total", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("payable_account_id", sa.String(length=36), nullable=False),
        sa.Column("converted_bill_id", sa.String(length=36), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"]),
        sa.ForeignKeyConstraint(["payable_account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["converted_bill_id"], ["purchase_bills.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organisation_id", "order_number", name="uq_purchase_order_org_number"),
    )
    op.create_index("ix_purchase_orders_organisation_id", "purchase_orders", ["organisation_id"], unique=False)
    op.create_index("ix_purchase_orders_supplier_id", "purchase_orders", ["supplier_id"], unique=False)
    op.create_index("ix_purchase_orders_order_number", "purchase_orders", ["order_number"], unique=False)
    op.create_index("ix_purchase_orders_order_date", "purchase_orders", ["order_date"], unique=False)
    op.create_index("ix_purchase_orders_expected_date", "purchase_orders", ["expected_date"], unique=False)
    op.create_index("ix_purchase_orders_status", "purchase_orders", ["status"], unique=False)
    op.create_index("ix_purchase_orders_converted_bill_id", "purchase_orders", ["converted_bill_id"], unique=False)

    op.create_table(
        "purchase_order_lines",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("order_id", sa.String(length=36), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("net_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("tax_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("tax_code_id", sa.String(length=36), nullable=True),
        sa.Column("expense_account_id", sa.String(length=36), nullable=False),
        sa.Column("dimensions", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["purchase_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tax_code_id"], ["tax_codes.id"]),
        sa.ForeignKeyConstraint(["expense_account_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_purchase_order_lines_order_id", "purchase_order_lines", ["order_id"], unique=False)
    op.create_index("ix_purchase_order_lines_tax_code_id", "purchase_order_lines", ["tax_code_id"], unique=False)


def downgrade():
    op.drop_index("ix_purchase_order_lines_tax_code_id", table_name="purchase_order_lines")
    op.drop_index("ix_purchase_order_lines_order_id", table_name="purchase_order_lines")
    op.drop_table("purchase_order_lines")

    op.drop_index("ix_purchase_orders_converted_bill_id", table_name="purchase_orders")
    op.drop_index("ix_purchase_orders_status", table_name="purchase_orders")
    op.drop_index("ix_purchase_orders_expected_date", table_name="purchase_orders")
    op.drop_index("ix_purchase_orders_order_date", table_name="purchase_orders")
    op.drop_index("ix_purchase_orders_order_number", table_name="purchase_orders")
    op.drop_index("ix_purchase_orders_supplier_id", table_name="purchase_orders")
    op.drop_index("ix_purchase_orders_organisation_id", table_name="purchase_orders")
    op.drop_table("purchase_orders")
