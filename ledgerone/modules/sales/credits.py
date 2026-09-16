from __future__ import annotations

from decimal import Decimal

from ledgerone.extensions import db
from ledgerone.models.core import new_id
from ledgerone.models.ledger import Journal
from ledgerone.modules.sales.credit_models import SalesCreditNote
from ledgerone.modules.sales.models import SalesInvoice, SalesPayment, SalesPaymentAllocation
from ledgerone.modules.sales.numbering import assign_sales_credit_number
from ledgerone.modules.sales.services import SalesService
from ledgerone.modules.tax.services import TaxService
from ledgerone.services.audit import record_audit_event
from ledgerone.services.context import AccessContext
from ledgerone.services.ledger import LedgerService


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


class SalesCreditService:
    @staticmethod
    def list_credit_notes(context: AccessContext, limit: int = 100):
        return (
            SalesCreditNote.query.filter_by(organisation_id=context.organisation_id)
            .order_by(SalesCreditNote.credit_date.desc(), SalesCreditNote.created_at.desc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def create_credit_note(
        context: AccessContext,
        *,
        invoice_id: str,
        credit_number: str | None,
        credit_date,
        amount,
        description: str | None = None,
    ):
        if not context.can("sales.write"):
            raise PermissionError("sales.write")
        invoice = db.session.get(SalesInvoice, invoice_id)
        if not invoice or invoice.organisation_id != context.organisation_id:
            raise ValueError("Sales invoice not found")
        if not invoice.posted_journal_id or invoice.status == "draft":
            raise ValueError("Only posted invoices can be credited")
        if len(invoice.lines) != 1:
            raise ValueError("The current credit-note workflow supports single-line invoices")

        net_amount = _money(amount)
        if net_amount <= 0:
            raise ValueError("Credit note amount must be greater than zero")
        original_line = invoice.lines[0]
        tax_code = original_line.tax_code
        tax_amount = TaxService.tax_amount(net_amount, tax_code)
        gross_amount = net_amount + tax_amount
        outstanding = SalesService.invoice_outstanding(invoice)
        if gross_amount > outstanding:
            raise ValueError("Credit note exceeds the invoice outstanding balance")

        original_journal = db.session.get(Journal, invoice.posted_journal_id)
        if not original_journal or original_journal.organisation_id != context.organisation_id:
            raise ValueError("Original invoice journal not found")
        receivable_line = next(
            (
                line for line in original_journal.lines
                if _money(line.debit) == _money(invoice.total) and _money(line.credit) == Decimal("0.00")
            ),
            None,
        )
        if receivable_line is None:
            debit_lines = [line for line in original_journal.lines if _money(line.debit) > 0]
            receivable_line = max(debit_lines, key=lambda line: _money(line.debit), default=None)
        if receivable_line is None:
            raise ValueError("Could not identify the invoice receivables account")
        if tax_amount and (not tax_code or not tax_code.sales_tax_account_id):
            raise ValueError("Original invoice tax code has no output VAT account")

        credit_id = new_id()
        settlement_id = new_id()
        note_description = (description or "").strip() or f"Credit for {invoice.invoice_number}"
        journal_lines = [
            {
                "account_id": original_line.revenue_account_id,
                "debit": net_amount,
                "credit": 0,
                "description": note_description,
                "currency": invoice.currency,
                "dimensions": {
                    "customer_id": invoice.customer_id,
                    "invoice_id": invoice.id,
                    "sales_credit_note_id": credit_id,
                },
            }
        ]
        if tax_amount:
            journal_lines.append(
                {
                    "account_id": tax_code.sales_tax_account_id,
                    "debit": tax_amount,
                    "credit": 0,
                    "description": f"{tax_code.code} VAT credit",
                    "currency": invoice.currency,
                    "dimensions": {
                        "customer_id": invoice.customer_id,
                        "invoice_id": invoice.id,
                        "sales_credit_note_id": credit_id,
                        "tax_code_id": tax_code.id,
                    },
                }
            )
        journal_lines.append(
            {
                "account_id": receivable_line.account_id,
                "debit": 0,
                "credit": gross_amount,
                "description": invoice.customer.name,
                "currency": invoice.currency,
                "dimensions": {
                    "customer_id": invoice.customer_id,
                    "invoice_id": invoice.id,
                    "sales_credit_note_id": credit_id,
                },
            }
        )

        try:
            issued_number = assign_sales_credit_number(
                context,
                credit_id=credit_id,
                credit_date=credit_date,
                requested_number=credit_number,
            )
            journal = LedgerService.post_journal(
                context,
                journal_date=credit_date,
                description=f"Sales credit note {issued_number} - {invoice.customer.name}",
                reference=issued_number,
                source_module="sales",
                source_reference=credit_id,
                lines=journal_lines,
                commit=False,
            )
            note = SalesCreditNote(
                id=credit_id,
                organisation_id=context.organisation_id,
                customer_id=invoice.customer_id,
                invoice_id=invoice.id,
                credit_number=issued_number,
                credit_date=credit_date,
                description=note_description,
                currency=invoice.currency,
                subtotal=net_amount,
                tax_total=tax_amount,
                total=gross_amount,
                posted_journal_id=journal.id,
            )
            settlement = SalesPayment(
                id=settlement_id,
                organisation_id=context.organisation_id,
                customer_id=invoice.customer_id,
                payment_date=credit_date,
                reference=issued_number,
                amount=gross_amount,
                currency=invoice.currency,
                journal_id=journal.id,
                settlement_type="credit_note",
                status="allocated",
            )
            db.session.add_all([note, settlement])
            db.session.flush()
            db.session.add(
                SalesPaymentAllocation(
                    payment_id=settlement.id,
                    invoice_id=invoice.id,
                    amount=gross_amount,
                )
            )
            remaining = outstanding - gross_amount
            invoice.status = "credited" if remaining == 0 else "part_credited"
            record_audit_event(
                context,
                module_id="sales",
                action="credit_note_posted",
                entity_type="sales_credit_note",
                entity_id=note.id,
                detail={
                    "credit_number": note.credit_number,
                    "invoice_id": invoice.id,
                    "journal_id": journal.id,
                    "subtotal": str(net_amount),
                    "tax_total": str(tax_amount),
                    "total": str(gross_amount),
                },
            )
            db.session.commit()
            return note
        except Exception:
            db.session.rollback()
            raise