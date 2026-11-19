from datetime import date, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from ledgerone.module_registry import module_registry
from ledgerone.modules.commercial.models import CommercialDocument
from ledgerone.modules.commercial.services import CommercialDocumentService
from ledgerone.modules.purchases.orders import PurchaseOrderService
from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.security import browser_context, require_module
from ledgerone.services.ledger import LedgerService

bp = Blueprint("purchase_orders", __name__, url_prefix="/purchases/orders")


@bp.route("/", methods=["GET", "POST"])
@login_required
@require_module("purchases")
def index():
    context = browser_context()
    match_preview = None
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "create":
                PurchaseOrderService.create_order(
                    context,
                    supplier_id=request.form.get("supplier_id", ""),
                    order_number=request.form.get("order_number", ""),
                    order_date=date.fromisoformat(request.form.get("order_date") or date.today().isoformat()),
                    expected_date=date.fromisoformat(request.form["expected_date"]) if request.form.get("expected_date") else None,
                    description=request.form.get("description", "Purchase"),
                    amount=request.form.get("amount", "0"),
                    payable_account_id=request.form.get("payable_account_id", ""),
                    expense_account_id=request.form.get("expense_account_id", ""),
                    currency=request.form.get("currency", "GBP"),
                    tax_code_id=request.form.get("tax_code_id") or None,
                )
                flash("Purchase order created. No ledger posting has been made.", "success")
            elif action == "create_multi":
                from ledgerone.modules.commercial.order_builder import MultiLineOrderService
                lines = []
                for index in range(1, 6):
                    description = (request.form.get(f"line_{index}_description") or "").strip()
                    if description:
                        lines.append({
                            "description": description,
                            "quantity": request.form.get(f"line_{index}_quantity"),
                            "unit_price": request.form.get(f"line_{index}_price"),
                            "account_id": request.form.get(f"line_{index}_account"),
                            "tax_code_id": request.form.get(f"line_{index}_tax") or None,
                        })
                order = MultiLineOrderService.create(
                    context, kind="purchase",
                    party_id=request.form.get("supplier_id", ""),
                    order_number=request.form.get("order_number") or None,
                    order_date=date.fromisoformat(
                        request.form.get("order_date") or date.today().isoformat()),
                    expected_date=date.fromisoformat(
                        request.form.get("expected_date"))
                    if request.form.get("expected_date") else None,
                    control_account_id=request.form.get(
                        "payable_account_id", ""),
                    currency=request.form.get("currency", "GBP"),
                    lines=lines)
                flash(f"Multi-line order {order.order_number} created.", "success")
            elif action == "status":
                PurchaseOrderService.set_status(
                    context,
                    request.form.get("order_id", ""),
                    status=request.form.get("status", "draft"),
                )
                flash("Purchase order status updated.", "success")
            elif action in {"po_ack", "grn"}:
                doc_type = action
                order_id = request.form.get("order_id", "")
                document_lines = None
                if doc_type == "grn":
                    document_lines = [{
                        "order_line_id": request.form.get("order_line_id", ""),
                        "quantity": request.form.get("quantity", ""),
                    }]
                document = CommercialDocumentService.create(
                    context, document_type=doc_type, order_id=order_id,
                    document_date=date.fromisoformat(
                        request.form.get("document_date") or date.today().isoformat()),
                    lines=document_lines,
                    external_reference=request.form.get("external_reference") or None)
                flash(f"{document.document_number} recorded without posting a journal.", "success")
            elif action == "po_ack_response":
                CommercialDocumentService.respond_to_po_ack(
                    context, request.form.get("document_id", ""),
                    response_status=request.form.get("response_status", ""),
                    supplier_reference=request.form.get("supplier_reference") or None)
                flash("Supplier acknowledgement recorded.", "success")
            elif action == "match_preview":
                from ledgerone.modules.commercial.purchase_matching import PurchaseMatchService
                line_ids = request.form.getlist("order_line_id")
                quantities = request.form.getlist("invoice_quantity")
                prices = request.form.getlist("invoice_unit_price")
                if not (len(line_ids) == len(quantities) == len(prices)):
                    raise ValueError("Invalid matching line submission")
                proposed = [
                    {"order_line_id": line_id, "quantity": quantity, "unit_price": price}
                    for line_id, quantity, price in zip(line_ids, quantities, prices)
                    if quantity.strip()
                ]
                match_preview = PurchaseMatchService.preview(
                    context, order_id=request.form.get("order_id", ""),
                    supplier_invoice_reference=request.form.get("supplier_invoice_reference", ""),
                    lines=proposed,
                    match_type=request.form.get("match_type", "three_way"),
                    price_tolerance_percent=request.form.get("price_tolerance_percent", "0"))
            elif action == "convert":
                bill, _ = PurchaseOrderService.convert_to_bill(
                    context,
                    request.form.get("order_id", ""),
                    bill_number=request.form.get("bill_number", ""),
                    supplier_invoice_reference=request.form.get("supplier_invoice_reference") or None,
                    bill_date=date.fromisoformat(request.form.get("bill_date") or date.today().isoformat()),
                    due_date=date.fromisoformat(request.form["due_date"]) if request.form.get("due_date") else None,
                )
                flash(f"Purchase order converted to bill {bill.bill_number} and posted.", "success")
            if action != "match_preview":
                return redirect(url_for("purchase_orders.index"))
        except (ValueError, PermissionError) as exc:
            flash(str(exc), "danger")

    accounts = LedgerService.list_accounts(context)
    tax_codes = []
    tax_enabled = module_registry.is_enabled(context.organisation_id, "tax")
    if tax_enabled and context.can("tax.read"):
        from ledgerone.modules.tax.services import TaxService
        tax_codes = TaxService.list_codes(context, usage="purchase")
    document_records = CommercialDocument.query.filter(
        CommercialDocument.organisation_id == context.organisation_id,
        CommercialDocument.document_type.in_(["po_ack","grn"]),
    ).order_by(CommercialDocument.created_at.desc()).limit(500).all()
    order_documents = {}
    for document in document_records:
        order_documents.setdefault(document.order_id, []).append(document)
    return render_template(
        "purchases/orders.html",
        order_documents=order_documents,
        match_preview=match_preview,
        orders=PurchaseOrderService.list_orders(context, 150),
        suppliers=PurchasesService.list_suppliers(context),
        payable_accounts=[row for row in accounts if row.account_type == "liability"],
        expense_accounts=[row for row in accounts if row.account_type == "expense"],
        tax_codes=tax_codes,
        tax_enabled=tax_enabled,
        today=date.today().isoformat(),
        default_expected=(date.today() + timedelta(days=14)).isoformat(),
        default_due="",
    )


