"""Supplier bill line to GRN line allocations (storage only, no posting).

Revision ID: 0028_bill_receipt_alloc
Revises: 0027_commercial_acc_events
"""
from alembic import op
import sqlalchemy as sa

revision = "0028_bill_receipt_alloc"
down_revision = "0027_commercial_acc_events"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "purchase_receipt_bill_allocations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organisation_id", sa.String(36),
                  sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("purchase_order_line_id", sa.String(36),
                  sa.ForeignKey("purchase_order_lines.id"), nullable=False),
        sa.Column("receipt_line_id", sa.String(36),
                  sa.ForeignKey("commercial_document_lines.id"), nullable=False),
        sa.Column("bill_line_id", sa.String(36),
                  sa.ForeignKey("purchase_bill_lines.id"), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("receipt_cost", sa.Numeric(18, 2), nullable=False),
        sa.Column("invoice_net", sa.Numeric(18, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("bill_line_id", "receipt_line_id",
                            name="uq_purchase_receipt_bill_line_pair"),
        sa.CheckConstraint("quantity > 0",
                           name="ck_purchase_receipt_allocation_positive_quantity"),
        sa.CheckConstraint("receipt_cost >= 0 AND invoice_net >= 0",
                           name="ck_purchase_receipt_allocation_nonnegative_values"),
    )
    for key in ("organisation_id", "purchase_order_line_id", "receipt_line_id", "bill_line_id"):
        op.create_index(
            f"ix_purchase_receipt_bill_allocations_{key}",
            "purchase_receipt_bill_allocations", [key])


def downgrade():
    for key in ("bill_line_id", "receipt_line_id", "purchase_order_line_id", "organisation_id"):
        op.drop_index(
            f"ix_purchase_receipt_bill_allocations_{key}",
            table_name="purchase_receipt_bill_allocations")
    op.drop_table("purchase_receipt_bill_allocations")
