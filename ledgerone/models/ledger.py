from __future__ import annotations

from decimal import Decimal

from ledgerone.extensions import db
from ledgerone.models.core import new_id, utcnow


class Account(db.Model):
    __tablename__ = "accounts"
    __table_args__ = (db.UniqueConstraint("organisation_id", "code", name="uq_account_org_code"),)

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(db.String(36), db.ForeignKey("organisations.id"), nullable=False, index=True)
    code = db.Column(db.String(40), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    account_type = db.Column(db.String(40), nullable=False, index=True)
    parent_id = db.Column(db.String(36), db.ForeignKey("accounts.id"), nullable=True)
    currency = db.Column(db.String(3), nullable=True)
    is_control_account = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    parent = db.relationship("Account", remote_side=[id], backref="children")


class Journal(db.Model):
    __tablename__ = "journals"

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(db.String(36), db.ForeignKey("organisations.id"), nullable=False, index=True)
    journal_date = db.Column(db.Date, nullable=False, index=True)
    reference = db.Column(db.String(120), nullable=True, index=True)
    description = db.Column(db.String(500), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="posted", index=True)
    source_module = db.Column(db.String(80), nullable=False, default="ledger", index=True)
    source_reference = db.Column(db.String(255), nullable=True, index=True)
    reversal_of_id = db.Column(db.String(36), db.ForeignKey("journals.id"), nullable=True)
    created_by_user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    posted_at = db.Column(db.DateTime(timezone=True), nullable=True, default=utcnow)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)

    lines = db.relationship("JournalLine", back_populates="journal", cascade="all, delete-orphan", lazy="selectin")
    reversal_of = db.relationship("Journal", remote_side=[id])

    @property
    def total_debit(self) -> Decimal:
        return sum((line.debit or Decimal("0")) for line in self.lines)

    @property
    def total_credit(self) -> Decimal:
        return sum((line.credit or Decimal("0")) for line in self.lines)


class JournalLine(db.Model):
    __tablename__ = "journal_lines"

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    journal_id = db.Column(db.String(36), db.ForeignKey("journals.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id = db.Column(db.String(36), db.ForeignKey("accounts.id"), nullable=False, index=True)
    line_number = db.Column(db.Integer, nullable=False)
    description = db.Column(db.String(500), nullable=True)
    debit = db.Column(db.Numeric(18, 2), nullable=False, default=Decimal("0"))
    credit = db.Column(db.Numeric(18, 2), nullable=False, default=Decimal("0"))
    currency = db.Column(db.String(3), nullable=True)
    foreign_amount = db.Column(db.Numeric(18, 2), nullable=True)
    dimensions = db.Column(db.JSON, nullable=False, default=dict)

    journal = db.relationship("Journal", back_populates="lines")
    account = db.relationship("Account")