@bp.route("/new", methods=["GET", "POST"])
@login_required
@require_module("purchases")
def new_order():
    from ledgerone.modules.commercial.order_builder import MultiLineOrderService
    from ledgerone.modules.commercial.workspace import order_form_data, submitted_order_lines
    context = browser_context()
    if not context.can("purchases.write"):
        raise PermissionError("purchases.write")
    if request.method == "POST":
        try:
            order = MultiLineOrderService.create(
                context, kind="purchase", party_id=request.form.get("party_id", ""),
                order_number=request.form.get("order_number") or None,
                order_date=date.fromisoformat(request.form.get("order_date") or ""),
                expected_date=date.fromisoformat(request.form["expected_date"])
                if request.form.get("expected_date") else None,
                control_account_id=request.form.get("control_account_id", ""),
                currency=request.form.get("currency", "GBP"),
                lines=submitted_order_lines(request.form))
            flash(f"Purchase order {order.order_number} created as draft.", "success")
            return redirect(url_for("purchase_orders.order_detail", order_id=order.id))
        except (ValueError, PermissionError) as exc:
            flash(str(exc), "danger")
    return render_template("commercial/order_editor.html", today=date.today().isoformat(),
                           **order_form_data(context, "purchase"))


@bp.route("/<order_id>/detail", methods=["GET", "POST"])
@login_required
@require_module("purchases")
def order_detail(order_id):
    from ledgerone.modules.purchases.order_models import PurchaseOrder
    from ledgerone.modules.commercial.workspace import order_documents
    from ledgerone.extensions import db
    context = browser_context()
    if not context.can("purchases.read"):
        raise PermissionError("purchases.read")
    order = db.session.get(PurchaseOrder, order_id)
    if not order or order.organisation_id != context.organisation_id:
        from flask import abort
        abort(404)
    if request.method == "POST":
        try:
            if request.form.get("action") == "create_ack":
                document = CommercialDocumentService.create(
                    context, document_type="po_ack", order_id=order.id,
                    document_date=date.fromisoformat(request.form.get("document_date") or ""),
                    external_reference=request.form.get("external_reference") or None)
                flash(f"PO acknowledgement {document.document_number} created.", "success")
            elif request.form.get("action") == "ack_response":
                CommercialDocumentService.respond_to_po_ack(
                    context, request.form.get("document_id", ""),
                    response_status=request.form.get("response_status", ""),
                    supplier_reference=request.form.get("supplier_reference") or None)
                flash("Supplier response saved.", "success")
            else:
                raise ValueError("Unknown acknowledgement action")
            return redirect(url_for("purchase_orders.order_detail", order_id=order.id, tab="ack"))
        except (ValueError, PermissionError) as exc:
            flash(str(exc), "danger")
    return render_template(
        "commercial/order_detail.html", order=order, is_purchase=True,
        tab=request.args.get("tab", "lines") if request.args.get("tab", "lines") in {"lines","ack","documents","invoice"} else "lines",
        acknowledgements=order_documents(context, order.id, "po_ack"),
        fulfilments=order_documents(context, order.id, "grn"),
        today=date.today().isoformat())


