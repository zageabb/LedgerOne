from ledgerone.module_registry import ModuleManifest

MANIFEST = ModuleManifest(
    id="core",
    name="Dashboard",
    description="LedgerOne home dashboard and system status.",
    icon="home",
    order=10,
    route_endpoint="core.dashboard",
    api_prefix="/api/v1/system",
    home_name="Overview",
    professional_name="Dashboard",
    always_on=True,
    permissions=("core.read",),
)
