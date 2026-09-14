from decimal import Decimal

from ledgerone.extensions import db
from ledgerone.models.core import new_id
from ledgerone.models.ledger import Account, Journal, JournalLine
from ledgerone.modules.sales.models import (
    Customer,
    SalesInvoice,
    SalesInvoiceLine,
    SalesPayment,
    SalesPaymentAllocation,
)
from ledgerone.services.audit import record_audit_event
from ledgerone.services.context import AccessContext
from ledgerone.services.ledger import LedgerService


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


class SalesService:
    @staticmethod
    def list_customers(context: AccessContext):
        return Customer.query.filter_by(
            organisation_id=context.organisation_id, is_active=True
        ).order_by(Customer.name.asc()).all()

    @staticmethod
    def create_customer(context: AccessContext, *, name: str, email: str | None = None,
                        phone: str | None = None):
        if not context.can("sales.write"):
            raise PermissionError("sales.write")
        if not name.strip():
            raise ValueError("Customer name is required")
        customer = Customer(
            organisation_id=context.organisation_id,
            name=name.strip(),
            email=(email or "").strip() or None,
            phone=(phone or "").strip() or None,
        )
        db.session.add(customer)
        db.session.flush()
        record_audit_event(
            context,
            module_id="sales",
            action="customer_created",
            entity_type="customer",
            entity_id=customer.id,
            detail={"name": customer.name, "email": customer.email},
        )
        db.session.commit()
        return customer

    @staticmethod
    def list_invoices(context: AccessContext, limit: int = 100):
        return (
            SalesInvoice.query.filter_by(organisation_id=context.organisation_id)
            .order_by(SalesInvoice.invoice_date.desc(), SalesInvoice.created_at.desc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def invoice_allocated(invoice_id: str) -> Decimal:
        value = (
            db.session.query(db.func.coalesce(db.func.sum(SalesPaymentAllocation.amount), 0))
            .filter(SalesPaymentAllocation.invoice_id == invoice_id)
            .scalar()
        )
        return _money(value)

    @staticmethod
    def invoice_outstanding(invoice: SalesInvoice) -> Decimal:
        return max(Decimal("0.00"), _money(invoice.total) - SalesService.invoice_allocated(invoice.id))

    @staticmethod
    def list_payments(context: AccessContext, limit: int = 100):
        return (
            SalesPayment.query.filter_by(organisation_id=context.organisation_id)
            .order_by(SalesPayment.payment_date.desc(), SalesPayment.created_at.desc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def payment_allocated(payment_id: str) -> Decimal:
        value = (
            db.session.query(db.func.coalesce(db.func.sum(SalesPaymentAllocation.amount), 0))
            .filter(SalesPaymentAllocation.payment_id == payment_id)
            .scalar()
        )
        return _money(value)

    @staticmethod
    def create_invoice(context: AccessContext, *, customer_id: str, invoice_number: str,
                       invoice_date, due_date, description: str, amount,
                       receivable_account_id: str, revenue_account_id: str,
                       currency: str = "GBP"):
        if not context.can("sales.write"):
            raise PermissionError("sales.write")
        amount = _money(amount)
        if amount <= 0:
            raise ValueError("Invoice amount must be greater than zero")
        customer = db.session.get(Customer, customer_id)
        if not customer or customer.organisation_id != context.organisation_id:
            raise ValueError("Invalid customer")
        if SalesInvoice.query.filter_by(
            organisation_id=context.organisation_id, invoice_number=invoice_number
        ).first():
            raise ValueError("Invoice number already exists")

        invoice = SalesInvoice(
            organisation_id=context.organisation_id,
            customer_id=customer.id,
            invoice_number=invoice_number.strip(),
            invoice_date=invoice_date,
            due_date=due_date,
            currency=currency.upper(),
            status="posting",
            subtotal=amount,
            total=amount,
        )
        db.session.add(invoice)
        db.session.flush()
        db.session.add(
            SalesInvoiceLine(
                invoice_id=invoice.id,
                line_number=1,
                description=description.strip() or "Sales",
                quantity=1,
                unit_price=amount,
                net_amount=amount,
                revenue_account_id=revenue_account_id,
            )
        )

        try:
            journal = LedgerService.post_journal(
                context,
                journal_date=invoice_date,
                description=f"Sales invoice {invoice.invoice_number} - {customer.name}",
                reference=invoice.invoice_number,
                source_module="sales",
                source_reference=invoice.id,
                lines=[
                    {
                        "account_id": receivable_account_id,
                        "debit": amount,
                        "credit": 0,
                        "description": customer.name,
                        "currency": currency.upper(),
                        "dimensions": {"customer_id": customer.id, "invoice_id": invoice.id},
                    },
                    {
                        "account_id": revenue_account_id,
                        "debit": 0,
                        "credit": amount,
                        "description": description.strip() or "Sales",
                        "currency": currency.upper(),
                        "dimensions": {"customer_id": customer.id, "invoice_id": invoice.id},
                    },
                ],
                commit=False,
            )
            invoice.posted_journal_id = journal.id
            invoice.status = "posted"
            record_audit_event(
                context,
                module_id="sales",
                action="invoice_posted",
                entity_type="sales_invoice",
                entity_id=invoice.id,
                detail={
                    "invoice_number": invoice.invoice_number,
                    "customer_id": customer.id,
                    "journal_id": journal.id,
                    "total": str(amount),
                    "currency": invoice.currency,
                },
            )
            db.session.commit()
            return invoice
        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def record_payment(context: AccessContext, *, customer_id: str, payment_date,
                       amount, bank_account_id: str, receivable_account_id: str,
                       reference: str | None = None, currency: str = "GBP"):
        if not context.can("sales.write"):
            raise PermissionError("sales.write")
        amount = _money(amount)
        if amount <= 0:
            raise ValueError("Payment amount must be greater than zero")
        customer = db.session.get(Customer, customer_id)
        if not customer or customer.organisation_id != context.organisation_id:
            raise ValueError("Invalid customer")
        bank_account = db.session.get(Account, bank_account_id)
        receivable = db.session.get(Account, receivable_account_id)
        if not bank_account or bank_account.organisation_id != context.organisation_id:
            raise ValueError("Invalid bank ledger account")
        if not receivable or receivable.organisation_id != context.organisation_id:
            raise ValueError("Invalid receivables account")

        payment_id = new_id()
        try:
            journal = LedgerService.post_journal(
                context,
                journal_date=payment_date,
                description=f"Customer payment - {customer.name}",
                reference=(reference or "").strip() or None,
                source_module="sales",
                source_reference=payment_id,
                lines=[
                    {
                        "account_id": bank_account.id,
                        "debit": amount,
                        "credit": 0,
                        "description": customer.name,
                        "currency": currency.upper(),
                        "dimensions": {"customer_id": customer.id, "sales_payment_id": payment_id},
                    },
                    {
                        "account_id": receivable.id,
                        "debit": 0,
                        "credit": amount,
                        "description": customer.name,
                        "currency": currency.upper(),
                        "dimensions": {"customer_id": customer.id, "sales_payment_id": payment_id},
                    },
                ],
                commit=False,
            )
            payment = SalesPayment(
                id=payment_id,
                organisation_id=context.organisation_id,
                customer_id=customer.id,
                payment_date=payment_date,
                reference=(reference or "").strip() or journal.reference,
                amount=amount,
                currency=currency.upper(),
                journal_id=journal.id,
                status="unallocated",
            )
            db.session.add(payment)
            record_audit_event(
                context,
                module_id="sales",
                action="payment_recorded",
                entity_type="sales_payment",
                entity_id=payment.id,
                detail={"customer_id": customer.id, "journal_id": journal.id, "amount": str(amount)},
            )
            db.session.commit()
            return payment
        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def adopt_payment_journal(context: AccessContext, *, customer_id: str, journal_id: str,
                              receivable_account_id: str, currency: str = "GBP"):
        if not context.can("sales.write"):
            raise PermissionError("sales.write")
        customer = db.session.get(Customer, customer_id)
        journal = db.session.get(Journal, journal_id)
        if not customer or customer.organisation_id != context.organisation_id:
            raise ValueError("Invalid customer")
        if not journal or journal.organisation_id != context.organisation_id or journal.status != "posted":
            raise ValueError("Invalid posted journal")
        if SalesPayment.query.filter_by(
            organisation_id=context.organisation_id, journal_id=journal.id
        ).first():
            raise ValueError("Journal is already registered as a customer payment")
        receivable = db.session.get(Account, receivable_account_id)
        if not receivable or receivable.organisation_id != context.organisation_id:
            raise ValueError("Invalid receivables account")
        amount = _money(
            db.session.query(
                db.func.coalesce(db.func.sum(JournalLine.credit - JournalLine.debit), 0)
            )
            .filter(JournalLine.journal_id == journal.id, JournalLine.account_id == receivable.id)
            .scalar()
        )
        if amount <= 0:
            raise ValueError("Journal does not contain a net credit to the selected receivables account")
        payment = SalesPayment(
            organisation_id=context.organisation_id,
            customer_id=customer.id,
            payment_date=journal.journal_date,
            reference=journal.reference,
            amount=amount,
            currency=currency.upper(),
            journal_id=journal.id,
            status="unallocated",
        )
        db.session.add(payment)
        db.session.flush()
        record_audit_event(
            context,
            module_id="sales",
            action="payment_journal_adopted",
            entity_type="sales_payment",
            entity_id=payment.id,
            detail={"customer_id": customer.id, "journal_id": journal.id, "amount": str(amount)},
        )
        db.session.commit()
        return payment

    @staticmethod
    def allocate_payment(context: AccessContext, payment_id: str, allocations: list[dict]):
        if not context.can("sales.write"):
            raise PermissionError("sales.write")
        payment = db.session.get(SalesPayment, payment_id)
        if not payment or payment.organisation_id != context.organisation_id:
            raise ValueError("Customer payment not found")
        existing_total = SalesService.payment_allocated(payment.id)
        available = _money(payment.amount) - existing_total
        requested = sum((_money(item.get("amount")) for item in allocations), Decimal("0.00"))
        if requested <= 0:
            raise ValueError("Allocation amount must be greater than zero")
        if requested > available:
            raise ValueError("Allocations exceed the unallocated payment amount")

        try:
            affected = []
            for item in allocations:
                amount = _money(item.get("amount"))
                if amount <= 0:
                    continue
                invoice = db.session.get(SalesInvoice, item.get("invoice_id"))
                if (
                    not invoice
                    or invoice.organisation_id != context.organisation_id
                    or invoice.customer_id != payment.customer_id
                ):
                    raise ValueError("Invalid invoice for this customer payment")
                outstanding = SalesService.invoice_outstanding(invoice)
                if amount > outstanding:
                    raise ValueError(f"Allocation exceeds outstanding amount for {invoice.invoice_number}")
                row = SalesPaymentAllocation.query.filter_by(
                    payment_id=payment.id, invoice_id=invoice.id
                ).first()
                if row:
                    row.amount = _money(row.amount) + amount
                else:
                    db.session.add(
                        SalesPaymentAllocation(
                            payment_id=payment.id,
                            invoice_id=invoice.id,
                            amount=amount,
                        )
                    )
                affected.append(invoice)

            db.session.flush()
            for invoice in affected:
                outstanding = SalesService.invoice_outstanding(invoice)
                invoice.status = "paid" if outstanding == 0 else "part_paid"

            allocated_total = SalesService.payment_allocated(payment.id)
            payment.status = "allocated" if allocated_total == _money(payment.amount) else "partially_allocated"
            record_audit_event(
                context,
                module_id="sales",
                action="payment_allocated",
                entity_type="sales_payment",
                entity_id=payment.id,
                detail={
                    "allocated": str(requested),
                    "allocated_total": str(allocated_total),
                    "payment_amount": str(payment.amount),
                },
            )
            db.session.commit()
            return payment
        except Exception:
            db.session.rollback()
            raise
