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
