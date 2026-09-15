from __future__ import annotations

from datetime import date

import pytest

from ledgerone.extensions import db
from ledgerone.models.core import ApiKey, Organisation, User
from ledgerone.models.ledger import Account, Journal, JournalLine
from ledgerone.modules.banking.services import BankingService
from ledgerone.modules.expense_claims.services import ExpenseClaimService
from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.modules.sales.services import SalesService
from ledgerone.modules.tax.services import TaxService
from ledgerone.services.context import AccessContext
from ledgerone.services.control_accounts import (
    ControlAccountError,
    ControlAccountService,
    seed_all_control_account_metadata,
)
from ledgerone.services.ledger import LedgerService


def _organisation_accounts():
    organisation = Organisation.query.one()
    accounts = {
        row.code: row
        for row in Account.query.filter_by(organisation_id=organisation.id).all()
    }
    return organisation, accounts


def _ensure_all_controls(organisation_id: str):
    TaxService.seed_defaults(organisation_id)
    ExpenseClaimService.seed_defaults(organisation_id)
    seed_all_control_account_metadata()


def _api_token(organisation_id: str):
    key, token = ApiKey.issue(
        name="control-account-test",
        organisation_id=organisation_id,
        full_access=True,
    )
    db.session.add(key)
    db.session.commit()
    return token


def test_control_accounts_are_typed_and_owned(app):
    with app.app_context():
        organisation, _ = _organisation_accounts()
        _ensure_all_controls(organisation.id)
        _, accounts = _organisation_accounts()

        expected = {
            "1200": ("accounts_receivable", "sales"),
            "2100": ("accounts_payable", "purchases"),
            "1300": ("input_vat", "purchases"),
            "2200": ("output_vat", "sales"),
            "2150": ("employee_reimbursements", "expense_claims"),
        }
        for code, (role, owner) in expected.items():
            row = accounts[code]
            assert row.is_control_account is True
            assert row.metadata_json["control_role"] == role
            assert row.metadata_json["control_owner_module"] == owner


def test_manual_and_api_journals_cannot_post_to_ar_ap_or_vat(app, client):
    with app.app_context():
        organisation, accounts = _organisation_accounts()
        _ensure_all_controls(organisation.id)
        _, accounts = _organisation_accounts()
        context = AccessContext.system(organisation.id)

        with pytest.raises(ControlAccountError, match="control account"):
            LedgerService.post_journal(
                context,
                journal_date=date(2026, 9, 15),
                description="Manual AR bypass",
                lines=[
                    {"account_id": accounts["1200"].id, "debit": "10.00", "credit": "0"},
                    {"account_id": accounts["4000"].id, "debit": "0", "credit": "10.00"},
                ],
            )
        db.session.rollback()
        token = _api_token(organisation.id)
        account_ids = {code: row.id for code, row in accounts.items()}

    cases = [
        (
            "AR",
            [
                {"account_id": account_ids["1200"], "debit": "10.00", "credit": "0"},
                {"account_id": account_ids["4000"], "debit": "0", "credit": "10.00"},
            ],
        ),
        (
            "AP",
            [
                {"account_id": account_ids["5000"], "debit": "10.00", "credit": "0"},
                {"account_id": account_ids["2100"], "debit": "0", "credit": "10.00"},
            ],
        ),
        (
            "Output VAT",
            [
                {"account_id": account_ids["5000"], "debit": "10.00", "credit": "0"},
                {"account_id": account_ids["2200"], "debit": "0", "credit": "10.00"},
            ],
        ),
        (
            "Input VAT",
            [
                {"account_id": account_ids["1300"], "debit": "10.00", "credit": "0"},
                {"account_id": account_ids["4000"], "debit": "0", "credit": "10.00"},
            ],
        ),
    ]
    for label, lines in cases:
        response = client.post(
            "/api/v1/ledger/journals",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "date": "2026-09-15",
                "description": f"Spoofed {label} posting",
                "source_module": "sales",
                "lines": lines,
            },
        )
        assert response.status_code == 400, label
        assert "control account" in response.get_json()["error"].lower(), label


def test_banking_and_payment_account_selection_cannot_bypass_controls(app):
    with app.app_context():
        organisation, accounts = _organisation_accounts()
        context = AccessContext.system(organisation.id)
        customer = SalesService.create_customer(context, name="Control Customer")

        with pytest.raises(ControlAccountError, match="cannot be used as a bank ledger account"):
            BankingService.create_account(
                context,
                name="Invalid AR bank",
                institution="Test Bank",
                currency="GBP",
                ledger_account_id=accounts["1200"].id,
            )
        db.session.rollback()

        with pytest.raises(ControlAccountError, match="cannot be used as a bank ledger account"):
            SalesService.record_payment(
                context,
                customer_id=customer.id,
                payment_date=date(2026, 9, 15),
                amount="10.00",
                bank_account_id=accounts["1200"].id,
                receivable_account_id=accounts["1200"].id,
                currency="GBP",
            )
        db.session.rollback()

        bank = BankingService.create_account(
            context,
            name="Current Account",
            institution="Test Bank",
            currency="GBP",
            ledger_account_id=accounts["1000"].id,
        )
        transaction = BankingService.add_transaction(
            context,
            bank_account_id=bank.id,
            transaction_date=date(2026, 9, 15),
            description="Customer receipt without subledger",
            amount="50.00",
            external_id="CTRL-001",
        )
        with pytest.raises(ControlAccountError, match="control account"):
            BankingService.post_and_match(
                context,
                transaction.id,
                offset_account_id=accounts["1200"].id,
            )
        db.session.rollback()


