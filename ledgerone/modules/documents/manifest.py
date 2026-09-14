from ledgerone.module_registry import ModuleManifest

MANIFEST = ModuleManifest(
    id="documents",
    name="Source Documents",
    description="Attach files and external evidence references to accounting records.",
    icon="paperclip",
    order=70,
    route_endpoint="documents.index",
    api_prefix="/api/v1/documents",
    home_name="Documents",
    professional_name="Source Documents",
    default_enabled=True,
    permissions=("documents.read", "documents.write"),
)
