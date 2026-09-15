from ledgerone.module_registry import ModuleManifest

MANIFEST = ModuleManifest(
    id="sales",
    name="Sales",
    description="Customers, income and sales invoices.",
    icon="receipt",
    order=40,
    route_endpoint="sales.index",
    api_prefix="/api/v1/sales",
    home_name="Income",
    professional_name="Sales",
    default_enabled=True,
    permissions=("sales.read", "sales.write"),
    dependencies=("ledger",),
    workflow_entity_type="sales_invoice",
    workflow_adapter="ledgerone.modules.workflows.adapters:SalesInvoiceWorkflowAdapter",
    workflow_post_permission="sales.write",
)
