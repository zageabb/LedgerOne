"""Add Tax and VAT support.

Revision ID: 0006_tax_vat
Revises: 0005_source_documents
Create Date: 2026-09-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006_tax_vat"
down_revision: Union[str, None] = "0005_source_documents"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "tax_profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("jurisdiction", sa.String(length=10), nullable=False),
        sa.Column("is_vat_registered", sa.Boolean(), nullable=False),
        sa.Column("registration_number", sa.String(length=80), nullable=True),
        sa.Column("scheme", sa.String(length=40), nullable=False),
        sa.Column("return_frequency", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organisation_id", name="uq_tax_profile_organisation"),
    )
    op.create_index("ix_tax_profiles_organisation_id", "tax_profiles", ["organisation_id"], unique=False)

    op.create_table(
        "tax_codes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("rate_percent", sa.Numeric(precision=7, scale=4), nullable=False),
        sa.Column("treatment", sa.String(length=30), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("sales_tax_account_id", sa.String(length=36), nullable=True),
        sa.Column("purchase_tax_account_id", sa.String(length=36), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.ForeignKeyConstraint(["sales_tax_account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["purchase_tax_account_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organisation_id", "code", name="uq_tax_code_org_code"),
    )
    op.create_index("ix_tax_codes_organisation_id", "tax_codes", ["organisation_id"], unique=False)
    op.create_index("ix_tax_codes_code", "tax_codes", ["code"], unique=False)
    op.create_index("ix_tax_codes_treatment", "tax_codes", ["treatment"], unique=False)
    op.create_index("ix_tax_codes_scope", "tax_codes", ["scope"], unique=False)
    op.create_index("ix_tax_codes_sales_tax_account_id", "tax_codes", ["sales_tax_account_id"], unique=False)
    op.create_index("ix_tax_codes_purchase_tax_account_id", "tax_codes", ["purchase_tax_account_id"], unique=False)
    op.create_index("ix_tax_codes_is_active", "tax_codes", ["is_active"], unique=False)

    with op.batch_alter_table("sales_invoice_lines", schema=None) as batch_op:
        batch_op.add_column(sa.Column("tax_code_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key("fk_sales_invoice_lines_tax_code_id", "tax_codes", ["tax_code_id"], ["id"])
        batch_op.create_index("ix_sales_invoice_lines_tax_code_id", ["tax_code_id"], unique=False)

    with op.batch_alter_table("purchase_bill_lines", schema=None) as batch_op:
        batch_op.add_column(sa.Column("tax_code_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key("fk_purchase_bill_lines_tax_code_id", "tax_codes", ["tax_code_id"], ["id"])
        batch_op.create_index("ix_purchase_bill_lines_tax_code_id", ["tax_code_id"], unique=False)


def downgrade():
    with op.batch_alter_table("purchase_bill_lines", schema=None) as batch_op:
        batch_op.drop_index("ix_purchase_bill_lines_tax_code_id")
        batch_op.drop_constraint("fk_purchase_bill_lines_tax_code_id", type_="foreignkey")
        batch_op.drop_column("tax_code_id")

    with op.batch_alter_table("sales_invoice_lines", schema=None) as batch_op:
        batch_op.drop_index("ix_sales_invoice_lines_tax_code_id")
        batch_op.drop_constraint("fk_sales_invoice_lines_tax_code_id", type_="foreignkey")
        batch_op.drop_column("tax_code_id")

    op.drop_index("ix_tax_codes_is_active", table_name="tax_codes")
    op.drop_index("ix_tax_codes_purchase_tax_account_id", table_name="tax_codes")
    op.drop_index("ix_tax_codes_sales_tax_account_id", table_name="tax_codes")
    op.drop_index("ix_tax_codes_scope", table_name="tax_codes")
    op.drop_index("ix_tax_codes_treatment", table_name="tax_codes")
    op.drop_index("ix_tax_codes_code", table_name="tax_codes")
    op.drop_index("ix_tax_codes_organisation_id", table_name="tax_codes")
    op.drop_table("tax_codes")
    op.drop_index("ix_tax_profiles_organisation_id", table_name="tax_profiles")
    op.drop_table("tax_profiles")
