"""Read-only PO -> GRN -> supplier bill line quantity lineage.

Allocation writers, posting and quantity reservations are intentionally absent.
Never use this read model as an atomic authority for bill or GRNI posting.
"""
from decimal import Decimal

from ledgerone.extensions import db
from ledgerone.modules.commercial.models import (
    CommercialDocument, PurchaseReceiptBillAllocation,
)
from ledgerone.modules.purchases.order_models import PurchaseOrder


class PurchaseReceiptAllocationService:
    @staticmethod
    def summary(context, *, order_id: str):
        if not context.can("purchases.read"):
            raise PermissionError("purchases.read")
        order = db.session.get(PurchaseOrder, order_id)
        if not order or order.organisation_id != context.organisation_id:
            raise ValueError("Purchase order not found")

        receipts = CommercialDocument.query.filter_by(
            organisation_id=context.organisation_id,
            document_type="grn", order_id=order.id, status="issued",
        ).all()
        quantities = {line.id: Decimal("0") for line in order.lines}
        valid_receipt_lines = set()
        for receipt in receipts:
            for line in receipt.lines:
                if line.order_line_id in quantities:
                    quantities[line.order_line_id] += Decimal(line.quantity)
                    valid_receipt_lines.add(line.id)

        allocated = {line.id: Decimal("0") for line in order.lines}
        orphaned = []
        allocations = PurchaseReceiptBillAllocation.query.filter_by(
            organisation_id=context.organisation_id,
        ).filter(
            PurchaseReceiptBillAllocation.purchase_order_line_id.in_(list(quantities)),
        ).all() if quantities else []
        for allocation in allocations:
            if allocation.receipt_line_id not in valid_receipt_lines:
                orphaned.append(allocation.id)
                continue
            allocated[allocation.purchase_order_line_id] += Decimal(allocation.quantity)

        return {
            "purchase_order_id": order.id,
            "purchase_order_number": order.order_number,
            "lines": [{
                "order_line_id": line.id,
                "ordered_quantity": str(line.quantity),
                "received_quantity": str(quantities[line.id]),
                "allocated_invoice_quantity": str(allocated[line.id]),
                "remaining_received_quantity": str(
                    max(Decimal("0"), quantities[line.id] - allocated[line.id])
                ),
                "overallocated": allocated[line.id] > quantities[line.id],
            } for line in order.lines],
            "invalid_allocation_ids": sorted(orphaned),
            "preview_only": True,
            "posting_authorised": False,
            "note": "Read-only quantities; no posting or invoice reservations. Prior legacy bills may lack allocations.",
        }
