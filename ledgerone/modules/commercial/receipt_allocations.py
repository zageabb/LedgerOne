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
        receipt_line_owners = {}
        receipt_line_quantities = {}
        for receipt in receipts:
            for line in receipt.lines:
                if line.order_line_id in quantities:
                    quantities[line.order_line_id] += Decimal(line.quantity)
                    receipt_line_owners[line.id] = line.order_line_id
                    receipt_line_quantities[line.id] = Decimal(line.quantity)

        allocated = {line.id: Decimal("0") for line in order.lines}
        allocated_per_receipt = {line_id: Decimal("0") for line_id in receipt_line_owners}
        invalid = []
        allocations = PurchaseReceiptBillAllocation.query.filter_by(
            organisation_id=context.organisation_id,
        ).filter(
            PurchaseReceiptBillAllocation.purchase_order_line_id.in_(list(quantities)),
        ).all() if quantities else []
        for allocation in allocations:
            # Reject evidence linked to a different PO line or a receipt which
            # is not an issued GRN for this PO. Never count invalid allocations.
            owner = receipt_line_owners.get(allocation.receipt_line_id)
            if owner != allocation.purchase_order_line_id:
                invalid.append(allocation.id)
                continue
            quantity = Decimal(allocation.quantity)
            allocated[owner] += quantity
            allocated_per_receipt[allocation.receipt_line_id] += quantity

        overallocated_receipts = sorted(
            receipt_id for receipt_id, quantity in allocated_per_receipt.items()
            if quantity > receipt_line_quantities[receipt_id]
        )
        overallocated_lines = {
            line_id for line_id, quantity in allocated.items()
            if quantity > quantities[line_id]
        }
        evidence_valid = not (invalid or overallocated_receipts or overallocated_lines)

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
                "overallocated": line.id in overallocated_lines,
                "allocation_evidence_valid": evidence_valid,
            } for line in order.lines],
            "invalid_allocation_ids": sorted(invalid),
            "overallocated_receipt_line_ids": overallocated_receipts,
            "allocation_evidence_valid": evidence_valid,
            "quantity_available_for_posting_certified": False,
            "preview_only": True,
            "posting_authorised": False,
            "note": "Read-only evidence checks only; no posting, invoice reservations or certification. Prior legacy bills may lack allocations.",
        }
