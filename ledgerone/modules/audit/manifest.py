from ledgerone.module_registry import ModuleManifest

MANIFEST = ModuleManifest(
    id="audit",
    name="Audit Trail",
    description="Search, export and verify tamper-evident activity across LedgerOne modules.",
    icon="shield-check",
    order=80,
    route_endpoint="audit.index",
    api_prefix="/api/v1/audit",
    home_name="Activity",
    professional_name="Audit Trail",
    default_enabled=True,
    permissions=("audit.read", "audit.export"),
)
