from datetime import date
from decimal import Decimal

import pytest

from ledgerone.extensions import db
from ledgerone.models.audit import AuditEvent
from ledgerone.models.core import Organisation
from ledgerone.models.ledger import Account, Journal
from ledgerone.modules.purchases.credits import PurchaseCreditService
from ledgerone.modules.purchases.models import PurchasePayment
from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.modules.sales.credits import SalesCreditService
from ledgerone.modules.sales.models import SalesPayment
from ledgerone.modules.sales.services import SalesService
from ledgerone.services.context import AccessContext
from ledgerone.services.control_accounts import ControlAccountService
from ledgerone.services.document_immutability import PostedDocumentImmutableError


def _setup():
    organisation = Organisation.query.one()
    context = AccessContext.system(organisation.id)
    accounts = {
        row.code: row
        for row in Account.query.filter_by(organisation_id=organisation.id).all()
    }
    return context, accounts


def test_fully_paid_invoice_credit_can_allocate_elsewhere_and_refund_remainder(app):
    with app.app_context():
        context, accounts = _setup()
        customer = SalesService.create_customer(context, name="Paid Credit Customer")

        original = SalesService.create_invoice(
            context,
            customer_id=customer.id,
            invoice_number="PAID-CREDIT-001",
            invoice_date=date(2026, 9, 18),
            due_date=None,
            description="Original service",
            amount="100.00",
            receivable_account_id=accounts["1200"].id,
            revenue_account_id=accounts["4000"].id,
        )
        cash = SalesService.record_payment(
            context,
            customer_id=customer.id,
            payment_date=date(2026, 9, 18),
            amount="100.00",
            bank_account_id=accounts["1000"].id,
            receivable_account_id=accounts["1200"].id,
            reference="CASH-100",
        )
        SalesService.allocate_payment(
            context,
            cash.id,
            [{"invoice_id": original.id, "amount": "100.00"}],
        )
        assert original.status == "paid"
        assert SalesService.invoice_outstanding(original) == Decimal("0.00")

        note = SalesCreditService.create_credit_note(
            context,
            invoice_id=original.id,
            credit_number="CN-PAID-001",
            credit_date=date(2026, 9, 18),
            amount="40.00",
            description="Post-payment price adjustment",
        )
        credit = SalesPayment.query.filter_by(journal_id=note.posted_journal_id).one()

        assert credit.settlement_type == "credit_note"
        assert SalesService.payment_allocated(credit.id) == Decimal("0.00")
        assert SalesService.payment_available(credit.id) == Decimal("40.00")
        assert SalesService.customer_credit_balance(context, customer.id) == Decimal("40.00")
        assert SalesService.invoice_allocated(original.id) == Decimal("100.00")
        assert SalesService.invoice_outstanding(original) == Decimal("0.00")

        replacement = SalesService.create_invoice(
            context,
            customer_id=customer.id,
            invoice_number="PAID-CREDIT-002",
            invoice_date=date(2026, 9, 18),
            due_date=None,
            description="Replacement service",
            amount="25.00",
            receivable_account_id=accounts["1200"].id,
            revenue_account_id=accounts["4000"].id,
        )
        SalesService.allocate_payment(
            context,
            credit.id,
            [{"invoice_id": replacement.id, "amount": "25.00"}],
        )
        assert SalesService.invoice_outstanding(replacement) == Decimal("0.00")
        assert SalesService.payment_available(credit.id) == Decimal("15.00")

        refund = SalesService.record_credit_refund(
            context,
            source_payment_id=credit.id,
            refund_date=date(2026, 9, 18),
            amount="15.00",
            bank_account_id=accounts["1000"].id,
            receivable_account_id=accounts["1200"].id,
            reference="CUSTOMER-REFUND-15",
        )
        assert SalesService.payment_available(credit.id) == Decimal("0.00")
        assert SalesService.payment_refunded(credit.id) == Decimal("15.00")
        assert credit.status == "settled"

        journal = db.session.get(Journal, refund.journal_id)
        by_code = {line.account.code: (line.debit, line.credit) for line in journal.lines}
        assert by_code["1200"] == (Decimal("15.00"), Decimal("0.00"))
        assert by_code["1000"] == (Decimal("0.00"), Decimal("15.00"))

        report = ControlAccountService.reconciliation(context, as_of=date(2026, 9, 18))
        ar = next(row for row in report["rows"] if row["role"] == "accounts_receivable")
        assert ar["ledger_balance"] == Decimal("0.00")
        assert ar["subledger_balance"] == Decimal("0.00")
        assert ar["difference"] == Decimal("0.00")

        audit = AuditEvent.query.filter_by(
            organisation_id=context.organisation_id,
            action="customer_credit_refunded",
            entity_id=refund.id,
        ).one()
        assert audit.detail["amount"] == "15.00"


