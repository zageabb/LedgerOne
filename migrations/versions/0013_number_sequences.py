"""Add configurable numbering sequences.

Revision ID: 0013_number_sequences
Revises: 0012_sales_orders
Create Date: 2026-09-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0013_number_sequences"
down_revision: Union[str, None] = "0012_sales_orders"
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
        sa.Column("next_value", sa.Integer(), nullable=False),
        sa.Column("padding", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organisation_id", "sequence_key", name="uq_number_sequence_org_key"),
    )
    op.create_index(
        op.f("ix_number_sequences_organisation_id"),
        "number_sequences",
        ["organisation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_number_sequences_sequence_key"),
        "number_sequences",
        ["sequence_key"],
        unique=False,
    )


def downgrade():
    op.drop_index(op.f("ix_number_sequences_sequence_key"), table_name="number_sequences")
    op.drop_index(op.f("ix_number_sequences_organisation_id"), table_name="number_sequences")
    op.drop_table("number_sequences")
