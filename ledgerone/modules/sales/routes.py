from datetime import date, datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from ledgerone.models.ledger import Journal
from ledgerone.module_registry import module_registry
from ledgerone.modules.sales.services import SalesService
from ledgerone.security import browser_context, require_module
from ledgerone.services.ledger import LedgerError, LedgerService

bp = Blueprint("sales", __name__, url_prefix="/sales")


@bp.route("/", methods=["GET", "POST"])
@login_required
@require_module("sales")
def index():
    context = browser_context()
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "customer":
                terms_raw = (request.form.get("payment_terms_days") or "").strip()
                SalesService.create_customer(
                    context,
                    name=request.form.get("name", ""),
                    email=request.form.get("email"),
                    phone=request.form.get("phone"),
                    payment_terms_days=int(terms_raw) if terms_raw else None,
                )
                flash("Customer added.", "success")
            elif action == "invoice":
                invoice_date = datetime.strptime(
                    request.form.get("invoice_date") or date.today().isoformat(), "%Y-%m-%d"
                ).date()
                due_date_raw = request.form.get("due_date")
                due_date = datetime.strptime(due_date_raw, "%Y-%m-%d").date() if due_date_raw else None
                if module_registry.is_enabled(context.organisation_id, "workflows"):
                    # Import lazily so Sales remains independent of the workflow package
                    # during module discovery.
                    from ledgerone.modules.workflows.sales_invoice_requests import SalesInvoiceWorkflowService

                    workflow = SalesInvoiceWorkflowService.create_request(
                        context,
                        customer_id=request.form.get("customer_id", ""),
                        invoice_number=request.form.get("invoice_number", ""),
                        invoice_date=invoice_date,
                        due_date=due_date,
                        description=request.form.get("description", "Sales"),
                        amount=request.form.get("amount", "0"),
                        receivable_account_id=request.form.get("receivable_account_id", ""),
                        revenue_account_id=request.form.get("revenue_account_id", ""),
                        currency=request.form.get("currency", "GBP"),
                        tax_code_id=request.form.get("tax_code_id") or None,
                    )
                    flash(
                        f"Invoice submitted to User Actions ({workflow.status.replace('_', ' ')}). Nothing has posted to receivables yet.",
                        "success",
                    )
                else:
                    SalesService.create_invoice(
                        context,
                        customer_id=request.form.get("customer_id", ""),
                        invoice_number=request.form.get("invoice_number", ""),
                        invoice_date=invoice_date,
                        due_date=due_date,
                        description=request.form.get("description", "Sales"),
                        amount=request.form.get("amount", "0"),
                        receivable_account_id=request.form.get("receivable_account_id", ""),
                        revenue_account_id=request.form.get("revenue_account_id", ""),
                        currency=request.form.get("currency", "GBP"),
                        tax_code_id=request.form.get("tax_code_id") or None,
                    )
                    flash("Invoice created and posted to the ledger.", "success")
            return redirect(url_for("sales.index"))
        except (ValueError, PermissionError, LedgerError) as exc:
            flash(str(exc), "danger")

    accounts = LedgerService.list_accounts(context)
    invoices = SalesService.list_invoices(context, 100)
    tax_codes = []
    if module_registry.is_enabled(context.organisation_id, "tax") and context.can("tax.read"):
        from ledgerone.modules.tax.services import TaxService
        tax_codes = TaxService.list_codes(context, usage="sales")
    return render_template(
        "sales/index.html",
        customers=SalesService.list_customers(context),
        invoices=invoices,
        outstanding={row.id: SalesService.invoice_outstanding(row) for row in invoices},
        receivable_accounts=[row for row in accounts if row.account_type == "asset"],
        revenue_accounts=[row for row in accounts if row.account_type == "income"],
        tax_codes=tax_codes,
        tax_enabled=module_registry.is_enabled(context.organisation_id, "tax"),
        workflows_enabled=module_registry.is_enabled(context.organisation_id, "workflows"),
        today=date.today().isoformat(),
        default_due="",
    )


@bp.route("/payments", methods=["GET", "POST"])
@login_required
@require_module("sales")
def payments():
    context = browser_context()
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "record":
                SalesService.record_payment(
                    context,
                    customer_id=request.form.get("customer_id", ""),
                    payment_date=date.fromisoformat(request.form.get("payment_date") or date.today().isoformat()),
                    amount=request.form.get("amount", "0"),
                    bank_account_id=request.form.get("bank_account_id", ""),
                    receivable_account_id=request.form.get("receivable_account_id", ""),
                    reference=request.form.get("reference") or None,
                    currency=request.form.get("currency", "GBP"),
                )
                flash("Customer payment recorded.", "success")
            elif action == "adopt":
                SalesService.adopt_payment_journal(
                    context,
                    customer_id=request.form.get("customer_id", ""),
                    journal_id=request.form.get("journal_id", ""),
                    receivable_account_id=request.form.get("receivable_account_id", ""),
                    currency=request.form.get("currency", "GBP"),
                )
                flash("Existing journal registered as a customer payment.", "success")
            elif action == "allocate":
                allocations = []
                for key, value in request.form.items():
                    if key.startswith("allocate_") and value.strip():
                        allocations.append({"invoice_id": key.removeprefix("allocate_"), "amount": value})
                SalesService.allocate_payment(context, request.form.get("payment_id", ""), allocations)
                flash("Payment allocation updated.", "success")
            return redirect(url_for("sales.payments"))
        except (ValueError, PermissionError, LedgerError) as exc:
            flash(str(exc), "danger")

    accounts = LedgerService.list_accounts(context)
    invoices = SalesService.list_invoices(context, 250)
    payment_rows = [
        row for row in SalesService.list_payments(context, 200)
        if getattr(row, "settlement_type", "payment") == "payment"
    ][:100]
    journals = (
        Journal.query.filter_by(organisation_id=context.organisation_id, status="posted")
        .order_by(Journal.journal_date.desc(), Journal.created_at.desc())
        .limit(100)
        .all()
    )
    return render_template(
        "sales/payments.html",
        customers=SalesService.list_customers(context),
        invoices=invoices,
        outstanding={row.id: SalesService.invoice_outstanding(row) for row in invoices},
        payments=payment_rows,
        allocated={row.id: SalesService.payment_allocated(row.id) for row in payment_rows},
        bank_accounts=[row for row in accounts if row.account_type == "asset"],
        receivable_accounts=[row for row in accounts if row.account_type == "asset"],
        journals=journals,
        today=date.today().isoformat(),
    )
