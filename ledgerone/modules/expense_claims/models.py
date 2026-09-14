from ledgerone.extensions import db
from ledgerone.models.core import new_id, utcnow


class ExpenseClaim(db.Model):
    __tablename__ = "expense_claims"
    __table_args__ = (
        db.UniqueConstraint("organisation_id", "claim_number", name="uq_expense_claim_org_number"),
    )

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(db.String(36), db.ForeignKey("organisations.id"), nullable=False, index=True)
    claimant_user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=True, index=True)
    claimant_name = db.Column(db.String(255), nullable=False, index=True)
    claim_number = db.Column(db.String(120), nullable=False, index=True)
    claim_date = db.Column(db.Date, nullable=False, index=True)
    currency = db.Column(db.String(3), nullable=False, default="GBP")
    status = db.Column(db.String(30), nullable=False, default="draft", index=True)
    subtotal = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    tax_total = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    total = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    reimbursement_account_id = db.Column(db.String(36), db.ForeignKey("accounts.id"), nullable=False)
    approved_at = db.Column(db.DateTime(timezone=True), nullable=True)
    approved_by_user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=True)
    posted_journal_id = db.Column(db.String(36), db.ForeignKey("journals.id"), nullable=True, index=True)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    claimant = db.relationship("User", foreign_keys=[claimant_user_id])
    approved_by = db.relationship("User", foreign_keys=[approved_by_user_id])
    reimbursement_account = db.relationship("Account")
    posted_journal = db.relationship("Journal")
    lines = db.relationship(
        "ExpenseClaimLine", back_populates="claim", cascade="all, delete-orphan", lazy="selectin"
    )


class ExpenseClaimLine(db.Model):
    __tablename__ = "expense_claim_lines"

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    claim_id = db.Column(db.String(36), db.ForeignKey("expense_claims.id", ondelete="CASCADE"), nullable=False, index=True)
    line_number = db.Column(db.Integer, nullable=False)
    expense_date = db.Column(db.Date, nullable=False, index=True)
    merchant = db.Column(db.String(255), nullable=True)
    description = db.Column(db.String(500), nullable=False)
    net_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    tax_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    tax_code_id = db.Column(db.String(36), db.ForeignKey("tax_codes.id"), nullable=True, index=True)
    expense_account_id = db.Column(db.String(36), db.ForeignKey("accounts.id"), nullable=False)
    dimensions = db.Column(db.JSON, nullable=False, default=dict)

    claim = db.relationship("ExpenseClaim", back_populates="lines")
    tax_code = db.relationship("TaxCode")
    expense_account = db.relationship("Account")
