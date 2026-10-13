"""Supplier invoice references must remain separate from internal controlled numbers."""
from datetime import date

import pytest

from ledgerone.models.core import Organisation
from ledgerone.models.ledger import Account
from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.services.context import AccessContext
from ledgerone.services.ledger import LedgerService


def test_supplier_reference_keeps_internal_bill_number_and_round_trips(app):
    with app.app_context():
        organisation = Organisation.query.one()
        context = AccessContext.system(organisation.id)
        accounts = {row.code: row for row in Account.query.filter_by(organisation_id=organisation.id).all()}
        LedgerService.create_period(
            context, name="October 2026",
            start_date=date(2026, 10, 1), end_date=date(2026, 10, 31),
        )
        supplier = PurchasesService.create_supplier(context, name="Reference supplier")
        kwargs = dict(
            supplier_id=supplier.id, bill_date=date(2026, 10, 3),
            due_date=date(2026, 11, 2), description="Supplier reference test",
            amount="25.00", payable_account_id=accounts["2100"].id,
            expense_account_id=accounts["5000"].id,
            currency=organisation.base_currency,
        )
        bill = PurchasesService.create_bill(
            context, bill_number="INTERNAL-001",
            supplier_invoice_reference=" SUPPLIER-42 ", **kwargs,
        )
        assert bill.bill_number == "INTERNAL-001"
        assert bill.supplier_invoice_reference == "SUPPLIER-42"
        assert PurchasesService.list_bills(context)[0].supplier_invoice_reference == "SUPPLIER-42"

        legacy = PurchasesService.create_bill(context, bill_number="INTERNAL-002", **kwargs)
        assert legacy.supplier_invoice_reference is None

        with pytest.raises(ValueError, match="exceeds 120"):
            PurchasesService.create_bill(
                context, bill_number="INTERNAL-003",
                supplier_invoice_reference="x" * 121, **kwargs,
            )
