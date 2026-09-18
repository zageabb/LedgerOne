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
    payment_terms_days = db.Column(db.Integer, nullable=True)
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
    tax_point = db.Column(db.Date, nullable=False, index=True)
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
    payment_allocations = db.relationship(
        "SalesPaymentAllocation", back_populates="invoice", cascade="all, delete-orphan", lazy="selectin"
    )


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
    tax_code_id = db.Column(db.String(36), db.ForeignKey("tax_codes.id"), nullable=True, index=True)
    revenue_account_id = db.Column(db.String(36), db.ForeignKey("accounts.id"), nullable=False)
    dimensions = db.Column(db.JSON, nullable=False, default=dict)

    invoice = db.relationship("SalesInvoice", back_populates="lines")
    revenue_account = db.relationship("Account")
    tax_code = db.relationship("TaxCode")


class SalesPayment(db.Model):
    __tablename__ = "sales_payments"
    __table_args__ = (
        db.UniqueConstraint("organisation_id", "journal_id", name="uq_sales_payment_org_journal"),
    )

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(db.String(36), db.ForeignKey("organisations.id"), nullable=False, index=True)
    customer_id = db.Column(db.String(36), db.ForeignKey("customers.id"), nullable=False, index=True)
    payment_date = db.Column(db.Date, nullable=False, index=True)
    reference = db.Column(db.String(120), nullable=True, index=True)
    amount = db.Column(db.Numeric(18, 2), nullable=False)
    currency = db.Column(db.String(3), nullable=False, default="GBP")
    journal_id = db.Column(db.String(36), db.ForeignKey("journals.id"), nullable=False, index=True)
    settlement_type = db.Column(db.String(30), nullable=False, default="payment", index=True)
    status = db.Column(db.String(30), nullable=False, default="unallocated", index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    customer = db.relationship("Customer")
    journal = db.relationship("Journal")
    allocations = db.relationship(
        "SalesPaymentAllocation", back_populates="payment", cascade="all, delete-orphan", lazy="selectin"
    )


class SalesPaymentAllocation(db.Model):
    __tablename__ = "sales_payment_allocations"
    __table_args__ = (
        db.UniqueConstraint("payment_id", "invoice_id", name="uq_sales_payment_invoice"),
    )

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    payment_id = db.Column(db.String(36), db.ForeignKey("sales_payments.id", ondelete="CASCADE"), nullable=False, index=True)
    invoice_id = db.Column(db.String(36), db.ForeignKey("sales_invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    amount = db.Column(db.Numeric(18, 2), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    payment = db.relationship("SalesPayment", back_populates="allocations")
    invoice = db.relationship("SalesInvoice", back_populates="payment_allocations")
