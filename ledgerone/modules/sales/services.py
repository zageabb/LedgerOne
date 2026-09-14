from decimal import Decimal

from ledgerone.extensions import db
from ledgerone.modules.sales.models import Customer, SalesInvoice, SalesInvoiceLine
from ledgerone.services.audit import record_audit_event
from ledgerone.services.context import AccessContext
from ledgerone.services.ledger import LedgerService


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
    def create_invoice(context: AccessContext, *, customer_id: str, invoice_number: str,
                       invoice_date, due_date, description: str, amount,
                       receivable_account_id: str, revenue_account_id: str,
                       currency: str = "GBP"):
        if not context.can("sales.write"):
            raise PermissionError("sales.write")
        amount = Decimal(str(amount)).quantize(Decimal("0.01"))
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
