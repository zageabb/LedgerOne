from decimal import Decimal

from ledgerone.extensions import db
from ledgerone.models.core import new_id
from ledgerone.models.ledger import Account, Journal, JournalLine
from ledgerone.modules.sales.models import (
    Customer,
    SalesInvoice,
    SalesCreditRefund,
    SalesInvoiceLine,
    SalesPayment,
    SalesPaymentAllocation,
)
from ledgerone.modules.sales.numbering import assign_sales_invoice_number
from ledgerone.services.audit import record_audit_event
from ledgerone.services.context import AccessContext
from ledgerone.services.ledger import LedgerService
from ledgerone.services.payment_terms import PaymentTermsService


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
                        phone: str | None = None, payment_terms_days: int | None = None):
        if not context.can("sales.write"):
            raise PermissionError("sales.write")
        if not name.strip():
            raise ValueError("Customer name is required")
        if payment_terms_days is not None:
            payment_terms_days = PaymentTermsService.customer_days(
                context.organisation_id, payment_terms_days
            )
        customer = Customer(
            organisation_id=context.organisation_id,
            name=name.strip(),
            email=(email or "").strip() or None,
            phone=(phone or "").strip() or None,
            payment_terms_days=payment_terms_days,
        )
        db.session.add(customer)
        db.session.flush()
        record_audit_event(
            context,
            module_id="sales",
            action="customer_created",
            entity_type="customer",
            entity_id=customer.id,
            detail={
                "name": customer.name,
                "email": customer.email,
                "payment_terms_days": customer.payment_terms_days,
            },
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
    def payment_refunded(payment_id: str) -> Decimal:
        value = (
            db.session.query(db.func.coalesce(db.func.sum(SalesCreditRefund.amount), 0))
            .filter(SalesCreditRefund.source_payment_id == payment_id)
            .scalar()
        )
        return _money(value)

    @staticmethod
    def payment_available(payment_id: str) -> Decimal:
        payment = db.session.get(SalesPayment, payment_id)
        if not payment:
            return Decimal("0.00")
        consumed = SalesService.payment_allocated(payment_id) + SalesService.payment_refunded(payment_id)
        return max(Decimal("0.00"), _money(payment.amount) - consumed)

    @staticmethod
    def customer_credit_balance(context: AccessContext, customer_id: str) -> Decimal:
        rows = SalesPayment.query.filter_by(
            organisation_id=context.organisation_id,
            customer_id=customer_id,
        ).all()
        return sum((SalesService.payment_available(row.id) for row in rows), Decimal("0.00"))

    @staticmethod
    def list_credit_refunds(context: AccessContext, limit: int = 100):
        return (
            SalesCreditRefund.query.filter_by(organisation_id=context.organisation_id)
            .order_by(SalesCreditRefund.refund_date.desc(), SalesCreditRefund.created_at.desc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def refresh_payment_status(payment: SalesPayment) -> None:
        allocated = SalesService.payment_allocated(payment.id)
        refunded = SalesService.payment_refunded(payment.id)
        consumed = allocated + refunded
        total = _money(payment.amount)
        if consumed <= 0:
            payment.status = "unallocated"
        elif consumed >= total:
            if refunded > 0 and allocated > 0:
                payment.status = "settled"
            elif refunded > 0:
                payment.status = "refunded"
            else:
                payment.status = "allocated"
        else:
            payment.status = "partially_used" if refunded > 0 else "partially_allocated"

    @staticmethod
    def refresh_invoice_status(invoice: SalesInvoice) -> None:
        from ledgerone.modules.sales.credit_models import SalesCreditNote

        credited = _money(
            db.session.query(db.func.coalesce(db.func.sum(SalesCreditNote.total), 0))
            .filter(SalesCreditNote.invoice_id == invoice.id)
            .scalar()
        )
        allocated = SalesService.invoice_allocated(invoice.id)
        outstanding = max(Decimal("0.00"), _money(invoice.total) - allocated)
        if credited >= _money(invoice.total):
            invoice.status = "credited"
        elif outstanding == 0:
            invoice.status = "paid"
        elif credited > 0:
            invoice.status = "part_credited"
        elif allocated > 0:
            invoice.status = "part_paid"
        else:
            invoice.status = "posted"

    @staticmethod
    def record_credit_refund(
        context: AccessContext,
        *,
        source_payment_id: str,
        refund_date,
        amount,
        bank_account_id: str,
        receivable_account_id: str,
        reference: str | None = None,
    ):
        if not context.can("sales.write"):
            raise PermissionError("sales.write")
        source = db.session.get(SalesPayment, source_payment_id)
        if not source or source.organisation_id != context.organisation_id:
            raise ValueError("Customer credit source not found")
        amount = _money(amount)
        if amount <= 0:
            raise ValueError("Refund amount must be greater than zero")
        available = SalesService.payment_available(source.id)
        if amount > available:
            raise ValueError("Refund exceeds the available customer credit")

        bank = db.session.get(Account, bank_account_id)
        receivable = db.session.get(Account, receivable_account_id)
        if (
            not bank
            or bank.organisation_id != context.organisation_id
            or not bank.is_active
            or bank.account_type != "asset"
            or bank.is_control_account
        ):
            raise ValueError("Bank ledger account must be an active non-control asset account")
        if (
            not receivable
            or receivable.organisation_id != context.organisation_id
            or not receivable.is_active
            or receivable.account_type != "asset"
            or (receivable.metadata_json or {}).get("control_role") != "accounts_receivable"
        ):
            raise ValueError("Receivables account must be the configured accounts-receivable control account")
        if bank.id == receivable.id:
            raise ValueError("Bank and receivables accounts must be different")

        refund_id = new_id()
        try:
            journal = LedgerService.post_journal(
                context,
                journal_date=refund_date,
                description=f"Customer credit refund - {source.customer.name}",
                reference=(reference or "").strip() or source.reference,
                source_module="sales",
                source_reference=refund_id,
                lines=[
                    {
                        "account_id": receivable.id,
                        "debit": amount,
                        "credit": 0,
                        "description": source.customer.name,
                        "currency": source.currency,
                        "dimensions": {
                            "customer_id": source.customer_id,
                            "sales_credit_refund_id": refund_id,
                            "source_payment_id": source.id,
                        },
                    },
                    {
                        "account_id": bank.id,
                        "debit": 0,
                        "credit": amount,
                        "description": source.customer.name,
                        "currency": source.currency,
                        "dimensions": {
                            "customer_id": source.customer_id,
                            "sales_credit_refund_id": refund_id,
                            "source_payment_id": source.id,
                        },
                    },
                ],
                commit=False,
            )
            refund = SalesCreditRefund(
                id=refund_id,
                organisation_id=context.organisation_id,
                customer_id=source.customer_id,
                source_payment_id=source.id,
                refund_date=refund_date,
                amount=amount,
                currency=source.currency,
                bank_account_id=bank.id,
                receivable_account_id=receivable.id,
                journal_id=journal.id,
                reference=(reference or "").strip() or journal.reference,
            )
            db.session.add(refund)
            db.session.flush()
            SalesService.refresh_payment_status(source)
            record_audit_event(
                context,
                module_id="sales",
                action="customer_credit_refunded",
                entity_type="sales_credit_refund",
                entity_id=refund.id,
                detail={
                    "customer_id": source.customer_id,
                    "source_payment_id": source.id,
                    "journal_id": journal.id,
                    "amount": str(amount),
                    "remaining_credit": str(SalesService.payment_available(source.id)),
                },
            )
            db.session.commit()
            return refund
        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def create_invoice(context: AccessContext, *, customer_id: str, invoice_number: str | None,
                       invoice_date, due_date, description: str, amount,
                       tax_point=None,
                       receivable_account_id: str, revenue_account_id: str,
                       currency: str = "GBP", tax_code_id: str | None = None,
                       metadata: dict | None = None, commit: bool = True):
        if not context.can("sales.write"):
            raise PermissionError("sales.write")
        amount = _money(amount)
        if amount <= 0:
            raise ValueError("Invoice amount must be greater than zero")
        customer = db.session.get(Customer, customer_id)
        if not customer or customer.organisation_id != context.organisation_id:
            raise ValueError("Invalid customer")
        if due_date is None:
            due_date = PaymentTermsService.customer_due_date(
                context.organisation_id,
                invoice_date,
                customer.payment_terms_days,
            )
        if due_date < invoice_date:
            raise ValueError("Invoice due date cannot be before the invoice date")

        from ledgerone.modules.tax.services import TaxService
        effective_tax_point = tax_point or invoice_date
        tax_code = TaxService.code_for_use(context, tax_code_id, "sales")
        if tax_code:
            TaxService.assert_tax_point_open(context, effective_tax_point)
        tax_amount = TaxService.tax_amount(amount, tax_code)
        total = amount + tax_amount
        if tax_amount and (not tax_code or not tax_code.sales_tax_account_id):
            raise ValueError("Selected tax code has no output VAT account")

        invoice_id = new_id()
        try:
            issued_number = assign_sales_invoice_number(
                context,
                invoice_id=invoice_id,
                invoice_date=invoice_date,
                requested_number=invoice_number,
            )
            invoice = SalesInvoice(
                id=invoice_id,
                organisation_id=context.organisation_id,
                customer_id=customer.id,
                invoice_number=issued_number,
                invoice_date=invoice_date,
                tax_point=effective_tax_point,
                due_date=due_date,
                currency=currency.upper(),
                status="posting",
                subtotal=amount,
                tax_total=tax_amount,
                total=total,
                metadata_json=dict(metadata or {}),
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
                    tax_amount=tax_amount,
                    tax_code_id=tax_code.id if tax_code else None,
                    revenue_account_id=revenue_account_id,
                )
            )

            journal_lines = [
                {
                    "account_id": receivable_account_id,
                    "debit": total,
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
                    "dimensions": {
                        "customer_id": customer.id,
                        "invoice_id": invoice.id,
                        "tax_code_id": tax_code.id if tax_code else None,
                    },
                },
            ]
            if tax_amount:
                journal_lines.append(
                    {
                        "account_id": tax_code.sales_tax_account_id,
                        "debit": 0,
                        "credit": tax_amount,
                        "description": f"{tax_code.code} output VAT",
                        "currency": currency.upper(),
                        "dimensions": {
                            "customer_id": customer.id,
                            "invoice_id": invoice.id,
                            "tax_code_id": tax_code.id,
                        },
                    }
                )

            journal = LedgerService.post_journal(
                context,
                journal_date=invoice_date,
                description=f"Sales invoice {invoice.invoice_number} - {customer.name}",
                reference=invoice.invoice_number,
                source_module="sales",
                source_reference=invoice.id,
                lines=journal_lines,
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
                    "subtotal": str(amount),
                    "tax_total": str(tax_amount),
                    "total": str(total),
                    "tax_code": tax_code.code if tax_code else None,
                    "tax_point": invoice.tax_point.isoformat(),
                    "currency": invoice.currency,
                    "due_date": invoice.due_date.isoformat(),
                },
            )
            if commit:
                db.session.commit()
            else:
                db.session.flush()
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
        available = SalesService.payment_available(payment.id)
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
                SalesService.refresh_invoice_status(invoice)

            allocated_total = SalesService.payment_allocated(payment.id)
            SalesService.refresh_payment_status(payment)
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