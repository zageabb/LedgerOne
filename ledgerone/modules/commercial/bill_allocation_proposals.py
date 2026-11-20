"""Non-authoritative FIFO suggestion for distributing an invoice draft over GRN lines.

No writes, locks, reservations, approval or GRNI posting. The proposal never
claims that another draft has reserved a receipt; reviewers must coordinate
concurrent drafts and revalidate against persistent allocations at posting.
"""
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from ledgerone.extensions import db
from ledgerone.modules.commercial.models import (
    CommercialDocument, CommercialAccountingEvent, PurchaseReceiptBillAllocation,
)
from ledgerone.modules.purchases.models import PurchaseBill, PurchaseBillLine
from ledgerone.modules.purchases.order_models import PurchaseOrder


class BillReceiptProposalService:
    @staticmethod
    def preview(context, *, order_id, bill_id):
        if not context.can("purchases.read"):
            raise PermissionError("purchases.read")
        order = PurchaseOrder.query.filter_by(
            id=order_id, organisation_id=context.organisation_id).first()
        if order is None:
            raise ValueError("Purchase order not found")
        bill = PurchaseBill.query.filter_by(
            id=bill_id, organisation_id=context.organisation_id,
            supplier_id=order.supplier_id).first()
        if (bill is None or bill.status != "draft" or bill.posted_journal_id
                or (bill.metadata_json or {}).get("creation_mode") != "multiline_po_draft"
                or (bill.metadata_json or {}).get("source_purchase_order_id") != order.id):
            raise ValueError("Eligible PO-linked supplier bill draft not found")
        if bill.currency != order.currency:
            raise ValueError("Bill and PO currency mismatch")

        lines_by_id = {line.id: line for line in order.lines}
        receipts = CommercialDocument.query.filter_by(
            organisation_id=context.organisation_id, order_id=order.id,
            document_type="grn", status="issued").all()
        receipts.sort(key=lambda row: (row.document_date, row.document_number, row.id))
        receipt_lines = [
            (doc, line) for doc in receipts
            for line in sorted(doc.lines, key=lambda row: (row.line_number, row.id))
            if line.order_line_id in lines_by_id
        ]
        receipt_ids = [doc.id for doc in receipts]
        events = (CommercialAccountingEvent.query.filter(
            CommercialAccountingEvent.organisation_id == context.organisation_id,
            CommercialAccountingEvent.document_id.in_(receipt_ids),
            CommercialAccountingEvent.event_type == "grn_inventory_accrual"
        ).all() if receipt_ids else [])
        posted_receipts = {event.document_id for event in events}

        receipt_ids_by_line = [line.id for _, line in receipt_lines]
        persisted = (PurchaseReceiptBillAllocation.query.filter(
            PurchaseReceiptBillAllocation.organisation_id == context.organisation_id,
            PurchaseReceiptBillAllocation.receipt_line_id.in_(receipt_ids_by_line)
        ).all() if receipt_ids_by_line else [])
        used = defaultdict(lambda: Decimal("0"))
        already_for_bill = set()
        invalid_allocation_ids = []
        invalid_bill_line_allocation_ids = []
        receipt_line_lookup = {line.id: line for _, line in receipt_lines}
        current_bill_line_ids = {line.id for line in bill.lines}
        # A valid GRN-to-PO link alone is insufficient. Its supplier bill
        # line must also belong to this company, supplier, PO and PO line.
        linked_bill_line_ids = {row.bill_line_id for row in persisted}
        linked_bill_lines = {
            row.id: row for row in PurchaseBillLine.query.filter(
                PurchaseBillLine.id.in_(linked_bill_line_ids)
            ).all()
        } if linked_bill_line_ids else {}
        linked_bill_ids = {row.bill_id for row in linked_bill_lines.values()}
        parent_bills = {
            row.id: row for row in PurchaseBill.query.filter(
                PurchaseBill.id.in_(linked_bill_ids),
                PurchaseBill.organisation_id == context.organisation_id,
                PurchaseBill.supplier_id == order.supplier_id,
            ).all()
        } if linked_bill_ids else {}
        for item in persisted:
            receipt_line = receipt_line_lookup.get(item.receipt_line_id)
            quantity = Decimal(item.quantity)
            if (receipt_line is None
                    or item.purchase_order_line_id != receipt_line.order_line_id
                    or not quantity.is_finite() or quantity <= 0):
                invalid_allocation_ids.append(item.id)
                continue
            linked_line = linked_bill_lines.get(item.bill_line_id)
            parent_bill = parent_bills.get(linked_line.bill_id) if linked_line else None
            if (parent_bill is None
                    or (parent_bill.metadata_json or {}).get("source_purchase_order_id") != order.id
                    or (linked_line.dimensions or {}).get("source_purchase_order_line_id")
                    != item.purchase_order_line_id
                    or parent_bill.currency != order.currency):
                invalid_bill_line_allocation_ids.append(item.id)
                continue
            used[item.receipt_line_id] += quantity
            if item.bill_line_id in current_bill_line_ids:
                already_for_bill.add(item.bill_line_id)
        overallocated_receipt_ids = sorted(
            receipt_line_id for receipt_line_id, amount in used.items()
            if amount > Decimal(receipt_line_lookup[receipt_line_id].quantity)
        )

        linked_bills = [
            row for row in PurchaseBill.query.filter_by(
                organisation_id=context.organisation_id,
                supplier_id=order.supplier_id).all()
            if (row.metadata_json or {}).get("source_purchase_order_id") == order.id
            and row.id != bill.id
        ]
        warnings = []
        if invalid_allocation_ids:
            warnings.append("invalid_persisted_receipt_allocations")
        if invalid_bill_line_allocation_ids:
            warnings.append("invalid_persisted_supplier_bill_lineage")
        if overallocated_receipt_ids:
            warnings.append("overallocated_receipt_line")
        if linked_bills:
            warnings.append("other_po_linked_bills_are_not_receipt_reservations")
        if any((row.metadata_json or {}).get("creation_mode") != "multiline_po_draft"
               or row.status != "draft" for row in linked_bills):
            warnings.append("legacy_or_posted_bill_requires_reconciliation")

        proposed = []
        shortages = []
        for bill_line in sorted(bill.lines, key=lambda line: (line.line_number, line.id)):
            po_line_id = (bill_line.dimensions or {}).get("source_purchase_order_line_id")
            if po_line_id not in lines_by_id:
                shortages.append({"bill_line_id": bill_line.id,
                                  "reason": "unverified_bill_po_line"})
                continue
            if bill_line.id in already_for_bill:
                shortages.append({"bill_line_id": bill_line.id,
                                  "reason": "bill_line_has_existing_allocation"})
                continue
            po_line = lines_by_id[po_line_id]
            remaining = Decimal(bill_line.quantity)
            if remaining <= 0:
                shortages.append({"bill_line_id": bill_line.id,
                                  "reason": "invalid_bill_quantity"})
                continue
            for doc, receipt_line in receipt_lines:
                if remaining <= 0:
                    break
                if receipt_line.order_line_id != po_line_id:
                    continue
                stock = (po_line.dimensions or {}).get("item_treatment") == "stock"
                # Never propose stock against a receipt lacking an accrual journal.
                if stock and doc.id not in posted_receipts:
                    continue
                available = Decimal(receipt_line.quantity) - used[receipt_line.id]
                if available <= 0:
                    continue
                qty = min(remaining, available)
                used[receipt_line.id] += qty  # in-memory proposal only
                remaining -= qty
                proposed.append({
                    "bill_line_id": bill_line.id,
                    "bill_line_number": bill_line.line_number,
                    "receipt_id": doc.id,
                    "receipt_number": doc.document_number,
                    "receipt_line_id": receipt_line.id,
                    "po_line_id": po_line_id,
                    "quantity": str(qty),
                    "receipt_unit_cost": str(receipt_line.unit_price),
                    "bill_unit_price": str(bill_line.unit_price),
                    "receipt_cost_estimate": str(
                        (qty * Decimal(receipt_line.unit_price)).quantize(
                            Decimal("0.01"), rounding=ROUND_HALF_UP)),
                    "invoice_net_estimate": str(
                        (qty * Decimal(bill_line.unit_price)).quantize(
                            Decimal("0.01"), rounding=ROUND_HALF_UP)),
                    "posted_receipt_accrual": doc.id in posted_receipts,
                })
            if remaining > 0:
                shortages.append({
                    "bill_line_id": bill_line.id,
                    "reason": "insufficient_eligible_receipt_quantity",
                    "uncovered_quantity": str(remaining),
                })
        return {
            "order_id": order.id, "bill_id": bill.id,
            "proposals": proposed, "shortages": shortages,
            "warnings": warnings, "fully_covered_in_preview": not shortages,
            "invalid_persisted_allocation_ids": sorted(invalid_allocation_ids),
            "invalid_bill_line_allocation_ids": sorted(invalid_bill_line_allocation_ids),
            "overallocated_receipt_line_ids": overallocated_receipt_ids,
            "evidence_safe_for_review": not shortages and not warnings,
            "preview_only": True, "allocation_reserved": False,
            "posting_authorised": False, "grni_clearing_authorised": False,
            "note": "FIFO suggestions only. Other drafts are not reserved or deducted; all allocations require atomic posting-time validation.",
        }