def test_fully_paid_bill_credit_can_allocate_elsewhere_and_record_supplier_refund(app):
    with app.app_context():
        context, accounts = _setup()
        supplier = PurchasesService.create_supplier(context, name="Paid Credit Supplier")

        original = PurchasesService.create_bill(
            context,
            supplier_id=supplier.id,
            bill_number="PAID-BILL-001",
            bill_date=date(2026, 9, 18),
            due_date=None,
            description="Original cost",
            amount="100.00",
            payable_account_id=accounts["2100"].id,
            expense_account_id=accounts["5000"].id,
        )
        cash = PurchasesService.record_payment(
            context,
            supplier_id=supplier.id,
            payment_date=date(2026, 9, 18),
            amount="100.00",
            bank_account_id=accounts["1000"].id,
            payable_account_id=accounts["2100"].id,
            reference="SUP-CASH-100",
        )
        PurchasesService.allocate_payment(
            context,
            cash.id,
            [{"bill_id": original.id, "amount": "100.00"}],
        )
        assert original.status == "paid"
        assert PurchasesService.bill_outstanding(original) == Decimal("0.00")

        note = PurchaseCreditService.create_credit_note(
            context,
            bill_id=original.id,
            credit_number="SCN-PAID-001",
            credit_date=date(2026, 9, 18),
            amount="40.00",
            description="Post-payment supplier adjustment",
        )
        credit = PurchasePayment.query.filter_by(journal_id=note.posted_journal_id).one()

        assert credit.settlement_type == "credit_note"
        assert PurchasesService.payment_allocated(credit.id) == Decimal("0.00")
        assert PurchasesService.payment_available(credit.id) == Decimal("40.00")
        assert PurchasesService.supplier_credit_balance(context, supplier.id) == Decimal("40.00")

        replacement = PurchasesService.create_bill(
            context,
            supplier_id=supplier.id,
            bill_number="PAID-BILL-002",
            bill_date=date(2026, 9, 18),
            due_date=None,
            description="Replacement cost",
            amount="25.00",
            payable_account_id=accounts["2100"].id,
            expense_account_id=accounts["5000"].id,
        )
        PurchasesService.allocate_payment(
            context,
            credit.id,
            [{"bill_id": replacement.id, "amount": "25.00"}],
        )
        assert PurchasesService.bill_outstanding(replacement) == Decimal("0.00")
        assert PurchasesService.payment_available(credit.id) == Decimal("15.00")

        refund = PurchasesService.record_credit_refund(
            context,
            source_payment_id=credit.id,
            refund_date=date(2026, 9, 18),
            amount="15.00",
            bank_account_id=accounts["1000"].id,
            payable_account_id=accounts["2100"].id,
            reference="SUPPLIER-REFUND-15",
        )
        assert PurchasesService.payment_available(credit.id) == Decimal("0.00")
        assert PurchasesService.payment_refunded(credit.id) == Decimal("15.00")
        assert credit.status == "settled"

        journal = db.session.get(Journal, refund.journal_id)
        by_code = {line.account.code: (line.debit, line.credit) for line in journal.lines}
        assert by_code["1000"] == (Decimal("15.00"), Decimal("0.00"))
        assert by_code["2100"] == (Decimal("0.00"), Decimal("15.00"))

        report = ControlAccountService.reconciliation(context, as_of=date(2026, 9, 18))
        ap = next(row for row in report["rows"] if row["role"] == "accounts_payable")
        assert ap["ledger_balance"] == Decimal("0.00")
        assert ap["subledger_balance"] == Decimal("0.00")
        assert ap["difference"] == Decimal("0.00")


def test_credit_cannot_exceed_original_value_not_already_credited(app):
    with app.app_context():
        context, accounts = _setup()
        customer = SalesService.create_customer(context, name="Credit Limit Customer")
        invoice = SalesService.create_invoice(
            context,
            customer_id=customer.id,
            invoice_number="CREDIT-LIMIT-001",
            invoice_date=date(2026, 9, 18),
            due_date=None,
            description="Service",
            amount="100.00",
            receivable_account_id=accounts["1200"].id,
            revenue_account_id=accounts["4000"].id,
        )
        SalesCreditService.create_credit_note(
            context,
            invoice_id=invoice.id,
            credit_number="CREDIT-LIMIT-CN1",
            credit_date=date(2026, 9, 18),
            amount="60.00",
        )
        with pytest.raises(ValueError, match="remaining uncredited invoice value"):
            SalesCreditService.create_credit_note(
                context,
                invoice_id=invoice.id,
                credit_number="CREDIT-LIMIT-CN2",
                credit_date=date(2026, 9, 18),
                amount="41.00",
            )


def test_refund_evidence_is_immutable_and_cannot_exceed_available_credit(app):
    with app.app_context():
        context, accounts = _setup()
        customer = SalesService.create_customer(context, name="Refund Guard Customer")
        payment = SalesService.record_payment(
            context,
            customer_id=customer.id,
            payment_date=date(2026, 9, 18),
            amount="20.00",
            bank_account_id=accounts["1000"].id,
            receivable_account_id=accounts["1200"].id,
        )
        with pytest.raises(ValueError, match="available customer credit"):
            SalesService.record_credit_refund(
                context,
                source_payment_id=payment.id,
                refund_date=date(2026, 9, 18),
                amount="21.00",
                bank_account_id=accounts["1000"].id,
                receivable_account_id=accounts["1200"].id,
            )
        db.session.rollback()

        refund = SalesService.record_credit_refund(
            context,
            source_payment_id=payment.id,
            refund_date=date(2026, 9, 18),
            amount="20.00",
            bank_account_id=accounts["1000"].id,
            receivable_account_id=accounts["1200"].id,
        )
        refund.amount = Decimal("19.00")
        with pytest.raises(PostedDocumentImmutableError, match="customer credit refund"):
            db.session.commit()
        db.session.rollback()


def test_credit_refund_api_routes_are_registered(app):
    rules = {rule.rule for rule in app.url_map.iter_rules()}
    assert "/api/v1/sales/payments/<payment_id>/refund" in rules
    assert "/api/v1/purchases/payments/<payment_id>/refund" in rules
