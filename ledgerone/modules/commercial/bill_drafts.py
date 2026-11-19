"""PO-linked multi-line supplier bill drafts; no ledger posting or GRNI clearing.

A draft is a commercial capture record, not approval to recognise liability.
Existing independently posted / legacy bills cannot be backfilled by this service.
"""
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from ledgerone.extensions import db
from ledgerone.models.core import new_id
from ledgerone.modules.purchases.models import PurchaseBill, PurchaseBillLine
from ledgerone.modules.purchases.order_models import PurchaseOrder
from ledgerone.modules.tax.services import TaxService
from ledgerone.services.audit import record_audit_event
from ledgerone.services.payment_terms import PaymentTermsService


def _quantity(value):
    try:
        original = Decimal(str(value))
        rounded = original.quantize(Decimal("0.0001"))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("Invalid bill quantity") from exc
    if not original.is_finite() or original <= 0 or original != rounded:
        raise ValueError("Bill quantity must be positive with at most four decimal places")
    return rounded


def _price(value):
    try:
        original = Decimal(str(value))
        rounded = original.quantize(Decimal("0.0001"))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("Invalid bill unit price") from exc
    if not original.is_finite() or original < 0 or original != rounded:
        raise ValueError("Bill price must be nonnegative with at most four decimal places")
    return rounded


class PurchaseBillDraftService:
    @staticmethod
    def create(context, *, order_id, supplier_invoice_reference, bill_date, lines,
               bill_number=None, due_date=None):
        if not context.can("purchases.write"):
            raise PermissionError("purchases.write")
        order = PurchaseOrder.query.filter_by(
            id=order_id, organisation_id=context.organisation_id).first()
        if order is None:
            raise ValueError("Purchase order not found")
        if order.status not in {"approved", "sent"}:
            raise ValueError("Only approved or sent purchase orders can be invoiced")
        if not isinstance(bill_date, date):
            raise ValueError("Bill date is required")
        if not isinstance(lines, list) or not 1 <= len(lines) <= 200:
            raise ValueError("Between 1 and 200 bill lines are required")
        reference = (supplier_invoice_reference or "").strip()
        if not reference or len(reference) > 120:
            raise ValueError("Supplier invoice reference is required (up to 120 characters)")
        number = (bill_number or "").strip() or "DRAFT-" + new_id()
        if len(number) > 120:
            raise ValueError("Bill number exceeds 120 characters")
        supplier = order.supplier
        if not supplier or not supplier.is_active:
            raise ValueError("Supplier is inactive")
        if due_date is None:
            due_date = PaymentTermsService.supplier_due_date(
                context.organisation_id, bill_date, supplier.payment_terms_days)
        if not isinstance(due_date, date) or due_date < bill_date:
            raise ValueError("Bill due date cannot precede bill date")
        if PurchaseBill.query.filter_by(
                organisation_id=context.organisation_id, bill_number=number).first():
            raise ValueError("Bill number already exists")
        if PurchaseBill.query.filter_by(
                organisation_id=context.organisation_id,
                supplier_id=order.supplier_id,
                supplier_invoice_reference=reference).first():
            raise ValueError("Supplier invoice reference already exists")

        # A legacy posted conversion has no PO-line quantity provenance.
        # Fail closed rather than silently allowing another invoice for it.
        linked = [
            bill for bill in PurchaseBill.query.filter_by(
                organisation_id=context.organisation_id,
                supplier_id=order.supplier_id).all()
            if (bill.metadata_json or {}).get("source_purchase_order_id") == order.id
        ]
        if order.converted_bill_id or any(
                bill.status != "draft" or any(
                    (line.dimensions or {}).get("source_purchase_order_line_id") is None
                    for line in bill.lines)
                for bill in linked):
            raise ValueError("Legacy or posted PO-linked bills require allocation reconciliation")

        po_lines = {line.id: line for line in order.lines}
        historical = {line_id: Decimal("0") for line_id in po_lines}
        for bill in linked:
            for line in bill.lines:
                line_id = (line.dimensions or {}).get("source_purchase_order_line_id")
                if line_id not in historical:
                    raise ValueError("Prior bill has an invalid PO-line link")
                historical[line_id] += Decimal(line.quantity)

        prepared = []
        seen = set()
        subtotal = Decimal("0.00")
        tax_total = Decimal("0.00")
        for index, supplied in enumerate(lines, 1):
            if not isinstance(supplied, dict):
                raise ValueError("Bill line must be an object")
            line_id = supplied.get("order_line_id")
            if line_id not in po_lines or line_id in seen:
                raise ValueError("Bill lines must uniquely identify PO lines")
            seen.add(line_id)
            source = po_lines[line_id]
            qty = _quantity(supplied.get("quantity"))
            price = _price(supplied.get("unit_price"))
            if qty + historical[line_id] > Decimal(source.quantity):
                raise ValueError(f"Bill line {index} exceeds remaining PO quantity")
            if supplied.get("tax_code_id", source.tax_code_id) != source.tax_code_id:
                raise ValueError("Draft tax code must agree with PO line")
            tax_code = TaxService.code_for_use(context, source.tax_code_id, "purchase")
            net = (qty * price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            tax = TaxService.tax_amount(net, tax_code)
            subtotal += net
            tax_total += tax
            prepared.append((source, qty, price, net, tax))
        if subtotal <= 0:
            raise ValueError("Bill net total must be positive")

        bill = PurchaseBill(
            id=new_id(), organisation_id=context.organisation_id,
            supplier_id=order.supplier_id, bill_number=number,
            supplier_invoice_reference=reference, bill_date=bill_date,
            tax_point=bill_date, due_date=due_date, currency=order.currency,
            status="draft", subtotal=subtotal, tax_total=tax_total,
            total=subtotal + tax_total, posted_journal_id=None,
            metadata_json={"source_purchase_order_id": order.id,
                           "source_purchase_order_number": order.order_number,
                           "creation_mode": "multiline_po_draft"},
        )
        try:
            db.session.add(bill)
            db.session.flush()
            for index, (source, qty, price, net, tax) in enumerate(prepared, 1):
                db.session.add(PurchaseBillLine(
                    bill_id=bill.id, line_number=index,
                    description=source.description, quantity=qty,
                    unit_price=price, net_amount=net, tax_amount=tax,
                    tax_code_id=source.tax_code_id,
                    expense_account_id=source.expense_account_id,
                    dimensions={"source_purchase_order_line_id": source.id,
                                "item_treatment": (source.dimensions or {}).get("item_treatment")},
                ))
            db.session.flush()
            record_audit_event(
                context, module_id="purchases",
                action="po_linked_multiline_bill_draft_created",
                entity_type="purchase_bill", entity_id=bill.id,
                detail={"order_id": order.id, "line_count": len(prepared),
                        "net_total": str(subtotal), "tax_total": str(tax_total),
                        "posting": False})
            db.session.commit()
            return bill
        except Exception:
            db.session.rollback()
            raise
