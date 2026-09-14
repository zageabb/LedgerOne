"""Add sales and purchase credit notes.

Revision ID: 0007_credit_notes
Revises: 0006_tax_vat
Create Date: 2026-09-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007_credit_notes"
down_revision: Union[str, None] = "0006_tax_vat"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    with op.batch_alter_table("sales_payments", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("settlement_type", sa.String(length=30), nullable=False, server_default="payment")
        )
        batch_op.create_index("ix_sales_payments_settlement_type", ["settlement_type"], unique=False)

    with op.batch_alter_table("purchase_payments", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("settlement_type", sa.String(length=30), nullable=False, server_default="payment")
        )
        batch_op.create_index("ix_purchase_payments_settlement_type", ["settlement_type"], unique=False)

    op.create_table(
        "sales_credit_notes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("customer_id", sa.String(length=36), nullable=False),
        sa.Column("invoice_id", sa.String(length=36), nullable=False),
        sa.Column("credit_number", sa.String(length=120), nullable=False),
        sa.Column("credit_date", sa.Date(), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("subtotal", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("tax_total", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("total", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("posted_journal_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.ForeignKeyConstraint(["invoice_id"], ["sales_invoices.id"]),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.ForeignKeyConstraint(["posted_journal_id"], ["journals.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organisation_id", "credit_number", name="uq_sales_credit_org_number"),
    )
    op.create_index("ix_sales_credit_notes_organisation_id", "sales_credit_notes", ["organisation_id"], unique=False)
    op.create_index("ix_sales_credit_notes_customer_id", "sales_credit_notes", ["customer_id"], unique=False)
    op.create_index("ix_sales_credit_notes_invoice_id", "sales_credit_notes", ["invoice_id"], unique=False)
    op.create_index("ix_sales_credit_notes_credit_number", "sales_credit_notes", ["credit_number"], unique=False)
    op.create_index("ix_sales_credit_notes_credit_date", "sales_credit_notes", ["credit_date"], unique=False)
    op.create_index("ix_sales_credit_notes_status", "sales_credit_notes", ["status"], unique=False)
    op.create_index("ix_sales_credit_notes_posted_journal_id", "sales_credit_notes", ["posted_journal_id"], unique=False)

    op.create_table(
        "purchase_credit_notes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("supplier_id", sa.String(length=36), nullable=False),
        sa.Column("bill_id", sa.String(length=36), nullable=False),
        sa.Column("credit_number", sa.String(length=120), nullable=False),
        sa.Column("credit_date", sa.Date(), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("subtotal", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("tax_total", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("total", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("posted_journal_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["bill_id"], ["purchase_bills.id"]),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.ForeignKeyConstraint(["posted_journal_id"], ["journals.id"]),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organisation_id", "credit_number", name="uq_purchase_credit_org_number"),
    )
    op.create_index("ix_purchase_credit_notes_organisation_id", "purchase_credit_notes", ["organisation_id"], unique=False)
    op.create_index("ix_purchase_credit_notes_supplier_id", "purchase_credit_notes", ["supplier_id"], unique=False)
    op.create_index("ix_purchase_credit_notes_bill_id", "purchase_credit_notes", ["bill_id"], unique=False)
    op.create_index("ix_purchase_credit_notes_credit_number", "purchase_credit_notes", ["credit_number"], unique=False)
    op.create_index("ix_purchase_credit_notes_credit_date", "purchase_credit_notes", ["credit_date"], unique=False)
    op.create_index("ix_purchase_credit_notes_status", "purchase_credit_notes", ["status"], unique=False)
    op.create_index("ix_purchase_credit_notes_posted_journal_id", "purchase_credit_notes", ["posted_journal_id"], unique=False)


def downgrade():
    op.drop_index("ix_purchase_credit_notes_posted_journal_id", table_name="purchase_credit_notes")
    op.drop_index("ix_purchase_credit_notes_status", table_name="purchase_credit_notes")
    op.drop_index("ix_purchase_credit_notes_credit_date", table_name="purchase_credit_notes")
    op.drop_index("ix_purchase_credit_notes_credit_number", table_name="purchase_credit_notes")
    op.drop_index("ix_purchase_credit_notes_bill_id", table_name="purchase_credit_notes")
    op.drop_index("ix_purchase_credit_notes_supplier_id", table_name="purchase_credit_notes")
    op.drop_index("ix_purchase_credit_notes_organisation_id", table_name="purchase_credit_notes")
    op.drop_table("purchase_credit_notes")

    op.drop_index("ix_sales_credit_notes_posted_journal_id", table_name="sales_credit_notes")
    op.drop_index("ix_sales_credit_notes_status", table_name="sales_credit_notes")
    op.drop_index("ix_sales_credit_notes_credit_date", table_name="sales_credit_notes")
    op.drop_index("ix_sales_credit_notes_credit_number", table_name="sales_credit_notes")
    op.drop_index("ix_sales_credit_notes_invoice_id", table_name="sales_credit_notes")
    op.drop_index("ix_sales_credit_notes_customer_id", table_name="sales_credit_notes")
    op.drop_index("ix_sales_credit_notes_organisation_id", table_name="sales_credit_notes")
    op.drop_table("sales_credit_notes")

    with op.batch_alter_table("purchase_payments", schema=None) as batch_op:
        batch_op.drop_index("ix_purchase_payments_settlement_type")
        batch_op.drop_column("settlement_type")

    with op.batch_alter_table("sales_payments", schema=None) as batch_op:
        batch_op.drop_index("ix_sales_payments_settlement_type")
        batch_op.drop_column("settlement_type")
