"""Dedicated ERP-000 order entry, acknowledgement and multi-line GRN regressions."""
from datetime import date
from decimal import Decimal

import pytest
from werkzeug.datastructures import MultiDict

from ledgerone.extensions import db
from ledgerone.models.core import Organisation
from ledgerone.models.ledger import Account, Journal
from ledgerone.modules.commercial.services import CommercialDocumentService
from ledgerone.modules.commercial.workspace import (
    submitted_order_lines, outstanding_quantities,
)
from ledgerone.modules.commercial.order_builder import MultiLineOrderService
from ledgerone.modules.purchases.orders import PurchaseOrderService
from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.services.context import AccessContext

DAY = date(2026, 11, 17)


def test_multi_line_order_editor_accepts_dynamic_rows_and_rejects_partial_rows():
    form = MultiDict([
        ("line_description[]", "Cable"), ("line_description[]", "Switch"),
        ("line_quantity[]", "2"), ("line_quantity[]", "3"),
        ("line_price[]", "10"), ("line_price[]", "8"),
        ("line_account[]", "expense-a"), ("line_account[]", "expense-a"),
        ("line_tax[]", ""), ("line_tax[]", "tax-b"),
    ])
    parsed = submitted_order_lines(form)
    assert len(parsed) == 2
    assert parsed[1]["description"] == "Switch"
    assert parsed[1]["tax_code_id"] == "tax-b"
    partial = MultiDict([
        ("line_description[]", "Cable"),
        ("line_quantity[]", ""), ("line_price[]", "10"),
        ("line_account[]", "expense-a"), ("line_tax[]", ""),
    ])
    with pytest.raises(ValueError, match="Complete all required"):
        submitted_order_lines(partial)


def test_multi_line_grn_outstanding_and_no_ledger_posting(app):
    with app.app_context():
        org = Organisation.query.one()
        context = AccessContext.system(org.id)
        accounts = {a.code: a.id for a in Account.query.filter_by(
            organisation_id=org.id).all()}
        supplier = PurchasesService.create_supplier(context, name="GRN workspace supplier")
        order = MultiLineOrderService.create(
            context, kind="purchase", party_id=supplier.id,
            order_number="PO-GRN-DETAIL", order_date=DAY, expected_date=None,
            control_account_id=accounts["2100"], lines=[
                {"description": "Cable", "quantity": "5",
                 "unit_price": "10", "account_id": accounts["5000"]},
                {"description": "Switch", "quantity": "3",
                 "unit_price": "20", "account_id": accounts["5000"]},
            ])
        PurchaseOrderService.set_status(context, order.id, status="approved")
        before = Journal.query.count()
        details = outstanding_quantities(context, order)
        assert len(details) == 2
        assert [x["outstanding"] for x in details] == [Decimal("5.0000"), Decimal("3.0000")]
        receipt = CommercialDocumentService.create(
            context, document_type="grn", order_id=order.id,
            document_date=DAY, lines=[
                {"order_line_id": details[0]["line"].id, "quantity": "2"},
                {"order_line_id": details[1]["line"].id, "quantity": "3"},
            ])
        assert len(receipt.lines) == 2
        remaining = outstanding_quantities(context, order)
        assert [x["outstanding"] for x in remaining] == [
            Decimal("3.0000"), Decimal("0")]
        assert Journal.query.count() == before
        with pytest.raises(ValueError, match="exceeds outstanding"):
            CommercialDocumentService.create(
                context, document_type="grn", order_id=order.id,
                document_date=DAY, lines=[
                    {"order_line_id": details[0]["line"].id, "quantity": "4"}])


def test_dedicated_workspaces_and_order_tabs_are_registered(app):
    with app.app_context():
        endpoints = {rule.endpoint for rule in app.url_map.iter_rules()}
        assert {
            "purchase_orders.new_order", "sales_orders.new_order",
            "purchase_orders.order_detail", "sales_orders.order_detail",
            "purchase_orders.grn_workspace", "purchase_orders.matching_workspace",
        } <= endpoints
        for template in (
            "commercial/order_editor.html", "commercial/order_detail.html",
            "commercial/grn_workspace.html", "commercial/match_workspace.html",
            "purchases/orders.html", "sales/orders.html",
        ):
            assert app.jinja_env.get_template(template) is not None


def test_po_grn_navigation_points_to_workspace_and_keeps_history(app):
    """GRNs must navigate to the receipt-entry page, not the document-history tab."""
    from flask import url_for

    with app.test_request_context():
        source, _, _ = app.jinja_env.loader.get_source(
            app.jinja_env, "commercial/order_detail.html")
        assert 'href="{{ url_for(\'purchase_orders.grn_workspace\', order_id=order.id) }}">GRNs</a>' in source
        assert 'href="?tab=documents">Receipt history</a>' in source
        assert 'href="?tab=documents">Delivery notes</a>' in source
        assert url_for("purchase_orders.grn_workspace", order_id="po-123").endswith(
            "/purchases/orders/grn?order_id=po-123"
        )
