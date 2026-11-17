"""ERP-000 multi-line purchase and sales order creation.

Uses existing document numbering, tax and account services. Order creation is
non-posting; conversion, fulfilment and invoices retain their own controls.
"""
from datetime import date
from decimal import Decimal, InvalidOperation

from ledgerone.extensions import db
from ledgerone.models.core import Organisation, new_id
from ledgerone.models.ledger import Account
from ledgerone.modules.purchases.models import Supplier
from ledgerone.modules.purchases.order_models import PurchaseOrder, PurchaseOrderLine
from ledgerone.modules.sales.models import Customer
from ledgerone.modules.sales.order_models import SalesOrder, SalesOrderLine
from ledgerone.modules.sales.numbering import _assign_number
from ledgerone.modules.tax.services import TaxService
from ledgerone.services.audit import record_audit_event


def _decimal(value, *, precision):
    try:
        parsed = Decimal(str(value)).quantize(Decimal(precision))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("Invalid quantity or unit price") from exc
    if not parsed.is_finite():
        raise ValueError("Quantity or unit price must be finite")
    return parsed


class MultiLineOrderService:
    @staticmethod
    def create(context, *, kind: str, party_id: str, order_number: str | None,
               order_date: date, expected_date: date | None,
               control_account_id: str, lines: list[dict],
               currency: str = "GBP"):
        if kind not in {"purchase", "sales"}:
            raise ValueError("Order kind must be purchase or sales")
        is_purchase = kind == "purchase"
        permission = "purchases.write" if is_purchase else "sales.write"
        if not context.can(permission):
            raise PermissionError(permission)
        if not context.organisation_id:
            raise ValueError("An organisation is required")
        if not isinstance(order_date, date):
            raise ValueError("Order date is required")
        if expected_date and expected_date < order_date:
            raise ValueError("Delivery date cannot precede order date")
        if not isinstance(lines, list) or not 1 <= len(lines) <= 200:
            raise ValueError("Order requires between 1 and 200 lines")
        organisation = db.session.get(Organisation, context.organisation_id)
        if not organisation:
            raise ValueError("Company not found")
        clean_currency = (currency or "").strip().upper()
        if clean_currency != organisation.base_currency:
            raise ValueError("Multi-currency accounting is not yet supported")
        party = db.session.get(Supplier if is_purchase else Customer, party_id)
        if not party or party.organisation_id != context.organisation_id or not party.is_active:
            raise ValueError("Invalid or inactive supplier/customer")
        control = db.session.get(Account, control_account_id)
        required_control = "liability" if is_purchase else "asset"
        if (not control or control.organisation_id != context.organisation_id
                or not control.is_active or control.account_type != required_control):
            raise ValueError("Invalid control account")

        prepared = []
        subtotal = Decimal("0.00")
        tax_total = Decimal("0.00")
        for position, supplied in enumerate(lines, 1):
            if not isinstance(supplied, dict):
                raise ValueError(f"Line {position} must be an object")
            description = (supplied.get("description") or "").strip()
            if not description or len(description) > 500:
                raise ValueError(f"Line {position} needs a description of up to 500 characters")
            qty = _decimal(supplied.get("quantity"), precision="0.0001")
            price = _decimal(supplied.get("unit_price"), precision="0.0001")
            if qty <= 0 or price < 0:
                raise ValueError(f"Line {position} quantity must be positive and price nonnegative")
            account = db.session.get(Account, supplied.get("account_id"))
            required_line_type = "expense" if is_purchase else "income"
            if (not account or account.organisation_id != context.organisation_id
                    or not account.is_active or account.account_type != required_line_type):
                raise ValueError(f"Invalid accounting account on line {position}")
            treatment = (supplied.get("item_treatment") or ("expense" if is_purchase else "service")).strip().lower()
            permitted = {"stock", "expense"} if is_purchase else {"stock", "service"}
            if treatment not in permitted:
                raise ValueError(f"Invalid item accounting treatment on line {position}")
            dimensions = dict(supplied.get("dimensions") or {})
            # A validated top-level field owns this reserved accounting attribute.
            dimensions["item_treatment"] = treatment
            tax_code = TaxService.code_for_use(
                context, supplied.get("tax_code_id"), kind)
            net = (qty * price).quantize(Decimal("0.01"))
            tax = TaxService.tax_amount(net, tax_code)
            subtotal += net
            tax_total += tax
            prepared.append({
                "description": description, "quantity": qty, "unit_price": price,
                "net_amount": net, "tax_amount": tax,
                "tax_code_id": tax_code.id if tax_code else None,
                "account_id": account.id,
                "dimensions": dimensions,
            })
        if subtotal <= 0:
            raise ValueError("Order amount must be greater than zero")
        total = subtotal + tax_total
        model = PurchaseOrder if is_purchase else SalesOrder
        line_model = PurchaseOrderLine if is_purchase else SalesOrderLine
        document_type = "purchase_order" if is_purchase else "sales_order"
        order_id = new_id()
        from ledgerone.modules.sales.numbering import _assign_number
        number = _assign_number(
            context, sequence_key=document_type, issue_date=order_date,
            entity_type=document_type, entity_id=order_id,
            requested_number=(order_number or "").strip() or None,
            model=model, number_field="order_number", date_field="order_date")
        common = dict(
            id=order_id, organisation_id=context.organisation_id,
            order_number=number, order_date=order_date, currency=clean_currency,
            status="draft", subtotal=subtotal, tax_total=tax_total, total=total)
        if is_purchase:
            order = PurchaseOrder(
                **common, supplier_id=party.id, expected_date=expected_date,
                payable_account_id=control.id)
        else:
            order = SalesOrder(
                **common, customer_id=party.id, requested_delivery_date=expected_date,
                receivable_account_id=control.id)
        db.session.add(order)
        db.session.flush()
        for position, item in enumerate(prepared, 1):
            common_line = {
                "order_id": order.id, "line_number": position,
                "description": item["description"],
                "quantity": item["quantity"],
                "unit_price": item["unit_price"],
                "net_amount": item["net_amount"],
                "tax_amount": item["tax_amount"],
                "tax_code_id": item["tax_code_id"],
                "dimensions": item["dimensions"],
            }
            if is_purchase:
                line = line_model(**common_line, expense_account_id=item["account_id"])
            else:
                line = line_model(**common_line, revenue_account_id=item["account_id"])
            db.session.add(line)
        record_audit_event(
            context, module_id="purchases" if is_purchase else "sales",
            action=f"{document_type}_created", entity_type=document_type,
            entity_id=order.id,
            detail={"order_number": order.order_number, "line_count": len(prepared),
                    "subtotal": str(subtotal), "tax_total": str(tax_total),
                    "total": str(total)})
        db.session.commit()
        return order
