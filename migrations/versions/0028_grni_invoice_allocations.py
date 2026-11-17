"""Track supplier-invoice allocations against GRN lines.

Revision ID: 0028_grni_invoice_alloc
Revises: 0027_commercial_acc_events
"""
from alembic import op
import sqlalchemy as sa

revision = "0028_grni_invoice_alloc"
down_revision = "0027_commercial_acc_events"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "grni_invoice_allocations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organisation_id", sa.String(36),
                  sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("bill_id", sa.String(36),
                  sa.ForeignKey("purchase_bills.id"), nullable=False),
        sa.Column("clearing_journal_id", sa.String(36),
                  sa.ForeignKey("journals.id"), nullable=False),
        sa.Column("receipt_line_id", sa.String(36),
                  sa.ForeignKey("commercial_document_lines.id"), nullable=False),
        sa.Column("order_line_id", sa.String(36), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("accrual_value", sa.Numeric(18, 2), nullable=False),
        sa.Column("invoice_net_value", sa.Numeric(18, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organisation_id", "bill_id", "receipt_line_id",
                            name="uq_grni_bill_receipt_line"),
        sa.CheckConstraint("quantity > 0", name="ck_grni_allocation_quantity_positive"),
        sa.CheckConstraint("accrual_value >= 0", name="ck_grni_allocation_accrual_nonnegative"),
        sa.CheckConstraint("invoice_net_value >= 0", name="ck_grni_allocation_invoice_nonnegative"),
    )
    for field in ("organisation_id", "bill_id", "clearing_journal_id", "receipt_line_id", "order_line_id"):
        op.create_index("ix_grni_invoice_allocations_" + field,
                        "grni_invoice_allocations", [field])


def downgrade():
    for field in ("order_line_id", "receipt_line_id", "clearing_journal_id", "bill_id", "organisation_id"):
        op.drop_index("ix_grni_invoice_allocations_" + field,
                      table_name="grni_invoice_allocations")
    op.drop_table("grni_invoice_allocations")
