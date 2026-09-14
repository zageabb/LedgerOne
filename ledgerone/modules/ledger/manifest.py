from ledgerone.module_registry import ModuleManifest

MANIFEST = ModuleManifest(
    id="ledger",
    name="Accounts & Ledger",
    description="Chart of accounts, journals and core financial reports.",
    icon="book-open",
    order=20,
    default_enabled=True,
    permissions=(
        "ledger.read",
        "ledger.accounts.write",
        "ledger.journals.post",
    ),
)
