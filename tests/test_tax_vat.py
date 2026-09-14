from datetime import date
from decimal import Decimal

import pytest

from ledgerone.extensions import db
from ledgerone.models.core import ModuleState, Organisation
from ledgerone.models.ledger import Account, Journal
from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.modules.sales.services import SalesService
from ledgerone.modules.tax.models import TaxCode
from ledgerone.modules.tax.services import TaxError, TaxService
from ledgerone.services.context import AccessContext


def _context_and_accounts(app, *, enable_tax=True):
    with app.app_context():
        organisation = Organisation.query.one()
        state = ModuleState.query.filter_by(
            organisation_id=organisation.id, module_id="tax"
        ).one()
        state.enabled = enable_tax
        db.session.commit()
        accounts = {
            row.code: row.id
            for row in Account.query.filter_by(organisation_id=organisation.id).all()
        }
        tax_codes = {
            row.code: row.id
            for row in TaxCode.query.filter_by(organisation_id=organisation.id).all()
        }
        return AccessContext.system(organisation.id), accounts, tax_codes


def test_tax_defaults_seed_control_accounts_and_uk_codes(app):
    with app.app_context():
        organisation = Organisation.query.one()
        accounts = {
            row.code: row for row in Account.query.filter_by(organisation_id=organisation.id).all()
        }
        assert accounts["1300"].name == "VAT Recoverable"
        assert accounts["1300"].account_type == "asset"
        assert accounts["1300"].is_control_account is True
        assert accounts["2200"].name == "VAT Payable"
        assert accounts["2200"].account_type == "liability"
        assert accounts["2200"].is_control_account is True
        codes = {
            row.code: row for row in TaxCode.query.filter_by(organisation_id=organisation.id).all()
        }
        assert codes["T20"].rate_percent == Decimal("20.0000")
        assert codes["T5"].rate_percent == Decimal("5.0000")
        assert codes["T0"].rate_percent == Decimal("0.0000")
        assert codes["EXEMPT"].treatment == "exempt"
        assert codes["OUT"].treatment == "out_of_scope"


def test_sales_and_purchase_vat_post_to_control_accounts_and_feed_return(app):
    with app.app_context():
        context, accounts, tax_codes = _context_and_accounts(app, enable_tax=True)
        customer = SalesService.create_customer(context, name="VAT Customer")
        supplier = PurchasesService.create_supplier(context, name="VAT Supplier")

        invoice = SalesService.create_invoice(
            context,
            customer_id=customer.id,
            invoice_number="VAT-INV-001",
            invoice_date=date(2026, 9, 14),
            due_date=None,
            description="Taxable services",
            amount="100.00",
            receivable_account_id=accounts["1200"],
            revenue_account_id=accounts["4000"],
            currency="GBP",
            tax_code_id=tax_codes["T20"],
        )
        assert invoice.subtotal == Decimal("100.00")
        assert invoice.tax_total == Decimal("20.00")
        assert invoice.total == Decimal("120.00")
        sales_journal = db.session.get(Journal, invoice.posted_journal_id)
        sales_by_account = {line.account.code: (line.debit, line.credit) for line in sales_journal.lines}
        assert sales_by_account["1200"] == (Decimal("120.00"), Decimal("0.00"))
        assert sales_by_account["4000"] == (Decimal("0.00"), Decimal("100.00"))
        assert sales_by_account["2200"] == (Decimal("0.00"), Decimal("20.00"))

        bill = PurchasesService.create_bill(
            context,
            supplier_id=supplier.id,
            bill_number="VAT-BILL-001",
            bill_date=date(2026, 9, 14),
            due_date=None,
            description="Taxable cost",
            amount="50.00",
            payable_account_id=accounts["2100"],
            expense_account_id=accounts["5000"],
            currency="GBP",
            tax_code_id=tax_codes["T20"],
        )
        assert bill.subtotal == Decimal("50.00")
        assert bill.tax_total == Decimal("10.00")
        assert bill.total == Decimal("60.00")
        purchase_journal = db.session.get(Journal, bill.posted_journal_id)
        purchase_by_account = {line.account.code: (line.debit, line.credit) for line in purchase_journal.lines}
        assert purchase_by_account["5000"] == (Decimal("50.00"), Decimal("0.00"))
        assert purchase_by_account["1300"] == (Decimal("10.00"), Decimal("0.00"))
        assert purchase_by_account["2100"] == (Decimal("0.00"), Decimal("60.00"))

        summary = TaxService.vat_return(
            context,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30),
        )
        assert summary["box_1_output_vat"] == Decimal("20.00")
        assert summary["box_4_input_vat"] == Decimal("10.00")
        assert summary["box_5_net_vat"] == Decimal("10.00")
        assert summary["net_vat_due"] == Decimal("10.00")
        assert summary["position"] == "payable"
        assert summary["box_6_sales_net"] == Decimal("100.00")
        assert summary["box_7_purchases_net"] == Decimal("50.00")


def test_supplying_tax_code_while_tax_module_disabled_is_rejected(app):
    with app.app_context():
        context, accounts, tax_codes = _context_and_accounts(app, enable_tax=False)
        customer = SalesService.create_customer(context, name="No VAT Customer")
        with pytest.raises(TaxError, match="disabled"):
            SalesService.create_invoice(
                context,
                customer_id=customer.id,
                invoice_number="NO-VAT-001",
                invoice_date=date(2026, 9, 14),
                due_date=None,
                description="Should fail",
                amount="100.00",
                receivable_account_id=accounts["1200"],
                revenue_account_id=accounts["4000"],
                tax_code_id=tax_codes["T20"],
            )


def test_vat_return_refuses_unsupported_cash_scheme(app):
    with app.app_context():
        context, _, _ = _context_and_accounts(app, enable_tax=True)
        TaxService.update_profile(
            context,
            jurisdiction="GB",
            is_vat_registered=True,
            registration_number="GB123456789",
            scheme="cash",
            return_frequency="quarterly",
        )
        with pytest.raises(TaxError, match="standard VAT accounting only"):
            TaxService.vat_return(
                context,
                start_date=date(2026, 7, 1),
                end_date=date(2026, 9, 30),
            )
