from ledgerone.module_registry import ModuleManifest

MANIFEST = ModuleManifest(
    id="purchases",
    name="Purchases",
    description="Suppliers, expenses and purchase bills.",
    icon="shopping-cart",
    order=50,
    route_endpoint="purchases.index",
    api_prefix="/api/v1/purchases",
    home_name="Expenses",
    professional_name="Purchases",
    default_enabled=True,
    permissions=("purchases.read", "purchases.write"),
    dependencies=("ledger",),
)
