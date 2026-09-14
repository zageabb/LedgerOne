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
)
