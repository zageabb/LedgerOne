from __future__ import annotations

from datetime import date
from decimal import Decimal

from ledgerone.extensions import db
from ledgerone.models.ledger import Account
from ledgerone.modules.sales.models import Customer
from ledgerone.modules.sales.order_models import SalesOrder, SalesOrderLine
from ledgerone.modules.sales.services import SalesService
from ledgerone.modules.tax.services import TaxService
from ledgerone.services.audit import record_audit_event
from ledgerone.services.context import AccessContext


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


class SalesOrderService:
    @staticmethod
    def list_orders(context: AccessContext, limit: int = 100):
        return (
            SalesOrder.query.filter_by(organisation_id=context.organisation_id)
            .order_by(SalesOrder.order_date.desc(), SalesOrder.created_at.desc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def create_order(
        context: AccessContext,
        *,
        customer_id: str,
        order_number: str,
        order_date: date,
        requested_delivery_date: date | None,
        description: str,
        amount,
        receivable_account_id: str,
        revenue_account_id: str,
        currency: str = "GBP",
        tax_code_id: str | None = None,
    ):
        if not context.can("sales.write"):
            raise PermissionError("sales.write")
        order_number = (order_number or "").strip()
        if not order_number:
            raise ValueError("Order number is required")
        if SalesOrder.query.filter_by(
            organisation_id=context.organisation_id,
            order_number=order_number,
        ).first():
            raise ValueError("Order number already exists")
        if requested_delivery_date and requested_delivery_date < order_date:
            raise ValueError("Requested delivery date cannot be before the order date")

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
            raise ValueError("Order amount must be greater than zero")
        tax_code = TaxService.code_for_use(context, tax_code_id, "sales")
        tax_amount = TaxService.tax_amount(net_amount, tax_code)
        total = net_amount + tax_amount
        order = SalesOrder(
            organisation_id=context.organisation_id,
            customer_id=customer.id,
            order_number=order_number,
            order_date=order_date,
            requested_delivery_date=requested_delivery_date,
            currency=(currency or "GBP").upper(),
            status="draft",
            subtotal=net_amount,
            tax_total=tax_amount,
            total=total,
            receivable_account_id=receivable.id,
        )
        db.session.add(order)
        db.session.flush()
        db.session.add(
            SalesOrderLine(
                order_id=order.id,
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
            action="sales_order_created",
            entity_type="sales_order",
            entity_id=order.id,
            detail={
                "order_number": order.order_number,
                "customer_id": customer.id,
                "subtotal": str(net_amount),
                "tax_total": str(tax_amount),
                "total": str(total),
            },
        )
        db.session.commit()
        return order

    @staticmethod
    def set_status(context: AccessContext, order_id: str, *, status: str):
        if not context.can("sales.write"):
            raise PermissionError("sales.write")
        status = (status or "").strip().lower()
        if status not in {"draft", "confirmed", "cancelled"}:
            raise ValueError("Sales order status must be draft, confirmed or cancelled")
        order = db.session.get(SalesOrder, order_id)
        if not order or order.organisation_id != context.organisation_id:
            raise ValueError("Sales order not found")
        if order.status == "converted":
            raise ValueError("A converted sales order cannot be changed")
        before = order.status
        order.status = status
        record_audit_event(
            context,
            module_id="sales",
            action="sales_order_status_changed",
            entity_type="sales_order",
            entity_id=order.id,
            detail={"before": before, "after": status},
        )
        db.session.commit()
        return order

    @staticmethod
    def convert_to_invoice(
        context: AccessContext,
        order_id: str,
        *,
        invoice_number: str,
        invoice_date: date,
        due_date: date | None = None,
    ):
        if not context.can("sales.write"):
            raise PermissionError("sales.write")
        order = db.session.get(SalesOrder, order_id)
        if not order or order.organisation_id != context.organisation_id:
            raise ValueError("Sales order not found")
        if order.status == "converted" or order.converted_invoice_id:
            raise ValueError("Sales order has already been converted")
        if order.status == "cancelled":
            raise ValueError("A cancelled sales order cannot be converted")
        if order.status != "confirmed":
            raise ValueError("Sales order must be confirmed before conversion")
        if len(order.lines) != 1:
            raise ValueError("The current sales order conversion supports single-line orders")
        line = order.lines[0]

        try:
            invoice = SalesService.create_invoice(
                context,
                customer_id=order.customer_id,
                invoice_number=invoice_number,
                invoice_date=invoice_date,
                due_date=due_date,
                description=line.description,
                amount=line.net_amount,
                receivable_account_id=order.receivable_account_id,
                revenue_account_id=line.revenue_account_id,
                currency=order.currency,
                tax_code_id=line.tax_code_id,
                commit=False,
            )
            order.status = "converted"
            order.converted_invoice_id = invoice.id
            invoice.metadata_json = {
                **(invoice.metadata_json or {}),
                "source_sales_order_id": order.id,
                "source_sales_order_number": order.order_number,
            }
            record_audit_event(
                context,
                module_id="sales",
                action="sales_order_converted",
                entity_type="sales_order",
                entity_id=order.id,
                detail={
                    "order_number": order.order_number,
                    "invoice_id": invoice.id,
                    "invoice_number": invoice.invoice_number,
                },
            )
            db.session.commit()
            return invoice, order
        except Exception:
            db.session.rollback()
            raise
