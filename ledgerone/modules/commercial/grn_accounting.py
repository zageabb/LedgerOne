"""Read-only GRN accrual journal preview.

This prepares journal lines but does not post or modify accounting balances.
Receipt and bill-clearing activation will require an atomic posting service.
"""
from decimal import Decimal, ROUND_HALF_UP

from ledgerone.extensions import db
from ledgerone.modules.commercial.models import CommercialDocument
from ledgerone.modules.purchases.order_models import PurchaseOrder
from ledgerone.services.account_roles import PostingAccountService, PostingAccountError


class GRNAccountingPreviewService:
    @staticmethod
    def preview(context, *, grn_id: str):
        if not context.can("purchases.read"):
            raise PermissionError("purchases.read")
        receipt = db.session.get(CommercialDocument, grn_id)
        if (not receipt or receipt.organisation_id != context.organisation_id
                or receipt.document_type != "grn"):
            raise ValueError("GRN not found")
        order = db.session.get(PurchaseOrder, receipt.order_id)
        if not order or order.organisation_id != context.organisation_id:
            raise ValueError("Purchase order not found")
        from ledgerone.models.core import Setting
        from ledgerone.services.inventory_accounting import InventoryAccountingConfiguration
        settings = Setting.query.filter_by(
            organisation_id=context.organisation_id,
            scope=InventoryAccountingConfiguration.SCOPE,
            key=InventoryAccountingConfiguration.KEY,
        ).first()
        account_ids = ((settings.value or {}).get("accounts") or {}) if settings else {}
        issues = []
        accounts = {}
        for role in ("inventory_asset", "grni_clearing"):
            try:
                account_id = account_ids.get(role)
                if not account_id:
                    raise PostingAccountError(f"No account configured for {role}")
                accounts[role] = PostingAccountService.validate(context, account_id, role)
            except PostingAccountError as exc:
                issues.append(str(exc))
        if accounts.get("inventory_asset") and accounts.get("grni_clearing") and (
                accounts["inventory_asset"].id == accounts["grni_clearing"].id):
            issues.append("GRNI and Inventory accounts must be different")
        source_lines = {row.id: row for row in order.lines}
        amount = Decimal("0.00")
        breakdown = []
        for received in sorted(receipt.lines, key=lambda row: row.line_number):
            source = source_lines.get(received.order_line_id)
            if source is None:
                issues.append(f"GRN line {received.line_number} has no matching PO line")
                continue
            treatment = (source.dimensions or {}).get("item_treatment")
            if treatment == "stock":
                net = (Decimal(received.quantity) * Decimal(source.unit_price)).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP)
                if net <= 0:
                    issues.append(f"Stock line {received.line_number} has zero purchase cost")
                amount += net
                breakdown.append({
                    "order_line_id": source.id, "description": source.description,
                    "quantity": str(received.quantity),
                    "unit_cost": str(source.unit_price),
                    "receipt_value": str(net),
                    "treatment": "stock",
                })
            elif treatment in {"expense", "service"}:
                breakdown.append({
                    "order_line_id": source.id, "description": source.description,
                    "quantity": str(received.quantity), "unit_cost": None,
                    "receipt_value": "0.00", "treatment": treatment,
                })
            else:
                issues.append(
                    f"PO line {received.line_number} is not classified as stock or non-stock"
                )
        if amount <= 0:
            issues.append("No positive-value stock items in receipt")
        lines = []
        if accounts.get("inventory_asset") and accounts.get("grni_clearing") and amount > 0:
            lines = [
                {"account_id": accounts["inventory_asset"].id,
                 "account_code": accounts["inventory_asset"].code,
                 "account_name": accounts["inventory_asset"].name,
                 "debit": str(amount), "credit": "0.00"},
                {"account_id": accounts["grni_clearing"].id,
                 "account_code": accounts["grni_clearing"].code,
                 "account_name": accounts["grni_clearing"].name,
                 "debit": "0.00", "credit": str(amount)},
            ]
        return {
            "grn_id": receipt.id, "grn_number": receipt.document_number,
            "purchase_order_id": order.id, "purchase_order_number": order.order_number,
            "date": receipt.document_date.isoformat(),
            "currency": order.currency,
            "stock_cost_value": str(amount),
            "breakdown": breakdown, "lines": lines,
            "issues": issues, "ready_for_future_posting": not issues,
            "posting_enabled": False, "posted": False,
            "preview_only": True,
            "note": "No journal is posted. Supplier invoice GRNI clearing must be implemented before activation.",
        }
