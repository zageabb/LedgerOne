from __future__ import annotations

import json
from datetime import date

import pytest

from ledgerone.extensions import db
from ledgerone.models.core import ApiKey, Organisation, User
from ledgerone.models.ledger import Account, Journal, RecurringJournal
from ledgerone.modules.ai.services import LocalAIService
from ledgerone.modules.banking.models import BankTransaction
from ledgerone.modules.banking.services import BankingService
from ledgerone.modules.expense_claims.models import ExpenseClaim
from ledgerone.modules.expense_claims.services import ExpenseClaimService
from ledgerone.modules.purchases.models import PurchaseBill, PurchasePayment
from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.modules.sales.models import SalesInvoice, SalesPayment
from ledgerone.modules.sales.services import SalesService
from ledgerone.services.context import AccessContext
from ledgerone.services.currency import CurrencyPolicyError
from ledgerone.services.ledger import LedgerService


def _organisation_and_accounts():
    organisation = Organisation.query.one()
    accounts = {
        row.code: row
        for row in Account.query.filter_by(organisation_id=organisation.id).all()
    }
    return organisation, accounts


def _api_token(organisation_id: str):
    key, token = ApiKey.issue(
        name="currency-gate-test",
        organisation_id=organisation_id,
        full_access=True,
    )
    db.session.add(key)
    db.session.commit()
    return token


def test_central_journal_gate_accepts_base_currency_and_blocks_fx_and_foreign_amount(app):
    with app.app_context():
        organisation, accounts = _organisation_and_accounts()
        context = AccessContext.system(organisation.id)

        journal = LedgerService.post_journal(
            context,
            journal_date=date(2026, 9, 15),
            description="Base-currency journal",
            lines=[
                {"account_id": accounts["1000"].id, "debit": "25.00", "credit": "0", "currency": "gbp"},
                {"account_id": accounts["4000"].id, "debit": "0", "credit": "25.00", "currency": "GBP"},
            ],
        )
        assert {line.currency for line in journal.lines} == {"GBP"}

        with pytest.raises(CurrencyPolicyError, match="base currency is GBP"):
            LedgerService.post_journal(
                context,
                journal_date=date(2026, 9, 15),
                description="Unsupported USD journal",
                lines=[
                    {"account_id": accounts["1000"].id, "debit": "10.00", "credit": "0", "currency": "USD"},
                    {"account_id": accounts["4000"].id, "debit": "0", "credit": "10.00", "currency": "USD"},
                ],
            )
        db.session.rollback()

        with pytest.raises(CurrencyPolicyError, match="Foreign-currency amounts are disabled"):
            LedgerService.post_journal(
                context,
                journal_date=date(2026, 9, 15),
                description="Foreign amount without FX engine",
                lines=[
                    {
                        "account_id": accounts["1000"].id,
                        "debit": "10.00",
                        "credit": "0",
                        "currency": "GBP",
                        "foreign_amount": "12.00",
                    },
                    {"account_id": accounts["4000"].id, "debit": "0", "credit": "10.00", "currency": "GBP"},
                ],
            )
        db.session.rollback()

        usd_account = LedgerService.create_account(
            context,
            code="1099",
            name="Future USD account",
            account_type="asset",
            currency="USD",
        )
        with pytest.raises(CurrencyPolicyError, match="Account 1099 uses USD"):
            LedgerService.post_journal(
                context,
                journal_date=date(2026, 9, 15),
                description="Omitted line currency must not bypass account currency",
                lines=[
                    {"account_id": usd_account.id, "debit": "10.00", "credit": "0"},
                    {"account_id": accounts["4000"].id, "debit": "0", "credit": "10.00"},
                ],
            )
        db.session.rollback()

        assert Journal.query.count() == 1


