from ledgerone.module_registry import ModuleManifest

MANIFEST = ModuleManifest(
    id="ai",
    name="LedgerOne AI",
    description="Local AI assistant with trusted access to enabled LedgerOne modules.",
    icon="sparkles",
    order=80,
    route_endpoint="ai.index",
    api_prefix="/api/v1/ai",
    home_name="Ask LedgerOne",
    professional_name="AI Workspace",
    default_enabled=True,
    permissions=("ai.read", "ai.use"),
)
