from ledgerone.module_registry import ModuleManifest


MANIFEST = ModuleManifest(
    id="organisation_profile",
    name="Business Profile",
    home_name="Business details",
    professional_name="Business Profile",
    description="Legal identity, registered address and customer-document details.",
    icon="building",
    order=89,
    route_endpoint="organisation_profile.index",
    always_on=True,
    permissions=("settings.read", "settings.manage"),
)
