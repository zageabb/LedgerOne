from datetime import date
from decimal import Decimal

import pytest

from ledgerone.extensions import db
from ledgerone.models.core import Organisation
from ledgerone.models.ledger import Account, Journal
from ledgerone.modules.purchases.models import PurchaseBill
from ledgerone.modules.purchases.order_models import PurchaseOrder
from ledgerone.modules.purchases.orders import PurchaseOrderService
from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.modules.settings.services import SettingsService
from ledgerone.modules.tax.models import TaxCode
from ledgerone.services.context import AccessContext
from ledgerone.services.ledger import LedgerError, LedgerService


def _context_and_accounts():
    organisation = Organisation.query.one()
    context = AccessContext.system(organisation.id)
    accounts = {
        row.code: row.id
        for row in Account.query.filter_by(organisation_id=organisation.id).all()
    }
    return context, accounts


def _make_order(context, accounts, *, number="PO-001", tax_code_id=None):
    supplier = PurchasesService.create_supplier(context, name=f"Supplier {number}")
    return PurchaseOrderService.create_order(
        context,
        supplier_id=supplier.id,
        order_number=number,
        order_date=date(2026, 9, 14),
        expected_date=date(2026, 9, 28),
        description="Ordered services",
        amount="100.00",
        payable_account_id=accounts["2100"],
        expense_account_id=accounts["5000"],
        tax_code_id=tax_code_id,
    )


def test_purchase_order_is_non_posting_until_approved_conversion(app):
    with app.app_context():
        context, accounts = _context_and_accounts()
        before_journals = Journal.query.count()
        order = _make_order(context, accounts)

        assert order.status == "draft"
        assert order.total == Decimal("100.00")
        assert order.converted_bill_id is None
        assert Journal.query.count() == before_journals

        with pytest.raises(ValueError, match="Approve the purchase order"):
            PurchaseOrderService.convert_to_bill(
                context,
                order.id,
                bill_number="BILL-FROM-PO-EARLY",
                bill_date=date(2026, 9, 15),
            )

        PurchaseOrderService.set_status(context, order.id, status="approved")
        bill, converted = PurchaseOrderService.convert_to_bill(
            context,
            order.id,
            bill_number="BILL-FROM-PO-001",
            bill_date=date(2026, 9, 15),
            due_date=date(2026, 10, 15),
        )

        assert converted.status == "converted"
        assert converted.converted_bill_id == bill.id
        assert bill.status == "posted"
        assert bill.total == Decimal("100.00")
        assert bill.metadata_json["source_purchase_order_id"] == order.id
        assert bill.metadata_json["source_purchase_order_number"] == "PO-001"
        assert Journal.query.count() == before_journals + 1

        with pytest.raises(ValueError, match="already been converted"):
            PurchaseOrderService.convert_to_bill(
                context,
                order.id,
                bill_number="BILL-DUPLICATE-PO",
                bill_date=date(2026, 9, 16),
            )


def test_vat_purchase_order_converts_through_standard_bill_posting(app):
    with app.app_context():
        context, accounts = _context_and_accounts()
        SettingsService.set_module_enabled(context, "tax", True)
        tax_code = TaxCode.query.filter_by(
            organisation_id=context.organisation_id, code="T20"
        ).one()
        order = _make_order(context, accounts, number="PO-VAT-001", tax_code_id=tax_code.id)

        assert order.subtotal == Decimal("100.00")
        assert order.tax_total == Decimal("20.00")
        assert order.total == Decimal("120.00")
        assert Journal.query.count() == 0

        PurchaseOrderService.set_status(context, order.id, status="approved")
        bill, _ = PurchaseOrderService.convert_to_bill(
            context,
            order.id,
            bill_number="BILL-VAT-PO-001",
            bill_date=date(2026, 9, 15),
        )

        journal = db.session.get(Journal, bill.posted_journal_id)
        by_account = {line.account.code: (line.debit, line.credit) for line in journal.lines}
        assert by_account["5000"] == (Decimal("100.00"), Decimal("0.00"))
        assert by_account["1300"] == (Decimal("20.00"), Decimal("0.00"))
        assert by_account["2100"] == (Decimal("0.00"), Decimal("120.00"))


def test_locked_period_purchase_order_conversion_rolls_back_bill_and_order(app):
    with app.app_context():
        context, accounts = _context_and_accounts()
        order = _make_order(context, accounts, number="PO-LOCKED-001")
        PurchaseOrderService.set_status(context, order.id, status="approved")
        period = LedgerService.create_period(
            context,
            name="October 2026 PO lock",
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 31),
        )
        LedgerService.set_period_locked(context, period.id, locked=True)
        before_bills = PurchaseBill.query.count()
        before_journals = Journal.query.count()

        with pytest.raises(LedgerError, match="locked period"):
            PurchaseOrderService.convert_to_bill(
                context,
                order.id,
                bill_number="BILL-LOCKED-PO",
                bill_date=date(2026, 10, 5),
            )

        db.session.expire_all()
        persisted_order = db.session.get(PurchaseOrder, order.id)
        assert persisted_order.status == "approved"
        assert persisted_order.converted_bill_id is None
        assert PurchaseBill.query.count() == before_bills
        assert Journal.query.count() == before_journals


def test_cancelled_purchase_order_cannot_convert(app):
    with app.app_context():
        context, accounts = _context_and_accounts()
        order = _make_order(context, accounts, number="PO-CANCELLED-001")
        PurchaseOrderService.set_status(context, order.id, status="cancelled")
        with pytest.raises(ValueError, match="cancelled"):
            PurchaseOrderService.convert_to_bill(
                context,
                order.id,
                bill_number="BILL-CANCELLED-PO",
                bill_date=date(2026, 9, 15),
            )
