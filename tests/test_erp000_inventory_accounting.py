"""ERP-000 inventory accounting account-role configuration and access tests."""
import pytest

from ledgerone.models.core import Organisation
from ledgerone.models.ledger import Journal
from ledgerone.services.account_roles import PostingAccountError
from ledgerone.services.context import AccessContext
from ledgerone.services.inventory_accounting import InventoryAccountingConfiguration
from ledgerone.services.ledger import LedgerService


def _accounts():
    organisation = Organisation.query.one()
    owner = AccessContext.system(organisation.id)
    grni = LedgerService.create_account(
        owner, code="GRNI-TEST", name="GRNI clearing", account_type="liability")
    stock = LedgerService.create_account(
        owner, code="STOCK-TEST", name="Inventory", account_type="asset")
    cogs = LedgerService.create_account(
        owner, code="COGS-TEST", name="Cost of goods sold", account_type="expense")
    return owner, grni, stock, cogs


def test_configures_grni_stock_and_cogs_without_creating_journals(app):
    with app.app_context():
        owner, grni, stock, cogs = _accounts()
        before = Journal.query.count()
        configured = InventoryAccountingConfiguration.configure(
            owner, grni_clearing=grni.id, inventory_asset=stock.id,
            cost_of_goods_sold=cogs.id)
        assert configured["accounts"] == {
            "grni_clearing": grni.id,
            "inventory_asset": stock.id,
            "cost_of_goods_sold": cogs.id,
        }
        assert configured["receipt_posting_enabled"] is False
        assert configured["delivery_posting_enabled"] is False
        assert configured["status"] == "configuration_only"
        assert Journal.query.count() == before


def test_account_type_and_company_isolation(app):
    with app.app_context():
        owner, grni, stock, cogs = _accounts()
        with pytest.raises(PostingAccountError, match="account type"):
            InventoryAccountingConfiguration.configure(
                owner, grni_clearing=stock.id,
                inventory_asset=stock.id, cost_of_goods_sold=cogs.id)
        with pytest.raises(PostingAccountError, match="account type"):
            InventoryAccountingConfiguration.configure(
                owner, grni_clearing=grni.id,
                inventory_asset=stock.id, cost_of_goods_sold=grni.id)
        other = AccessContext.system("another-company")
        with pytest.raises(PostingAccountError, match="not found"):
            InventoryAccountingConfiguration.configure(
                other, grni_clearing=grni.id,
                inventory_asset=stock.id, cost_of_goods_sold=cogs.id)


def test_requires_settings_permissions(app):
    with app.app_context():
        owner, grni, stock, cogs = _accounts()
        viewer = AccessContext(identity_type="user",
                               organisation_id=owner.organisation_id,
                               permissions=frozenset({"settings.read"}))
        with pytest.raises(PermissionError, match="settings.manage"):
            InventoryAccountingConfiguration.configure(
                viewer, grni_clearing=grni.id,
                inventory_asset=stock.id, cost_of_goods_sold=cogs.id)
        no_access = AccessContext(identity_type="user",
                                  organisation_id=owner.organisation_id)
        with pytest.raises(PermissionError, match="settings.read"):
            InventoryAccountingConfiguration.get(no_access)
