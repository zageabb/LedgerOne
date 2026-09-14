"""Add sales quote support.

Revision ID: 0008_sales_quotes
Revises: 0007_credit_notes
Create Date: 2026-09-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008_sales_quotes"
down_revision: Union[str, None] = "0007_credit_notes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "sales_quotes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("customer_id", sa.String(length=36), nullable=False),
        sa.Column("quote_number", sa.String(length=120), nullable=False),
        sa.Column("quote_date", sa.Date(), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=True),
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
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.ForeignKeyConstraint(["receivable_account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["converted_invoice_id"], ["sales_invoices.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organisation_id", "quote_number", name="uq_sales_quote_org_number"),
    )
    op.create_index("ix_sales_quotes_organisation_id", "sales_quotes", ["organisation_id"], unique=False)
    op.create_index("ix_sales_quotes_customer_id", "sales_quotes", ["customer_id"], unique=False)
    op.create_index("ix_sales_quotes_quote_number", "sales_quotes", ["quote_number"], unique=False)
    op.create_index("ix_sales_quotes_quote_date", "sales_quotes", ["quote_date"], unique=False)
    op.create_index("ix_sales_quotes_expiry_date", "sales_quotes", ["expiry_date"], unique=False)
    op.create_index("ix_sales_quotes_status", "sales_quotes", ["status"], unique=False)
    op.create_index("ix_sales_quotes_converted_invoice_id", "sales_quotes", ["converted_invoice_id"], unique=False)

    op.create_table(
        "sales_quote_lines",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("quote_id", sa.String(length=36), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("net_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("tax_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("tax_code_id", sa.String(length=36), nullable=True),
        sa.Column("revenue_account_id", sa.String(length=36), nullable=False),
        sa.Column("dimensions", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["quote_id"], ["sales_quotes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tax_code_id"], ["tax_codes.id"]),
        sa.ForeignKeyConstraint(["revenue_account_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sales_quote_lines_quote_id", "sales_quote_lines", ["quote_id"], unique=False)
    op.create_index("ix_sales_quote_lines_tax_code_id", "sales_quote_lines", ["tax_code_id"], unique=False)


def downgrade():
    op.drop_index("ix_sales_quote_lines_tax_code_id", table_name="sales_quote_lines")
    op.drop_index("ix_sales_quote_lines_quote_id", table_name="sales_quote_lines")
    op.drop_table("sales_quote_lines")

    op.drop_index("ix_sales_quotes_converted_invoice_id", table_name="sales_quotes")
    op.drop_index("ix_sales_quotes_status", table_name="sales_quotes")
    op.drop_index("ix_sales_quotes_expiry_date", table_name="sales_quotes")
    op.drop_index("ix_sales_quotes_quote_date", table_name="sales_quotes")
    op.drop_index("ix_sales_quotes_quote_number", table_name="sales_quotes")
    op.drop_index("ix_sales_quotes_customer_id", table_name="sales_quotes")
    op.drop_index("ix_sales_quotes_organisation_id", table_name="sales_quotes")
    op.drop_table("sales_quotes")
