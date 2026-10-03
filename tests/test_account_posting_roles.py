from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from ledgerone.extensions import db
from ledgerone.models.core import Organisation
from ledgerone.models.ledger import Account, Journal
from ledgerone.modules.banking.services import BankingService
from ledgerone.modules.purchases.models import PurchaseBill
from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.modules.sales.models import SalesInvoice
from ledgerone.modules.sales.services import SalesService
from ledgerone.services.account_roles import PostingAccountError, PostingAccountService
from ledgerone.services.context import AccessContext
from ledgerone.services.ledger import LedgerError, LedgerService


def _setup():
    organisation = Organisation.query.one()
    accounts = {
        row.code: row
        for row in Account.query.filter_by(organisation_id=organisation.id).all()
    }
    return organisation, accounts, AccessContext.system(organisation.id)


def test_account_type_is_restricted_in_service_and_database(app):
    with app.app_context():
        organisation, _, context = _setup()

        with pytest.raises(LedgerError, match="Account type must be one of"):
            LedgerService.create_account(
                context,
                code="9990",
                name="Invalid classification",
                account_type="banana",
            )

        db.session.add(
            Account(
                organisation_id=organisation.id,
                code="9991",
                name="Invalid raw classification",
                account_type="banana",
            )
        )
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_parent_and_child_accounts_must_share_classification(app):
    with app.app_context():
        _, accounts, context = _setup()

        with pytest.raises(LedgerError, match="incompatible with child type"):
            LedgerService.create_account(
                context,
                code="5401",
                name="Wrong child",
                account_type="expense",
                parent_id=accounts["4000"].id,
            )

        child = LedgerService.create_account(
            context,
            code="5402",
            name="Travel child",
            account_type="expense",
            parent_id=accounts["5000"].id,
        )
        assert child.parent_id == accounts["5000"].id


def test_sales_invoice_rejects_non_income_revenue_account_without_side_effects(app):
    with app.app_context():
        organisation, accounts, context = _setup()
        customer = SalesService.create_customer(context, name="Role Test Customer")
        before_journals = Journal.query.count()

        with pytest.raises(PostingAccountError, match="sales_revenue"):
            SalesService.create_invoice(
                context,
                customer_id=customer.id,
                invoice_number=None,
                invoice_date=date(2026, 10, 3),
                due_date=date(2026, 11, 2),
                description="Invalid revenue role",
                amount="100.00",
                receivable_account_id=accounts["1200"].id,
                revenue_account_id=accounts["5000"].id,
                currency=organisation.base_currency,
            )
        db.session.rollback()

        assert SalesInvoice.query.count() == 0
        assert Journal.query.count() == before_journals


def test_purchase_bill_rejects_income_as_purchase_cost_without_side_effects(app):
    with app.app_context():
        organisation, accounts, context = _setup()
        supplier = PurchasesService.create_supplier(context, name="Role Test Supplier")
        before_journals = Journal.query.count()

        with pytest.raises(PostingAccountError, match="purchase_cost"):
            PurchasesService.create_bill(
                context,
                supplier_id=supplier.id,
                bill_number="ROLE-001",
                bill_date=date(2026, 10, 3),
                due_date=date(2026, 11, 2),
                description="Invalid cost role",
                amount="100.00",
                payable_account_id=accounts["2100"].id,
                expense_account_id=accounts["4000"].id,
                currency=organisation.base_currency,
            )
        db.session.rollback()

        assert PurchaseBill.query.count() == 0
        assert Journal.query.count() == before_journals


def test_purchase_bill_allows_asset_cost_account(app):
    with app.app_context():
        organisation, accounts, context = _setup()
        supplier = PurchasesService.create_supplier(context, name="Asset Supplier")

        bill = PurchasesService.create_bill(
            context,
            supplier_id=supplier.id,
            bill_number="ASSET-001",
            bill_date=date(2026, 10, 3),
            due_date=date(2026, 11, 2),
            description="Capital purchase",
            amount="250.00",
            payable_account_id=accounts["2100"].id,
            expense_account_id=accounts["1000"].id,
            currency=organisation.base_currency,
        )

        assert bill.posted_journal_id


def test_bank_link_requires_active_non_control_asset_account(app):
    with app.app_context():
        organisation, accounts, context = _setup()

        with pytest.raises(PostingAccountError, match="bank"):
            BankingService.create_account(
                context,
                name="Invalid liability bank",
                institution="Test",
                currency=organisation.base_currency,
                ledger_account_id=accounts["2000"].id,
            )

        with pytest.raises(PostingAccountError, match="control accounts"):
            BankingService.create_account(
                context,
                name="Invalid AR bank",
                institution="Test",
                currency=organisation.base_currency,
                ledger_account_id=accounts["1200"].id,
            )

        bank = BankingService.create_account(
            context,
            name="Valid current account",
            institution="Test",
            currency=organisation.base_currency,
            ledger_account_id=accounts["1000"].id,
        )
        assert bank.ledger_account_id == accounts["1000"].id


def test_default_posting_accounts_are_central_and_role_validated(app):
    with app.app_context():
        _, accounts, context = _setup()

        selected = PostingAccountService.configure_default(
            context, "sales_revenue", accounts["4000"].id
        )
        assert selected.id == accounts["4000"].id
        assert (
            PostingAccountService.default_account_id(
                context.organisation_id, "sales_revenue"
            )
            == accounts["4000"].id
        )

        with pytest.raises(PostingAccountError, match="sales_revenue"):
            PostingAccountService.configure_default(
                context, "sales_revenue", accounts["5000"].id
            )


def test_privileged_posting_role_override_requires_reason_and_is_auditable_policy(app):
    with app.app_context():
        _, accounts, context = _setup()

        with pytest.raises(PostingAccountError, match="requires a reason"):
            PostingAccountService.set_override(
                context,
                accounts["5000"].id,
                "sales_revenue",
                enabled=True,
                reason="",
            )

        PostingAccountService.set_override(
            context,
            accounts["5000"].id,
            "sales_revenue",
            enabled=True,
            reason="Approved exceptional classification for migration",
        )
        assert (
            PostingAccountService.validate(
                context, accounts["5000"].id, "sales_revenue"
            ).id
            == accounts["5000"].id
        )
