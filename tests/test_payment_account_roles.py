from datetime import date

import pytest

from ledgerone.extensions import db
from ledgerone.models.core import Organisation
from ledgerone.models.ledger import Account, Journal
from ledgerone.modules.purchases.models import PurchasePayment
from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.modules.sales.models import SalesPayment
from ledgerone.modules.sales.services import SalesService
from ledgerone.services.context import AccessContext
from ledgerone.services.control_accounts import ControlAccountError


def _setup():
    organisation = Organisation.query.one()
    accounts = {
        row.code: row
        for row in Account.query.filter_by(organisation_id=organisation.id).all()
    }
    return organisation, accounts, AccessContext.system(organisation.id)


def test_customer_payment_rejects_same_bank_and_receivables_account_without_side_effects(app):
    with app.app_context():
        organisation, accounts, context = _setup()
        customer = SalesService.create_customer(context, name="Same Account Customer")
        journal_count = Journal.query.count()

        with pytest.raises(ControlAccountError, match="cannot be used as a bank ledger account|must be different"):
            SalesService.record_payment(
                context,
                customer_id=customer.id,
                payment_date=date(2026, 9, 15),
                amount="4000.00",
                bank_account_id=accounts["1200"].id,
                receivable_account_id=accounts["1200"].id,
                currency=organisation.base_currency,
            )
        db.session.rollback()

        assert SalesPayment.query.count() == 0
        assert Journal.query.count() == journal_count


def test_supplier_payment_rejects_same_bank_and_payables_account_without_side_effects(app):
    with app.app_context():
        organisation, accounts, context = _setup()
        supplier = PurchasesService.create_supplier(context, name="Same Account Supplier")
        journal_count = Journal.query.count()

        with pytest.raises(ControlAccountError, match="cannot be used as a bank ledger account|must be different"):
            PurchasesService.record_payment(
                context,
                supplier_id=supplier.id,
                payment_date=date(2026, 9, 15),
                amount="4000.00",
                bank_account_id=accounts["2100"].id,
                payable_account_id=accounts["2100"].id,
                currency=organisation.base_currency,
            )
        db.session.rollback()

        assert PurchasePayment.query.count() == 0
        assert Journal.query.count() == journal_count
