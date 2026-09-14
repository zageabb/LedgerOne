from ledgerone.extensions import db
from ledgerone.models.core import new_id, utcnow


class Customer(db.Model):
    __tablename__ = "customers"

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(db.String(36), db.ForeignKey("organisations.id"), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False, index=True)
    email = db.Column(db.String(255), nullable=True)
    phone = db.Column(db.String(80), nullable=True)
    tax_id = db.Column(db.String(120), nullable=True)
    address = db.Column(db.JSON, nullable=False, default=dict)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class SalesInvoice(db.Model):
    __tablename__ = "sales_invoices"
    __table_args__ = (
        db.UniqueConstraint("organisation_id", "invoice_number", name="uq_sales_invoice_org_number"),
    )

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(db.String(36), db.ForeignKey("organisations.id"), nullable=False, index=True)
    customer_id = db.Column(db.String(36), db.ForeignKey("customers.id"), nullable=False, index=True)
    invoice_number = db.Column(db.String(120), nullable=False, index=True)
    invoice_date = db.Column(db.Date, nullable=False, index=True)
    due_date = db.Column(db.Date, nullable=True)
    currency = db.Column(db.String(3), nullable=False, default="GBP")
    status = db.Column(db.String(30), nullable=False, default="draft", index=True)
    subtotal = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    tax_total = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    total = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    posted_journal_id = db.Column(db.String(36), db.ForeignKey("journals.id"), nullable=True)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    customer = db.relationship("Customer")
    posted_journal = db.relationship("Journal")
    lines = db.relationship("SalesInvoiceLine", back_populates="invoice", cascade="all, delete-orphan", lazy="selectin")


class SalesInvoiceLine(db.Model):
    __tablename__ = "sales_invoice_lines"

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    invoice_id = db.Column(db.String(36), db.ForeignKey("sales_invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    line_number = db.Column(db.Integer, nullable=False)
    description = db.Column(db.String(500), nullable=False)
    quantity = db.Column(db.Numeric(18, 4), nullable=False, default=1)
    unit_price = db.Column(db.Numeric(18, 4), nullable=False, default=0)
    net_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    tax_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    revenue_account_id = db.Column(db.String(36), db.ForeignKey("accounts.id"), nullable=False)
    dimensions = db.Column(db.JSON, nullable=False, default=dict)

    invoice = db.relationship("SalesInvoice", back_populates="lines")
    revenue_account = db.relationship("Account")
