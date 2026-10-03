# Approval Policies and Maker/Checker Controls

LedgerOne uses the existing Workflows & Actions engine as the retained approval
ledger. Organisation approval policies decide when an operation must enter that
engine before it can execute.

## Supported policies

- `journal` — journal proposals; supports value threshold routing.
- `sales_invoice` — sales-invoice proposals; supports value thresholds.
- `purchase_bill` — purchase-bill proposals; supports value thresholds.
- `master_data` — customer and supplier creation.
- `payment` — customer and supplier payments; supports value thresholds.
- `bank_posting` — bank transaction post-and-match operations.
- `period_reopen` — reopening a closed accounting period.
- `control_adjustment` — exceptional control-account adjustments.
- `ai_write` — AI tool calls that would change LedgerOne data; supports value thresholds when the tool supplies an amount.

Policies are organisation-scoped and are managed through:

- `GET /api/v1/settings/approval-policies`
- `PUT /api/v1/settings/approval-policies/<policy_key>`

A policy contains `enabled`, optional `threshold`, optional
`approval_role`, and `separate_approver`.

## Maker/checker behaviour

When a protected operation meets an enabled policy:

1. LedgerOne fingerprints the exact operation payload.
2. The operation is not executed.
3. A Workflow & Actions approval request is created or the existing request is reused.
4. The maker cannot approve their own request when `separate_approver` is enabled.
5. The checker records an approve/reject/return decision, comments, identity and timestamp in the existing `UserAction` history.
6. After approval, retrying the same operation automatically finds the approved fingerprint.
7. The operation executes once and the approval workflow is marked `executed` with retained execution evidence.

This avoids a second approval subsystem and keeps the same audit history for
API, browser/service and AI-originated changes.

## Thresholds

A policy with no threshold applies to every matching operation. A threshold
applies when the absolute transaction amount is equal to or above that value.

Journal, sales-invoice and purchase-bill policies are represented directly as
high-priority Workflow Definitions so their existing proposal/posting adapters
continue to be used. Other protected operations use a generic approval request
whose approval is consumed when the same operation is retried.

## AI writes

Per-message AI write approval remains the first safety gate. If the
organisation also enables the `ai_write` maker/checker policy, an AI write tool
must additionally receive workflow approval before the tool can execute.
Accounting writes such as journals, invoices and bills can therefore retain
both AI-origin approval evidence and the normal accounting workflow controls.
