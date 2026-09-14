from ledgerone.extensions import db
from ledgerone.models.core import new_id, utcnow


class PurchaseOrder(db.Model):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        db.UniqueConstraint("organisation_id", "order_number", name="uq_purchase_order_org_number"),
    )

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(db.String(36), db.ForeignKey("organisations.id"), nullable=False, index=True)
    supplier_id = db.Column(db.String(36), db.ForeignKey("suppliers.id"), nullable=False, index=True)
    order_number = db.Column(db.String(120), nullable=False, index=True)
    order_date = db.Column(db.Date, nullable=False, index=True)
    expected_date = db.Column(db.Date, nullable=True, index=True)
    currency = db.Column(db.String(3), nullable=False, default="GBP")
    status = db.Column(db.String(30), nullable=False, default="draft", index=True)
    subtotal = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    tax_total = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    total = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    payable_account_id = db.Column(db.String(36), db.ForeignKey("accounts.id"), nullable=False)
    converted_bill_id = db.Column(db.String(36), db.ForeignKey("purchase_bills.id"), nullable=True, index=True)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    supplier = db.relationship("Supplier")
    payable_account = db.relationship("Account")
    converted_bill = db.relationship("PurchaseBill")
    lines = db.relationship(
        "PurchaseOrderLine", back_populates="order", cascade="all, delete-orphan", lazy="selectin"
    )


class PurchaseOrderLine(db.Model):
    __tablename__ = "purchase_order_lines"

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    order_id = db.Column(db.String(36), db.ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    line_number = db.Column(db.Integer, nullable=False)
    description = db.Column(db.String(500), nullable=False)
    quantity = db.Column(db.Numeric(18, 4), nullable=False, default=1)
    unit_price = db.Column(db.Numeric(18, 4), nullable=False, default=0)
    net_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    tax_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    tax_code_id = db.Column(db.String(36), db.ForeignKey("tax_codes.id"), nullable=True, index=True)
    expense_account_id = db.Column(db.String(36), db.ForeignKey("accounts.id"), nullable=False)
    dimensions = db.Column(db.JSON, nullable=False, default=dict)

    order = db.relationship("PurchaseOrder", back_populates="lines")
    expense_account = db.relationship("Account")
    tax_code = db.relationship("TaxCode")
