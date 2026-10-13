"""Store supplier's source invoice reference separately from LedgerOne bill number.

Revision ID: 0022_supplier_invoice_reference
Revises: 0021_bank_reconciliations
"""

from alembic import op
import sqlalchemy as sa

revision = "0022_supplier_invoice_reference"
down_revision = "0021_bank_reconciliations"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("purchase_bills") as batch_op:
        batch_op.add_column(sa.Column("supplier_invoice_reference", sa.String(length=120), nullable=True))


def downgrade():
    with op.batch_alter_table("purchase_bills") as batch_op:
        batch_op.drop_column("supplier_invoice_reference")
