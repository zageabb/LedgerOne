"""Add source documents.

Revision ID: 0005_source_documents
Revises: 0004_payment_allocations
Create Date: 2026-09-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005_source_documents"
down_revision: Union[str, None] = "0004_payment_allocations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "source_documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("module_id", sa.String(length=80), nullable=False),
        sa.Column("entity_type", sa.String(length=80), nullable=False),
        sa.Column("entity_id", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("storage_key", sa.String(length=500), nullable=True),
        sa.Column("reference_url", sa.String(length=1000), nullable=True),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("uploaded_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.ForeignKeyConstraint(["uploaded_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index("ix_source_documents_organisation_id", "source_documents", ["organisation_id"], unique=False)
    op.create_index("ix_source_documents_module_id", "source_documents", ["module_id"], unique=False)
    op.create_index("ix_source_documents_entity_type", "source_documents", ["entity_type"], unique=False)
    op.create_index("ix_source_documents_entity_id", "source_documents", ["entity_id"], unique=False)
    op.create_index("ix_source_documents_kind", "source_documents", ["kind"], unique=False)
    op.create_index("ix_source_documents_sha256", "source_documents", ["sha256"], unique=False)
    op.create_index("ix_source_documents_created_at", "source_documents", ["created_at"], unique=False)
    op.create_index(
        "ix_source_documents_entity",
        "source_documents",
        ["organisation_id", "entity_type", "entity_id"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_source_documents_entity", table_name="source_documents")
    op.drop_index("ix_source_documents_created_at", table_name="source_documents")
    op.drop_index("ix_source_documents_sha256", table_name="source_documents")
    op.drop_index("ix_source_documents_kind", table_name="source_documents")
    op.drop_index("ix_source_documents_entity_id", table_name="source_documents")
    op.drop_index("ix_source_documents_entity_type", table_name="source_documents")
    op.drop_index("ix_source_documents_module_id", table_name="source_documents")
    op.drop_index("ix_source_documents_organisation_id", table_name="source_documents")
    op.drop_table("source_documents")
