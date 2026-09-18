from ledgerone.module_registry import ModuleManifest

MANIFEST = ModuleManifest(
    id="tax",
    name="Tax & VAT",
    description="Tax codes, VAT accounts, tax points, adjustments and controlled UK VAT return periods.",
    icon="receipt-text",
    order=65,
    route_endpoint="tax.index",
    api_prefix="/api/v1/tax",
    home_name="VAT",
    professional_name="Tax & VAT",
    default_enabled=False,
    permissions=("tax.read", "tax.manage"),
    dependencies=("ledger",),
)
