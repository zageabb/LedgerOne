"""Add contact payment term overrides.

Revision ID: 0011_payment_terms
Revises: 0010_expense_claims
Create Date: 2026-09-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0011_payment_terms"
down_revision: Union[str, None] = "0010_expense_claims"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    with op.batch_alter_table("customers") as batch_op:
        batch_op.add_column(sa.Column("payment_terms_days", sa.Integer(), nullable=True))
    with op.batch_alter_table("suppliers") as batch_op:
        batch_op.add_column(sa.Column("payment_terms_days", sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table("suppliers") as batch_op:
        batch_op.drop_column("payment_terms_days")
    with op.batch_alter_table("customers") as batch_op:
        batch_op.drop_column("payment_terms_days")
