"""Add VAT tax points, return periods and adjustments.

Revision ID: 0016_vat_return_lifecycle
Revises: 0015_number_sequences
Create Date: 2026-09-18
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0016_vat_return_lifecycle"
down_revision: Union[str, None] = "0015_number_sequences"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_tax_point(table_name: str, date_column: str):
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.add_column(sa.Column("tax_point", sa.Date(), nullable=True))
    op.execute(
        sa.text(
            f"UPDATE {table_name} SET tax_point = {date_column} WHERE tax_point IS NULL"
        )
    )
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.alter_column("tax_point", existing_type=sa.Date(), nullable=False)
        batch_op.create_index(f"ix_{table_name}_tax_point", ["tax_point"], unique=False)


def upgrade():
    _add_tax_point("sales_invoices", "invoice_date")
    _add_tax_point("purchase_bills", "bill_date")
    _add_tax_point("sales_credit_notes", "credit_date")
    _add_tax_point("purchase_credit_notes", "credit_date")

    op.create_table(
        "vat_return_periods",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("finalised_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("finalised_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submission_reference", sa.String(length=160), nullable=True),
        sa.Column("submission_note", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.ForeignKeyConstraint(["finalised_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["submitted_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organisation_id", "start_date", "end_date",
            name="uq_vat_return_period_org_dates",
        ),
    )
    op.create_index(
        "ix_vat_return_periods_organisation_id",
        "vat_return_periods", ["organisation_id"], unique=False,
    )
    op.create_index("ix_vat_return_periods_start_date", "vat_return_periods", ["start_date"], unique=False)
    op.create_index("ix_vat_return_periods_end_date", "vat_return_periods", ["end_date"], unique=False)
    op.create_index("ix_vat_return_periods_status", "vat_return_periods", ["status"], unique=False)

    op.create_table(
        "vat_adjustments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("tax_point", sa.Date(), nullable=False),
        sa.Column("box_number", sa.String(length=2), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("evidence_reference", sa.String(length=500), nullable=True),
        sa.Column("return_period_id", sa.String(length=36), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.ForeignKeyConstraint(["return_period_id"], ["vat_return_periods.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_vat_adjustments_organisation_id", "vat_adjustments", ["organisation_id"], unique=False)
    op.create_index("ix_vat_adjustments_tax_point", "vat_adjustments", ["tax_point"], unique=False)
    op.create_index("ix_vat_adjustments_box_number", "vat_adjustments", ["box_number"], unique=False)
    op.create_index("ix_vat_adjustments_return_period_id", "vat_adjustments", ["return_period_id"], unique=False)


def downgrade():
    op.drop_index("ix_vat_adjustments_return_period_id", table_name="vat_adjustments")
    op.drop_index("ix_vat_adjustments_box_number", table_name="vat_adjustments")
    op.drop_index("ix_vat_adjustments_tax_point", table_name="vat_adjustments")
    op.drop_index("ix_vat_adjustments_organisation_id", table_name="vat_adjustments")
    op.drop_table("vat_adjustments")

    op.drop_index("ix_vat_return_periods_status", table_name="vat_return_periods")
    op.drop_index("ix_vat_return_periods_end_date", table_name="vat_return_periods")
    op.drop_index("ix_vat_return_periods_start_date", table_name="vat_return_periods")
    op.drop_index("ix_vat_return_periods_organisation_id", table_name="vat_return_periods")
    op.drop_table("vat_return_periods")

    for table_name in (
        "purchase_credit_notes",
        "sales_credit_notes",
        "purchase_bills",
        "sales_invoices",
    ):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_index(f"ix_{table_name}_tax_point")
            batch_op.drop_column("tax_point")