def test_sales_and_purchases_post_through_controls_and_reconcile(app):
    with app.app_context():
        organisation, accounts = _organisation_accounts()
        _ensure_all_controls(organisation.id)
        _, accounts = _organisation_accounts()
        context = AccessContext.system(organisation.id)

        customer = SalesService.create_customer(context, name="Reconcile Customer")
        invoice = SalesService.create_invoice(
            context,
            customer_id=customer.id,
            invoice_number="REC-INV-001",
            invoice_date=date(2026, 9, 15),
            due_date=None,
            description="Reconciliation sale",
            amount="100.00",
            receivable_account_id=accounts["1200"].id,
            revenue_account_id=accounts["4000"].id,
            currency="GBP",
        )
        assert invoice.status == "posted"
        SalesService.record_payment(
            context,
            customer_id=customer.id,
            payment_date=date(2026, 9, 15),
            amount="40.00",
            bank_account_id=accounts["1000"].id,
            receivable_account_id=accounts["1200"].id,
            currency="GBP",
        )

        supplier = PurchasesService.create_supplier(context, name="Reconcile Supplier")
        bill = PurchasesService.create_bill(
            context,
            supplier_id=supplier.id,
            bill_number="REC-BILL-001",
            bill_date=date(2026, 9, 15),
            due_date=None,
            description="Reconciliation purchase",
            amount="80.00",
            payable_account_id=accounts["2100"].id,
            expense_account_id=accounts["5000"].id,
            currency="GBP",
        )
        assert bill.status == "posted"
        PurchasesService.record_payment(
            context,
            supplier_id=supplier.id,
            payment_date=date(2026, 9, 15),
            amount="30.00",
            bank_account_id=accounts["1000"].id,
            payable_account_id=accounts["2100"].id,
            currency="GBP",
        )

        report = ControlAccountService.reconciliation(
            context, as_of=date(2026, 9, 15)
        )
        rows = {row["role"]: row for row in report["rows"]}
        assert rows["accounts_receivable"]["ledger_balance"] == pytest.approx(60)
        assert rows["accounts_receivable"]["subledger_balance"] == pytest.approx(60)
        assert rows["accounts_receivable"]["difference"] == 0
        assert rows["accounts_payable"]["ledger_balance"] == pytest.approx(50)
        assert rows["accounts_payable"]["subledger_balance"] == pytest.approx(50)
        assert rows["accounts_payable"]["difference"] == 0
        assert rows["output_vat"]["difference"] == 0
        assert rows["input_vat"]["difference"] == 0
        assert report["all_configured_reconciled"] is True


def test_control_adjustment_requires_permission_and_reason(app):
    with app.app_context():
        organisation, accounts = _organisation_accounts()
        restricted = AccessContext(
            identity_type="user",
            organisation_id=organisation.id,
            user_id=User.query.first().id,
            permissions=frozenset({"ledger.journals.post"}),
        )
        lines = [
            {"account_id": accounts["1200"].id, "debit": "25.00", "credit": "0"},
            {"account_id": accounts["3000"].id, "debit": "0", "credit": "25.00"},
        ]
        with pytest.raises(PermissionError, match="ledger.control_accounts.adjust"):
            ControlAccountService.post_adjustment(
                restricted,
                journal_date=date(2026, 9, 15),
                description="Restricted adjustment",
                reason="Required correction",
                lines=lines,
            )

        context = AccessContext.system(organisation.id)
        with pytest.raises(ControlAccountError, match="requires a reason"):
            ControlAccountService.post_adjustment(
                context,
                journal_date=date(2026, 9, 15),
                description="No reason adjustment",
                reason="",
                lines=lines,
            )

        journal = ControlAccountService.post_adjustment(
            context,
            journal_date=date(2026, 9, 15),
            description="Approved AR adjustment",
            reason="Correct legacy opening balance after reconciliation review",
            lines=lines,
        )
        assert journal.source_module == "control_adjustment"
        assert journal.metadata_json["control_adjustment"] is True
        assert "legacy opening balance" in journal.metadata_json["control_adjustment_reason"]


def test_direct_orm_control_account_posting_is_blocked(app):
    with app.app_context():
        organisation, accounts = _organisation_accounts()
        journal = Journal(
            organisation_id=organisation.id,
            journal_date=date(2026, 9, 15),
            description="Direct ORM bypass",
            source_module="ledger",
            status="posted",
        )
        db.session.add(journal)
        db.session.flush()
        db.session.add_all(
            [
                JournalLine(
                    journal_id=journal.id,
                    account_id=accounts["1200"].id,
                    line_number=1,
                    debit="10.00",
                    credit="0.00",
                    currency="GBP",
                ),
                JournalLine(
                    journal_id=journal.id,
                    account_id=accounts["4000"].id,
                    line_number=2,
                    debit="0.00",
                    credit="10.00",
                    currency="GBP",
                ),
            ]
        )
        with pytest.raises(ControlAccountError, match="control account"):
            db.session.commit()
        db.session.rollback()


def test_control_reconciliation_api(app, client):
    with app.app_context():
        organisation, _ = _organisation_accounts()
        token = _api_token(organisation.id)

    response = client.get(
        "/api/v1/reports/control-accounts/",
        headers={"Authorization": f"Bearer {token}"},
        query_string={"as_of": "2026-09-15"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    roles = {row["role"] for row in payload["rows"]}
    assert {"accounts_receivable", "accounts_payable"}.issubset(roles)
