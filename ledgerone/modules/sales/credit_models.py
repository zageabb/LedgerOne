from ledgerone.extensions import db
from ledgerone.models.core import new_id, utcnow


def _credit_tax_point_default(context):
    return context.get_current_parameters().get("credit_date")


class SalesCreditNote(db.Model):
    __tablename__ = "sales_credit_notes"
    __table_args__ = (
        db.UniqueConstraint("organisation_id", "credit_number", name="uq_sales_credit_org_number"),
    )

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(db.String(36), db.ForeignKey("organisations.id"), nullable=False, index=True)
    customer_id = db.Column(db.String(36), db.ForeignKey("customers.id"), nullable=False, index=True)
    invoice_id = db.Column(db.String(36), db.ForeignKey("sales_invoices.id"), nullable=False, index=True)
    credit_number = db.Column(db.String(120), nullable=False, index=True)
    credit_date = db.Column(db.Date, nullable=False, index=True)
    tax_point = db.Column(db.Date, nullable=False, index=True, default=_credit_tax_point_default)
    description = db.Column(db.String(500), nullable=False)
    currency = db.Column(db.String(3), nullable=False, default="GBP")
    status = db.Column(db.String(30), nullable=False, default="posted", index=True)
    subtotal = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    tax_total = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    total = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    posted_journal_id = db.Column(db.String(36), db.ForeignKey("journals.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    customer = db.relationship("Customer")
    invoice = db.relationship("SalesInvoice")
    posted_journal = db.relationship("Journal")
