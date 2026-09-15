# LedgerOne Workflow Engine and Controlled Posting

## Purpose

LedgerOne's workflow layer separates **preparation, review and approval** from **accounting posting**. Browser users, API clients, AI tools and schedulers may prepare or propose work, but they do not gain a separate route around the accounting kernel.

The core rule is:

> **A channel may propose accounting work; only an explicit User Actions Post operation, delegated to the owning domain service, may create the final accounting effect.**

The workflow engine is not a second ledger. Final journals continue to pass through the owning module and `LedgerService`.

## Architecture

```mermaid
flowchart LR
    A[Browser / REST API / AI / Scheduler] --> B[Owning domain validation]
    B --> C[Workflow proposal or submitted domain record]
    C --> D[Workflow Instance]
    D --> E[User Actions]
    E --> F{Decision}
    F -->|Review / Approve| G[Ready to Post]
    F -->|Return| H[Correction required]
    F -->|Reject| I[Rejected]
    H --> R[Revise + revalidate]
    R --> S[Supersede returned workflow]
    S --> T[Replacement workflow]
    T --> E
    G --> J[Explicit Post]
    J --> K[Manifest-owned workflow adapter]
    K --> L[Owning domain service]
    L --> M[LedgerService]
    M --> N[Posted journal / AR / AP]
```

Each workflow-aware module declares its workflow ownership in `ModuleManifest`. The central Workflows module resolves the adapter lazily, so adding a new controlled accounting module does not require adding hard-coded imports or `if/elif` dispatch logic to the workflow controller.

## Current controlled entity types

| Entity type | Owning module | Final domain permission | Accounting effect at Post |
| --- | --- | --- | --- |
| `scheduled_transaction` | Workflows | `ledger.journals.post` | General-ledger journal |
| `journal` | Ledger | `ledger.journals.post` | General-ledger journal |
| `purchase_bill` | Purchases | `purchases.write` | Purchase bill, AP and journal |
| `sales_invoice` | Sales | `sales.write` | Sales invoice, AR and journal |
| `expense_claim` | Expense Claims | `expense_claims.approve` | Approved claim and journal |

All final posting also requires `workflows.post`.

## Proposal boundary

When Workflows is enabled, normal creation channels for manual journals, purchase bills and sales invoices create **workflow proposals**, not posted accounting records. This applies consistently to browser, AI and REST API entry points.

Before a proposal is accepted, LedgerOne performs accounting and domain validation that should not be deferred to a reviewer. This includes, as applicable:

- balanced journal lines;
- valid and active accounts;
- organisation base-currency enforcement;
- control-account protection;
- valid customer or supplier;
- valid VAT/tax-code use and totals;
- due-date rules;
- duplicate/open document-number checks; and
- accounting-period policy, including locked periods.

A request that cannot legally or correctly post should therefore fail **before** a workflow record is created. The same controls are rechecked by the owning service at final Post.

## Workflow concepts

The workflow engine persists:

1. **Workflow Definition** — reusable review/approval rules.
2. **Workflow Instance** — one controlled item and its current state.
3. **User Action** — a review, approval or explicit posting task assigned to a user or role.
4. **Transaction Template** — configuration for recurring money movements.
5. **Scheduled Transaction** — a generated occurrence of a transaction template.

The common statuses include:

```text
draft
awaiting_review
awaiting_approval
ready_to_post
returned
superseded
rejected
posted
```

`superseded` is used when a returned payload-backed proposal is corrected by creating a replacement workflow. The old workflow remains history and is not reused for approval or posting.

These are workflow states, not journal states.

## User Actions

The **User Actions** page is LedgerOne's common controlled-work inbox. Typical actions are:

- Review;
- Approve;
- Post;
- Return;
- Correct & resubmit; and
- Reject.

Actions can be assigned to a user or role. Maker/checker separation can prevent an originator from approving their own item where the workflow definition requires independent approval.

For returned Journal, Purchase Bill and Sales Invoice proposals, the browser exposes a correction form rather than allowing the unchanged returned task to be approved. The same rule is enforced server-side so an API client cannot bypass the correction requirement.

## Home / Apprentice and Professional modes

Both UI modes use the same accounting and workflow services.

When no explicit workflow definition applies:

- **Home / Apprentice** proposals can move directly to **Ready to Post**, but still require an explicit Post action.
- **Professional** proposals receive a **Review** action before they become Ready to Post.

An organisation can configure additional approval steps, for example:

```text
Submitted -> Review -> Manager Approval -> Ready to Post -> Explicit Post -> Posted
```

There is no automatic accounting-post path hidden behind the simpler Home UI.

## Domain-specific posting

A User Actions Post does not grant general journal authority to every business module. The owning module's manifest declares the permission required to post its entity.

For example, a purchasing user can post an approved `purchase_bill` with `purchases.write` plus `workflows.post`. The Purchases service then performs its normal AP/journal transaction through `LedgerService`; that user does not receive permission to post arbitrary manual journals.

The current manifest fields are:

```python
workflow_entity_type="purchase_bill"
workflow_adapter="ledgerone.modules.workflows.adapters:PurchaseBillWorkflowAdapter"
workflow_post_permission="purchases.write"
```

The adapter is loaded only when an action for that entity type is handled. It provides the small translation layer between generic User Actions and the owning domain service; it must not duplicate accounting rules.

