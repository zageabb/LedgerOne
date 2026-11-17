"""Read-only ERP-000 purchase invoice two-/three-way matching preview.

This service deliberately does not post bills or reserve received quantities.
A matching preview is not proof that a concurrent posting remains valid.
"""
from decimal import Decimal, InvalidOperation

from ledgerone.extensions import db
from ledgerone.modules.commercial.models import CommercialAccountingEvent, CommercialDocument
from ledgerone.modules.purchases.models import PurchaseBill
from ledgerone.modules.purchases.order_models import PurchaseOrder


def _quantity(value):
    try:
        q = Decimal(str(value)).quantize(Decimal("0.0001"))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("Invalid invoice line quantity") from exc
    if not q.is_finite() or q <= 0:
        raise ValueError("Invoice line quantity must be positive")
    return q


def _money(value):
    try:
        m = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("Invalid invoice unit price") from exc
    if not m.is_finite() or m < 0:
        raise ValueError("Invoice unit price cannot be negative")
    return m


class PurchaseMatchService:
    @staticmethod
    def preview(context, *, order_id: str, supplier_invoice_reference: str,
                lines: list[dict], match_type: str = "three_way",
                price_tolerance_percent="0"):
        if not context.can("purchases.read"):
            raise PermissionError("purchases.read")
        if match_type not in {"two_way", "three_way"}:
            raise ValueError("Matching must be two_way or three_way")
        order = db.session.get(PurchaseOrder, order_id)
        if not order or order.organisation_id != context.organisation_id:
            raise ValueError("Purchase order not found")
        if order.status not in {"approved", "sent"}:
            raise ValueError("Only approved or sent purchase orders can be matched")
        reference = (supplier_invoice_reference or "").strip()
        if not reference or len(reference) > 120:
            raise ValueError("A supplier invoice reference (up to 120 characters) is required")
        if not isinstance(lines, list) or not 1 <= len(lines) <= 200:
            raise ValueError("Between 1 and 200 invoice lines required")
        try:
            tolerance = Decimal(str(price_tolerance_percent))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("Invalid price tolerance") from exc
        if not tolerance.is_finite() or not Decimal("0") <= tolerance <= Decimal("100"):
            raise ValueError("Price tolerance must be between 0 and 100 percent")

        existing = PurchaseBill.query.filter_by(
            organisation_id=context.organisation_id,
            supplier_id=order.supplier_id,
            supplier_invoice_reference=reference).first()

        # Legacy PO conversion records the source PO at bill header level but
        # does not allocate bill quantities to individual PO / GRN lines.
        # Any previously linked bill therefore blocks a "safe to clear" claim.
        # This is intentionally conservative until line-level allocation exists.
        prior_bills = [
            bill for bill in PurchaseBill.query.filter_by(
                organisation_id=context.organisation_id,
                supplier_id=order.supplier_id).all()
            if (bill.metadata_json or {}).get("source_purchase_order_id") == order.id
        ]
        if order.converted_bill_id and not any(
            bill.id == order.converted_bill_id for bill in prior_bills
        ):
            converted = PurchaseBill.query.filter_by(
                id=order.converted_bill_id,
                organisation_id=context.organisation_id,
                supplier_id=order.supplier_id).first()
            if converted is not None:
                prior_bills.append(converted)

        # Only issued GRNs count; acknowledgements do not constitute receipt.
        receipts = CommercialDocument.query.filter_by(
            organisation_id=context.organisation_id, document_type="grn",
            order_id=order.id, status="issued").all()
        received = {}
        accrued_quantity = {}
        accrued_cost = {}
        # A physical GRN does not establish a ledger accrual: only a linked,
        # immutable receipt event can be eligible for later GRNI clearance.
        receipt_ids = [document.id for document in receipts]
        events = (CommercialAccountingEvent.query.filter(
            CommercialAccountingEvent.organisation_id == context.organisation_id,
            CommercialAccountingEvent.document_id.in_(receipt_ids),
            CommercialAccountingEvent.event_type == "grn_inventory_accrual",
        ).all() if receipt_ids else [])
        linked_ids = {event.document_id for event in events}
        for document in receipts:
            for line in document.lines:
                received[line.order_line_id] = (
                    received.get(line.order_line_id, Decimal("0")) + line.quantity
                )
                if document.id in linked_ids:
                    accrued_quantity[line.order_line_id] = (
                        accrued_quantity.get(line.order_line_id, Decimal("0")) + line.quantity
                    )
                    accrued_cost[line.order_line_id] = (
                        accrued_cost.get(line.order_line_id, Decimal("0")) +
                        (Decimal(line.quantity) * Decimal(line.unit_price)).quantize(Decimal("0.01"))
                    )

        order_lines = {line.id: line for line in order.lines}
        seen = set()
        evaluated = []
        issues = []
        grni_issues = []
        total_net = Decimal("0.00")
        for index, supplied in enumerate(lines, 1):
            if not isinstance(supplied, dict):
                raise ValueError("Each invoice line must be an object")
            line_id = supplied.get("order_line_id")
            if not isinstance(line_id, str) or line_id not in order_lines or line_id in seen:
                raise ValueError("Invoice line must uniquely identify a line of this order")
            seen.add(line_id)
            original = order_lines[line_id]
            quantity = _quantity(supplied.get("quantity"))
            price = _money(supplied.get("unit_price"))
            ordered_qty = Decimal(original.quantity)
            received_qty = received.get(line_id, Decimal("0"))
            ordered_price = Decimal(original.unit_price)
            line_issues = []
            if quantity > ordered_qty:
                line_issues.append("exceeds_ordered_quantity")
            if match_type == "three_way" and quantity > received_qty:
                line_issues.append("exceeds_received_quantity")
            permitted_difference = (ordered_price * tolerance / Decimal("100"))
            if abs(price - ordered_price) > permitted_difference:
                line_issues.append("unit_price_variance")
            treatment = (original.dimensions or {}).get("item_treatment")
            stock = treatment == "stock"
            posted_quantity = accrued_quantity.get(line_id, Decimal("0"))
            posted_cost = accrued_cost.get(line_id, Decimal("0.00"))
            # A preview is *not* a reservation. Prior bill allocations,
            # returns and price variance treatment must be enforced atomically
            # before this data can support any actual clearing journal.
            if stock and quantity > posted_quantity:
                grni_issues.append(f"line_{index}:grni_receipt_accrual_missing")
            expected_net = (quantity * price).quantize(Decimal("0.01"))
            total_net += expected_net
            if line_issues:
                issues.extend(f"line_{index}:{issue}" for issue in line_issues)
            evaluated.append({
                "order_line_id": line_id,
                "ordered_quantity": str(ordered_qty),
                "received_quantity": str(received_qty),
                "proposed_invoice_quantity": str(quantity),
                "ordered_unit_price": str(ordered_price),
                "invoice_unit_price": str(price),
                "net_amount": str(expected_net),
                "issues": line_issues,
                "grni": {
                    "applicable": stock,
                    "posted_receipt_quantity": str(posted_quantity) if stock else None,
                    "posted_receipt_cost": str(posted_cost) if stock else None,
                    "accrual_coverage_sufficient": quantity <= posted_quantity if stock else None,
                    "clearing_posting_authorised": False,
                },
            })
        if prior_bills:
            issues.append("existing_po_bill_requires_line_allocation")
        if existing:
            issues.insert(0, "duplicate_supplier_invoice_reference")
        return {
            "company_id": context.organisation_id,
            "purchase_order_id": order.id,
            "purchase_order_number": order.order_number,
            "supplier_id": order.supplier_id,
            "supplier_invoice_reference": reference,
            "match_type": match_type,
            "price_tolerance_percent": str(tolerance),
            "matched": not issues,
            "issues": issues,
            "grni_issues": grni_issues,
            "grni_accrual_coverage_sufficient": not grni_issues,
            "grni_clearing_posting_authorised": False,
            "existing_linked_bill_count": len(prior_bills),
            "existing_linked_bill_ids": sorted(bill.id for bill in prior_bills),
            "invoice_net_total": str(total_net),
            "lines": evaluated,
            "preview_only": True,
            "posting_authorised": False,
        }