@bp.route("/grn", methods=["GET", "POST"])
@login_required
@require_module("purchases")
def grn_workspace():
    from decimal import Decimal, InvalidOperation
    from flask import abort
    from ledgerone.extensions import db
    from ledgerone.modules.purchases.order_models import PurchaseOrder
    from ledgerone.modules.commercial.workspace import outstanding_quantities, order_documents
    context = browser_context()
    if not context.can("purchases.read"):
        raise PermissionError("purchases.read")
    selected_id = request.form.get("order_id") if request.method == "POST" else request.args.get("order_id")
    orders = PurchaseOrderService.list_orders(context, 500)
    selected = db.session.get(PurchaseOrder, selected_id) if selected_id else None
    if selected and selected.organisation_id != context.organisation_id:
        abort(404)
    if request.method == "POST":
        try:
            if not context.can("purchases.write"):
                raise PermissionError("purchases.write")
            if not selected:
                raise ValueError("Select a purchase order")
            ids = request.form.getlist("order_line_id[]")
            quantities = request.form.getlist("receive_quantity[]")
            if len(ids) != len(quantities) or not ids or len(ids) > 200 or len(set(ids)) != len(ids):
                raise ValueError("Invalid receipt line submission")
            eligible = {item["line"].id for item in outstanding_quantities(context, selected)}
            if set(ids) != eligible:
                raise ValueError("Receipt lines must match the current purchase order")
            lines = []
            for line_id, value in zip(ids, quantities):
                try:
                    quantity = Decimal(value)
                except (InvalidOperation, TypeError):
                    raise ValueError("Invalid receipt quantity")
                if not quantity.is_finite() or quantity < 0:
                    raise ValueError("Receipt quantities must be zero or positive")
                if quantity > 0:
                    lines.append({"order_line_id": line_id, "quantity": str(quantity)})
            if not lines:
                raise ValueError("Enter a received quantity on at least one line")
            document = CommercialDocumentService.create(
                context, document_type="grn", order_id=selected.id,
                document_date=date.fromisoformat(request.form.get("document_date") or ""),
                external_reference=request.form.get("external_reference") or None,
                lines=lines)
            flash(f"{document.document_number} recorded for {len(lines)} lines.", "success")
            return redirect(url_for("purchase_orders.grn_workspace", order_id=selected.id))
        except (ValueError, PermissionError) as exc:
            flash(str(exc), "danger")
    outstanding = outstanding_quantities(context, selected) if selected else []
    return render_template(
        "commercial/grn_workspace.html", orders=orders, selected=selected,
        outstanding=outstanding, available=any(item["outstanding"] > 0 for item in outstanding),
        receipts=order_documents(context, selected.id, "grn") if selected else [],
        today=date.today().isoformat())


@bp.route("/<order_id>/match", methods=["GET", "POST"])
@login_required
@require_module("purchases")
def matching_workspace(order_id):
    from flask import abort
    from ledgerone.extensions import db
    from ledgerone.modules.purchases.order_models import PurchaseOrder
    from ledgerone.modules.commercial.purchase_matching import PurchaseMatchService
    context = browser_context()
    if not context.can("purchases.read"):
        raise PermissionError("purchases.read")
    order = db.session.get(PurchaseOrder, order_id)
    if not order or order.organisation_id != context.organisation_id:
        abort(404)
    match_preview = None
    if request.method == "POST":
        try:
            ids = request.form.getlist("order_line_id[]")
            quantities = request.form.getlist("invoice_quantity[]")
            prices = request.form.getlist("invoice_unit_price[]")
            if len(ids) != len(quantities) or len(ids) != len(prices) or len(set(ids)) != len(ids):
                raise ValueError("Invalid invoice lines")
            lines = [
                {"order_line_id": line_id, "quantity": qty, "unit_price": price}
                for line_id, qty, price in zip(ids, quantities, prices)
                if qty and qty.strip() and qty.strip() != "0"
            ]
            match_preview = PurchaseMatchService.preview(
                context, order_id=order.id,
                supplier_invoice_reference=request.form.get("supplier_invoice_reference", ""),
                lines=lines, match_type=request.form.get("match_type", "three_way"),
                price_tolerance_percent=request.form.get("price_tolerance_percent", "0"))
        except (ValueError, PermissionError) as exc:
            flash(str(exc), "danger")
    return render_template(
        "commercial/match_workspace.html", order=order,
        match_preview=match_preview)


