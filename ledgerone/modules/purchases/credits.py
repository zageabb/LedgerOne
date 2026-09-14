from __future__ import annotations

from decimal import Decimal

from ledgerone.extensions import db
from ledgerone.models.core import new_id
from ledgerone.models.ledger import Journal
from ledgerone.modules.purchases.credit_models import PurchaseCreditNote
from ledgerone.modules.purchases.models import PurchaseBill, PurchasePayment, PurchasePaymentAllocation
from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.modules.tax.services import TaxService
from ledgerone.services.audit import record_audit_event
from ledgerone.services.context import AccessContext
from ledgerone.services.ledger import LedgerService


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


class PurchaseCreditService:
    @staticmethod
    def list_credit_notes(context: AccessContext, limit: int = 100):
        return (
            PurchaseCreditNote.query.filter_by(organisation_id=context.organisation_id)
            .order_by(PurchaseCreditNote.credit_date.desc(), PurchaseCreditNote.created_at.desc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def create_credit_note(
        context: AccessContext,
        *,
        bill_id: str,
        credit_number: str,
        credit_date,
        amount,
        description: str | None = None,
    ):
        if not context.can("purchases.write"):
            raise PermissionError("purchases.write")
        bill = db.session.get(PurchaseBill, bill_id)
        if not bill or bill.organisation_id != context.organisation_id:
            raise ValueError("Purchase bill not found")
        if not bill.posted_journal_id or bill.status == "draft":
            raise ValueError("Only posted bills can be credited")
        credit_number = (credit_number or "").strip()
        if not credit_number:
            raise ValueError("Credit note number is required")
        if PurchaseCreditNote.query.filter_by(
            organisation_id=context.organisation_id, credit_number=credit_number
        ).first():
            raise ValueError("Credit note number already exists")
        if len(bill.lines) != 1:
            raise ValueError("The current credit-note workflow supports single-line bills")

        net_amount = _money(amount)
        if net_amount <= 0:
            raise ValueError("Credit note amount must be greater than zero")
        original_line = bill.lines[0]
        tax_code = original_line.tax_code
        tax_amount = TaxService.tax_amount(net_amount, tax_code)
        gross_amount = net_amount + tax_amount
        outstanding = PurchasesService.bill_outstanding(bill)
        if gross_amount > outstanding:
            raise ValueError("Credit note exceeds the bill outstanding balance")

        original_journal = db.session.get(Journal, bill.posted_journal_id)
        if not original_journal or original_journal.organisation_id != context.organisation_id:
            raise ValueError("Original bill journal not found")
        payable_line = next(
            (
                line for line in original_journal.lines
                if _money(line.credit) == _money(bill.total) and _money(line.debit) == Decimal("0.00")
            ),
            None,
        )
        if payable_line is None:
            credit_lines = [line for line in original_journal.lines if _money(line.credit) > 0]
            payable_line = max(credit_lines, key=lambda line: _money(line.credit), default=None)
        if payable_line is None:
            raise ValueError("Could not identify the bill payables account")
        if tax_amount and (not tax_code or not tax_code.purchase_tax_account_id):
            raise ValueError("Original bill tax code has no input VAT account")

        credit_id = new_id()
        settlement_id = new_id()
        note_description = (description or "").strip() or f"Credit for {bill.bill_number}"
        journal_lines = [
            {
                "account_id": payable_line.account_id,
                "debit": gross_amount,
                "credit": 0,
                "description": bill.supplier.name,
                "currency": bill.currency,
                "dimensions": {
                    "supplier_id": bill.supplier_id,
                    "bill_id": bill.id,
                    "purchase_credit_note_id": credit_id,
                },
            },
            {
                "account_id": original_line.expense_account_id,
                "debit": 0,
                "credit": net_amount,
                "description": note_description,
                "currency": bill.currency,
                "dimensions": {
                    "supplier_id": bill.supplier_id,
                    "bill_id": bill.id,
                    "purchase_credit_note_id": credit_id,
                },
            },
        ]
        if tax_amount:
            journal_lines.append(
                {
                    "account_id": tax_code.purchase_tax_account_id,
                    "debit": 0,
                    "credit": tax_amount,
                    "description": f"{tax_code.code} VAT credit",
                    "currency": bill.currency,
                    "dimensions": {
                        "supplier_id": bill.supplier_id,
                        "bill_id": bill.id,
                        "purchase_credit_note_id": credit_id,
                        "tax_code_id": tax_code.id,
                    },
                }
            )

        try:
            journal = LedgerService.post_journal(
                context,
                journal_date=credit_date,
                description=f"Purchase credit note {credit_number} - {bill.supplier.name}",
                reference=credit_number,
                source_module="purchases",
                source_reference=credit_id,
                lines=journal_lines,
                commit=False,
            )
            note = PurchaseCreditNote(
                id=credit_id,
                organisation_id=context.organisation_id,
                supplier_id=bill.supplier_id,
                bill_id=bill.id,
                credit_number=credit_number,
                credit_date=credit_date,
                description=note_description,
                currency=bill.currency,
                subtotal=net_amount,
                tax_total=tax_amount,
                total=gross_amount,
                posted_journal_id=journal.id,
            )
            settlement = PurchasePayment(
                id=settlement_id,
                organisation_id=context.organisation_id,
                supplier_id=bill.supplier_id,
                payment_date=credit_date,
                reference=credit_number,
                amount=gross_amount,
                currency=bill.currency,
                journal_id=journal.id,
                settlement_type="credit_note",
                status="allocated",
            )
            db.session.add_all([note, settlement])
            db.session.flush()
            db.session.add(
                PurchasePaymentAllocation(
                    payment_id=settlement.id,
                    bill_id=bill.id,
                    amount=gross_amount,
                )
            )
            remaining = outstanding - gross_amount
            bill.status = "credited" if remaining == 0 else "part_credited"
            record_audit_event(
                context,
                module_id="purchases",
                action="credit_note_posted",
                entity_type="purchase_credit_note",
                entity_id=note.id,
                detail={
                    "credit_number": note.credit_number,
                    "bill_id": bill.id,
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
