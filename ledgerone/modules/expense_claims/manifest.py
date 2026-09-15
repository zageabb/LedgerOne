from ledgerone.module_registry import ModuleManifest

MANIFEST = ModuleManifest(
    id="expense_claims",
    name="Expense Claims",
    description="Employee and personal expense claims with approval, receipts and ledger posting.",
    icon="wallet-cards",
    order=55,
    route_endpoint="expense_claims.index",
    api_prefix="/api/v1/expense-claims",
    home_name="Expense Claims",
    professional_name="Expense Claims",
    default_enabled=False,
    permissions=("expense_claims.read", "expense_claims.write", "expense_claims.approve"),
    dependencies=("ledger", "documents"),
    workflow_entity_type="expense_claim",
    workflow_adapter="ledgerone.modules.workflows.adapters:ExpenseClaimWorkflowAdapter",
    workflow_post_permission="expense_claims.approve",
)
