"""Add AI conversations, requester attribution and organisation Knowledge.

Revision ID: 0013_ai_workspace_knowledge
Revises: 0012_sales_orders
Create Date: 2026-09-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0013_ai_workspace_knowledge"
down_revision: Union[str, None] = "0012_sales_orders"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "ai_conversations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("owner_identity_type", sa.String(length=32), nullable=False),
        sa.Column("owner_identity_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_conversations_organisation_id", "ai_conversations", ["organisation_id"], unique=False)
    op.create_index("ix_ai_conversations_owner_identity_id", "ai_conversations", ["owner_identity_id"], unique=False)
    op.create_index("ix_ai_conversations_created_at", "ai_conversations", ["created_at"], unique=False)
    op.create_index("ix_ai_conversations_updated_at", "ai_conversations", ["updated_at"], unique=False)

    with op.batch_alter_table("ai_interactions") as batch_op:
        batch_op.add_column(sa.Column("conversation_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("requester_type", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("requester_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("knowledge_log", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
        batch_op.create_foreign_key(
            "fk_ai_interactions_conversation_id_ai_conversations",
            "ai_conversations",
            ["conversation_id"],
            ["id"],
        )
        batch_op.create_index("ix_ai_interactions_conversation_id", ["conversation_id"], unique=False)
        batch_op.create_index("ix_ai_interactions_requester_id", ["requester_id"], unique=False)

    op.create_table(
        "ai_knowledge_sources",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=True),
        sa.Column("media_type", sa.String(length=120), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("uploaded_by_type", sa.String(length=32), nullable=True),
        sa.Column("uploaded_by_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_knowledge_sources_organisation_id", "ai_knowledge_sources", ["organisation_id"], unique=False)
    op.create_index("ix_ai_knowledge_sources_enabled", "ai_knowledge_sources", ["enabled"], unique=False)
    op.create_index("ix_ai_knowledge_sources_status", "ai_knowledge_sources", ["status"], unique=False)
    op.create_index("ix_ai_knowledge_sources_created_at", "ai_knowledge_sources", ["created_at"], unique=False)
    op.create_index("ix_ai_knowledge_sources_updated_at", "ai_knowledge_sources", ["updated_at"], unique=False)

    op.create_table(
        "ai_knowledge_chunks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["ai_knowledge_sources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_knowledge_chunks_organisation_id", "ai_knowledge_chunks", ["organisation_id"], unique=False)
    op.create_index("ix_ai_knowledge_chunks_source_id", "ai_knowledge_chunks", ["source_id"], unique=False)


def downgrade():
    op.drop_index("ix_ai_knowledge_chunks_source_id", table_name="ai_knowledge_chunks")
    op.drop_index("ix_ai_knowledge_chunks_organisation_id", table_name="ai_knowledge_chunks")
    op.drop_table("ai_knowledge_chunks")

    op.drop_index("ix_ai_knowledge_sources_updated_at", table_name="ai_knowledge_sources")
    op.drop_index("ix_ai_knowledge_sources_created_at", table_name="ai_knowledge_sources")
    op.drop_index("ix_ai_knowledge_sources_status", table_name="ai_knowledge_sources")
    op.drop_index("ix_ai_knowledge_sources_enabled", table_name="ai_knowledge_sources")
    op.drop_index("ix_ai_knowledge_sources_organisation_id", table_name="ai_knowledge_sources")
    op.drop_table("ai_knowledge_sources")

    with op.batch_alter_table("ai_interactions") as batch_op:
        batch_op.drop_index("ix_ai_interactions_requester_id")
        batch_op.drop_index("ix_ai_interactions_conversation_id")
        batch_op.drop_constraint("fk_ai_interactions_conversation_id_ai_conversations", type_="foreignkey")
        batch_op.drop_column("knowledge_log")
        batch_op.drop_column("requester_id")
        batch_op.drop_column("requester_type")
        batch_op.drop_column("conversation_id")

    op.drop_index("ix_ai_conversations_updated_at", table_name="ai_conversations")
    op.drop_index("ix_ai_conversations_created_at", table_name="ai_conversations")
    op.drop_index("ix_ai_conversations_owner_identity_id", table_name="ai_conversations")
    op.drop_index("ix_ai_conversations_organisation_id", table_name="ai_conversations")
    op.drop_table("ai_conversations")
