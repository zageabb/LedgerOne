from __future__ import annotations

from decimal import Decimal

from sqlalchemy import event, inspect as sa_inspect

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


class AccountingPeriod(db.Model):
    __tablename__ = "accounting_periods"
    __table_args__ = (
        db.UniqueConstraint(
            "organisation_id",
            "start_date",
            "end_date",
            name="uq_accounting_period_org_dates",
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(db.String(36), db.ForeignKey("organisations.id"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    start_date = db.Column(db.Date, nullable=False, index=True)
    end_date = db.Column(db.Date, nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default="open", index=True)
    locked_at = db.Column(db.DateTime(timezone=True), nullable=True)
    locked_by_user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


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
    reversal_of = db.relationship("Journal", remote_side=[id], foreign_keys=[reversal_of_id])

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


class OpeningBalanceBatch(db.Model):
    __tablename__ = "opening_balance_batches"

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(db.String(36), db.ForeignKey("organisations.id"), nullable=False, index=True)
    as_of_date = db.Column(db.Date, nullable=False, index=True)
    reference = db.Column(db.String(120), nullable=True)
    description = db.Column(db.String(500), nullable=False, default="Opening balances")
    balancing_account_id = db.Column(db.String(36), db.ForeignKey("accounts.id"), nullable=True)
    journal_id = db.Column(db.String(36), db.ForeignKey("journals.id"), nullable=False, unique=True)
    created_by_user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    journal = db.relationship("Journal", foreign_keys=[journal_id])
    balancing_account = db.relationship("Account", foreign_keys=[balancing_account_id])


class RecurringJournal(db.Model):
    __tablename__ = "recurring_journals"

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(db.String(36), db.ForeignKey("organisations.id"), nullable=False, index=True)
    name = db.Column(db.String(160), nullable=False)
    description = db.Column(db.String(500), nullable=False)
    reference = db.Column(db.String(120), nullable=True)
    frequency = db.Column(db.String(20), nullable=False, index=True)
    next_run_date = db.Column(db.Date, nullable=False, index=True)
    end_date = db.Column(db.Date, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    template_lines = db.Column(db.JSON, nullable=False, default=list)
    last_run_date = db.Column(db.Date, nullable=True)
    run_count = db.Column(db.Integer, nullable=False, default=0)
    created_by_user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    runs = db.relationship("RecurringJournalRun", back_populates="recurring_journal", cascade="all, delete-orphan")


class RecurringJournalRun(db.Model):
    __tablename__ = "recurring_journal_runs"
    __table_args__ = (
        db.UniqueConstraint(
            "recurring_journal_id",
            "scheduled_date",
            name="uq_recurring_journal_scheduled_date",
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    recurring_journal_id = db.Column(db.String(36), db.ForeignKey("recurring_journals.id", ondelete="CASCADE"), nullable=False, index=True)
    scheduled_date = db.Column(db.Date, nullable=False, index=True)
    journal_id = db.Column(db.String(36), db.ForeignKey("journals.id"), nullable=False, unique=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    recurring_journal = db.relationship("RecurringJournal", back_populates="runs")
    journal = db.relationship("Journal")


def _reject_posted_mutation(mapper, connection, target):
    state = sa_inspect(target)
    if state.persistent:
        raise RuntimeError("Posted journals are immutable; use a reversal instead of editing or deleting them")


for _immutable_model in (Journal, JournalLine):
    event.listen(_immutable_model, "before_update", _reject_posted_mutation)
    event.listen(_immutable_model, "before_delete", _reject_posted_mutation)
