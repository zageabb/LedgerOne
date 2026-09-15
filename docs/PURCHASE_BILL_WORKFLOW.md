# Purchase Bill Workflow

When the Workflows module is enabled, LedgerOne treats a supplier bill as a proposal until the configured review/approval path is complete and a permitted user explicitly posts it.

## Sequence

```text
Bill entry / AI proposal
  -> Validate supplier, dates, currency, accounts and VAT basis
  -> Workflow instance
  -> Review / approval policy
  -> User Actions: Ready to Post
  -> Explicit Post
  -> PurchasesService.create_bill()
  -> Accounts Payable + expense/VAT journal through LedgerService
```

No `PurchaseBill`, Accounts Payable balance, VAT posting or journal is created at proposal time.

## Home and Professional behaviour

- **Home**: with no matching workflow rule, the bill goes to `Ready to Post`. A human still has to use the Post action.
- **Professional**: with no matching workflow rule, the bill receives a review action first. There is no automatic posting path.
- An organisation can configure stronger Workflow Definitions, including approval roles, amount thresholds and maker/checker separation.

## Permissions

Permissions are deliberately separated:

- `purchases.write` authorises creation/submission of the supplier bill proposal.
- `workflows.review` and `workflows.approve` govern workflow decisions.
- `workflows.post` **and** `purchases.write` are required for the final supplier-bill Post action.

A purchasing approver does not need `ledger.journals.post`. The Purchases module remains the trusted owner of the AP posting and reaches the central ledger through its existing module-authorised path.

## Accounting validation

Before a proposal enters workflow LedgerOne checks:

- supplier exists and is active;
- supplier bill number is not already posted;
- supplier bill number is not already reserved by another open workflow;
- net amount is positive;
- due date is valid;
- payables account is an active liability;
- expense account is an active expense account;
- transaction currency is the organisation base currency;
- tax code is valid for purchase use;
- reviewed VAT and gross total are calculated.

The reviewed payload stores the supplier, dates, coding, VAT basis and total.

Immediately before final posting, VAT is recalculated using the current tax setup. If the resulting gross amount no longer equals the reviewed amount, LedgerOne refuses to post and requires the item to be returned for review.

The final call to `PurchasesService.create_bill()` then reuses all central controls, including accounting periods, currency policy, AP/VAT control-account ownership and audit logging.

## AI

The AI tool `purchases.create_bill` keeps its existing tool name for compatibility. When Workflows is enabled it creates a purchase-bill workflow proposal and returns `posted: false` instead of posting the bill directly.

AI still requires the requesting caller's `purchases.write` permission and the existing per-message AI write approval. AI cannot perform the later review/approval/Post actions simply by having created the proposal.

## Audit

The workflow integration records:

- `purchase_bill_workflow_submitted`;
- normal workflow decision events;
- `purchase_bill_workflow_posted`;
- the existing purchase-bill and ledger audit events created by the Purchases/Ledger services.

The posted purchase bill stores its workflow instance/request IDs in metadata so the final accounting record can be traced to the approval path.

## Compatibility

If Workflows is disabled for an organisation, the existing direct Purchases service behaviour remains available. This compatibility path is explicit; enabling Workflows opts the organisation into the controlled proposal/review/Post route.
