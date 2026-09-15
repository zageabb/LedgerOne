from datetime import date
from decimal import Decimal

import pytest

from ledgerone.extensions import db
from ledgerone.models.core import Organisation
from ledgerone.models.ledger import Account
from ledgerone.modules.expense_claims.models import ExpenseClaim, ExpenseClaimLine
from ledgerone.modules.expense_claims.services import ExpenseClaimService
from ledgerone.modules.purchases.credit_models import PurchaseCreditNote
from ledgerone.modules.purchases.credits import PurchaseCreditService
from ledgerone.modules.purchases.models import PurchaseBill, PurchaseBillLine
from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.modules.sales.credit_models import SalesCreditNote
from ledgerone.modules.sales.credits import SalesCreditService
from ledgerone.modules.sales.models import SalesInvoice, SalesInvoiceLine
from ledgerone.modules.sales.services import SalesService
from ledgerone.services.context import AccessContext
from ledgerone.services.document_immutability import PostedDocumentImmutableError


def _setup():
    organisation = Organisation.query.one()
    accounts = {
        row.code: row
        for row in Account.query.filter_by(organisation_id=organisation.id).all()
    }
    return organisation, accounts, AccessContext.system(organisation.id)


def _posted_invoice(context, accounts, *, number="IMM-INV-001", amount="100.00"):
    customer = SalesService.create_customer(context, name=f"Customer {number}")
    return SalesService.create_invoice(
        context,
        customer_id=customer.id,
        invoice_number=number,
        invoice_date=date(2026, 9, 15),
        due_date=None,
        description="Original sale",
        amount=amount,
        receivable_account_id=accounts["1200"].id,
        revenue_account_id=accounts["4000"].id,
        currency="GBP",
    )


def _posted_bill(context, accounts, *, number="IMM-BILL-001", amount="80.00"):
    supplier = PurchasesService.create_supplier(context, name=f"Supplier {number}")
    return PurchasesService.create_bill(
        context,
        supplier_id=supplier.id,
        bill_number=number,
        bill_date=date(2026, 9, 15),
        due_date=None,
        description="Original purchase",
        amount=amount,
        payable_account_id=accounts["2100"].id,
        expense_account_id=accounts["5000"].id,
        currency="GBP",
    )


def test_posted_sales_invoice_header_and_lines_are_immutable(app):
    with app.app_context():
        _, accounts, context = _setup()
        invoice = _posted_invoice(context, accounts)
        invoice_id = invoice.id
        line_id = invoice.lines[0].id

        invoice.invoice_date = date(2026, 9, 16)
        with pytest.raises(PostedDocumentImmutableError, match="sales invoice"):
            db.session.commit()
        db.session.rollback()
        assert db.session.get(SalesInvoice, invoice_id).invoice_date == date(2026, 9, 15)

        line = db.session.get(SalesInvoiceLine, line_id)
        line.net_amount = Decimal("999.00")
        with pytest.raises(PostedDocumentImmutableError, match="invoice lines"):
            db.session.commit()
        db.session.rollback()

        line = db.session.get(SalesInvoiceLine, line_id)
        db.session.delete(line)
        with pytest.raises(PostedDocumentImmutableError, match="delete a line"):
            db.session.commit()
        db.session.rollback()

        invoice = db.session.get(SalesInvoice, invoice_id)
        db.session.add(
            SalesInvoiceLine(
                invoice_id=invoice.id,
                line_number=99,
                description="Injected line",
                quantity=1,
                unit_price=1,
                net_amount=1,
                tax_amount=0,
                revenue_account_id=accounts["4000"].id,
            )
        )
        with pytest.raises(PostedDocumentImmutableError, match="add a line"):
            db.session.commit()
        db.session.rollback()

        invoice = db.session.get(SalesInvoice, invoice_id)
        db.session.delete(invoice)
        with pytest.raises(PostedDocumentImmutableError, match="cannot be deleted"):
            db.session.commit()
        db.session.rollback()


