"""ERP-000 contact-purpose routing and safe email draft tables.

Revision ID: 0026_commercial_contacts
Revises: 0025_commercial_documents
"""
from alembic import op
import sqlalchemy as sa

revision = "0026_commercial_contacts"
down_revision = "0025_commercial_documents"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "commercial_contact_routes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organisation_id", sa.String(36), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("party_type", sa.String(12), nullable=False),
        sa.Column("party_id", sa.String(36), nullable=False),
        sa.Column("purpose", sa.String(40), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("contact_name", sa.String(160)),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organisation_id", "party_type", "party_id", "purpose", "email",
                            name="uq_commercial_contact_route"),
    )
    for field in ("organisation_id", "party_id", "purpose"):
        op.create_index("ix_commercial_contact_routes_" + field,
                        "commercial_contact_routes", [field])
    op.create_table(
        "commercial_message_drafts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organisation_id", sa.String(36), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("commercial_documents.id"), nullable=False),
        sa.Column("purpose", sa.String(40), nullable=False),
        sa.Column("recipients_json", sa.JSON(), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("idempotency_key", sa.String(120), nullable=False),
        sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organisation_id", "idempotency_key",
                            name="uq_commercial_message_draft_idempotency"),
    )
    op.create_index("ix_commercial_message_drafts_organisation_id",
                    "commercial_message_drafts", ["organisation_id"])
    op.create_index("ix_commercial_message_drafts_document_id",
                    "commercial_message_drafts", ["document_id"])


def downgrade():
    for field in ("document_id", "organisation_id"):
        op.drop_index("ix_commercial_message_drafts_" + field,
                      table_name="commercial_message_drafts")
    op.drop_table("commercial_message_drafts")
    for field in ("purpose", "party_id", "organisation_id"):
        op.drop_index("ix_commercial_contact_routes_" + field,
                      table_name="commercial_contact_routes")
    op.drop_table("commercial_contact_routes")
