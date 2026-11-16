"""Keep supplier invoice references distinct from LedgerOne bill numbers.

Revision ID: 0022_supplier_invoice_reference
Revises: 0021_bank_reconciliations
Create Date: 2026-10-13
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0022_supplier_invoice_reference"
down_revision: Union[str, None] = "0021_bank_reconciliations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    with op.batch_alter_table("purchase_bills") as batch_op:
        batch_op.add_column(sa.Column("supplier_invoice_reference", sa.String(length=120), nullable=True))
        batch_op.create_index("ix_purchase_bills_supplier_invoice_reference", ["supplier_invoice_reference"])


def downgrade():
    with op.batch_alter_table("purchase_bills") as batch_op:
        batch_op.drop_index("ix_purchase_bills_supplier_invoice_reference")
        batch_op.drop_column("supplier_invoice_reference")