def test_sales_purchase_payments_and_expenses_cannot_post_foreign_currency(app):
    with app.app_context():
        organisation, accounts = _organisation_and_accounts()
        context = AccessContext.system(organisation.id)

        customer = SalesService.create_customer(context, name="Currency Customer")
        with pytest.raises(CurrencyPolicyError, match="base currency is GBP"):
            SalesService.create_invoice(
                context,
                customer_id=customer.id,
                invoice_number="FX-INV-001",
                invoice_date=date(2026, 9, 15),
                due_date=None,
                description="USD sale",
                amount="100.00",
                receivable_account_id=accounts["1200"].id,
                revenue_account_id=accounts["4000"].id,
                currency="USD",
            )
        assert SalesInvoice.query.count() == 0

        supplier = PurchasesService.create_supplier(context, name="Currency Supplier")
        with pytest.raises(CurrencyPolicyError, match="base currency is GBP"):
            PurchasesService.create_bill(
                context,
                supplier_id=supplier.id,
                bill_number="FX-BILL-001",
                bill_date=date(2026, 9, 15),
                due_date=None,
                description="EUR purchase",
                amount="75.00",
                payable_account_id=accounts["2100"].id,
                expense_account_id=accounts["5000"].id,
                currency="EUR",
            )
        assert PurchaseBill.query.count() == 0

        gbp_invoice = SalesService.create_invoice(
            context,
            customer_id=customer.id,
            invoice_number="GBP-INV-001",
            invoice_date=date(2026, 9, 15),
            due_date=None,
            description="GBP sale",
            amount="40.00",
            receivable_account_id=accounts["1200"].id,
            revenue_account_id=accounts["4000"].id,
            currency="GBP",
        )
        assert gbp_invoice.status == "posted"
        with pytest.raises(CurrencyPolicyError, match="base currency is GBP"):
            SalesService.record_payment(
                context,
                customer_id=customer.id,
                payment_date=date(2026, 9, 15),
                amount="40.00",
                bank_account_id=accounts["1000"].id,
                receivable_account_id=accounts["1200"].id,
                currency="USD",
            )
        assert SalesPayment.query.count() == 0

        gbp_bill = PurchasesService.create_bill(
            context,
            supplier_id=supplier.id,
            bill_number="GBP-BILL-001",
            bill_date=date(2026, 9, 15),
            due_date=None,
            description="GBP purchase",
            amount="30.00",
            payable_account_id=accounts["2100"].id,
            expense_account_id=accounts["5000"].id,
            currency="GBP",
        )
        assert gbp_bill.status == "posted"
        with pytest.raises(CurrencyPolicyError, match="base currency is GBP"):
            PurchasesService.record_payment(
                context,
                supplier_id=supplier.id,
                payment_date=date(2026, 9, 15),
                amount="30.00",
                bank_account_id=accounts["1000"].id,
                payable_account_id=accounts["2100"].id,
                currency="EUR",
            )
        assert PurchasePayment.query.count() == 0

        claim = ExpenseClaimService.create_claim(
            context,
            claimant_name="Test Claimant",
            claim_number="FX-EXP-001",
            claim_date=date(2026, 9, 15),
            expense_date=date(2026, 9, 14),
            merchant="Foreign Merchant",
            description="Foreign expense",
            amount="20.00",
            expense_account_id=accounts["5000"].id,
            reimbursement_account_id=accounts["2100"].id,
            currency="USD",
        )
        ExpenseClaimService.submit(context, claim.id)
        with pytest.raises(CurrencyPolicyError, match="base currency is GBP"):
            ExpenseClaimService.approve_and_post(
                context,
                claim.id,
                posting_date=date(2026, 9, 15),
            )
        claim = db.session.get(ExpenseClaim, claim.id)
        assert claim.status == "submitted"
        assert claim.posted_journal_id is None


def test_payment_adoption_cannot_relabel_base_currency_journal_as_foreign(app):
    with app.app_context():
        organisation, accounts = _organisation_and_accounts()
        context = AccessContext.system(organisation.id)
        customer = SalesService.create_customer(context, name="Adoption Customer")

        journal = LedgerService.post_journal(
            context,
            journal_date=date(2026, 9, 15),
            description="Customer receipt",
            lines=[
                {"account_id": accounts["1000"].id, "debit": "50.00", "credit": "0", "currency": "GBP"},
                {"account_id": accounts["1200"].id, "debit": "0", "credit": "50.00", "currency": "GBP"},
            ],
        )

        with pytest.raises(CurrencyPolicyError, match="base currency is GBP"):
            SalesService.adopt_payment_journal(
                context,
                customer_id=customer.id,
                journal_id=journal.id,
                receivable_account_id=accounts["1200"].id,
                currency="USD",
            )
        db.session.rollback()
        assert SalesPayment.query.count() == 0


