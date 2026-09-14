from ledgerone.module_registry import ModuleManifest

MANIFEST = ModuleManifest(
    id="auth",
    name="Identity",
    description="Authentication, organisations and user session controls.",
    icon="user",
    order=5,
    always_on=True,
    home_visible=False,
    professional_visible=False,
    permissions=("identity.read", "identity.manage"),
)
