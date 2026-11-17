"""One ledger posting per commercial document event.

Revision ID: 0027_commercial_accounting_events
Revises: 0026_commercial_contacts
"""
from alembic import op
import sqlalchemy as sa

revision = "0027_commercial_accounting_events"
down_revision = "0026_commercial_contacts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "commercial_accounting_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organisation_id", sa.String(36),
                  sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("document_id", sa.String(36),
                  sa.ForeignKey("commercial_documents.id"), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("journal_id", sa.String(36),
                  sa.ForeignKey("journals.id"), nullable=False),
        sa.Column("posted_value", sa.Numeric(18, 2), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organisation_id", "document_id", "event_type",
                            name="uq_commercial_accounting_one_event"),
        sa.UniqueConstraint("journal_id",
                            name="uq_commercial_accounting_journal"),
    )
    op.create_index("ix_commercial_accounting_events_organisation_id",
                    "commercial_accounting_events", ["organisation_id"])
    op.create_index("ix_commercial_accounting_events_document_id",
                    "commercial_accounting_events", ["document_id"])


def downgrade():
    op.drop_index("ix_commercial_accounting_events_document_id",
                  table_name="commercial_accounting_events")
    op.drop_index("ix_commercial_accounting_events_organisation_id",
                  table_name="commercial_accounting_events")
    op.drop_table("commercial_accounting_events")