Adapters expose the common completion/posting contract and may additionally expose controlled revision support. Journal, Purchase Bill and Sales Invoice adapters support `revise_action(...)`; Expense Claims retain their domain-owned draft/edit/resubmit flow.

## Expense Claim return/resubmit behaviour

Expense Claims implement the correction loop through the domain document itself:

```text
Draft -> Submit -> Review -> Return -> Draft/Edit -> Resubmit -> Review -> Post
```

The submitted claim is snapshotted. If underlying claim data changes after review without being formally returned and resubmitted, final posting is blocked.

## Returned Journal/Bill/Invoice proposals

Manual Journal, Purchase Bill and Sales Invoice proposals implement **replacement workflow resubmission**.

The controlled sequence is:

```text
Review -> Return -> Correct -> Revalidate -> Supersede old workflow
                                      |
                                      v
                           New workflow instance
                                      |
                                      v
                    Re-run current review/approval rules
```

The important controls are:

- the returned workflow is preserved as immutable workflow/audit history;
- the returned workflow becomes `superseded` only after the corrected proposal validates successfully;
- the replacement links to the old workflow and the old workflow links to the replacement through metadata;
- correction itself creates **no** Journal, AR invoice or AP bill;
- validation failure rolls the revision transaction back and leaves the returned workflow open for correction;
- document dates, amounts, descriptions and coding are revalidated using the same domain rules used for initial proposal creation;
- workflow-definition selection is run again instead of inheriting the old definition, so a revised amount can move into a higher approval band;
- a returned revisable proposal cannot be approved unchanged through the normal decision endpoint; it must be corrected/resubmitted or rejected; and
- superseded Sales/Purchase workflows release their open document-number reservation so a legitimate second return/resubmit cycle can keep the same invoice/bill number.

The browser User Actions page provides the correction surface. REST callers use:

```text
POST /api/v1/workflows/actions/<action_id>/revise
```

The response identifies the replacement workflow. It does not represent a posted accounting transaction.

## Scheduled transactions

Scheduled transactions support:

- income;
- expense/bill-style direct payments; and
- transfers.

Generation does **not** change the ledger or bank balance. Generated items become workflow work and require explicit Post.

Typical accounting is:

```text
Income:   Dr settlement account / Cr income
Expense:  Dr expense / Cr settlement account
Transfer: Dr destination / Cr source
```

Recurring templates cannot use AR/AP/VAT control accounts as simple category or settlement accounts.

Amount modes are `fixed`, `expected` and `variable`; supported frequencies are weekly, four-weekly, monthly, quarterly and annual.

## API behaviour

The workflow API is under `/api/v1/workflows` and includes templates, generation, definitions, instances and User Actions.

When Workflows is enabled, normal domain creation APIs for journals, purchase bills and sales invoices return a proposal response rather than a posted record. HTTP `201` may be retained for compatibility, but the response explicitly reports that the work is not posted and identifies the workflow instance.

Returned Journal/Bill/Invoice proposals are revised through the generic action revision endpoint. Revision goes through the manifest-owned adapter, the owning domain validator and the replacement workflow service; it does not create accounting effects.

API callers therefore cannot bypass the same User Actions boundary used by browser and AI channels.

## Permissions

The workflow module defines:

```text
workflows.read
workflows.write
workflows.review
workflows.approve
workflows.post
workflows.manage
```

`workflows.post` is necessary but not sufficient. The caller must also hold the owning module's `workflow_post_permission` declared in its manifest.

Revision is also constrained by the owning domain permission. For example, revising a returned Sales Invoice proposal requires the Sales write authority used by that domain flow; a generic workflow caller does not gain Sales mutation rights merely because the workflow is visible.

## Design rule for workflow-aware modules

A new controlled financial module should:

1. validate its proposal using the same business/accounting rules needed for posting;
2. create a workflow instance without creating premature financial effects;
3. declare `workflow_entity_type`, `workflow_adapter` and `workflow_post_permission` in its manifest;
4. let the common engine create review/approval/post User Actions;
5. let its adapter translate the final action into the owning domain service call;
6. if returned data is editable, require a formal correction/resubmission path that revalidates and re-runs current approval rules;
7. revalidate at final posting;
8. route financial effects through `LedgerService`; and
9. test browser, API and AI paths so none can bypass the boundary.

The adapter is orchestration only. The owning service remains authoritative for the business document and accounting transaction.

## Acceptance coverage

The replacement/resubmission implementation is covered by regression tests for:

- Sales Invoice replacement and later posting;
- approval-threshold re-evaluation after an amount change;
- failed revision rollback;
- Purchase Bill replacement without premature AP accounting;
- Journal replacement without premature posting;
- REST revision without premature accounting;
- blocking stale returned-workflow approval;
- repeated return/resubmit cycles using the same valid document number; and
- browser rendering of the returned correction form.

The integrated acceptance run on 15 September 2026 completed with **160 passed, 3 skipped**, with Python compilation and Alembic migration-drift checks also clean.

## Next integrations

The next workflow-control increments are:

1. purchase-order approval workflows;
2. sales/purchase credit-note approval rules;
3. bank-reconciliation exception review;
4. accounting-period reopen/override approval;
5. control-account adjustment approval; and
6. supplier/customer master-data changes such as bank details.

AI-proposed writes should continue to reuse these same domain workflows rather than receiving a separate approval mechanism.
