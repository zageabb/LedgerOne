# Manual and AI Journal Workflow

LedgerOne routes journal proposals through the common Workflows & Actions layer when that module is enabled.

## Manual journal

A user entering a manual journal under **Ledger -> New journal** does not immediately create a posted journal when Workflows is enabled.

The sequence is:

```text
Journal proposal
  -> Workflow instance
  -> Review / approval according to policy
  -> User Actions: Ready to Post
  -> Explicit Post
  -> LedgerService.post_journal()
  -> Posted journal
```

Home mode still requires an explicit Post action. Professional mode receives a review step by default if no matching workflow definition exists.

## AI journal proposal

The existing AI tool name remains `ledger.post_journal` for compatibility, but its behaviour changes when Workflows is enabled: it submits a journal proposal to User Actions rather than posting automatically.

The AI still needs the requesting user's `ledger.journals.post` permission and per-message AI write approval. Creating the workflow request also requires `workflows.write`. The final human Post action requires both `workflows.post` and `ledger.journals.post`.

## Validation

Before a journal proposal is accepted, LedgerOne validates:

- balanced debit and credit lines;
- valid and active ledger accounts;
- base-currency policy;
- no unsupported foreign amounts;
- no direct AR/AP/VAT/control-account posting.

At final posting, the journal is validated again through the central `LedgerService`, including accounting-period policy and all posting guards active at that time.

## Audit trail

Two additional audit events are recorded:

- `journal_workflow_submitted`;
- `journal_workflow_posted`.

The posted journal metadata retains the workflow instance and request IDs so the accounting record can be traced back to the approval path.

## Compatibility

If the Workflows module is disabled for an organisation, the existing explicit manual/AI journal posting path remains available. There is still no background or automatic posting path introduced by this integration.

## Next integrations

The same User Actions model is intended to be adopted by:

- purchase bill review/approval;
- expense claim approval;
- sales invoice approval where configured;
- AI-created source-document proposals;
- exceptional control-account adjustments.
