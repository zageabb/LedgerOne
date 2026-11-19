"""Read-only review of PO-linked supplier bill drafts against goods receipts.

This is evidence for human review, not approval, quantity reservation,
posting authorisation, or a GRNI-clearing computation.
"""
from decimal import Decimal

from ledgerone.extensions import db
from ledgerone.modules.commercial.models import CommercialAccountingEvent, CommercialDocument
from ledgerone.modules.purchases.models import PurchaseBill
from ledgerone.modules.purchases.order_models import PurchaseOrder


class PurchaseBillDraftReview:
    @staticmethod
    def preview(context, *, order_id: str, bill_id: str):
        if not context.can("purchases.read"):
            raise PermissionError("purchases.read")
        order = PurchaseOrder.query.filter_by(
            id=order_id, organisation_id=context.organisation_id).first()
        if order is None:
            raise ValueError("Purchase order not found")
        bill = PurchaseBill.query.filter_by(
            id=bill_id, organisation_id=context.organisation_id,
            supplier_id=order.supplier_id).first()
        if (bill is None or
                (bill.metadata_json or {}).get("source_purchase_order_id") != order.id):
            raise ValueError("PO-linked supplier bill not found")
        if (bill.metadata_json or {}).get("creation_mode") != "multiline_po_draft":
            raise ValueError("Only sourced multi-line supplier bill drafts can be reviewed")
        if bill.status != "draft" or bill.posted_journal_id is not None:
            raise ValueError("Only unposted supplier bill drafts can be reviewed")
        if bill.currency != order.currency:
            raise ValueError("Bill currency differs from PO currency")

        other_bills = [
            row for row in PurchaseBill.query.filter_by(
                organisation_id=context.organisation_id,
                supplier_id=order.supplier_id).all()
            if (row.metadata_json or {}).get("source_purchase_order_id") == order.id
        ]
        order_lines = {line.id: line for line in order.lines}
        billed_qty = {line_id: Decimal("0") for line_id in order_lines}
        issues = []
        for linked in other_bills:
            if ((linked.metadata_json or {}).get("creation_mode") != "multiline_po_draft"
                    or linked.status != "draft" or linked.posted_journal_id):
                issues.append("legacy_or_posted_bill_requires_reconciliation")
                continue
            for line in linked.lines:
                source_id = (line.dimensions or {}).get("source_purchase_order_line_id")
                if source_id not in billed_qty:
                    issues.append("unverified_po_line_in_linked_bill")
                    continue
                billed_qty[source_id] += Decimal(line.quantity)

        receipts = CommercialDocument.query.filter_by(
            organisation_id=context.organisation_id,
            document_type="grn", order_id=order.id, status="issued").all()
        received_qty = {line_id: Decimal("0") for line_id in order_lines}
        accrued_qty = {line_id: Decimal("0") for line_id in order_lines}
        receipt_ids = [receipt.id for receipt in receipts]
        events = (CommercialAccountingEvent.query.filter(
            CommercialAccountingEvent.organisation_id == context.organisation_id,
            CommercialAccountingEvent.document_id.in_(receipt_ids),
            CommercialAccountingEvent.event_type == "grn_inventory_accrual",
        ).all() if receipt_ids else [])
        accrued_document_ids = {event.document_id for event in events}
        for receipt in receipts:
            for line in receipt.lines:
                if line.order_line_id not in order_lines:
                    issues.append("invalid_receipt_po_line")
                    continue
                received_qty[line.order_line_id] += Decimal(line.quantity)
                if receipt.id in accrued_document_ids:
                    accrued_qty[line.order_line_id] += Decimal(line.quantity)

        evaluated = []
        for line in sorted(bill.lines, key=lambda item: item.line_number):
            source_id = (line.dimensions or {}).get("source_purchase_order_line_id")
            original = order_lines.get(source_id)
            if original is None:
                issues.append(f"bill_line_{line.line_number}:invalid_po_line")
                continue
            treatment = (original.dimensions or {}).get("item_treatment")
            total = billed_qty[source_id]
            received = received_qty[source_id]
            posted = accrued_qty[source_id]
            row_issues = []
            if total > Decimal(original.quantity):
                row_issues.append("exceeds_order_quantity")
            if total > received:
                row_issues.append("invoice_quantity_exceeds_receipts")
            if Decimal(line.unit_price) != Decimal(original.unit_price):
                row_issues.append("price_variance_requires_review")
            if treatment == "stock" and total > posted:
                row_issues.append("stock_grni_accrual_incomplete")
            issues.extend(f"bill_line_{line.line_number}:{item}" for item in row_issues)
            evaluated.append({
                "bill_line_number": line.line_number,
                "description": line.description,
                "source_purchase_order_line_id": source_id,
                "item_treatment": treatment or "unclassified",
                "ordered_quantity": str(original.quantity),
                "received_quantity": str(received),
                "total_linked_draft_quantity": str(total),
                "this_bill_quantity": str(line.quantity),
                "remaining_received_unbilled_quantity": str(max(Decimal("0"), received - total)),
                "posted_accrual_quantity": str(posted) if treatment == "stock" else None,
                "po_unit_price": str(original.unit_price),
                "bill_unit_price": str(line.unit_price),
                "net_amount": str(line.net_amount),
                "tax_amount": str(line.tax_amount),
                "issues": row_issues,
            })
        return {
            "purchase_order_id": order.id,
            "purchase_order_number": order.order_number,
            "bill_id": bill.id,
            "bill_number": bill.bill_number,
            "supplier_invoice_reference": bill.supplier_invoice_reference,
            "subtotal": str(bill.subtotal),
            "tax_total": str(bill.tax_total),
            "total": str(bill.total),
            "currency": bill.currency,
            "issues": sorted(set(issues)),
            "lines": evaluated,
            "operational_match": not issues,
            "preview_only": True,
            "approval_authorised": False,
            "posting_authorised": False,
            "grni_clearing_authorised": False,
        }
