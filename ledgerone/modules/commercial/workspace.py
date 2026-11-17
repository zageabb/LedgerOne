"""Shared browser helpers for dedicated PO/SO order-entry workspaces.

The server validates every submitted row; the client-side add-line button is
only a convenience, not a business-control boundary.
"""
from decimal import Decimal

from ledgerone.extensions import db
from ledgerone.module_registry import module_registry
from ledgerone.modules.commercial.models import CommercialDocument
from ledgerone.services.ledger import LedgerService


def order_form_data(context, kind):
    is_purchase = kind == "purchase"
    accounts = LedgerService.list_accounts(context)
    tax_enabled = module_registry.is_enabled(context.organisation_id, "tax")
    tax_codes = []
    if tax_enabled and context.can("tax.read"):
        from ledgerone.modules.tax.services import TaxService
        tax_codes = TaxService.list_codes(context, usage=kind)
    if is_purchase:
        from ledgerone.modules.purchases.services import PurchasesService
        parties = PurchasesService.list_suppliers(context)
    else:
        from ledgerone.modules.sales.services import SalesService
        parties = SalesService.list_customers(context)
    return dict(
        kind=kind, is_purchase=is_purchase, parties=parties,
        control_accounts=[a for a in accounts if a.account_type == (
            "liability" if is_purchase else "asset")],
        line_accounts=[a for a in accounts if a.account_type == (
            "expense" if is_purchase else "income")],
        tax_codes=tax_codes, tax_enabled=tax_enabled,
    )


def submitted_order_lines(form):
    descriptions = form.getlist("line_description[]")
    quantities = form.getlist("line_quantity[]")
    prices = form.getlist("line_price[]")
    accounts = form.getlist("line_account[]")
    taxes = form.getlist("line_tax[]")
    treatments = form.getlist("line_treatment[]")
    if not (len(descriptions) == len(quantities) == len(prices) == len(accounts) == len(taxes)):
        raise ValueError("Every order row must contain description, quantity, price, account and tax fields")
    if treatments and len(treatments) != len(descriptions):
        raise ValueError("Every order row needs an item accounting treatment")
    if len(descriptions) > 200:
        raise ValueError("Maximum 200 order lines")
    rows = []
    for i, (description, quantity, price, account, tax) in enumerate(
        zip(descriptions, quantities, prices, accounts, taxes), 1
    ):
        if not any([description.strip(), quantity.strip(), price.strip(), account.strip(), tax.strip()]):
            continue
        if not all([description.strip(), quantity.strip(), price.strip(), account.strip()]):
            raise ValueError(f"Complete all required fields on line {i}, or remove the row")
        rows.append({
            "description": description.strip(), "quantity": quantity,
            "unit_price": price, "account_id": account,
            "tax_code_id": tax or None,
            "item_treatment": treatments[i-1] if treatments else None,
        })
    if not rows:
        raise ValueError("Add at least one complete order line")
    return rows


def order_documents(context, order_id, document_type):
    return CommercialDocument.query.filter_by(
        organisation_id=context.organisation_id, order_id=order_id,
        document_type=document_type,
    ).order_by(CommercialDocument.created_at.desc()).all()


def outstanding_quantities(context, order):
    receipts = order_documents(context, order.id, "grn")
    consumed = {}
    for receipt in receipts:
        if receipt.status != "issued":
            continue
        for line in receipt.lines:
            consumed[line.order_line_id] = consumed.get(
                line.order_line_id, Decimal("0")
            ) + Decimal(line.quantity)
    result = []
    for line in sorted(order.lines, key=lambda row: row.line_number):
        received = consumed.get(line.id, Decimal("0"))
        result.append({
            "line": line,
            "received": received,
            "outstanding": max(Decimal("0"), Decimal(line.quantity) - received),
        })
    return result
