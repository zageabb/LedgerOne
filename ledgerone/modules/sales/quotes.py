from __future__ import annotations

from datetime import date
from decimal import Decimal

from ledgerone.extensions import db
from ledgerone.models.ledger import Account
from ledgerone.modules.sales.models import Customer
from ledgerone.modules.sales.quote_models import SalesQuote, SalesQuoteLine
from ledgerone.modules.sales.services import SalesService
from ledgerone.modules.tax.services import TaxService
from ledgerone.services.audit import record_audit_event
from ledgerone.services.context import AccessContext


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


class SalesQuoteService:
    @staticmethod
    def list_quotes(context: AccessContext, limit: int = 100):
        return (
            SalesQuote.query.filter_by(organisation_id=context.organisation_id)
            .order_by(SalesQuote.quote_date.desc(), SalesQuote.created_at.desc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def create_quote(
        context: AccessContext,
        *,
        customer_id: str,
        quote_number: str,
        quote_date: date,
        expiry_date: date | None,
        description: str,
        amount,
        receivable_account_id: str,
        revenue_account_id: str,
        currency: str = "GBP",
        tax_code_id: str | None = None,
    ):
        if not context.can("sales.write"):
            raise PermissionError("sales.write")
        quote_number = (quote_number or "").strip()
        if not quote_number:
            raise ValueError("Quote number is required")
        if SalesQuote.query.filter_by(
            organisation_id=context.organisation_id,
            quote_number=quote_number,
        ).first():
            raise ValueError("Quote number already exists")
        if expiry_date and expiry_date < quote_date:
            raise ValueError("Quote expiry date cannot be before the quote date")

        customer = db.session.get(Customer, customer_id)
        if not customer or customer.organisation_id != context.organisation_id:
            raise ValueError("Invalid customer")
        receivable = db.session.get(Account, receivable_account_id)
        revenue = db.session.get(Account, revenue_account_id)
        if not receivable or receivable.organisation_id != context.organisation_id:
            raise ValueError("Invalid receivables account")
        if receivable.account_type != "asset":
            raise ValueError("Receivables account must be an asset account")
        if not revenue or revenue.organisation_id != context.organisation_id:
            raise ValueError("Invalid revenue account")
        if revenue.account_type != "income":
            raise ValueError("Revenue account must be an income account")

        net_amount = _money(amount)
        if net_amount <= 0:
            raise ValueError("Quote amount must be greater than zero")
        tax_code = TaxService.code_for_use(context, tax_code_id, "sales")
        tax_amount = TaxService.tax_amount(net_amount, tax_code)
        total = net_amount + tax_amount
        quote = SalesQuote(
            organisation_id=context.organisation_id,
            customer_id=customer.id,
            quote_number=quote_number,
            quote_date=quote_date,
            expiry_date=expiry_date,
            currency=(currency or "GBP").upper(),
            status="draft",
            subtotal=net_amount,
            tax_total=tax_amount,
            total=total,
            receivable_account_id=receivable.id,
        )
        db.session.add(quote)
        db.session.flush()
        db.session.add(
            SalesQuoteLine(
                quote_id=quote.id,
                line_number=1,
                description=(description or "").strip() or "Sales",
                quantity=1,
                unit_price=net_amount,
                net_amount=net_amount,
                tax_amount=tax_amount,
                tax_code_id=tax_code.id if tax_code else None,
                revenue_account_id=revenue.id,
                dimensions={"tax_code": tax_code.code} if tax_code else {},
            )
        )
        record_audit_event(
            context,
            module_id="sales",
            action="quote_created",
            entity_type="sales_quote",
            entity_id=quote.id,
            detail={
                "quote_number": quote.quote_number,
                "customer_id": customer.id,
                "subtotal": str(net_amount),
                "tax_total": str(tax_amount),
                "total": str(total),
            },
        )
        db.session.commit()
        return quote

    @staticmethod
    def set_status(context: AccessContext, quote_id: str, *, status: str):
        if not context.can("sales.write"):
            raise PermissionError("sales.write")
        status = (status or "").strip().lower()
        if status not in {"draft", "sent", "accepted", "rejected"}:
            raise ValueError("Quote status must be draft, sent, accepted or rejected")
        quote = db.session.get(SalesQuote, quote_id)
        if not quote or quote.organisation_id != context.organisation_id:
            raise ValueError("Quote not found")
        if quote.status == "converted":
            raise ValueError("A converted quote cannot be changed")
        before = quote.status
        quote.status = status
        record_audit_event(
            context,
            module_id="sales",
            action="quote_status_changed",
            entity_type="sales_quote",
            entity_id=quote.id,
            detail={"before": before, "after": status},
        )
        db.session.commit()
        return quote

    @staticmethod
    def convert_to_invoice(
        context: AccessContext,
        quote_id: str,
        *,
        invoice_number: str,
        invoice_date: date,
        due_date: date | None = None,
    ):
        if not context.can("sales.write"):
            raise PermissionError("sales.write")
        quote = db.session.get(SalesQuote, quote_id)
        if not quote or quote.organisation_id != context.organisation_id:
            raise ValueError("Quote not found")
        if quote.status == "converted" or quote.converted_invoice_id:
            raise ValueError("Quote has already been converted")
        if quote.status == "rejected":
            raise ValueError("A rejected quote cannot be converted")
        if quote.expiry_date and quote.expiry_date < invoice_date and quote.status != "accepted":
            raise ValueError("Quote has expired; mark it accepted before conversion")
        if len(quote.lines) != 1:
            raise ValueError("The current quote conversion supports single-line quotes")
        line = quote.lines[0]
        invoice = SalesService.create_invoice(
            context,
            customer_id=quote.customer_id,
            invoice_number=invoice_number,
            invoice_date=invoice_date,
            due_date=due_date,
            description=line.description,
            amount=line.net_amount,
            receivable_account_id=quote.receivable_account_id,
            revenue_account_id=line.revenue_account_id,
            currency=quote.currency,
            tax_code_id=line.tax_code_id,
        )
        quote.status = "converted"
        quote.converted_invoice_id = invoice.id
        invoice.metadata_json = {
            **(invoice.metadata_json or {}),
            "source_quote_id": quote.id,
            "source_quote_number": quote.quote_number,
        }
        record_audit_event(
            context,
            module_id="sales",
            action="quote_converted",
            entity_type="sales_quote",
            entity_id=quote.id,
            detail={
                "quote_number": quote.quote_number,
                "invoice_id": invoice.id,
                "invoice_number": invoice.invoice_number,
            },
        )
        db.session.commit()
        return invoice, quote
