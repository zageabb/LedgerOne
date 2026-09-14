"""Add expense claims.

Revision ID: 0010_expense_claims
Revises: 0009_purchase_orders
Create Date: 2026-09-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0010_expense_claims"
down_revision: Union[str, None] = "0009_purchase_orders"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "expense_claims",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("claimant_user_id", sa.String(length=36), nullable=True),
        sa.Column("claimant_name", sa.String(length=255), nullable=False),
        sa.Column("claim_number", sa.String(length=120), nullable=False),
        sa.Column("claim_date", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("subtotal", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("tax_total", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("total", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("reimbursement_account_id", sa.String(length=36), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("posted_journal_id", sa.String(length=36), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.ForeignKeyConstraint(["claimant_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["reimbursement_account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["posted_journal_id"], ["journals.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organisation_id", "claim_number", name="uq_expense_claim_org_number"),
    )
    op.create_index("ix_expense_claims_organisation_id", "expense_claims", ["organisation_id"], unique=False)
    op.create_index("ix_expense_claims_claimant_user_id", "expense_claims", ["claimant_user_id"], unique=False)
    op.create_index("ix_expense_claims_claimant_name", "expense_claims", ["claimant_name"], unique=False)
    op.create_index("ix_expense_claims_claim_number", "expense_claims", ["claim_number"], unique=False)
    op.create_index("ix_expense_claims_claim_date", "expense_claims", ["claim_date"], unique=False)
    op.create_index("ix_expense_claims_status", "expense_claims", ["status"], unique=False)
    op.create_index("ix_expense_claims_posted_journal_id", "expense_claims", ["posted_journal_id"], unique=False)

    op.create_table(
        "expense_claim_lines",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("claim_id", sa.String(length=36), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("expense_date", sa.Date(), nullable=False),
        sa.Column("merchant", sa.String(length=255), nullable=True),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("net_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("tax_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("tax_code_id", sa.String(length=36), nullable=True),
        sa.Column("expense_account_id", sa.String(length=36), nullable=False),
        sa.Column("dimensions", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["claim_id"], ["expense_claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tax_code_id"], ["tax_codes.id"]),
        sa.ForeignKeyConstraint(["expense_account_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_expense_claim_lines_claim_id", "expense_claim_lines", ["claim_id"], unique=False)
    op.create_index("ix_expense_claim_lines_expense_date", "expense_claim_lines", ["expense_date"], unique=False)
    op.create_index("ix_expense_claim_lines_tax_code_id", "expense_claim_lines", ["tax_code_id"], unique=False)


def downgrade():
    op.drop_index("ix_expense_claim_lines_tax_code_id", table_name="expense_claim_lines")
    op.drop_index("ix_expense_claim_lines_expense_date", table_name="expense_claim_lines")
    op.drop_index("ix_expense_claim_lines_claim_id", table_name="expense_claim_lines")
    op.drop_table("expense_claim_lines")

    op.drop_index("ix_expense_claims_posted_journal_id", table_name="expense_claims")
    op.drop_index("ix_expense_claims_status", table_name="expense_claims")
    op.drop_index("ix_expense_claims_claim_date", table_name="expense_claims")
    op.drop_index("ix_expense_claims_claim_number", table_name="expense_claims")
    op.drop_index("ix_expense_claims_claimant_name", table_name="expense_claims")
    op.drop_index("ix_expense_claims_claimant_user_id", table_name="expense_claims")
    op.drop_index("ix_expense_claims_organisation_id", table_name="expense_claims")
    op.drop_table("expense_claims")
