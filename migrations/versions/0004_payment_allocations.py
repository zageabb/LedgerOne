"""Add customer and supplier payment allocations.

Revision ID: 0004_payment_allocations
Revises: 0003_opening_balances_recurring
Create Date: 2026-09-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_payment_allocations"
down_revision: Union[str, None] = "0003_opening_balances_recurring"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "sales_payments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("customer_id", sa.String(length=36), nullable=False),
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("reference", sa.String(length=120), nullable=True),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("journal_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.ForeignKeyConstraint(["journal_id"], ["journals.id"]),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organisation_id", "journal_id", name="uq_sales_payment_org_journal"),
    )
    op.create_index("ix_sales_payments_organisation_id", "sales_payments", ["organisation_id"], unique=False)
    op.create_index("ix_sales_payments_customer_id", "sales_payments", ["customer_id"], unique=False)
    op.create_index("ix_sales_payments_payment_date", "sales_payments", ["payment_date"], unique=False)
    op.create_index("ix_sales_payments_reference", "sales_payments", ["reference"], unique=False)
    op.create_index("ix_sales_payments_journal_id", "sales_payments", ["journal_id"], unique=False)
    op.create_index("ix_sales_payments_status", "sales_payments", ["status"], unique=False)

    op.create_table(
        "sales_payment_allocations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("payment_id", sa.String(length=36), nullable=False),
        sa.Column("invoice_id", sa.String(length=36), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["invoice_id"], ["sales_invoices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["payment_id"], ["sales_payments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payment_id", "invoice_id", name="uq_sales_payment_invoice"),
    )
    op.create_index("ix_sales_payment_allocations_payment_id", "sales_payment_allocations", ["payment_id"], unique=False)
    op.create_index("ix_sales_payment_allocations_invoice_id", "sales_payment_allocations", ["invoice_id"], unique=False)

    op.create_table(
        "purchase_payments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("supplier_id", sa.String(length=36), nullable=False),
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("reference", sa.String(length=120), nullable=True),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("journal_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["journal_id"], ["journals.id"]),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organisation_id", "journal_id", name="uq_purchase_payment_org_journal"),
    )
    op.create_index("ix_purchase_payments_organisation_id", "purchase_payments", ["organisation_id"], unique=False)
    op.create_index("ix_purchase_payments_supplier_id", "purchase_payments", ["supplier_id"], unique=False)
    op.create_index("ix_purchase_payments_payment_date", "purchase_payments", ["payment_date"], unique=False)
    op.create_index("ix_purchase_payments_reference", "purchase_payments", ["reference"], unique=False)
    op.create_index("ix_purchase_payments_journal_id", "purchase_payments", ["journal_id"], unique=False)
    op.create_index("ix_purchase_payments_status", "purchase_payments", ["status"], unique=False)

    op.create_table(
        "purchase_payment_allocations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("payment_id", sa.String(length=36), nullable=False),
        sa.Column("bill_id", sa.String(length=36), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["bill_id"], ["purchase_bills.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["payment_id"], ["purchase_payments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payment_id", "bill_id", name="uq_purchase_payment_bill"),
    )
    op.create_index("ix_purchase_payment_allocations_payment_id", "purchase_payment_allocations", ["payment_id"], unique=False)
    op.create_index("ix_purchase_payment_allocations_bill_id", "purchase_payment_allocations", ["bill_id"], unique=False)


def downgrade():
    op.drop_index("ix_purchase_payment_allocations_bill_id", table_name="purchase_payment_allocations")
    op.drop_index("ix_purchase_payment_allocations_payment_id", table_name="purchase_payment_allocations")
    op.drop_table("purchase_payment_allocations")
    op.drop_index("ix_purchase_payments_status", table_name="purchase_payments")
    op.drop_index("ix_purchase_payments_journal_id", table_name="purchase_payments")
    op.drop_index("ix_purchase_payments_reference", table_name="purchase_payments")
    op.drop_index("ix_purchase_payments_payment_date", table_name="purchase_payments")
    op.drop_index("ix_purchase_payments_supplier_id", table_name="purchase_payments")
    op.drop_index("ix_purchase_payments_organisation_id", table_name="purchase_payments")
    op.drop_table("purchase_payments")

    op.drop_index("ix_sales_payment_allocations_invoice_id", table_name="sales_payment_allocations")
    op.drop_index("ix_sales_payment_allocations_payment_id", table_name="sales_payment_allocations")
    op.drop_table("sales_payment_allocations")
    op.drop_index("ix_sales_payments_status", table_name="sales_payments")
    op.drop_index("ix_sales_payments_journal_id", table_name="sales_payments")
    op.drop_index("ix_sales_payments_reference", table_name="sales_payments")
    op.drop_index("ix_sales_payments_payment_date", table_name="sales_payments")
    op.drop_index("ix_sales_payments_customer_id", table_name="sales_payments")
    op.drop_index("ix_sales_payments_organisation_id", table_name="sales_payments")
    op.drop_table("sales_payments")
