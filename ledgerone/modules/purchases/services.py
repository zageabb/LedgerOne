from decimal import Decimal

from ledgerone.extensions import db
from ledgerone.models.core import new_id
from ledgerone.models.ledger import Account, Journal, JournalLine
from ledgerone.modules.purchases.models import (
    PurchaseBill,
    PurchaseBillLine,
    PurchasePayment,
    PurchasePaymentAllocation,
    Supplier,
)
from ledgerone.services.audit import record_audit_event
from ledgerone.services.context import AccessContext
from ledgerone.services.ledger import LedgerService


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
                        phone: str | None = None):
        if not context.can("purchases.write"):
            raise PermissionError("purchases.write")
        if not name.strip():
            raise ValueError("Supplier name is required")
        supplier = Supplier(
            organisation_id=context.organisation_id,
            name=name.strip(),
            email=(email or "").strip() or None,
            phone=(phone or "").strip() or None,
        )
        db.session.add(supplier)
        db.session.flush()
        record_audit_event(
            context,
            module_id="purchases",
            action="supplier_created",
            entity_type="supplier",
            entity_id=supplier.id,
            detail={"name": supplier.name, "email": supplier.email},
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
    def create_bill(context: AccessContext, *, supplier_id: str, bill_number: str,
                    bill_date, due_date, description: str, amount,
                    payable_account_id: str, expense_account_id: str,
                    currency: str = "GBP"):
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

        bill = PurchaseBill(
            organisation_id=context.organisation_id,
            supplier_id=supplier.id,
            bill_number=bill_number.strip(),
            bill_date=bill_date,
            due_date=due_date,
            currency=currency.upper(),
            status="posting",
            subtotal=amount,
            total=amount,
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
                expense_account_id=expense_account_id,
            )
        )

        try:
            journal = LedgerService.post_journal(
                context,
                journal_date=bill_date,
                description=f"Purchase bill {bill.bill_number} - {supplier.name}",
                reference=bill.bill_number,
                source_module="purchases",
                source_reference=bill.id,
                lines=[
                    {
                        "account_id": expense_account_id,
                        "debit": amount,
                        "credit": 0,
                        "description": description.strip() or "Purchase",
                        "currency": currency.upper(),
                        "dimensions": {"supplier_id": supplier.id, "bill_id": bill.id},
                    },
                    {
                        "account_id": payable_account_id,
                        "debit": 0,
                        "credit": amount,
                        "description": supplier.name,
                        "currency": currency.upper(),
                        "dimensions": {"supplier_id": supplier.id, "bill_id": bill.id},
                    },
                ],
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
                    "total": str(amount),
                    "currency": bill.currency,
                },
            )
            db.session.commit()
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
        existing_total = PurchasesService.payment_allocated(payment.id)
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
                outstanding = PurchasesService.bill_outstanding(bill)
                bill.status = "paid" if outstanding == 0 else "part_paid"

            allocated_total = PurchasesService.payment_allocated(payment.id)
            payment.status = "allocated" if allocated_total == _money(payment.amount) else "partially_allocated"
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
