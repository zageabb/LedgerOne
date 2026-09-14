"""Add accounting periods.

Revision ID: 0002_accounting_periods
Revises: 0001_initial
Create Date: 2026-09-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_accounting_periods"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "accounting_periods",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["locked_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organisation_id",
            "start_date",
            "end_date",
            name="uq_accounting_period_org_dates",
        ),
    )
    op.create_index(
        "ix_accounting_periods_organisation_id",
        "accounting_periods",
        ["organisation_id"],
        unique=False,
    )
    op.create_index(
        "ix_accounting_periods_start_date",
        "accounting_periods",
        ["start_date"],
        unique=False,
    )
    op.create_index(
        "ix_accounting_periods_end_date",
        "accounting_periods",
        ["end_date"],
        unique=False,
    )
    op.create_index(
        "ix_accounting_periods_status",
        "accounting_periods",
        ["status"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_accounting_periods_status", table_name="accounting_periods")
    op.drop_index("ix_accounting_periods_end_date", table_name="accounting_periods")
    op.drop_index("ix_accounting_periods_start_date", table_name="accounting_periods")
    op.drop_index("ix_accounting_periods_organisation_id", table_name="accounting_periods")
    op.drop_table("accounting_periods")
