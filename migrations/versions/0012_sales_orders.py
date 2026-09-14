"""Add sales orders.

Revision ID: 0012_sales_orders
Revises: 0011_payment_terms
Create Date: 2026-09-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0012_sales_orders"
down_revision: Union[str, None] = "0011_payment_terms"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "sales_orders",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("customer_id", sa.String(length=36), nullable=False),
        sa.Column("order_number", sa.String(length=120), nullable=False),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column("requested_delivery_date", sa.Date(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("subtotal", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("tax_total", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("total", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("receivable_account_id", sa.String(length=36), nullable=False),
        sa.Column("converted_invoice_id", sa.String(length=36), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["converted_invoice_id"], ["sales_invoices.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.ForeignKeyConstraint(["receivable_account_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organisation_id", "order_number", name="uq_sales_order_org_number"),
    )
    op.create_index(op.f("ix_sales_orders_converted_invoice_id"), "sales_orders", ["converted_invoice_id"], unique=False)
    op.create_index(op.f("ix_sales_orders_customer_id"), "sales_orders", ["customer_id"], unique=False)
    op.create_index(op.f("ix_sales_orders_order_date"), "sales_orders", ["order_date"], unique=False)
    op.create_index(op.f("ix_sales_orders_order_number"), "sales_orders", ["order_number"], unique=False)
    op.create_index(op.f("ix_sales_orders_organisation_id"), "sales_orders", ["organisation_id"], unique=False)
    op.create_index(op.f("ix_sales_orders_requested_delivery_date"), "sales_orders", ["requested_delivery_date"], unique=False)
    op.create_index(op.f("ix_sales_orders_status"), "sales_orders", ["status"], unique=False)

    op.create_table(
        "sales_order_lines",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("order_id", sa.String(length=36), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("net_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("tax_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("tax_code_id", sa.String(length=36), nullable=True),
        sa.Column("revenue_account_id", sa.String(length=36), nullable=False),
        sa.Column("dimensions", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["sales_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["revenue_account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["tax_code_id"], ["tax_codes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sales_order_lines_order_id"), "sales_order_lines", ["order_id"], unique=False)
    op.create_index(op.f("ix_sales_order_lines_tax_code_id"), "sales_order_lines", ["tax_code_id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_sales_order_lines_tax_code_id"), table_name="sales_order_lines")
    op.drop_index(op.f("ix_sales_order_lines_order_id"), table_name="sales_order_lines")
    op.drop_table("sales_order_lines")
    op.drop_index(op.f("ix_sales_orders_status"), table_name="sales_orders")
    op.drop_index(op.f("ix_sales_orders_requested_delivery_date"), table_name="sales_orders")
    op.drop_index(op.f("ix_sales_orders_organisation_id"), table_name="sales_orders")
    op.drop_index(op.f("ix_sales_orders_order_number"), table_name="sales_orders")
    op.drop_index(op.f("ix_sales_orders_order_date"), table_name="sales_orders")
    op.drop_index(op.f("ix_sales_orders_customer_id"), table_name="sales_orders")
    op.drop_index(op.f("ix_sales_orders_converted_invoice_id"), table_name="sales_orders")
    op.drop_table("sales_orders")