def test_posted_purchase_bill_header_and_lines_are_immutable(app):
    with app.app_context():
        _, accounts, context = _setup()
        bill = _posted_bill(context, accounts)
        bill_id = bill.id
        line_id = bill.lines[0].id

        bill.bill_number = "MUTATED-BILL"
        with pytest.raises(PostedDocumentImmutableError, match="purchase bill"):
            db.session.commit()
        db.session.rollback()

        line = db.session.get(PurchaseBillLine, line_id)
        line.expense_account_id = accounts["5100"].id
        with pytest.raises(PostedDocumentImmutableError, match="bill lines"):
            db.session.commit()
        db.session.rollback()

        line = db.session.get(PurchaseBillLine, line_id)
        db.session.delete(line)
        with pytest.raises(PostedDocumentImmutableError, match="delete a line"):
            db.session.commit()
        db.session.rollback()

        bill = db.session.get(PurchaseBill, bill_id)
        db.session.delete(bill)
        with pytest.raises(PostedDocumentImmutableError, match="cannot be deleted"):
            db.session.commit()
        db.session.rollback()


def test_posted_credit_notes_and_expense_claims_are_immutable(app):
    with app.app_context():
        organisation, accounts, context = _setup()
        invoice = _posted_invoice(context, accounts, number="IMM-CREDIT-INV", amount="100.00")
        sales_credit = SalesCreditService.create_credit_note(
            context,
            invoice_id=invoice.id,
            credit_number="IMM-SCN-001",
            credit_date=date(2026, 9, 15),
            amount="10.00",
        )
        sales_credit.description = "Mutated credit"
        with pytest.raises(PostedDocumentImmutableError, match="sales credit note"):
            db.session.commit()
        db.session.rollback()
        assert db.session.get(SalesCreditNote, sales_credit.id).description != "Mutated credit"

        bill = _posted_bill(context, accounts, number="IMM-CREDIT-BILL", amount="100.00")
        purchase_credit = PurchaseCreditService.create_credit_note(
            context,
            bill_id=bill.id,
            credit_number="IMM-PCN-001",
            credit_date=date(2026, 9, 15),
            amount="10.00",
        )
        purchase_credit.credit_number = "MUTATED-PCN"
        with pytest.raises(PostedDocumentImmutableError, match="purchase credit note"):
            db.session.commit()
        db.session.rollback()
        assert db.session.get(PurchaseCreditNote, purchase_credit.id).credit_number == "IMM-PCN-001"

        ExpenseClaimService.seed_defaults(organisation.id)
        accounts = {
            row.code: row
            for row in Account.query.filter_by(organisation_id=organisation.id).all()
        }
        claim = ExpenseClaimService.create_claim(
            context,
            claimant_name="Immutable Claimant",
            claim_number="IMM-EXP-001",
            claim_date=date(2026, 9, 15),
            expense_date=date(2026, 9, 15),
            merchant="Merchant",
            description="Travel",
            amount="20.00",
            expense_account_id=accounts["5200"].id,
            reimbursement_account_id=accounts["2150"].id,
            currency="GBP",
        )
        ExpenseClaimService.submit(context, claim.id)
        claim = ExpenseClaimService.approve_and_post(
            context, claim.id, posting_date=date(2026, 9, 15)
        )
        claim.claimant_name = "Mutated claimant"
        with pytest.raises(PostedDocumentImmutableError, match="expense claim"):
            db.session.commit()
        db.session.rollback()

        claim = db.session.get(ExpenseClaim, claim.id)
        claim.lines[0].description = "Mutated expense line"
        with pytest.raises(PostedDocumentImmutableError, match="expense claim lines"):
            db.session.commit()
        db.session.rollback()


def test_draft_financial_documents_remain_editable(app):
    with app.app_context():
        organisation, accounts, context = _setup()
        customer = SalesService.create_customer(context, name="Draft Customer")
        draft = SalesInvoice(
            organisation_id=organisation.id,
            customer_id=customer.id,
            invoice_number="DRAFT-IMM-001",
            invoice_date=date(2026, 9, 15),
            due_date=date(2026, 10, 15),
            currency="GBP",
            status="draft",
            subtotal=Decimal("10.00"),
            tax_total=Decimal("0.00"),
            total=Decimal("10.00"),
        )
        db.session.add(draft)
        db.session.flush()
        db.session.add(
            SalesInvoiceLine(
                invoice_id=draft.id,
                line_number=1,
                description="Draft line",
                quantity=1,
                unit_price=Decimal("10.00"),
                net_amount=Decimal("10.00"),
                tax_amount=Decimal("0.00"),
                revenue_account_id=accounts["4000"].id,
            )
        )
        db.session.commit()

        draft.invoice_number = "DRAFT-IMM-002"
        draft.lines[0].description = "Edited before posting"
        db.session.commit()

        stored = db.session.get(SalesInvoice, draft.id)
        assert stored.invoice_number == "DRAFT-IMM-002"
        assert stored.lines[0].description == "Edited before posting"
