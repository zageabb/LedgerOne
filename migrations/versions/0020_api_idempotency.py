"""Add API idempotency records.

Revision ID: 0020_api_idempotency
Revises: 0019_account_roles
Create Date: 2026-10-03
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0020_api_idempotency"
down_revision: Union[str, None] = "0019_account_roles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("operation", sa.String(length=160), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("source_system", sa.String(length=120), nullable=True),
        sa.Column("source_reference", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_json", sa.JSON(), nullable=True),
        sa.Column("result_entity_type", sa.String(length=120), nullable=True),
        sa.Column("result_entity_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organisation_id", "operation", "idempotency_key",
            name="uq_idempotency_org_operation_key",
        ),
        sa.UniqueConstraint(
            "organisation_id", "operation", "source_system", "source_reference",
            name="uq_idempotency_org_operation_source",
        ),
    )
    op.create_index("ix_idempotency_records_organisation_id", "idempotency_records", ["organisation_id"], unique=False)
    op.create_index("ix_idempotency_records_operation", "idempotency_records", ["operation"], unique=False)
    op.create_index("ix_idempotency_records_status", "idempotency_records", ["status"], unique=False)
    op.create_index("ix_idempotency_records_expires_at", "idempotency_records", ["expires_at"], unique=False)


def downgrade():
    op.drop_index("ix_idempotency_records_expires_at", table_name="idempotency_records")
    op.drop_index("ix_idempotency_records_status", table_name="idempotency_records")
    op.drop_index("ix_idempotency_records_operation", table_name="idempotency_records")
    op.drop_index("ix_idempotency_records_organisation_id", table_name="idempotency_records")
    op.drop_table("idempotency_records")
