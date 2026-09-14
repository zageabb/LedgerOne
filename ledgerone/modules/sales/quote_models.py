from ledgerone.extensions import db
from ledgerone.models.core import new_id, utcnow


class SalesQuote(db.Model):
    __tablename__ = "sales_quotes"
    __table_args__ = (
        db.UniqueConstraint("organisation_id", "quote_number", name="uq_sales_quote_org_number"),
    )

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(db.String(36), db.ForeignKey("organisations.id"), nullable=False, index=True)
    customer_id = db.Column(db.String(36), db.ForeignKey("customers.id"), nullable=False, index=True)
    quote_number = db.Column(db.String(120), nullable=False, index=True)
    quote_date = db.Column(db.Date, nullable=False, index=True)
    expiry_date = db.Column(db.Date, nullable=True, index=True)
    currency = db.Column(db.String(3), nullable=False, default="GBP")
    status = db.Column(db.String(30), nullable=False, default="draft", index=True)
    subtotal = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    tax_total = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    total = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    receivable_account_id = db.Column(db.String(36), db.ForeignKey("accounts.id"), nullable=False)
    converted_invoice_id = db.Column(db.String(36), db.ForeignKey("sales_invoices.id"), nullable=True, index=True)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    customer = db.relationship("Customer")
    receivable_account = db.relationship("Account")
    converted_invoice = db.relationship("SalesInvoice")
    lines = db.relationship(
        "SalesQuoteLine", back_populates="quote", cascade="all, delete-orphan", lazy="selectin"
    )


class SalesQuoteLine(db.Model):
    __tablename__ = "sales_quote_lines"

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    quote_id = db.Column(db.String(36), db.ForeignKey("sales_quotes.id", ondelete="CASCADE"), nullable=False, index=True)
    line_number = db.Column(db.Integer, nullable=False)
    description = db.Column(db.String(500), nullable=False)
    quantity = db.Column(db.Numeric(18, 4), nullable=False, default=1)
    unit_price = db.Column(db.Numeric(18, 4), nullable=False, default=0)
    net_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    tax_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    tax_code_id = db.Column(db.String(36), db.ForeignKey("tax_codes.id"), nullable=True, index=True)
    revenue_account_id = db.Column(db.String(36), db.ForeignKey("accounts.id"), nullable=False)
    dimensions = db.Column(db.JSON, nullable=False, default=dict)

    quote = db.relationship("SalesQuote", back_populates="lines")
    revenue_account = db.relationship("Account")
    tax_code = db.relationship("TaxCode")
