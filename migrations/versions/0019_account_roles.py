"""Constrain ledger account classifications.

Revision ID: 0019_account_roles
Revises: 0018_credit_refunds
Create Date: 2026-10-03
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0019_account_roles"
down_revision: Union[str, None] = "0018_credit_refunds"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.create_check_constraint(
            "ck_accounts_account_type",
            "account_type IN ('asset','liability','equity','income','expense')",
        )


def downgrade():
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.drop_constraint("ck_accounts_account_type", type_="check")
