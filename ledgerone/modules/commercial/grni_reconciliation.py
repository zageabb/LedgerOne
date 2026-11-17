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
from ledgerone.models.core import Setting
from ledgerone.models.ledger import Journal
from ledgerone.modules.purchases.models import PurchaseBill


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
        posted_by_grn = {}
        for event in events:
            source_journal = db.session.get(Journal, event.journal_id)
            reversal = Journal.query.filter_by(
                organisation_id=context.organisation_id,
                reversal_of_id=event.journal_id, status="posted").first()
            if (source_journal and source_journal.organisation_id == context.organisation_id
                    and source_journal.status == "posted" and not reversal):
                posted_by_grn[event.document_id] = event
        line_ids = [line.id for doc in grns for line in doc.lines]
        allocations = GRNIInvoiceAllocation.query.filter(
            GRNIInvoiceAllocation.organisation_id == context.organisation_id,
            GRNIInvoiceAllocation.receipt_line_id.in_(line_ids or [""]),
        ).all()
        issues = []
        config = Setting.query.filter_by(
            organisation_id=context.organisation_id,
            scope="erp_inventory_accounting", key="configuration").first()
        grni_id = (((config.value or {}).get("accounts") or {}).get("grni_clearing")
                   if config else None)
        # An allocation only counts as cleared when the *bill's own posting*
        # debited the configured GRNI account for the allocated accrual value.
        # Merely having an allocation row, or an unrelated journal, is not enough.
        by_bill = {}
        for row in allocations:
            by_bill.setdefault(row.bill_id, []).append(row)
        valid_allocations = []
        for bill_id, rows in by_bill.items():
            bill = db.session.get(PurchaseBill, bill_id)
            journal = db.session.get(Journal, rows[0].clearing_journal_id)
            cleared_on_journal = sum(
                (Decimal(line.debit) - Decimal(line.credit)
                 for line in journal.lines if line.account_id == grni_id),
                Decimal("0")) if journal and grni_id else Decimal("0")
            requested = sum((Decimal(row.accrual_value) for row in rows), Decimal("0"))
            if (not bill or bill.organisation_id != context.organisation_id
                    or bill.supplier_id != order.supplier_id or bill.status != "posted"
                    or not journal or journal.organisation_id != context.organisation_id
                    or journal.id != bill.posted_journal_id or journal.status != "posted"
                    or Journal.query.filter_by(organisation_id=context.organisation_id,
                                               reversal_of_id=journal.id, status="posted").first() is not None
                    or any(row.clearing_journal_id != journal.id for row in rows)
                    or not grni_id or cleared_on_journal < requested):
                issues.append(f"Bill {bill_id} does not have verified GRNI clearing journal evidence")
                continue
            valid_allocations.extend(rows)
        allocated_qty = {}
        allocated_value = {}
        for row in valid_allocations:
            allocated_qty[row.receipt_line_id] = (
                allocated_qty.get(row.receipt_line_id, Decimal("0")) + Decimal(row.quantity))
            allocated_value[row.receipt_line_id] = (
                allocated_value.get(row.receipt_line_id, Decimal("0")) + Decimal(row.accrual_value))
        po_lines = {line.id: line for line in order.lines}
        result = []
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
