from datetime import date
from decimal import Decimal

import pytest

from ledgerone.extensions import db
from ledgerone.models.core import Organisation
from ledgerone.models.ledger import Account, Journal
from ledgerone.modules.documents.services import DocumentService
from ledgerone.modules.expense_claims.models import ExpenseClaim
from ledgerone.modules.expense_claims.services import ExpenseClaimError, ExpenseClaimService
from ledgerone.modules.settings.services import SettingsService
from ledgerone.modules.tax.models import TaxCode
from ledgerone.services.context import AccessContext
from ledgerone.services.ledger import LedgerError, LedgerService


def _enable_claims():
    organisation = Organisation.query.one()
    context = AccessContext.system(organisation.id)
    SettingsService.set_module_enabled(context, "expense_claims", True)
    accounts = {
        row.code: row.id
        for row in Account.query.filter_by(organisation_id=organisation.id).all()
    }
    return context, accounts


def _create_claim(context, accounts, *, number="EXP-001", tax_code_id=None):
    return ExpenseClaimService.create_claim(
        context,
        claimant_name="Test Claimant",
        claim_number=number,
        claim_date=date(2026, 9, 14),
        expense_date=date(2026, 9, 13),
        merchant="Test Merchant",
        description="Travel expense",
        amount="100.00",
        expense_account_id=accounts["5000"],
        reimbursement_account_id=accounts["2150"],
        tax_code_id=tax_code_id,
    )


def test_enabling_expense_claims_seeds_reimbursement_account(app):
    with app.app_context():
        organisation = Organisation.query.one()
        assert Account.query.filter_by(organisation_id=organisation.id, code="2150").first() is None
        _, accounts = _enable_claims()
        row = db.session.get(Account, accounts["2150"])
        assert row.name == "Employee Reimbursements"
        assert row.account_type == "liability"
        assert row.is_control_account is True


def test_claim_is_non_posting_until_approval_and_supports_extra_lines(app):
    with app.app_context():
        context, accounts = _enable_claims()
        before_journals = Journal.query.count()
        claim = _create_claim(context, accounts)
        assert claim.status == "draft"
        assert claim.total == Decimal("100.00")
        assert Journal.query.count() == before_journals

        _, claim = ExpenseClaimService.add_line(
            context,
            claim.id,
            expense_date=date(2026, 9, 12),
            merchant="Parking",
            description="Parking",
            amount="10.00",
            expense_account_id=accounts["5000"],
        )
        assert claim.subtotal == Decimal("110.00")
        assert claim.total == Decimal("110.00")
        assert len(claim.lines) == 2
        assert Journal.query.count() == before_journals

        ExpenseClaimService.submit(context, claim.id)
        assert claim.status == "submitted"
        assert Journal.query.count() == before_journals

        posted, journal = ExpenseClaimService.approve_and_post(
            context, claim.id, posting_date=date(2026, 9, 15)
        )
        assert posted.status == "posted"
        assert posted.posted_journal_id == journal.id
        assert Journal.query.count() == before_journals + 1
        expense_debits = sum(
            (line.debit for line in journal.lines if line.account.code == "5000"),
            Decimal("0.00"),
        )
        reimbursement_credits = sum(
            (line.credit for line in journal.lines if line.account.code == "2150"),
            Decimal("0.00"),
        )
        assert expense_debits == Decimal("110.00")
        assert reimbursement_credits == Decimal("110.00")

        with pytest.raises(ExpenseClaimError, match="submitted"):
            ExpenseClaimService.approve_and_post(
                context, claim.id, posting_date=date(2026, 9, 16)
            )


def test_vat_expense_claim_posts_recoverable_vat(app):
    with app.app_context():
        context, accounts = _enable_claims()
        SettingsService.set_module_enabled(context, "tax", True)
        accounts = {
            row.code: row.id
            for row in Account.query.filter_by(organisation_id=context.organisation_id).all()
        }
        t20 = TaxCode.query.filter_by(
            organisation_id=context.organisation_id, code="T20"
        ).one()
        claim = _create_claim(context, accounts, number="EXP-VAT-001", tax_code_id=t20.id)
        assert claim.subtotal == Decimal("100.00")
        assert claim.tax_total == Decimal("20.00")
        assert claim.total == Decimal("120.00")

        ExpenseClaimService.submit(context, claim.id)
        posted, journal = ExpenseClaimService.approve_and_post(
            context, claim.id, posting_date=date(2026, 9, 15)
        )
        by_account = {line.account.code: (line.debit, line.credit) for line in journal.lines}
        assert by_account["5000"] == (Decimal("100.00"), Decimal("0.00"))
        assert by_account["1300"] == (Decimal("20.00"), Decimal("0.00"))
        assert by_account["2150"] == (Decimal("0.00"), Decimal("120.00"))
        assert posted.status == "posted"


def test_locked_period_claim_approval_rolls_back_posting(app):
    with app.app_context():
        context, accounts = _enable_claims()
        claim = _create_claim(context, accounts, number="EXP-LOCKED-001")
        ExpenseClaimService.submit(context, claim.id)
        period = LedgerService.create_period(
            context,
            name="October 2026 expense claim lock",
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 31),
        )
        LedgerService.set_period_locked(context, period.id, locked=True)
        before_journals = Journal.query.count()

        with pytest.raises(LedgerError, match="locked period"):
            ExpenseClaimService.approve_and_post(
                context, claim.id, posting_date=date(2026, 10, 5)
            )

        db.session.expire_all()
        persisted = db.session.get(ExpenseClaim, claim.id)
        assert persisted.status == "submitted"
        assert persisted.posted_journal_id is None
        assert persisted.approved_at is None
        assert Journal.query.count() == before_journals


def test_rejected_claim_and_receipt_reference_remain_non_posting(app):
    with app.app_context():
        context, accounts = _enable_claims()
        claim = _create_claim(context, accounts, number="EXP-REJECT-001")
        receipt = DocumentService.create_reference(
            context,
            entity_type="expense_claim",
            entity_id=claim.id,
            reference_url="https://example.com/receipt/123",
            title="Receipt evidence",
        )
        assert receipt.module_id == "expense_claims"
        assert receipt.entity_type == "expense_claim"

        before_journals = Journal.query.count()
        ExpenseClaimService.submit(context, claim.id)
        rejected = ExpenseClaimService.reject(context, claim.id, reason="Missing business purpose")
        assert rejected.status == "rejected"
        assert rejected.metadata_json["rejection_reason"] == "Missing business purpose"
        assert Journal.query.count() == before_journals
