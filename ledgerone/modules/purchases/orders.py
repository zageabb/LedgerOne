from __future__ import annotations

from datetime import date
from decimal import Decimal

from ledgerone.extensions import db
from ledgerone.models.ledger import Account
from ledgerone.modules.purchases.models import Supplier
from ledgerone.modules.purchases.order_models import PurchaseOrder, PurchaseOrderLine
from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.modules.tax.services import TaxService
from ledgerone.services.audit import record_audit_event
from ledgerone.services.context import AccessContext


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


class PurchaseOrderService:
    @staticmethod
    def list_orders(context: AccessContext, limit: int = 100):
        return (
            PurchaseOrder.query.filter_by(organisation_id=context.organisation_id)
            .order_by(PurchaseOrder.order_date.desc(), PurchaseOrder.created_at.desc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def create_order(
        context: AccessContext,
        *,
        supplier_id: str,
        order_number: str,
        order_date: date,
        expected_date: date | None,
        description: str,
        amount,
        payable_account_id: str,
        expense_account_id: str,
        currency: str = "GBP",
        tax_code_id: str | None = None,
    ):
        if not context.can("purchases.write"):
            raise PermissionError("purchases.write")
        order_number = (order_number or "").strip()
        if not order_number:
            raise ValueError("Purchase order number is required")
        if PurchaseOrder.query.filter_by(
            organisation_id=context.organisation_id,
            order_number=order_number,
        ).first():
            raise ValueError("Purchase order number already exists")
        if expected_date and expected_date < order_date:
            raise ValueError("Expected date cannot be before the purchase order date")

        supplier = db.session.get(Supplier, supplier_id)
        if not supplier or supplier.organisation_id != context.organisation_id:
            raise ValueError("Invalid supplier")
        payable = db.session.get(Account, payable_account_id)
        expense = db.session.get(Account, expense_account_id)
        if not payable or payable.organisation_id != context.organisation_id:
            raise ValueError("Invalid payables account")
        if payable.account_type != "liability":
            raise ValueError("Payables account must be a liability account")
        if not expense or expense.organisation_id != context.organisation_id:
            raise ValueError("Invalid expense account")
        if expense.account_type != "expense":
            raise ValueError("Expense account must be an expense account")

        net_amount = _money(amount)
        if net_amount <= 0:
            raise ValueError("Purchase order amount must be greater than zero")
        tax_code = TaxService.code_for_use(context, tax_code_id, "purchase")
        tax_amount = TaxService.tax_amount(net_amount, tax_code)
        total = net_amount + tax_amount
        order = PurchaseOrder(
            organisation_id=context.organisation_id,
            supplier_id=supplier.id,
            order_number=order_number,
            order_date=order_date,
            expected_date=expected_date,
            currency=(currency or "GBP").upper(),
            status="draft",
            subtotal=net_amount,
            tax_total=tax_amount,
            total=total,
            payable_account_id=payable.id,
        )
        db.session.add(order)
        db.session.flush()
        db.session.add(
            PurchaseOrderLine(
                order_id=order.id,
                line_number=1,
                description=(description or "").strip() or "Purchase",
                quantity=1,
                unit_price=net_amount,
                net_amount=net_amount,
                tax_amount=tax_amount,
                tax_code_id=tax_code.id if tax_code else None,
                expense_account_id=expense.id,
                dimensions={"tax_code": tax_code.code} if tax_code else {},
            )
        )
        record_audit_event(
            context,
            module_id="purchases",
            action="purchase_order_created",
            entity_type="purchase_order",
            entity_id=order.id,
            detail={
                "order_number": order.order_number,
                "supplier_id": supplier.id,
                "subtotal": str(net_amount),
                "tax_total": str(tax_amount),
                "total": str(total),
            },
        )
        db.session.commit()
        return order

    @staticmethod
    def set_status(context: AccessContext, order_id: str, *, status: str):
        if not context.can("purchases.write"):
            raise PermissionError("purchases.write")
        status = (status or "").strip().lower()
        if status not in {"draft", "sent", "approved", "cancelled"}:
            raise ValueError("Purchase order status must be draft, sent, approved or cancelled")
        order = db.session.get(PurchaseOrder, order_id)
        if not order or order.organisation_id != context.organisation_id:
            raise ValueError("Purchase order not found")
        if order.status == "converted":
            raise ValueError("A converted purchase order cannot be changed")
        before = order.status
        order.status = status
        record_audit_event(
            context,
            module_id="purchases",
            action="purchase_order_status_changed",
            entity_type="purchase_order",
            entity_id=order.id,
            detail={"before": before, "after": status},
        )
        db.session.commit()
        return order

    @staticmethod
    def convert_to_bill(
        context: AccessContext,
        order_id: str,
        *,
        bill_number: str,
        bill_date: date,
        due_date: date | None = None,
    ):
        if not context.can("purchases.write"):
            raise PermissionError("purchases.write")
        order = db.session.get(PurchaseOrder, order_id)
        if not order or order.organisation_id != context.organisation_id:
            raise ValueError("Purchase order not found")
        if order.status == "converted" or order.converted_bill_id:
            raise ValueError("Purchase order has already been converted")
        if order.status == "cancelled":
            raise ValueError("A cancelled purchase order cannot be converted")
        if order.status != "approved":
            raise ValueError("Approve the purchase order before converting it to a bill")
        if len(order.lines) != 1:
            raise ValueError("The current purchase order conversion supports single-line orders")
        line = order.lines[0]

        try:
            bill = PurchasesService.create_bill(
                context,
                supplier_id=order.supplier_id,
                bill_number=bill_number,
                bill_date=bill_date,
                due_date=due_date,
                description=line.description,
                amount=line.net_amount,
                payable_account_id=order.payable_account_id,
                expense_account_id=line.expense_account_id,
                currency=order.currency,
                tax_code_id=line.tax_code_id,
                commit=False,
            )
            order.status = "converted"
            order.converted_bill_id = bill.id
            bill.metadata_json = {
                **(bill.metadata_json or {}),
                "source_purchase_order_id": order.id,
                "source_purchase_order_number": order.order_number,
            }
            record_audit_event(
                context,
                module_id="purchases",
                action="purchase_order_converted",
                entity_type="purchase_order",
                entity_id=order.id,
                detail={
                    "order_number": order.order_number,
                    "bill_id": bill.id,
                    "bill_number": bill.bill_number,
                },
            )
            db.session.commit()
            return bill, order
        except Exception:
            db.session.rollback()
            raise
