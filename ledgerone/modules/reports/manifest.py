from ledgerone.module_registry import ModuleManifest

MANIFEST = ModuleManifest(
    id="reports",
    name="Reports",
    description="Profit and loss, balance sheet and financial summaries.",
    icon="bar-chart-3",
    order=60,
    route_endpoint="reports.index",
    api_prefix="/api/v1/reports",
    home_name="Reports",
    professional_name="Financial Reports",
    default_enabled=True,
    permissions=("reports.read",),
    dependencies=("ledger",),
)
