"""Add opening balances and recurring journals.

Revision ID: 0003_opening_balances_recurring
Revises: 0002_accounting_periods
Create Date: 2026-09-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_opening_balances_recurring"
down_revision: Union[str, None] = "0002_accounting_periods"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "opening_balance_batches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("reference", sa.String(length=120), nullable=True),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("balancing_account_id", sa.String(length=36), nullable=True),
        sa.Column("journal_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["balancing_account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["journal_id"], ["journals.id"]),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("journal_id"),
    )
    op.create_index(
        "ix_opening_balance_batches_organisation_id",
        "opening_balance_batches",
        ["organisation_id"],
        unique=False,
    )
    op.create_index(
        "ix_opening_balance_batches_as_of_date",
        "opening_balance_batches",
        ["as_of_date"],
        unique=False,
    )

    op.create_table(
        "recurring_journals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("reference", sa.String(length=120), nullable=True),
        sa.Column("frequency", sa.String(length=20), nullable=False),
        sa.Column("next_run_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("template_lines", sa.JSON(), nullable=False),
        sa.Column("last_run_date", sa.Date(), nullable=True),
        sa.Column("run_count", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_recurring_journals_organisation_id",
        "recurring_journals",
        ["organisation_id"],
        unique=False,
    )
    op.create_index(
        "ix_recurring_journals_frequency",
        "recurring_journals",
        ["frequency"],
        unique=False,
    )
    op.create_index(
        "ix_recurring_journals_next_run_date",
        "recurring_journals",
        ["next_run_date"],
        unique=False,
    )
    op.create_index(
        "ix_recurring_journals_is_active",
        "recurring_journals",
        ["is_active"],
        unique=False,
    )

    op.create_table(
        "recurring_journal_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("recurring_journal_id", sa.String(length=36), nullable=False),
        sa.Column("scheduled_date", sa.Date(), nullable=False),
        sa.Column("journal_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["recurring_journal_id"],
            ["recurring_journals.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["journal_id"], ["journals.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("journal_id"),
        sa.UniqueConstraint(
            "recurring_journal_id",
            "scheduled_date",
            name="uq_recurring_journal_scheduled_date",
        ),
    )
    op.create_index(
        "ix_recurring_journal_runs_recurring_journal_id",
        "recurring_journal_runs",
        ["recurring_journal_id"],
        unique=False,
    )
    op.create_index(
        "ix_recurring_journal_runs_scheduled_date",
        "recurring_journal_runs",
        ["scheduled_date"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_recurring_journal_runs_scheduled_date", table_name="recurring_journal_runs")
    op.drop_index("ix_recurring_journal_runs_recurring_journal_id", table_name="recurring_journal_runs")
    op.drop_table("recurring_journal_runs")

    op.drop_index("ix_recurring_journals_is_active", table_name="recurring_journals")
    op.drop_index("ix_recurring_journals_next_run_date", table_name="recurring_journals")
    op.drop_index("ix_recurring_journals_frequency", table_name="recurring_journals")
    op.drop_index("ix_recurring_journals_organisation_id", table_name="recurring_journals")
    op.drop_table("recurring_journals")

    op.drop_index("ix_opening_balance_batches_as_of_date", table_name="opening_balance_batches")
    op.drop_index("ix_opening_balance_batches_organisation_id", table_name="opening_balance_batches")
    op.drop_table("opening_balance_batches")
