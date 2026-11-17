"""Read-only GRNI receipt-to-invoice reconciliation.

Only GRNs with a posted accrual journal contribute to the ledger GRNI
balance; an operational receipt by itself is not a financial accrual.
"""
from decimal import Decimal

from ledgerone.extensions import db
from ledgerone.modules.commercial.models import (
    CommercialAccountingEvent, CommercialDocument, GRNIInvoiceAllocation,
)
from ledgerone.modules.purchases.order_models import PurchaseOrder


class GRNIReconciliationService:
    @staticmethod
    def preview(context, *, order_id):
        if not context.can("purchases.read"):
            raise PermissionError("purchases.read")
        order = db.session.get(PurchaseOrder, order_id)
        if not order or order.organisation_id != context.organisation_id:
            raise ValueError("Purchase order not found")
        grns = CommercialDocument.query.filter_by(
            organisation_id=context.organisation_id, order_id=order.id,
            document_type="grn", status="issued").all()
        events = CommercialAccountingEvent.query.filter(
            CommercialAccountingEvent.organisation_id == context.organisation_id,
            CommercialAccountingEvent.document_id.in_([x.id for x in grns] or [""]),
            CommercialAccountingEvent.event_type == "grn_inventory_accrual",
        ).all()
        posted_by_grn = {event.document_id: event for event in events}
        line_ids = [line.id for doc in grns for line in doc.lines]
        allocations = GRNIInvoiceAllocation.query.filter(
            GRNIInvoiceAllocation.organisation_id == context.organisation_id,
            GRNIInvoiceAllocation.receipt_line_id.in_(line_ids or [""]),
        ).all()
        allocated_qty = {}
        allocated_value = {}
        for row in allocations:
            allocated_qty[row.receipt_line_id] = (
                allocated_qty.get(row.receipt_line_id, Decimal("0")) + Decimal(row.quantity))
            allocated_value[row.receipt_line_id] = (
                allocated_value.get(row.receipt_line_id, Decimal("0")) + Decimal(row.accrual_value))
        po_lines = {line.id: line for line in order.lines}
        result = []
        issues = []
        total_posted = Decimal("0.00")
        total_cleared = Decimal("0.00")
        for grn in sorted(grns, key=lambda row: (row.document_date, row.document_number)):
            event = posted_by_grn.get(grn.id)
            for row in sorted(grn.lines, key=lambda line: line.line_number):
                source = po_lines.get(row.order_line_id)
                if source is None:
                    issues.append(f"GRN {grn.document_number} line {row.line_number} has no PO line")
                    continue
                treatment = (source.dimensions or {}).get("item_treatment", "unclassified")
                accrued = (Decimal(row.quantity) * Decimal(source.unit_price)).quantize(Decimal("0.01"))
                is_posted = bool(event and treatment == "stock")
                recorded = accrued if is_posted else Decimal("0.00")
                cleared = allocated_value.get(row.id, Decimal("0.00"))
                qty_cleared = allocated_qty.get(row.id, Decimal("0.0000"))
                if cleared > recorded or qty_cleared > Decimal(row.quantity):
                    issues.append(f"GRN {grn.document_number} has allocations exceeding accrued receipt")
                if not event and treatment == "stock":
                    issues.append(f"GRN {grn.document_number} has stock received without a posted GRNI journal")
                total_posted += recorded
                total_cleared += cleared
                result.append({
                    "grn_id": grn.id, "grn_number": grn.document_number,
                    "receipt_line_id": row.id, "order_line_id": row.order_line_id,
                    "description": source.description, "treatment": treatment,
                    "received_quantity": str(row.quantity),
                    "allocated_quantity": str(qty_cleared),
                    "available_quantity": str(Decimal(row.quantity) - qty_cleared),
                    "accrual_posted": is_posted,
                    "posted_accrual": str(recorded),
                    "cleared_accrual": str(cleared),
                    "outstanding_grni": str(recorded - cleared),
                })
        return {
            "order_id": order.id, "order_number": order.order_number,
            "currency": order.currency,
            "total_posted_grni": str(total_posted),
            "total_cleared_grni": str(total_cleared),
            "outstanding_grni": str(total_posted - total_cleared),
            "lines": result, "issues": issues,
            "preview_only": True, "posting_enabled": False,
        }
