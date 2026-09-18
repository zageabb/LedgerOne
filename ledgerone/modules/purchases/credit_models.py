from ledgerone.extensions import db
from ledgerone.models.core import new_id, utcnow


class PurchaseCreditNote(db.Model):
    __tablename__ = "purchase_credit_notes"
    __table_args__ = (
        db.UniqueConstraint("organisation_id", "credit_number", name="uq_purchase_credit_org_number"),
    )

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(db.String(36), db.ForeignKey("organisations.id"), nullable=False, index=True)
    supplier_id = db.Column(db.String(36), db.ForeignKey("suppliers.id"), nullable=False, index=True)
    bill_id = db.Column(db.String(36), db.ForeignKey("purchase_bills.id"), nullable=False, index=True)
    credit_number = db.Column(db.String(120), nullable=False, index=True)
    credit_date = db.Column(db.Date, nullable=False, index=True)
    tax_point = db.Column(db.Date, nullable=False, index=True)
    description = db.Column(db.String(500), nullable=False)
    currency = db.Column(db.String(3), nullable=False, default="GBP")
    status = db.Column(db.String(30), nullable=False, default="posted", index=True)
    subtotal = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    tax_total = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    total = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    posted_journal_id = db.Column(db.String(36), db.ForeignKey("journals.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    supplier = db.relationship("Supplier")
    bill = db.relationship("PurchaseBill")
    posted_journal = db.relationship("Journal")
