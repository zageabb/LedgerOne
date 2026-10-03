from decimal import Decimal

from ledgerone.extensions import db
from ledgerone.models.core import new_id
from ledgerone.models.ledger import Account, Journal, JournalLine
from ledgerone.modules.purchases.models import (
    PurchaseBill,
    PurchaseBillLine,
    PurchaseCreditRefund,
    PurchasePayment,
    PurchasePaymentAllocation,
    Supplier,
)
from ledgerone.services.audit import record_audit_event
from ledgerone.services.context import AccessContext
from ledgerone.services.ledger import LedgerService
from ledgerone.services.payment_terms import PaymentTermsService


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


class PurchasesService:
    @staticmethod
    def list_suppliers(context: AccessContext):
        return Supplier.query.filter_by(
            organisation_id=context.organisation_id, is_active=True
        ).order_by(Supplier.name.asc()).all()

    @staticmethod
    def create_supplier(context: AccessContext, *, name: str, email: str | None = None,
                        phone: str | None = None, payment_terms_days: int | None = None):
        if not context.can("purchases.write"):
            raise PermissionError("purchases.write")
        if not name.strip():
            raise ValueError("Supplier name is required")
        if payment_terms_days is not None:
            payment_terms_days = PaymentTermsService.supplier_days(
                context.organisation_id, payment_terms_days
            )
        supplier = Supplier(
            organisation_id=context.organisation_id,
            name=name.strip(),
            email=(email or "").strip() or None,
            phone=(phone or "").strip() or None,
            payment_terms_days=payment_terms_days,
        )
        db.session.add(supplier)
        db.session.flush()
        record_audit_event(
            context,
            module_id="purchases",
            action="supplier_created",
            entity_type="supplier",
            entity_id=supplier.id,
            detail={
                "name": supplier.name,
                "email": supplier.email,
                "payment_terms_days": supplier.payment_terms_days,
            },
        )
        db.session.commit()
        return supplier

    @staticmethod
    def list_bills(context: AccessContext, limit: int = 100):
        return (
            PurchaseBill.query.filter_by(organisation_id=context.organisation_id)
            .order_by(PurchaseBill.bill_date.desc(), PurchaseBill.created_at.desc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def bill_allocated(bill_id: str) -> Decimal:
        value = (
            db.session.query(db.func.coalesce(db.func.sum(PurchasePaymentAllocation.amount), 0))
            .filter(PurchasePaymentAllocation.bill_id == bill_id)
            .scalar()
        )
        return _money(value)

    @staticmethod
    def bill_outstanding(bill: PurchaseBill) -> Decimal:
        return max(Decimal("0.00"), _money(bill.total) - PurchasesService.bill_allocated(bill.id))

    @staticmethod
    def list_payments(context: AccessContext, limit: int = 100):
        return (
            PurchasePayment.query.filter_by(organisation_id=context.organisation_id)
            .order_by(PurchasePayment.payment_date.desc(), PurchasePayment.created_at.desc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def payment_allocated(payment_id: str) -> Decimal:
        value = (
            db.session.query(db.func.coalesce(db.func.sum(PurchasePaymentAllocation.amount), 0))
            .filter(PurchasePaymentAllocation.payment_id == payment_id)
            .scalar()
        )
        return _money(value)

    @staticmethod
    def payment_refunded(payment_id: str) -> Decimal:
        value = (
            db.session.query(db.func.coalesce(db.func.sum(PurchaseCreditRefund.amount), 0))
            .filter(PurchaseCreditRefund.source_payment_id == payment_id)
            .scalar()
        )
        return _money(value)

    @staticmethod
    def payment_available(payment_id: str) -> Decimal:
        payment = db.session.get(PurchasePayment, payment_id)
        if not payment:
            return Decimal("0.00")
        consumed = PurchasesService.payment_allocated(payment_id) + PurchasesService.payment_refunded(payment_id)
        return max(Decimal("0.00"), _money(payment.amount) - consumed)

    @staticmethod
    def supplier_credit_balance(context: AccessContext, supplier_id: str) -> Decimal:
        rows = PurchasePayment.query.filter_by(
            organisation_id=context.organisation_id,
            supplier_id=supplier_id,
        ).all()
        return sum((PurchasesService.payment_available(row.id) for row in rows), Decimal("0.00"))

    @staticmethod
    def list_credit_refunds(context: AccessContext, limit: int = 100):
        return (
            PurchaseCreditRefund.query.filter_by(organisation_id=context.organisation_id)
            .order_by(PurchaseCreditRefund.refund_date.desc(), PurchaseCreditRefund.created_at.desc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def refresh_payment_status(payment: PurchasePayment) -> None:
        allocated = PurchasesService.payment_allocated(payment.id)
        refunded = PurchasesService.payment_refunded(payment.id)
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
    def refresh_bill_status(bill: PurchaseBill) -> None:
        from ledgerone.modules.purchases.credit_models import PurchaseCreditNote

        credited = _money(
            db.session.query(db.func.coalesce(db.func.sum(PurchaseCreditNote.total), 0))
            .filter(PurchaseCreditNote.bill_id == bill.id)
            .scalar()
        )
        allocated = PurchasesService.bill_allocated(bill.id)
        outstanding = max(Decimal("0.00"), _money(bill.total) - allocated)
        if credited >= _money(bill.total):
            bill.status = "credited"
        elif outstanding == 0:
            bill.status = "paid"
        elif credited > 0:
            bill.status = "part_credited"
        elif allocated > 0:
            bill.status = "part_paid"
        else:
            bill.status = "posted"

    @staticmethod
    def record_credit_refund(
        context: AccessContext,
        *,
        source_payment_id: str,
        refund_date,
        amount,
        bank_account_id: str,
        payable_account_id: str,
        reference: str | None = None,
    ):
        if not context.can("purchases.write"):
            raise PermissionError("purchases.write")
        source = db.session.get(PurchasePayment, source_payment_id)
        if not source or source.organisation_id != context.organisation_id:
            raise ValueError("Supplier credit source not found")
        amount = _money(amount)
        if amount <= 0:
            raise ValueError("Refund amount must be greater than zero")
        available = PurchasesService.payment_available(source.id)
        if amount > available:
            raise ValueError("Refund exceeds the available supplier credit")

        bank = db.session.get(Account, bank_account_id)
        payable = db.session.get(Account, payable_account_id)
        if (
            not bank
            or bank.organisation_id != context.organisation_id
            or not bank.is_active
            or bank.account_type != "asset"
            or bank.is_control_account
        ):
            raise ValueError("Bank ledger account must be an active non-control asset account")
        if (
            not payable
            or payable.organisation_id != context.organisation_id
            or not payable.is_active
            or payable.account_type != "liability"
            or (payable.metadata_json or {}).get("control_role") != "accounts_payable"
        ):
            raise ValueError("Payables account must be the configured accounts-payable control account")
        if bank.id == payable.id:
            raise ValueError("Bank and payables accounts must be different")

        refund_id = new_id()
        try:
            journal = LedgerService.post_journal(
                context,
                journal_date=refund_date,
                description=f"Supplier credit refund - {source.supplier.name}",
                reference=(reference or "").strip() or source.reference,
                source_module="purchases",
                source_reference=refund_id,
                lines=[
                    {
                        "account_id": bank.id,
                        "debit": amount,
                        "credit": 0,
                        "description": source.supplier.name,
                        "currency": source.currency,
                        "dimensions": {
                            "supplier_id": source.supplier_id,
                            "purchase_credit_refund_id": refund_id,
                            "source_payment_id": source.id,
                        },
                    },
                    {
                        "account_id": payable.id,
                        "debit": 0,
                        "credit": amount,
                        "description": source.supplier.name,
                        "currency": source.currency,
                        "dimensions": {
                            "supplier_id": source.supplier_id,
                            "purchase_credit_refund_id": refund_id,
                            "source_payment_id": source.id,
                        },
                    },
                ],
                commit=False,
            )
            refund = PurchaseCreditRefund(
                id=refund_id,
                organisation_id=context.organisation_id,
                supplier_id=source.supplier_id,
                source_payment_id=source.id,
                refund_date=refund_date,
                amount=amount,
                currency=source.currency,
                bank_account_id=bank.id,
                payable_account_id=payable.id,
                journal_id=journal.id,
                reference=(reference or "").strip() or journal.reference,
            )
            db.session.add(refund)
            db.session.flush()
            PurchasesService.refresh_payment_status(source)
            record_audit_event(
                context,
                module_id="purchases",
                action="supplier_credit_refunded",
                entity_type="purchase_credit_refund",
                entity_id=refund.id,
                detail={
                    "supplier_id": source.supplier_id,
                    "source_payment_id": source.id,
                    "journal_id": journal.id,
                    "amount": str(amount),
                    "remaining_credit": str(PurchasesService.payment_available(source.id)),
                },
            )
            db.session.commit()
            return refund
        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def create_bill(context: AccessContext, *, supplier_id: str, bill_number: str,
                    bill_date, due_date, description: str, amount,
                    tax_point=None,
                    payable_account_id: str, expense_account_id: str,
                    currency: str = "GBP", tax_code_id: str | None = None,
                    metadata: dict | None = None, commit: bool = True):
        if not context.can("purchases.write"):
            raise PermissionError("purchases.write")
        amount = _money(amount)
        if amount <= 0:
            raise ValueError("Bill amount must be greater than zero")
        supplier = db.session.get(Supplier, supplier_id)
        if not supplier or supplier.organisation_id != context.organisation_id:
            raise ValueError("Invalid supplier")
        if PurchaseBill.query.filter_by(
            organisation_id=context.organisation_id, bill_number=bill_number
        ).first():
            raise ValueError("Bill number already exists")
        if due_date is None:
            due_date = PaymentTermsService.supplier_due_date(
                context.organisation_id,
                bill_date,
                supplier.payment_terms_days,
            )
        if due_date < bill_date:
            raise ValueError("Bill due date cannot be before the bill date")

        from ledgerone.modules.tax.services import TaxService
        effective_tax_point = tax_point or bill_date
        tax_code = TaxService.code_for_use(context, tax_code_id, "purchase")
        if tax_code:
            TaxService.assert_tax_point_open(context, effective_tax_point)
        tax_amount = TaxService.tax_amount(amount, tax_code)
        total = amount + tax_amount

        bill = PurchaseBill(
            organisation_id=context.organisation_id,
            supplier_id=supplier.id,
            bill_number=bill_number.strip(),
            bill_date=bill_date,
            tax_point=effective_tax_point,
            due_date=due_date,
            currency=currency.upper(),
            status="posting",
            subtotal=amount,
            tax_total=tax_amount,
            total=total,
            metadata_json=dict(metadata or {}),
        )
        db.session.add(bill)
        db.session.flush()
        db.session.add(
            PurchaseBillLine(
                bill_id=bill.id,
                line_number=1,
                description=description.strip() or "Purchase",
                quantity=1,
                unit_price=amount,
                net_amount=amount,
                tax_amount=tax_amount,
                tax_code_id=tax_code.id if tax_code else None,
                expense_account_id=expense_account_id,
            )
        )

        journal_lines = [
            {
                "account_id": expense_account_id,
                "debit": amount,
                "credit": 0,
                "description": description.strip() or "Purchase",
                "currency": currency.upper(),
                "dimensions": {
                    "supplier_id": supplier.id,
                    "bill_id": bill.id,
                    "tax_code_id": tax_code.id if tax_code else None,
                },
            },
            {
                "account_id": payable_account_id,
                "debit": 0,
                "credit": total,
                "description": supplier.name,
                "currency": currency.upper(),
                "dimensions": {"supplier_id": supplier.id, "bill_id": bill.id},
            },
        ]
        if tax_amount:
            if not tax_code or not tax_code.purchase_tax_account_id:
                raise ValueError("Selected tax code has no input VAT account")
            journal_lines.insert(
                1,
                {
                    "account_id": tax_code.purchase_tax_account_id,
                    "debit": tax_amount,
                    "credit": 0,
                    "description": f"{tax_code.code} input VAT",
                    "currency": currency.upper(),
                    "dimensions": {
                        "supplier_id": supplier.id,
                        "bill_id": bill.id,
                        "tax_code_id": tax_code.id,
                    },
                },
            )

        try:
            journal = LedgerService.post_journal(
                context,
                journal_date=bill_date,
                description=f"Purchase bill {bill.bill_number} - {supplier.name}",
                reference=bill.bill_number,
                source_module="purchases",
                source_reference=bill.id,
                lines=journal_lines,
                commit=False,
            )
            bill.posted_journal_id = journal.id
            bill.status = "posted"
            record_audit_event(
                context,
                module_id="purchases",
                action="bill_posted",
                entity_type="purchase_bill",
                entity_id=bill.id,
                detail={
                    "bill_number": bill.bill_number,
                    "supplier_id": supplier.id,
                    "journal_id": journal.id,
                    "subtotal": str(amount),
                    "tax_total": str(tax_amount),
                    "total": str(total),
                    "tax_code": tax_code.code if tax_code else None,
                    "tax_point": bill.tax_point.isoformat(),
                    "currency": bill.currency,
                    "due_date": bill.due_date.isoformat(),
                },
            )
            if commit:
                db.session.commit()
            else:
                db.session.flush()
            return bill
        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def record_payment(context: AccessContext, *, supplier_id: str, payment_date,
                       amount, bank_account_id: str, payable_account_id: str,
                       reference: str | None = None, currency: str = "GBP"):
        if not context.can("purchases.write"):
            raise PermissionError("purchases.write")
        amount = _money(amount)
        if amount <= 0:
            raise ValueError("Payment amount must be greater than zero")
        supplier = db.session.get(Supplier, supplier_id)
        if not supplier or supplier.organisation_id != context.organisation_id:
            raise ValueError("Invalid supplier")
        bank_account = db.session.get(Account, bank_account_id)
        payable = db.session.get(Account, payable_account_id)
        if not bank_account or bank_account.organisation_id != context.organisation_id:
            raise ValueError("Invalid bank ledger account")
        if not payable or payable.organisation_id != context.organisation_id:
            raise ValueError("Invalid payables account")

        payment_id = new_id()
        try:
            journal = LedgerService.post_journal(
                context,
                journal_date=payment_date,
                description=f"Supplier payment - {supplier.name}",
                reference=(reference or "").strip() or None,
                source_module="purchases",
                source_reference=payment_id,
                lines=[
                    {
                        "account_id": payable.id,
                        "debit": amount,
                        "credit": 0,
                        "description": supplier.name,
                        "currency": currency.upper(),
                        "dimensions": {"supplier_id": supplier.id, "purchase_payment_id": payment_id},
                    },
                    {
                        "account_id": bank_account.id,
                        "debit": 0,
                        "credit": amount,
                        "description": supplier.name,
                        "currency": currency.upper(),
                        "dimensions": {"supplier_id": supplier.id, "purchase_payment_id": payment_id},
                    },
                ],
                commit=False,
            )
            payment = PurchasePayment(
                id=payment_id,
                organisation_id=context.organisation_id,
                supplier_id=supplier.id,
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
                module_id="purchases",
                action="payment_recorded",
                entity_type="purchase_payment",
                entity_id=payment.id,
                detail={"supplier_id": supplier.id, "journal_id": journal.id, "amount": str(amount)},
            )
            db.session.commit()
            return payment
        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def adopt_payment_journal(context: AccessContext, *, supplier_id: str, journal_id: str,
                              payable_account_id: str, currency: str = "GBP"):
        if not context.can("purchases.write"):
            raise PermissionError("purchases.write")
        supplier = db.session.get(Supplier, supplier_id)
        journal = db.session.get(Journal, journal_id)
        if not supplier or supplier.organisation_id != context.organisation_id:
            raise ValueError("Invalid supplier")
        if not journal or journal.organisation_id != context.organisation_id or journal.status != "posted":
            raise ValueError("Invalid posted journal")
        if PurchasePayment.query.filter_by(
            organisation_id=context.organisation_id, journal_id=journal.id
        ).first():
            raise ValueError("Journal is already registered as a supplier payment")
        payable = db.session.get(Account, payable_account_id)
        if not payable or payable.organisation_id != context.organisation_id:
            raise ValueError("Invalid payables account")
        amount = _money(
            db.session.query(
                db.func.coalesce(db.func.sum(JournalLine.debit - JournalLine.credit), 0)
            )
            .filter(JournalLine.journal_id == journal.id, JournalLine.account_id == payable.id)
            .scalar()
        )
        if amount <= 0:
            raise ValueError("Journal does not contain a net debit to the selected payables account")
        payment = PurchasePayment(
            organisation_id=context.organisation_id,
            supplier_id=supplier.id,
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
            module_id="purchases",
            action="payment_journal_adopted",
            entity_type="purchase_payment",
            entity_id=payment.id,
            detail={"supplier_id": supplier.id, "journal_id": journal.id, "amount": str(amount)},
        )
        db.session.commit()
        return payment

    @staticmethod
    def allocate_payment(context: AccessContext, payment_id: str, allocations: list[dict]):
        if not context.can("purchases.write"):
            raise PermissionError("purchases.write")
        payment = db.session.get(PurchasePayment, payment_id)
        if not payment or payment.organisation_id != context.organisation_id:
            raise ValueError("Supplier payment not found")
        available = PurchasesService.payment_available(payment.id)
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
                bill = db.session.get(PurchaseBill, item.get("bill_id"))
                if (
                    not bill
                    or bill.organisation_id != context.organisation_id
                    or bill.supplier_id != payment.supplier_id
                ):
                    raise ValueError("Invalid bill for this supplier payment")
                outstanding = PurchasesService.bill_outstanding(bill)
                if amount > outstanding:
                    raise ValueError(f"Allocation exceeds outstanding amount for {bill.bill_number}")
                row = PurchasePaymentAllocation.query.filter_by(
                    payment_id=payment.id, bill_id=bill.id
                ).first()
                if row:
                    row.amount = _money(row.amount) + amount
                else:
                    db.session.add(
                        PurchasePaymentAllocation(
                            payment_id=payment.id,
                            bill_id=bill.id,
                            amount=amount,
                        )
                    )
                affected.append(bill)

            db.session.flush()
            for bill in affected:
                PurchasesService.refresh_bill_status(bill)

            allocated_total = PurchasesService.payment_allocated(payment.id)
            PurchasesService.refresh_payment_status(payment)
            record_audit_event(
                context,
                module_id="purchases",
                action="payment_allocated",
                entity_type="purchase_payment",
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
