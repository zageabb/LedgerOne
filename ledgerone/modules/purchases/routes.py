from datetime import date, datetime, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from ledgerone.models.ledger import Journal
from ledgerone.module_registry import module_registry
from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.security import browser_context, require_module
from ledgerone.services.ledger import LedgerError, LedgerService

bp = Blueprint("purchases", __name__, url_prefix="/purchases")


@bp.route("/", methods=["GET", "POST"])
@login_required
@require_module("purchases")
def index():
    context = browser_context()
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "supplier":
                PurchasesService.create_supplier(
                    context,
                    name=request.form.get("name", ""),
                    email=request.form.get("email"),
                    phone=request.form.get("phone"),
                )
                flash("Supplier added.", "success")
            elif action == "bill":
                bill_date = datetime.strptime(
                    request.form.get("bill_date") or date.today().isoformat(), "%Y-%m-%d"
                ).date()
                due_date_raw = request.form.get("due_date")
                due_date = datetime.strptime(due_date_raw, "%Y-%m-%d").date() if due_date_raw else None
                PurchasesService.create_bill(
                    context,
                    supplier_id=request.form.get("supplier_id", ""),
                    bill_number=request.form.get("bill_number", ""),
                    bill_date=bill_date,
                    due_date=due_date,
                    description=request.form.get("description", "Purchase"),
                    amount=request.form.get("amount", "0"),
                    payable_account_id=request.form.get("payable_account_id", ""),
                    expense_account_id=request.form.get("expense_account_id", ""),
                    currency=request.form.get("currency", "GBP"),
                    tax_code_id=request.form.get("tax_code_id") or None,
                )
                flash("Bill created and posted to the ledger.", "success")
            return redirect(url_for("purchases.index"))
        except (ValueError, PermissionError, LedgerError) as exc:
            flash(str(exc), "danger")

    accounts = LedgerService.list_accounts(context)
    bills = PurchasesService.list_bills(context, 100)
    tax_codes = []
    if module_registry.is_enabled(context.organisation_id, "tax") and context.can("tax.read"):
        from ledgerone.modules.tax.services import TaxService
        tax_codes = TaxService.list_codes(context, usage="purchase")
    return render_template(
        "purchases/index.html",
        suppliers=PurchasesService.list_suppliers(context),
        bills=bills,
        outstanding={row.id: PurchasesService.bill_outstanding(row) for row in bills},
        payable_accounts=[row for row in accounts if row.account_type == "liability"],
        expense_accounts=[row for row in accounts if row.account_type == "expense"],
        tax_codes=tax_codes,
        tax_enabled=module_registry.is_enabled(context.organisation_id, "tax"),
        today=date.today().isoformat(),
        default_due=(date.today() + timedelta(days=30)).isoformat(),
    )


@bp.route("/payments", methods=["GET", "POST"])
@login_required
@require_module("purchases")
def payments():
    context = browser_context()
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "record":
                PurchasesService.record_payment(
                    context,
                    supplier_id=request.form.get("supplier_id", ""),
                    payment_date=date.fromisoformat(request.form.get("payment_date") or date.today().isoformat()),
                    amount=request.form.get("amount", "0"),
                    bank_account_id=request.form.get("bank_account_id", ""),
                    payable_account_id=request.form.get("payable_account_id", ""),
                    reference=request.form.get("reference") or None,
                    currency=request.form.get("currency", "GBP"),
                )
                flash("Supplier payment recorded.", "success")
            elif action == "adopt":
                PurchasesService.adopt_payment_journal(
                    context,
                    supplier_id=request.form.get("supplier_id", ""),
                    journal_id=request.form.get("journal_id", ""),
                    payable_account_id=request.form.get("payable_account_id", ""),
                    currency=request.form.get("currency", "GBP"),
                )
                flash("Existing journal registered as a supplier payment.", "success")
            elif action == "allocate":
                allocations = []
                for key, value in request.form.items():
                    if key.startswith("allocate_") and value.strip():
                        allocations.append({"bill_id": key.removeprefix("allocate_"), "amount": value})
                PurchasesService.allocate_payment(context, request.form.get("payment_id", ""), allocations)
                flash("Payment allocation updated.", "success")
            return redirect(url_for("purchases.payments"))
        except (ValueError, PermissionError, LedgerError) as exc:
            flash(str(exc), "danger")

    accounts = LedgerService.list_accounts(context)
    bills = PurchasesService.list_bills(context, 250)
    payment_rows = [
        row for row in PurchasesService.list_payments(context, 200)
        if getattr(row, "settlement_type", "payment") == "payment"
    ][:100]
    journals = (
        Journal.query.filter_by(organisation_id=context.organisation_id, status="posted")
        .order_by(Journal.journal_date.desc(), Journal.created_at.desc())
        .limit(100)
        .all()
    )
    return render_template(
        "purchases/payments.html",
        suppliers=PurchasesService.list_suppliers(context),
        bills=bills,
        outstanding={row.id: PurchasesService.bill_outstanding(row) for row in bills},
        payments=payment_rows,
        allocated={row.id: PurchasesService.payment_allocated(row.id) for row in payment_rows},
        bank_accounts=[row for row in accounts if row.account_type == "asset"],
        payable_accounts=[row for row in accounts if row.account_type == "liability"],
        journals=journals,
        today=date.today().isoformat(),
    )
