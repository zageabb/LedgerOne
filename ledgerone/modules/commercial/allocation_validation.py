"""Read-only validation of proposed PO/GRN/supplier-bill line allocations.

Never reserves quantities, writes allocations, or posts GRNI. Concurrent changes
must be revalidated under a PO lock in the future posting transaction.
"""
from decimal import Decimal, InvalidOperation

from ledgerone.extensions import db
from ledgerone.modules.commercial.models import (
    CommercialDocument, CommercialDocumentLine, PurchaseReceiptBillAllocation,
)
from ledgerone.modules.purchases.models import PurchaseBill, PurchaseBillLine
from ledgerone.modules.purchases.order_models import PurchaseOrder


def _positive_quantity(value):
    try:
        parsed = Decimal(str(value))
        rounded = parsed.quantize(Decimal("0.0001"))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Invalid allocation quantity") from exc
    if not parsed.is_finite() or parsed <= 0 or parsed != rounded:
        raise ValueError("Allocation quantity must be positive with up to four decimals")
    return rounded


class PurchaseReceiptAllocationValidation:
    @staticmethod
    def preview(context, *, order_id, bill_id, allocations):
        if not context.can("purchases.read"):
            raise PermissionError("purchases.read")
        order = PurchaseOrder.query.filter_by(
            id=order_id, organisation_id=context.organisation_id).first()
        if order is None:
            raise ValueError("Purchase order not found")
        bill = PurchaseBill.query.filter_by(
            id=bill_id, organisation_id=context.organisation_id,
            supplier_id=order.supplier_id).first()
        if bill is None:
            raise ValueError("Supplier bill not found for this purchase order")
        if ((bill.metadata_json or {}).get("source_purchase_order_id") != order.id
                and order.converted_bill_id != bill.id):
            raise ValueError("Supplier bill is not linked to this purchase order")
        if bill.currency != order.currency:
            raise ValueError("Bill and order currencies differ")
        if not isinstance(allocations, list) or not 1 <= len(allocations) <= 200:
            raise ValueError("Between 1 and 200 allocations required")

        line_by_id = {line.id: line for line in order.lines}
        bill_lines = {line.id: line for line in bill.lines}
        receipts = CommercialDocument.query.filter_by(
            organisation_id=context.organisation_id, order_id=order.id,
            document_type="grn", status="issued").all()
        receipt_lines = {
            line.id: line for receipt in receipts for line in receipt.lines
            if line.order_line_id in line_by_id
        }
        # Existing allocations across all bills consume GRN quantities.
        receipt_used = {line_id: Decimal("0") for line_id in receipt_lines}
        bill_used = {line_id: Decimal("0") for line_id in bill_lines}
        existing_pairs = set()
        issues_preexisting = []
        prior_invalid_allocation_ids = []
        existing = (PurchaseReceiptBillAllocation.query.filter_by(
            organisation_id=context.organisation_id
        ).filter(
            PurchaseReceiptBillAllocation.receipt_line_id.in_(list(receipt_lines))
        ).all() if receipt_lines else [])
        source_bill_line_ids = {entry.bill_line_id for entry in existing}
        source_bill_lines = {
            line.id: line for line in PurchaseBillLine.query.filter(
                PurchaseBillLine.id.in_(source_bill_line_ids)
            ).all()
        } if source_bill_line_ids else {}
        parent_ids = {line.bill_id for line in source_bill_lines.values()}
        parent_bills = {
            row.id: row for row in PurchaseBill.query.filter(
                PurchaseBill.id.in_(parent_ids),
                PurchaseBill.organisation_id == context.organisation_id,
                PurchaseBill.supplier_id == order.supplier_id
            ).all()
        } if parent_ids else {}
        for entry in existing:
            receipt_line = receipt_lines[entry.receipt_line_id]
            linked_line = source_bill_lines.get(entry.bill_line_id)
            linked_bill = parent_bills.get(linked_line.bill_id) if linked_line else None
            quantity = Decimal(entry.quantity)
            if (entry.purchase_order_line_id != receipt_line.order_line_id
                    or not quantity.is_finite() or quantity <= 0
                    or linked_bill is None
                    or (linked_bill.metadata_json or {}).get("source_purchase_order_id") != order.id
                    or linked_bill.currency != order.currency
                    or (linked_line.dimensions or {}).get("source_purchase_order_line_id")
                    != receipt_line.order_line_id):
                prior_invalid_allocation_ids.append(entry.id)
                continue
            receipt_used[entry.receipt_line_id] += quantity
            if entry.bill_line_id in bill_used:
                bill_used[entry.bill_line_id] += quantity
            existing_pairs.add((entry.bill_line_id, entry.receipt_line_id))
        for receipt_line_id, consumed in receipt_used.items():
            if consumed > Decimal(receipt_lines[receipt_line_id].quantity):
                issues_preexisting.append("previous_receipt_overallocated")
        for bill_line_id, consumed in bill_used.items():
            if consumed > Decimal(bill_lines[bill_line_id].quantity):
                issues_preexisting.append("previous_bill_line_overallocated")

        requested_receipt = {}
        requested_bill = {}
        seen = set()
        results = []
        issues = list(dict.fromkeys(issues_preexisting))
        if prior_invalid_allocation_ids:
            issues.insert(0, "invalid_persisted_allocation_lineage")
        for index, proposal in enumerate(allocations, 1):
            if not isinstance(proposal, dict):
                raise ValueError("Every allocation must be an object")
            receipt_id = proposal.get("receipt_line_id")
            bill_line_id = proposal.get("bill_line_id")
            if receipt_id not in receipt_lines or bill_line_id not in bill_lines:
                raise ValueError("Allocation line does not belong to the selected GRN or bill")
            receipt_line = receipt_lines[receipt_id]
            bill_line = bill_lines[bill_line_id]
            quantity = _positive_quantity(proposal.get("quantity"))
            pair = (bill_line_id, receipt_id)
            row_issues = []
            if pair in seen or pair in existing_pairs:
                row_issues.append("duplicate_bill_receipt_line_pair")
            seen.add(pair)
            requested_receipt[receipt_id] = requested_receipt.get(receipt_id, Decimal("0")) + quantity
            requested_bill[bill_line_id] = requested_bill.get(bill_line_id, Decimal("0")) + quantity
            # Legacy purchase bills use quantity=1 for the entire value, so
            # no unverified assumption is made that bill quantity equals PO units.
            if (bill_line.dimensions or {}).get("source_purchase_order_line_id") != receipt_line.order_line_id:
                row_issues.append("bill_line_po_line_link_unverified")
            if receipt_used[receipt_id] + requested_receipt[receipt_id] > Decimal(receipt_line.quantity):
                row_issues.append("receipt_quantity_exceeded")
            if bill_used[bill_line_id] + requested_bill[bill_line_id] > Decimal(bill_line.quantity):
                row_issues.append("bill_line_quantity_exceeded")
            issues.extend(f"allocation_{index}:{issue}" for issue in row_issues)
            results.append({
                "receipt_line_id": receipt_id,
                "bill_line_id": bill_line_id,
                "quantity": str(quantity),
                "issues": row_issues,
            })
        return {
            "purchase_order_id": order.id,
            "bill_id": bill.id,
            "valid": not issues,
            "issues": issues,
            "invalid_persisted_allocation_ids": sorted(prior_invalid_allocation_ids),
            "allocations": results,
            "preview_only": True,
            "posting_authorised": False,
            "note": "Validation is read-only. Actual allocations require atomic locking and source-linked bill lines; no GRNI clearing is authorised.",
        }
