from datetime import date
from decimal import Decimal

from ledgerone.models.core import Organisation
from ledgerone.models.ledger import Account
from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.modules.reports.services import ReportsService
from ledgerone.modules.sales.services import SalesService
from ledgerone.services.context import AccessContext


def _setup():
    organisation = Organisation.query.one()
    context = AccessContext.system(organisation.id)
    accounts = {
        row.code: row.id
        for row in Account.query.filter_by(organisation_id=organisation.id).all()
    }
    return context, accounts


def test_aged_receivables_uses_payment_dates_for_historical_snapshot(app):
    with app.app_context():
        context, accounts = _setup()
        customer = SalesService.create_customer(context, name="Aging Customer")
        invoice = SalesService.create_invoice(
            context,
            customer_id=customer.id,
            invoice_number="INV-AGING-001",
            invoice_date=date(2026, 8, 1),
            due_date=date(2026, 8, 31),
            description="Aging sale",
            amount="100.00",
            receivable_account_id=accounts["1200"],
            revenue_account_id=accounts["4000"],
        )
        first = SalesService.record_payment(
            context,
            customer_id=customer.id,
            payment_date=date(2026, 9, 15),
            amount="40.00",
            bank_account_id=accounts["1000"],
            receivable_account_id=accounts["1200"],
            reference="AGING-40",
        )
        SalesService.allocate_payment(
            context, first.id, [{"invoice_id": invoice.id, "amount": "40.00"}]
        )
        later = SalesService.record_payment(
            context,
            customer_id=customer.id,
            payment_date=date(2026, 10, 5),
            amount="60.00",
            bank_account_id=accounts["1000"],
            receivable_account_id=accounts["1200"],
            reference="AGING-60",
        )
        SalesService.allocate_payment(
            context, later.id, [{"invoice_id": invoice.id, "amount": "60.00"}]
        )

        report = ReportsService.aged_receivables(context, as_of=date(2026, 9, 30))
        assert len(report["rows"]) == 1
        row = report["rows"][0]
        assert row["number"] == "INV-AGING-001"
        assert row["days_overdue"] == 30
        assert row["bucket"] == "1_30"
        assert row["outstanding"] == Decimal("60.00")
        assert report["totals_by_currency"]["GBP"]["1_30"] == Decimal("60.00")
        assert report["totals_by_currency"]["GBP"]["total"] == Decimal("60.00")

        settled = ReportsService.aged_receivables(context, as_of=date(2026, 10, 10))
        assert settled["rows"] == []
        assert settled["totals_by_currency"] == {}


def test_aged_payables_groups_overdue_bills_and_ignores_future_payment(app):
    with app.app_context():
        context, accounts = _setup()
        supplier = PurchasesService.create_supplier(context, name="Aging Supplier")
        bill = PurchasesService.create_bill(
            context,
            supplier_id=supplier.id,
            bill_number="BILL-AGING-001",
            bill_date=date(2026, 7, 1),
            due_date=date(2026, 7, 15),
            description="Aging purchase",
            amount="50.00",
            payable_account_id=accounts["2100"],
            expense_account_id=accounts["5000"],
        )
        first = PurchasesService.record_payment(
            context,
            supplier_id=supplier.id,
            payment_date=date(2026, 9, 1),
            amount="10.00",
            bank_account_id=accounts["1000"],
            payable_account_id=accounts["2100"],
            reference="AGING-PAY-10",
        )
        PurchasesService.allocate_payment(
            context, first.id, [{"bill_id": bill.id, "amount": "10.00"}]
        )
        later = PurchasesService.record_payment(
            context,
            supplier_id=supplier.id,
            payment_date=date(2026, 10, 5),
            amount="40.00",
            bank_account_id=accounts["1000"],
            payable_account_id=accounts["2100"],
            reference="AGING-PAY-40",
        )
        PurchasesService.allocate_payment(
            context, later.id, [{"bill_id": bill.id, "amount": "40.00"}]
        )

        report = ReportsService.aged_payables(context, as_of=date(2026, 9, 30))
        assert len(report["rows"]) == 1
        row = report["rows"][0]
        assert row["number"] == "BILL-AGING-001"
        assert row["days_overdue"] == 77
        assert row["bucket"] == "61_90"
        assert row["outstanding"] == Decimal("40.00")
        assert report["totals_by_currency"]["GBP"]["61_90"] == Decimal("40.00")
        assert report["totals_by_currency"]["GBP"]["total"] == Decimal("40.00")


def test_aging_keeps_not_yet_due_documents_current(app):
    with app.app_context():
        context, accounts = _setup()
        customer = SalesService.create_customer(context, name="Current Customer")
        SalesService.create_invoice(
            context,
            customer_id=customer.id,
            invoice_number="INV-CURRENT-001",
            invoice_date=date(2026, 9, 20),
            due_date=date(2026, 10, 20),
            description="Future due sale",
            amount="25.00",
            receivable_account_id=accounts["1200"],
            revenue_account_id=accounts["4000"],
        )
        report = ReportsService.aged_receivables(context, as_of=date(2026, 9, 30))
        assert report["rows"][0]["bucket"] == "current"
        assert report["rows"][0]["days_overdue"] == 0
        assert report["totals_by_currency"]["GBP"]["current"] == Decimal("25.00")
