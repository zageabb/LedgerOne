from ledgerone.module_registry import ModuleManifest

MANIFEST = ModuleManifest(
    id="core",
    name="Dashboard",
    description="LedgerOne home dashboard and system status.",
    icon="home",
    order=10,
    always_on=True,
    permissions=("core.read",),
)