@bp.route("/<order_id>/bill-drafts/new", methods=["GET", "POST"])
@login_required
@require_module("purchases")
def new_bill_draft(order_id):
    from decimal import Decimal
    from flask import abort
    from ledgerone.extensions import db
    from ledgerone.modules.commercial.bill_drafts import PurchaseBillDraftService
    from ledgerone.modules.purchases.models import PurchaseBill
    from ledgerone.modules.purchases.order_models import PurchaseOrder
    context = browser_context()
    if not context.can("purchases.read"):
        raise PermissionError("purchases.read")
    order = db.session.get(PurchaseOrder, order_id)
    if not order or order.organisation_id != context.organisation_id:
        abort(404)
    existing = [
        bill for bill in PurchaseBill.query.filter_by(
            organisation_id=context.organisation_id,
            supplier_id=order.supplier_id).all()
        if (bill.metadata_json or {}).get("source_purchase_order_id") == order.id
    ]
    used = {line.id: Decimal("0") for line in order.lines}
    for bill in existing:
        for line in bill.lines:
            source = (line.dimensions or {}).get("source_purchase_order_line_id")
            if source in used:
                used[source] += Decimal(line.quantity)
    remaining = {
        line.id: max(Decimal("0"), Decimal(line.quantity) - used[line.id])
        for line in order.lines
    }
    if request.method == "POST":
        try:
            if not context.can("purchases.write"):
                raise PermissionError("purchases.write")
            ids = request.form.getlist("order_line_id[]")
            quantities = request.form.getlist("bill_quantity[]")
            prices = request.form.getlist("bill_price[]")
            expected = [line.id for line in sorted(order.lines, key=lambda row: row.line_number)]
            if (ids != expected or len(ids) != len(quantities)
                    or len(ids) != len(prices) or len(ids) > 200):
                raise ValueError("Invoice lines must match the current PO lines")
            submitted = [
                {"order_line_id": line_id, "quantity": qty, "unit_price": price}
                for line_id, qty, price in zip(ids, quantities, prices)
                if qty.strip() and Decimal(qty) > 0
            ]
            draft = PurchaseBillDraftService.create(
                context, order_id=order.id,
                supplier_invoice_reference=request.form.get("supplier_invoice_reference", ""),
                bill_number=request.form.get("bill_number") or None,
                bill_date=date.fromisoformat(request.form.get("bill_date") or ""),
                due_date=date.fromisoformat(request.form["due_date"])
                if request.form.get("due_date") else None,
                lines=submitted)
            flash(f"Supplier invoice {draft.bill_number} saved as draft; no journal posted.", "success")
            return redirect(url_for("purchase_orders.new_bill_draft", order_id=order.id))
        except (ValueError, PermissionError, ArithmeticError) as exc:
            flash(str(exc), "danger")
    return render_template(
        "commercial/bill_draft_editor.html",
        order=order, existing_bills=existing,
        remaining=remaining, today=date.today().isoformat())


@bp.get("/<order_id>/bill-drafts/<bill_id>/review")
@login_required
@require_module("purchases")
def review_bill_draft(order_id, bill_id):
    from flask import abort
    from ledgerone.modules.commercial.bill_review import PurchaseBillDraftReview
    from ledgerone.modules.commercial.bill_allocation_proposals import BillReceiptProposalService
    context = browser_context()
    try:
        review = PurchaseBillDraftReview.preview(
            context, order_id=order_id, bill_id=bill_id)
        proposal = BillReceiptProposalService.preview(
            context, order_id=order_id, bill_id=bill_id)
    except ValueError:
        abort(404)
    return render_template("commercial/bill_draft_review.html", review=review, proposal=proposal)


@bp.get("/grn/<grn_id>/accounting-preview")
@login_required
@require_module("purchases")
def grn_accounting_preview(grn_id):
    from ledgerone.modules.commercial.grn_accounting import GRNAccountingPreviewService
    from flask import abort
    context = browser_context()
    try:
        preview = GRNAccountingPreviewService.preview(context, grn_id=grn_id)
    except ValueError:
        abort(404)
    return render_template("commercial/grn_accounting_preview.html", preview=preview)
