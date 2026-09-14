from ledgerone.extensions import db
from ledgerone.models.core import new_id, utcnow


class Supplier(db.Model):
    __tablename__ = "suppliers"

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


class PurchaseBill(db.Model):
    __tablename__ = "purchase_bills"
    __table_args__ = (
        db.UniqueConstraint("organisation_id", "bill_number", name="uq_purchase_bill_org_number"),
    )

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(db.String(36), db.ForeignKey("organisations.id"), nullable=False, index=True)
    supplier_id = db.Column(db.String(36), db.ForeignKey("suppliers.id"), nullable=False, index=True)
    bill_number = db.Column(db.String(120), nullable=False, index=True)
    bill_date = db.Column(db.Date, nullable=False, index=True)
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

    supplier = db.relationship("Supplier")
    posted_journal = db.relationship("Journal")
    lines = db.relationship("PurchaseBillLine", back_populates="bill", cascade="all, delete-orphan", lazy="selectin")
    payment_allocations = db.relationship(
        "PurchasePaymentAllocation", back_populates="bill", cascade="all, delete-orphan", lazy="selectin"
    )


class PurchaseBillLine(db.Model):
    __tablename__ = "purchase_bill_lines"

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    bill_id = db.Column(db.String(36), db.ForeignKey("purchase_bills.id", ondelete="CASCADE"), nullable=False, index=True)
    line_number = db.Column(db.Integer, nullable=False)
    description = db.Column(db.String(500), nullable=False)
    quantity = db.Column(db.Numeric(18, 4), nullable=False, default=1)
    unit_price = db.Column(db.Numeric(18, 4), nullable=False, default=0)
    net_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    tax_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    tax_code_id = db.Column(db.String(36), db.ForeignKey("tax_codes.id"), nullable=True, index=True)
    expense_account_id = db.Column(db.String(36), db.ForeignKey("accounts.id"), nullable=False)
    dimensions = db.Column(db.JSON, nullable=False, default=dict)

    bill = db.relationship("PurchaseBill", back_populates="lines")
    expense_account = db.relationship("Account")
    tax_code = db.relationship("TaxCode")


class PurchasePayment(db.Model):
    __tablename__ = "purchase_payments"
    __table_args__ = (
        db.UniqueConstraint("organisation_id", "journal_id", name="uq_purchase_payment_org_journal"),
    )

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(db.String(36), db.ForeignKey("organisations.id"), nullable=False, index=True)
    supplier_id = db.Column(db.String(36), db.ForeignKey("suppliers.id"), nullable=False, index=True)
    payment_date = db.Column(db.Date, nullable=False, index=True)
    reference = db.Column(db.String(120), nullable=True, index=True)
    amount = db.Column(db.Numeric(18, 2), nullable=False)
    currency = db.Column(db.String(3), nullable=False, default="GBP")
    journal_id = db.Column(db.String(36), db.ForeignKey("journals.id"), nullable=False, index=True)
    settlement_type = db.Column(db.String(30), nullable=False, default="payment", index=True)
    status = db.Column(db.String(30), nullable=False, default="unallocated", index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    supplier = db.relationship("Supplier")
    journal = db.relationship("Journal")
    allocations = db.relationship(
        "PurchasePaymentAllocation", back_populates="payment", cascade="all, delete-orphan", lazy="selectin"
    )


class PurchasePaymentAllocation(db.Model):
    __tablename__ = "purchase_payment_allocations"
    __table_args__ = (
        db.UniqueConstraint("payment_id", "bill_id", name="uq_purchase_payment_bill"),
    )

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    payment_id = db.Column(db.String(36), db.ForeignKey("purchase_payments.id", ondelete="CASCADE"), nullable=False, index=True)
    bill_id = db.Column(db.String(36), db.ForeignKey("purchase_bills.id", ondelete="CASCADE"), nullable=False, index=True)
    amount = db.Column(db.Numeric(18, 2), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    payment = db.relationship("PurchasePayment", back_populates="allocations")
    bill = db.relationship("PurchaseBill", back_populates="payment_allocations")
