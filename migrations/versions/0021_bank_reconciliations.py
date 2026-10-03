"""Add formal bank reconciliations.

Revision ID: 0021_bank_reconciliations
Revises: 0020_api_idempotency
Create Date: 2026-10-03
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0021_bank_reconciliations"
down_revision: Union[str, None] = "0020_api_idempotency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "bank_reconciliations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("bank_account_id", sa.String(length=36), nullable=False),
        sa.Column("statement_start_date", sa.Date(), nullable=False),
        sa.Column("statement_end_date", sa.Date(), nullable=False),
        sa.Column("statement_opening_balance", sa.Numeric(18, 2), nullable=False),
        sa.Column("statement_closing_balance", sa.Numeric(18, 2), nullable=False),
        sa.Column("ledger_balance", sa.Numeric(18, 2), nullable=False),
        sa.Column("unmatched_statement_total", sa.Numeric(18, 2), nullable=False),
        sa.Column("outstanding_book_total", sa.Numeric(18, 2), nullable=False),
        sa.Column("explained_difference", sa.Numeric(18, 2), nullable=False),
        sa.Column("residual_difference", sa.Numeric(18, 2), nullable=False),
        sa.Column("explanation", sa.String(length=2000), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("prepared_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("approved_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("prepared_identity", sa.String(length=120), nullable=True),
        sa.Column("approved_identity", sa.String(length=120), nullable=True),
        sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalised_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.ForeignKeyConstraint(["bank_account_id"], ["bank_accounts.id"]),
        sa.ForeignKeyConstraint(["prepared_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bank_reconciliations_organisation_id", "bank_reconciliations", ["organisation_id"])
    op.create_index("ix_bank_reconciliations_bank_account_id", "bank_reconciliations", ["bank_account_id"])
    op.create_index("ix_bank_reconciliations_statement_end_date", "bank_reconciliations", ["statement_end_date"])
    op.create_index("ix_bank_reconciliations_status", "bank_reconciliations", ["status"])


def downgrade():
    op.drop_index("ix_bank_reconciliations_status", table_name="bank_reconciliations")
    op.drop_index("ix_bank_reconciliations_statement_end_date", table_name="bank_reconciliations")
    op.drop_index("ix_bank_reconciliations_bank_account_id", table_name="bank_reconciliations")
    op.drop_index("ix_bank_reconciliations_organisation_id", table_name="bank_reconciliations")
    op.drop_table("bank_reconciliations")
