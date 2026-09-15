from types import SimpleNamespace

from ledgerone.module_registry import module_registry
from ledgerone.modules.workflows.posting import required_post_permission


EXPECTED = {
    "scheduled_transaction": ("workflows", "ledger.journals.post", "ScheduledTransactionWorkflowAdapter"),
    "journal": ("ledger", "ledger.journals.post", "JournalWorkflowAdapter"),
    "sales_invoice": ("sales", "sales.write", "SalesInvoiceWorkflowAdapter"),
    "purchase_bill": ("purchases", "purchases.write", "PurchaseBillWorkflowAdapter"),
    "expense_claim": ("expense_claims", "expense_claims.approve", "ExpenseClaimWorkflowAdapter"),
}


def test_workflow_entity_ownership_is_declared_in_module_manifests(app):
    with app.app_context():
        for entity_type, (module_id, permission, adapter_name) in EXPECTED.items():
            manifest = module_registry.workflow_manifest(entity_type)
            assert manifest is not None
            assert manifest.id == module_id
            assert manifest.workflow_post_permission == permission
            adapter = module_registry.workflow_adapter(entity_type)
            assert adapter.__name__ == adapter_name
            assert adapter is module_registry.workflow_adapter(entity_type)


def test_post_permissions_resolve_from_registry_not_central_mapping(app):
    with app.app_context():
        for entity_type, (_, permission, _) in EXPECTED.items():
            assert required_post_permission(SimpleNamespace(entity_type=entity_type)) == permission
        assert required_post_permission(SimpleNamespace(entity_type="external_item")) is None
