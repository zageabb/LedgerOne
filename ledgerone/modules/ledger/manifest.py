from ledgerone.module_registry import ModuleManifest

MANIFEST = ModuleManifest(
    id="ledger",
    name="Accounts & Ledger",
    description="Chart of accounts, journals and core financial reports.",
    icon="book-open",
    order=20,
    route_endpoint="ledger.accounts",
    api_prefix="/api/v1/ledger",
    home_name="Accounts",
    professional_name="General Ledger",
    default_enabled=True,
    permissions=(
        "ledger.read",
        "ledger.accounts.write",
        "ledger.journals.post",
        "ledger.journals.reverse",
        "ledger.periods.manage",
    ),
)
