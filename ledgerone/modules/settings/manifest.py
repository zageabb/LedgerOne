from ledgerone.module_registry import ModuleManifest

MANIFEST = ModuleManifest(
    id="settings",
    name="Settings",
    description="Organisation, modules, security and API access.",
    icon="settings",
    order=90,
    route_endpoint="settings.index",
    api_prefix="/api/v1/settings",
    always_on=True,
    permissions=("settings.read", "settings.manage"),
)
