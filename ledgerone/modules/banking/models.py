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


class BankReconciliation(db.Model):
    __tablename__ = "bank_reconciliations"

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(db.String(36), db.ForeignKey("organisations.id"), nullable=False, index=True)
    bank_account_id = db.Column(db.String(36), db.ForeignKey("bank_accounts.id"), nullable=False, index=True)
    statement_start_date = db.Column(db.Date, nullable=False)
    statement_end_date = db.Column(db.Date, nullable=False, index=True)
    statement_opening_balance = db.Column(db.Numeric(18, 2), nullable=False)
    statement_closing_balance = db.Column(db.Numeric(18, 2), nullable=False)
    ledger_balance = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    unmatched_statement_total = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    outstanding_book_total = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    explained_difference = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    residual_difference = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    explanation = db.Column(db.String(2000), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="draft", index=True)
    snapshot_json = db.Column(db.JSON, nullable=False, default=dict)
    prepared_by_user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=True)
    approved_by_user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=True)
    prepared_identity = db.Column(db.String(120), nullable=True)
    approved_identity = db.Column(db.String(120), nullable=True)
    prepared_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    approved_at = db.Column(db.DateTime(timezone=True), nullable=True)
    finalised_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    bank_account = db.relationship("BankAccount")
    prepared_by_user = db.relationship("User", foreign_keys=[prepared_by_user_id])
    approved_by_user = db.relationship("User", foreign_keys=[approved_by_user_id])
