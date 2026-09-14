from decimal import Decimal

from ledgerone.extensions import db
from ledgerone.modules.purchases.models import PurchaseBill, PurchaseBillLine, Supplier
from ledgerone.services.audit import record_audit_event
from ledgerone.services.context import AccessContext
from ledgerone.services.ledger import LedgerService


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
    def create_bill(context: AccessContext, *, supplier_id: str, bill_number: str,
                    bill_date, due_date, description: str, amount,
                    payable_account_id: str, expense_account_id: str,
                    currency: str = "GBP"):
        if not context.can("purchases.write"):
            raise PermissionError("purchases.write")
        amount = Decimal(str(amount)).quantize(Decimal("0.01"))
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
