from ledgerone.module_registry import ModuleManifest

MANIFEST = ModuleManifest(
    id="banking",
    name="Banking",
    description="Bank accounts, imported transactions and reconciliation.",
    icon="landmark",
    order=30,
    route_endpoint="banking.index",
    api_prefix="/api/v1/banking",
    home_name="Money & Bank",
    professional_name="Banking",
    default_enabled=True,
    permissions=("banking.read", "banking.write", "banking.reconcile"),
    dependencies=("ledger",),
)