def test_banking_posting_cannot_bypass_base_currency_gate(app):
    with app.app_context():
        organisation, accounts = _organisation_and_accounts()
        context = AccessContext.system(organisation.id)
        bank = BankingService.create_account(
            context,
            name="Legacy USD bank",
            institution="Test Bank",
            currency="USD",
            ledger_account_id=accounts["1000"].id,
        )
        transaction = BankingService.add_transaction(
            context,
            bank_account_id=bank.id,
            transaction_date=date(2026, 9, 15),
            description="USD receipt",
            amount="100.00",
            external_id="USD-001",
        )

        with pytest.raises(CurrencyPolicyError, match="base currency is GBP"):
            BankingService.post_and_match(
                context,
                transaction.id,
                offset_account_id=accounts["4000"].id,
            )

        transaction = db.session.get(BankTransaction, transaction.id)
        assert transaction.status == "unreconciled"
        assert transaction.matched_journal_id is None
        assert Journal.query.count() == 0


def test_foreign_currency_recurring_journal_is_rejected_before_schedule_creation(app):
    with app.app_context():
        organisation, accounts = _organisation_and_accounts()
        context = AccessContext.system(organisation.id)
        with pytest.raises(CurrencyPolicyError, match="base currency is GBP"):
            LedgerService.create_recurring_journal(
                context,
                name="USD recurring",
                description="Unsupported recurring FX",
                frequency="monthly",
                next_run_date=date(2026, 10, 1),
                lines=[
                    {"account_id": accounts["5000"].id, "debit": "15.00", "credit": "0", "currency": "USD"},
                    {"account_id": accounts["2100"].id, "debit": "0", "credit": "15.00", "currency": "USD"},
                ],
            )
        assert RecurringJournal.query.count() == 0


def test_api_and_ai_cannot_bypass_currency_gate(app, client, monkeypatch):
    with app.app_context():
        organisation, accounts = _organisation_and_accounts()
        token = _api_token(organisation.id)
        account_ids = {code: row.id for code, row in accounts.items()}

    response = client.post(
        "/api/v1/ledger/journals",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "date": "2026-09-15",
            "description": "Foreign API journal",
            "lines": [
                {"account_id": account_ids["1000"], "debit": "10.00", "credit": "0", "currency": "USD"},
                {"account_id": account_ids["4000"], "debit": "0", "credit": "10.00", "currency": "USD"},
            ],
        },
    )
    assert response.status_code == 400
    assert "Multi-currency accounting is not yet enabled" in response.get_json()["error"]

    with app.app_context():
        organisation = Organisation.query.one()
        user = User.query.first()
        context = AccessContext(
            identity_type="user",
            organisation_id=organisation.id,
            user_id=user.id,
            permissions=frozenset({"ai.use", "ledger.journals.post"}),
        )
        monkeypatch.setattr(
            "ledgerone.modules.ai.services.AIConfiguration.get",
            lambda organisation_id: {
                "enabled": True,
                "base_url": "http://local-ai.invalid",
                "model": "currency-test-model",
                "timeout": 1,
                "allow_writes": True,
            },
        )
        responses = iter(
            [
                json.dumps(
                    {
                        "message": "Posting the requested journal.",
                        "tool_calls": [
                            {
                                "name": "ledger.post_journal",
                                "arguments": {
                                    "date": "2026-09-15",
                                    "description": "Foreign AI journal",
                                    "lines": [
                                        {"account_id": account_ids["1000"], "debit": "10.00", "credit": "0", "currency": "USD"},
                                        {"account_id": account_ids["4000"], "debit": "0", "credit": "10.00", "currency": "USD"},
                                    ],
                                },
                            }
                        ],
                    }
                ),
                json.dumps(
                    {
                        "message": "I cannot post that because LedgerOne is restricted to the organisation base currency.",
                        "tool_calls": [],
                    }
                ),
            ]
        )
        monkeypatch.setattr(
            LocalAIService,
            "_call_model",
            staticmethod(lambda messages, config: next(responses)),
        )

        result = LocalAIService.chat(
            context=context,
            organisation_name=organisation.name,
            prompt="Post a USD journal",
            approve_writes=True,
        )

        assert "Multi-currency accounting is not yet enabled" in result["tools"][0]["result"]["error"]
        assert Journal.query.count() == 0
