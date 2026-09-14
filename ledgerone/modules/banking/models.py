from ledgerone.extensions import db
from ledgerone.models.core import new_id, utcnow


class BankAccount(db.Model):
    __tablename__ = "bank_accounts"

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(db.String(36), db.ForeignKey("organisations.id"), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    institution = db.Column(db.String(255), nullable=True)
    currency = db.Column(db.String(3), nullable=False, default="GBP")
    ledger_account_id = db.Column(db.String(36), db.ForeignKey("accounts.id"), nullable=True, index=True)
    account_mask = db.Column(db.String(40), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    ledger_account = db.relationship("Account")
    transactions = db.relationship(
        "BankTransaction", back_populates="bank_account", cascade="all, delete-orphan", lazy="dynamic"
    )


class BankTransaction(db.Model):
    __tablename__ = "bank_transactions"
    __table_args__ = (
        db.UniqueConstraint("bank_account_id", "external_id", name="uq_bank_transaction_external"),
    )

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    bank_account_id = db.Column(db.String(36), db.ForeignKey("bank_accounts.id"), nullable=False, index=True)
    transaction_date = db.Column(db.Date, nullable=False, index=True)
    description = db.Column(db.String(500), nullable=False)
    amount = db.Column(db.Numeric(18, 2), nullable=False)
    external_id = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(30), nullable=False, default="unreconciled", index=True)
    matched_journal_id = db.Column(db.String(36), db.ForeignKey("journals.id"), nullable=True)
    raw_payload = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    bank_account = db.relationship("BankAccount", back_populates="transactions")
    matched_journal = db.relationship("Journal")
