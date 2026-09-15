from ledgerone.module_registry import ModuleManifest

MANIFEST = ModuleManifest(
    id="workflows",
    name="Workflows & Actions",
    description="Scheduled transactions, approvals, review queues and controlled posting.",
    icon="list-checks",
    order=18,
    route_endpoint="workflows.index",
    api_prefix="/api/v1/workflows",
    home_name="Scheduled & Actions",
    professional_name="Workflow & Approvals",
    default_enabled=True,
    permissions=(
        "workflows.read",
        "workflows.write",
        "workflows.review",
        "workflows.approve",
        "workflows.post",
        "workflows.manage",
    ),
    dependencies=("ledger",),
)
