"""ERP-000 commercial documents and linked quantity lines.

Revision ID: 0025_commercial_documents
Revises: 0024_workflow_roles
"""
from alembic import op
import sqlalchemy as sa

revision = "0025_commercial_documents"
down_revision = "0024_workflow_roles"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "commercial_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organisation_id", sa.String(36), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("document_type", sa.String(32), nullable=False),
        sa.Column("order_id", sa.String(36), nullable=False),
        sa.Column("document_number", sa.String(120), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("document_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("external_reference", sa.String(120)),
        sa.Column("response_status", sa.String(32)),
        sa.Column("confirmed_date", sa.Date()),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("issued_by_user_id", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organisation_id", "document_type", "document_number",
                            name="uq_commercial_document_org_type_number"),
        sa.UniqueConstraint("organisation_id", "document_type", "order_id", "revision",
                            name="uq_commercial_document_order_revision"),
    )
    for column in ("organisation_id", "document_type", "order_id"):
        op.create_index("ix_commercial_documents_" + column, "commercial_documents", [column])
    op.create_table(
        "commercial_document_lines",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.String(36),
                  sa.ForeignKey("commercial_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_line_id", sa.String(36), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 4), nullable=False),
        sa.Column("expected_date", sa.Date()),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.UniqueConstraint("document_id", "order_line_id",
                            name="uq_commercial_document_line_order_line"),
    )
    op.create_index("ix_commercial_document_lines_document_id",
                    "commercial_document_lines", ["document_id"])
    op.create_index("ix_commercial_document_lines_order_line_id",
                    "commercial_document_lines", ["order_line_id"])


def downgrade():
    op.drop_index("ix_commercial_document_lines_order_line_id",
                  table_name="commercial_document_lines")
    op.drop_index("ix_commercial_document_lines_document_id",
                  table_name="commercial_document_lines")
    op.drop_table("commercial_document_lines")
    for column in ("order_id", "document_type", "organisation_id"):
        op.drop_index("ix_commercial_documents_" + column, table_name="commercial_documents")
    op.drop_table("commercial_documents")
