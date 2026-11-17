"""Company-scoped commercial documents linked to existing purchase/sales orders.

Document lines retain quantities and original order-line IDs. Issued documents
are append-only and superseded with new revisions rather than being overwritten.
"""
from ledgerone.extensions import db
from ledgerone.models.core import new_id, utcnow


class CommercialDocument(db.Model):
    __tablename__ = "commercial_documents"
    __table_args__ = (
        db.UniqueConstraint("organisation_id", "document_type", "document_number",
                            name="uq_commercial_document_org_type_number"),
        db.UniqueConstraint("organisation_id", "document_type", "order_id", "revision",
                            name="uq_commercial_document_order_revision"),
    )

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(db.String(36), db.ForeignKey("organisations.id"),
                                nullable=False, index=True)
    document_type = db.Column(db.String(32), nullable=False, index=True)
    order_id = db.Column(db.String(36), nullable=False, index=True)
    document_number = db.Column(db.String(120), nullable=False)
    revision = db.Column(db.Integer, nullable=False, default=1)
    document_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(24), nullable=False, default="issued")
    external_reference = db.Column(db.String(120), nullable=True)
    response_status = db.Column(db.String(32), nullable=True)
    confirmed_date = db.Column(db.Date, nullable=True)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)
    issued_by_user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    lines = db.relationship("CommercialDocumentLine", back_populates="document",
                            cascade="all, delete-orphan", lazy="selectin")


class CommercialDocumentLine(db.Model):
    __tablename__ = "commercial_document_lines"
    __table_args__ = (
        db.UniqueConstraint("document_id", "order_line_id",
                            name="uq_commercial_document_line_order_line"),
    )

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    document_id = db.Column(db.String(36), db.ForeignKey("commercial_documents.id", ondelete="CASCADE"),
                            nullable=False, index=True)
    order_line_id = db.Column(db.String(36), nullable=False, index=True)
    line_number = db.Column(db.Integer, nullable=False)
    description = db.Column(db.String(500), nullable=False)
    quantity = db.Column(db.Numeric(18, 4), nullable=False)
    unit_price = db.Column(db.Numeric(18, 4), nullable=False)
    expected_date = db.Column(db.Date, nullable=True)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)

    document = db.relationship("CommercialDocument", back_populates="lines")


class CommercialContactRoute(db.Model):
    """A named purpose (ORDERS, ACCOUNTS, LOGISTICS) for a company party."""
    __tablename__ = "commercial_contact_routes"
    __table_args__ = (
        db.UniqueConstraint("organisation_id", "party_type", "party_id", "purpose", "email",
                            name="uq_commercial_contact_route"),
    )

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(db.String(36), db.ForeignKey("organisations.id"),
                                nullable=False, index=True)
    party_type = db.Column(db.String(12), nullable=False)
    party_id = db.Column(db.String(36), nullable=False, index=True)
    purpose = db.Column(db.String(40), nullable=False, index=True)
    email = db.Column(db.String(255), nullable=False)
    contact_name = db.Column(db.String(160))
    is_active = db.Column(db.Boolean(), nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class CommercialMessageDraft(db.Model):
    """A document-linked outgoing draft; no external sending implied."""
    __tablename__ = "commercial_message_drafts"
    __table_args__ = (
        db.UniqueConstraint("organisation_id", "idempotency_key",
                            name="uq_commercial_message_draft_idempotency"),
    )

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(db.String(36), db.ForeignKey("organisations.id"),
                                nullable=False, index=True)
    document_id = db.Column(db.String(36), db.ForeignKey("commercial_documents.id"),
                            nullable=False, index=True)
    purpose = db.Column(db.String(40), nullable=False)
    recipients_json = db.Column(db.JSON(), nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text(), nullable=False)
    status = db.Column(db.String(24), nullable=False, default="draft")
    idempotency_key = db.Column(db.String(120), nullable=False)
    created_by_user_id = db.Column(db.String(36), db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class CommercialAccountingEvent(db.Model):
    """Uniquely associates a commercial event with its accounting journal.

    The database uniqueness constraints are the final retry guard. A committed
    GRN may never silently create a second inventory accrual.
    """
    __tablename__ = "commercial_accounting_events"
    __table_args__ = (
        db.UniqueConstraint("organisation_id", "document_id", "event_type",
                            name="uq_commercial_accounting_one_event"),
        db.UniqueConstraint("journal_id", name="uq_commercial_accounting_journal"),
    )

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(db.String(36), db.ForeignKey("organisations.id"),
                                nullable=False, index=True)
    document_id = db.Column(db.String(36), db.ForeignKey("commercial_documents.id"),
                            nullable=False, index=True)
    event_type = db.Column(db.String(40), nullable=False)
    journal_id = db.Column(db.String(36), db.ForeignKey("journals.id"),
                           nullable=False)
    posted_value = db.Column(db.Numeric(18, 2), nullable=False)
    metadata_json = db.Column(db.JSON(), nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    document = db.relationship("CommercialDocument")
    journal = db.relationship("Journal")


class GRNIInvoiceAllocation(db.Model):
    """A posted supplier-bill line's allocation to one received stock line.

    Allocation rows will only be created by a future atomic bill-clearing
    service, not by a preview or a generic supplier bill.
    """
    __tablename__ = "grni_invoice_allocations"
    __table_args__ = (
        db.UniqueConstraint("organisation_id", "bill_id", "receipt_line_id",
                            name="uq_grni_bill_receipt_line"),
    )

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(db.String(36), db.ForeignKey("organisations.id"),
                                nullable=False, index=True)
    bill_id = db.Column(db.String(36), db.ForeignKey("purchase_bills.id"),
                        nullable=False, index=True)
    clearing_journal_id = db.Column(db.String(36), db.ForeignKey("journals.id"),
                                    nullable=False, index=True)
    receipt_line_id = db.Column(db.String(36),
                                db.ForeignKey("commercial_document_lines.id"),
                                nullable=False, index=True)
    order_line_id = db.Column(db.String(36), nullable=False, index=True)
    quantity = db.Column(db.Numeric(18, 4), nullable=False)
    accrual_value = db.Column(db.Numeric(18, 2), nullable=False)
    invoice_net_value = db.Column(db.Numeric(18, 2), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    bill = db.relationship("PurchaseBill")
    clearing_journal = db.relationship("Journal")
    receipt_line = db.relationship("CommercialDocumentLine")
