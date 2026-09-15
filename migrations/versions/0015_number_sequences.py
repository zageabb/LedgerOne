"""Add controlled numbering sequences and allocation history.

Revision ID: 0015_number_sequences
Revises: 0014_workflow_engine
Create Date: 2026-09-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0015_number_sequences"
down_revision: Union[str, None] = "0014_workflow_engine"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "number_sequences",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("sequence_key", sa.String(length=80), nullable=False),
        sa.Column("prefix", sa.String(length=40), nullable=False),
        sa.Column("suffix", sa.String(length=40), nullable=False),
        sa.Column("starting_value", sa.Integer(), nullable=False),
        sa.Column("padding", sa.Integer(), nullable=False),
        sa.Column("reset_policy", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organisation_id", "sequence_key", name="uq_number_sequence_org_key"),
    )
    op.create_index("ix_number_sequences_organisation_id", "number_sequences", ["organisation_id"], unique=False)
    op.create_index("ix_number_sequences_sequence_key", "number_sequences", ["sequence_key"], unique=False)

    op.create_table(
        "number_sequence_counters",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("sequence_id", sa.String(length=36), nullable=False),
        sa.Column("reset_key", sa.String(length=20), nullable=False),
        sa.Column("next_value", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.ForeignKeyConstraint(["sequence_id"], ["number_sequences.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sequence_id", "reset_key", name="uq_number_sequence_counter_period"),
    )
    op.create_index("ix_number_sequence_counters_organisation_id", "number_sequence_counters", ["organisation_id"], unique=False)
    op.create_index("ix_number_sequence_counters_sequence_id", "number_sequence_counters", ["sequence_id"], unique=False)
    op.create_index("ix_number_sequence_counters_reset_key", "number_sequence_counters", ["reset_key"], unique=False)

    op.create_table(
        "number_allocations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("sequence_id", sa.String(length=36), nullable=False),
        sa.Column("sequence_key", sa.String(length=80), nullable=False),
        sa.Column("reset_key", sa.String(length=20), nullable=False),
        sa.Column("sequence_value", sa.Integer(), nullable=True),
        sa.Column("formatted_number", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("entity_type", sa.String(length=80), nullable=True),
        sa.Column("entity_id", sa.String(length=36), nullable=True),
        sa.Column("manual_override", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("allocated_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("allocated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.ForeignKeyConstraint(["sequence_id"], ["number_sequences.id"]),
        sa.ForeignKeyConstraint(["allocated_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "sequence_id", "reset_key", "sequence_value", name="uq_number_allocation_sequence_value"
        ),
        sa.UniqueConstraint(
            "organisation_id", "sequence_key", "formatted_number", name="uq_number_allocation_formatted"
        ),
    )
    op.create_index("ix_number_allocations_organisation_id", "number_allocations", ["organisation_id"], unique=False)
    op.create_index("ix_number_allocations_sequence_id", "number_allocations", ["sequence_id"], unique=False)
    op.create_index("ix_number_allocations_sequence_key", "number_allocations", ["sequence_key"], unique=False)
    op.create_index("ix_number_allocations_reset_key", "number_allocations", ["reset_key"], unique=False)
    op.create_index("ix_number_allocations_formatted_number", "number_allocations", ["formatted_number"], unique=False)
    op.create_index("ix_number_allocations_status", "number_allocations", ["status"], unique=False)
    op.create_index("ix_number_allocations_issue_date", "number_allocations", ["issue_date"], unique=False)
    op.create_index("ix_number_allocations_entity_type", "number_allocations", ["entity_type"], unique=False)
    op.create_index("ix_number_allocations_entity_id", "number_allocations", ["entity_id"], unique=False)


def downgrade():
    op.drop_index("ix_number_allocations_entity_id", table_name="number_allocations")
    op.drop_index("ix_number_allocations_entity_type", table_name="number_allocations")
    op.drop_index("ix_number_allocations_issue_date", table_name="number_allocations")
    op.drop_index("ix_number_allocations_status", table_name="number_allocations")
    op.drop_index("ix_number_allocations_formatted_number", table_name="number_allocations")
    op.drop_index("ix_number_allocations_reset_key", table_name="number_allocations")
    op.drop_index("ix_number_allocations_sequence_key", table_name="number_allocations")
    op.drop_index("ix_number_allocations_sequence_id", table_name="number_allocations")
    op.drop_index("ix_number_allocations_organisation_id", table_name="number_allocations")
    op.drop_table("number_allocations")

    op.drop_index("ix_number_sequence_counters_reset_key", table_name="number_sequence_counters")
    op.drop_index("ix_number_sequence_counters_sequence_id", table_name="number_sequence_counters")
    op.drop_index("ix_number_sequence_counters_organisation_id", table_name="number_sequence_counters")
    op.drop_table("number_sequence_counters")

    op.drop_index("ix_number_sequences_sequence_key", table_name="number_sequences")
    op.drop_index("ix_number_sequences_organisation_id", table_name="number_sequences")
    op.drop_table("number_sequences")
