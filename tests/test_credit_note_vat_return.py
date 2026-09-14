from datetime import date
from decimal import Decimal

from ledgerone.models.core import Organisation
from ledgerone.models.ledger import Account
from ledgerone.module_registry import module_registry
from ledgerone.modules.purchases.credits import PurchaseCreditService
from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.modules.sales.credits import SalesCreditService
from ledgerone.modules.sales.services import SalesService
from ledgerone.modules.settings.services import SettingsService
from ledgerone.modules.tax.models import TaxCode
from ledgerone.modules.tax.services import TaxService
from ledgerone.services.context import AccessContext


def test_credit_notes_reduce_standard_vat_return_boxes(app):
    with app.app_context():
        organisation = Organisation.query.one()
        context = AccessContext.system(organisation.id)
        SettingsService.set_module_enabled(context, "tax", True)
        module_registry.seed_module_defaults(organisation.id, "tax")
        accounts = {
            row.code: row.id
            for row in Account.query.filter_by(organisation_id=organisation.id).all()
        }
        t20 = TaxCode.query.filter_by(organisation_id=organisation.id, code="T20").one()

        customer = SalesService.create_customer(context, name="VAT Credit Customer")
        invoice = SalesService.create_invoice(
            context,
            customer_id=customer.id,
            invoice_number="VAT-CREDIT-SALE",
            invoice_date=date(2026, 9, 10),
            due_date=None,
            description="Sale",
            amount="100.00",
            receivable_account_id=accounts["1200"],
            revenue_account_id=accounts["4000"],
            tax_code_id=t20.id,
        )
        SalesCreditService.create_credit_note(
            context,
            invoice_id=invoice.id,
            credit_number="VAT-SCN-1",
            credit_date=date(2026, 9, 15),
            amount="25.00",
        )

        supplier = PurchasesService.create_supplier(context, name="VAT Credit Supplier")
        bill = PurchasesService.create_bill(
            context,
            supplier_id=supplier.id,
            bill_number="VAT-CREDIT-BUY",
            bill_date=date(2026, 9, 11),
            due_date=None,
            description="Purchase",
            amount="50.00",
            payable_account_id=accounts["2100"],
            expense_account_id=accounts["5000"],
            tax_code_id=t20.id,
        )
        PurchaseCreditService.create_credit_note(
            context,
            bill_id=bill.id,
            credit_number="VAT-PCN-1",
            credit_date=date(2026, 9, 16),
            amount="10.00",
        )

        result = TaxService.vat_return(
            context,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30),
        )
        assert result["box_1_output_vat"] == Decimal("15.00")
        assert result["box_4_input_vat"] == Decimal("8.00")
        assert result["box_5_net_vat"] == Decimal("7.00")
        assert result["box_6_sales_net"] == Decimal("75.00")
        assert result["box_7_purchases_net"] == Decimal("40.00")
        assert result["sales_credit_notes"] == 1
        assert result["purchase_credit_notes"] == 1
