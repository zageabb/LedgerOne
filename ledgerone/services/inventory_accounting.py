"""Company-level receipt and dispatch accounting setup.

Account mappings are company-local. Setup never activates financial posting:
valuation, invoice clearing, reversals and concurrency controls are required
before an event may create an inventory journal.
"""
from ledgerone.extensions import db
from ledgerone.models.core import Setting
from ledgerone.services.account_roles import PostingAccountService
from ledgerone.services.audit import record_audit_event


class InventoryAccountingConfiguration:
    SCOPE = "erp_inventory_accounting"
    KEY = "configuration"
    ROLES = ("grni_clearing", "inventory_asset", "cost_of_goods_sold")

    @staticmethod
    def get(context):
        if not context.can("settings.read"):
            raise PermissionError("settings.read")
        setting = Setting.query.filter_by(
            organisation_id=context.organisation_id,
            scope=InventoryAccountingConfiguration.SCOPE,
            key=InventoryAccountingConfiguration.KEY,
        ).first()
        saved = setting.value if setting and isinstance(setting.value, dict) else {}
        return {
            "accounts": {
                role: saved.get("accounts", {}).get(role) for role in InventoryAccountingConfiguration.ROLES
            },
            "receipt_posting_enabled": False,
            "delivery_posting_enabled": False,
            "status": "configuration_only",
        }

    @staticmethod
    def configure(context, *, grni_clearing: str, inventory_asset: str,
                  cost_of_goods_sold: str):
        if not context.can("settings.manage"):
            raise PermissionError("settings.manage")
        new_values = {}
        for role, account_id in (
            ("grni_clearing", grni_clearing),
            ("inventory_asset", inventory_asset),
            ("cost_of_goods_sold", cost_of_goods_sold),
        ):
            if account_id:
                account = PostingAccountService.validate(context, account_id, role)
                new_values[role] = account.id
            else:
                new_values[role] = None
        if new_values["grni_clearing"] and new_values["grni_clearing"] == new_values["inventory_asset"]:
            raise ValueError("Inventory asset and GRNI clearing accounts must be separate")
        if new_values["inventory_asset"] and new_values["inventory_asset"] == new_values["cost_of_goods_sold"]:
            raise ValueError("Inventory and cost-of-goods-sold accounts must be separate")
        existing = Setting.query.filter_by(
            organisation_id=context.organisation_id,
            scope=InventoryAccountingConfiguration.SCOPE,
            key=InventoryAccountingConfiguration.KEY,
        ).first()
        previous = dict(existing.value or {}) if existing else {}
        values = {"accounts": new_values, "receipt_posting_enabled": False,
                  "delivery_posting_enabled": False}
        if existing:
            existing.value = values
        else:
            db.session.add(Setting(
                organisation_id=context.organisation_id,
                scope=InventoryAccountingConfiguration.SCOPE,
                key=InventoryAccountingConfiguration.KEY,
                value=values,
            ))
        record_audit_event(
            context, module_id="ledger", action="inventory_accounting_configuration",
            entity_type="organisation", entity_id=context.organisation_id,
            detail={"previous_accounts": previous.get("accounts", {}),
                    "new_accounts": new_values,
                    "financial_posting_enabled": False},
        )
        db.session.commit()
        return InventoryAccountingConfiguration.get(context)
