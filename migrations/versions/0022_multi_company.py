"""Add company profile metadata to existing organisations.

Revision ID: 0022_multi_company
Revises: 0021_bank_reconciliations
"""
from alembic import op
import sqlalchemy as sa

revision = "0022_multi_company"
down_revision = "0021_bank_reconciliations"
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table("organisations") as batch:
        batch.add_column(sa.Column("company_code", sa.String(20), nullable=True))
        batch.add_column(sa.Column("trading_name", sa.String(255), nullable=True))
        batch.add_column(sa.Column("registration_number", sa.String(60), nullable=True))
        batch.add_column(sa.Column("vat_number", sa.String(60), nullable=True))
        batch.add_column(sa.Column("registered_address", sa.JSON(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.create_index("ix_organisations_company_code", ["company_code"], unique=True)

def downgrade():
    with op.batch_alter_table("organisations") as batch:
        batch.drop_index("ix_organisations_company_code")
        for column in ("is_active", "registered_address", "vat_number",
                       "registration_number", "trading_name", "company_code"):
            batch.drop_column(column)
