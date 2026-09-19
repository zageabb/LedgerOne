"""Add customer and supplier credit refunds.

Revision ID: 0018_credit_refunds
Revises: 0017_audit_integrity
Create Date: 2026-09-18
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0018_credit_refunds"
down_revision: Union[str, None] = "0017_audit_integrity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "sales_credit_refunds",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("customer_id", sa.String(length=36), nullable=False),
        sa.Column("source_payment_id", sa.String(length=36), nullable=False),
        sa.Column("refund_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("bank_account_id", sa.String(length=36), nullable=False),
        sa.Column("receivable_account_id", sa.String(length=36), nullable=False),
        sa.Column("journal_id", sa.String(length=36), nullable=False),
        sa.Column("reference", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.ForeignKeyConstraint(["source_payment_id"], ["sales_payments.id"]),
        sa.ForeignKeyConstraint(["bank_account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["receivable_account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["journal_id"], ["journals.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sales_credit_refunds_organisation_id", "sales_credit_refunds", ["organisation_id"], unique=False)
    op.create_index("ix_sales_credit_refunds_customer_id", "sales_credit_refunds", ["customer_id"], unique=False)
    op.create_index("ix_sales_credit_refunds_source_payment_id", "sales_credit_refunds", ["source_payment_id"], unique=False)
    op.create_index("ix_sales_credit_refunds_refund_date", "sales_credit_refunds", ["refund_date"], unique=False)
    op.create_index("ix_sales_credit_refunds_journal_id", "sales_credit_refunds", ["journal_id"], unique=True)
    op.create_index("ix_sales_credit_refunds_reference", "sales_credit_refunds", ["reference"], unique=False)

    op.create_table(
        "purchase_credit_refunds",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("supplier_id", sa.String(length=36), nullable=False),
        sa.Column("source_payment_id", sa.String(length=36), nullable=False),
        sa.Column("refund_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("bank_account_id", sa.String(length=36), nullable=False),
        sa.Column("payable_account_id", sa.String(length=36), nullable=False),
        sa.Column("journal_id", sa.String(length=36), nullable=False),
        sa.Column("reference", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"]),
        sa.ForeignKeyConstraint(["source_payment_id"], ["purchase_payments.id"]),
        sa.ForeignKeyConstraint(["bank_account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["payable_account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["journal_id"], ["journals.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_purchase_credit_refunds_organisation_id", "purchase_credit_refunds", ["organisation_id"], unique=False)
    op.create_index("ix_purchase_credit_refunds_supplier_id", "purchase_credit_refunds", ["supplier_id"], unique=False)
    op.create_index("ix_purchase_credit_refunds_source_payment_id", "purchase_credit_refunds", ["source_payment_id"], unique=False)
    op.create_index("ix_purchase_credit_refunds_refund_date", "purchase_credit_refunds", ["refund_date"], unique=False)
    op.create_index("ix_purchase_credit_refunds_journal_id", "purchase_credit_refunds", ["journal_id"], unique=True)
    op.create_index("ix_purchase_credit_refunds_reference", "purchase_credit_refunds", ["reference"], unique=False)


def downgrade():
    op.drop_index("ix_purchase_credit_refunds_reference", table_name="purchase_credit_refunds")
    op.drop_index("ix_purchase_credit_refunds_journal_id", table_name="purchase_credit_refunds")
    op.drop_index("ix_purchase_credit_refunds_refund_date", table_name="purchase_credit_refunds")
    op.drop_index("ix_purchase_credit_refunds_source_payment_id", table_name="purchase_credit_refunds")
    op.drop_index("ix_purchase_credit_refunds_supplier_id", table_name="purchase_credit_refunds")
    op.drop_index("ix_purchase_credit_refunds_organisation_id", table_name="purchase_credit_refunds")
    op.drop_table("purchase_credit_refunds")

    op.drop_index("ix_sales_credit_refunds_reference", table_name="sales_credit_refunds")
    op.drop_index("ix_sales_credit_refunds_journal_id", table_name="sales_credit_refunds")
    op.drop_index("ix_sales_credit_refunds_refund_date", table_name="sales_credit_refunds")
    op.drop_index("ix_sales_credit_refunds_source_payment_id", table_name="sales_credit_refunds")
    op.drop_index("ix_sales_credit_refunds_customer_id", table_name="sales_credit_refunds")
    op.drop_index("ix_sales_credit_refunds_organisation_id", table_name="sales_credit_refunds")
    op.drop_table("sales_credit_refunds")
