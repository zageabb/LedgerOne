from datetime import date
from decimal import Decimal

import pytest

from ledgerone.extensions import db
from ledgerone.models.core import Organisation
from ledgerone.models.ledger import Account, Journal
from ledgerone.module_registry import module_registry
from ledgerone.modules.purchases.credits import PurchaseCreditService
from ledgerone.modules.purchases.models import PurchasePayment
from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.modules.sales.credits import SalesCreditService
from ledgerone.modules.sales.models import SalesPayment
from ledgerone.modules.sales.services import SalesService
from ledgerone.modules.settings.services import SettingsService
from ledgerone.modules.tax.models import TaxCode
from ledgerone.services.context import AccessContext
from ledgerone.services.ledger import LedgerError, LedgerService


def _setup(app):
    organisation = Organisation.query.one()
    context = AccessContext.system(organisation.id)
    SettingsService.set_module_enabled(context, "tax", True)
    module_registry.seed_module_defaults(organisation.id, "tax")
    accounts = {
        row.code: row.id
        for row in Account.query.filter_by(organisation_id=organisation.id).all()
    }
    tax_code = TaxCode.query.filter_by(organisation_id=organisation.id, code="T20").one()
    return context, accounts, tax_code


def test_sales_credit_note_reverses_revenue_vat_and_reduces_outstanding(app):
    with app.app_context():
        context, accounts, tax_code = _setup(app)
        customer = SalesService.create_customer(context, name="Credit Customer")
        invoice = SalesService.create_invoice(
            context,
            customer_id=customer.id,
            invoice_number="INV-CN-001",
            invoice_date=date(2026, 9, 14),
            due_date=None,
            description="Taxable service",
            amount="100.00",
            receivable_account_id=accounts["1200"],
            revenue_account_id=accounts["4000"],
            tax_code_id=tax_code.id,
        )
        note = SalesCreditService.create_credit_note(
            context,
            invoice_id=invoice.id,
            credit_number="CN-001",
            credit_date=date(2026, 9, 15),
            amount="25.00",
            description="Service adjustment",
        )
        assert note.subtotal == Decimal("25.00")
        assert note.tax_total == Decimal("5.00")
        assert note.total == Decimal("30.00")
        assert SalesService.invoice_outstanding(invoice) == Decimal("90.00")
        journal = db.session.get(Journal, note.posted_journal_id)
        by_account = {line.account.code: (line.debit, line.credit) for line in journal.lines}
        assert by_account["4000"] == (Decimal("25.00"), Decimal("0.00"))
        assert by_account["2200"] == (Decimal("5.00"), Decimal("0.00"))
        assert by_account["1200"] == (Decimal("0.00"), Decimal("30.00"))
        settlement = SalesPayment.query.filter_by(journal_id=journal.id).one()
        assert settlement.settlement_type == "credit_note"
        assert settlement.status == "allocated"


def test_purchase_credit_note_reverses_expense_vat_and_reduces_outstanding(app):
    with app.app_context():
        context, accounts, tax_code = _setup(app)
        supplier = PurchasesService.create_supplier(context, name="Credit Supplier")
        bill = PurchasesService.create_bill(
            context,
            supplier_id=supplier.id,
            bill_number="BILL-CN-001",
            bill_date=date(2026, 9, 14),
            due_date=None,
            description="Taxable cost",
            amount="50.00",
            payable_account_id=accounts["2100"],
            expense_account_id=accounts["5000"],
            tax_code_id=tax_code.id,
        )
        note = PurchaseCreditService.create_credit_note(
            context,
            bill_id=bill.id,
            credit_number="SCN-001",
            credit_date=date(2026, 9, 15),
            amount="10.00",
            description="Supplier adjustment",
        )
        assert note.subtotal == Decimal("10.00")
        assert note.tax_total == Decimal("2.00")
        assert note.total == Decimal("12.00")
        assert PurchasesService.bill_outstanding(bill) == Decimal("48.00")
        journal = db.session.get(Journal, note.posted_journal_id)
        by_account = {line.account.code: (line.debit, line.credit) for line in journal.lines}
        assert by_account["2100"] == (Decimal("12.00"), Decimal("0.00"))
        assert by_account["5000"] == (Decimal("0.00"), Decimal("10.00"))
        assert by_account["1300"] == (Decimal("0.00"), Decimal("2.00"))
        settlement = PurchasePayment.query.filter_by(journal_id=journal.id).one()
        assert settlement.settlement_type == "credit_note"
        assert settlement.status == "allocated"


def test_credit_note_cannot_exceed_original_uncredited_value(app):
    with app.app_context():
        context, accounts, tax_code = _setup(app)
        customer = SalesService.create_customer(context, name="Limit Customer")
        invoice = SalesService.create_invoice(
            context,
            customer_id=customer.id,
            invoice_number="INV-LIMIT-001",
            invoice_date=date(2026, 9, 14),
            due_date=None,
            description="Taxable service",
            amount="100.00",
            receivable_account_id=accounts["1200"],
            revenue_account_id=accounts["4000"],
            tax_code_id=tax_code.id,
        )
        with pytest.raises(ValueError, match="remaining uncredited invoice value"):
            SalesCreditService.create_credit_note(
                context,
                invoice_id=invoice.id,
                credit_number="CN-TOO-MUCH",
                credit_date=date(2026, 9, 15),
                amount="101.00",
            )


def test_credit_note_respects_locked_period(app):
    with app.app_context():
        context, accounts, tax_code = _setup(app)
        customer = SalesService.create_customer(context, name="Locked Credit Customer")
        invoice = SalesService.create_invoice(
            context,
            customer_id=customer.id,
            invoice_number="INV-LOCK-CN",
            invoice_date=date(2026, 9, 14),
            due_date=None,
            description="Taxable service",
            amount="50.00",
            receivable_account_id=accounts["1200"],
            revenue_account_id=accounts["4000"],
            tax_code_id=tax_code.id,
        )
        period = LedgerService.create_period(
            context,
            name="October 2026",
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 31),
        )
        LedgerService.set_period_locked(context, period.id, locked=True)
        with pytest.raises(LedgerError, match="locked period"):
            SalesCreditService.create_credit_note(
                context,
                invoice_id=invoice.id,
                credit_number="CN-LOCKED",
                credit_date=date(2026, 10, 5),
                amount="10.00",
            )
