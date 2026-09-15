# LedgerOne Module Development

LedgerOne modules are intended to be self-contained business capabilities. A module should be installable beneath `ledgerone/modules/` without adding hard-coded registration or workflow-dispatch logic to the application factory or central Workflows controller.

## Standard module layout

```text
ledgerone/modules/example/
├── __init__.py
├── manifest.py
├── routes.py
├── api.py
├── services.py
├── permissions.py      # optional
├── models.py           # optional
└── templates/          # optional
```

The package `__init__.py` exposes `register(app)` and should import model metadata before schema/migration inspection.

## Manifest

Every module requires `MANIFEST = ModuleManifest(...)`.

```python
from ledgerone.module_registry import ModuleManifest

MANIFEST = ModuleManifest(
    id="assets",
    name="Fixed Assets",
    description="Asset register and depreciation.",
    home_name="Assets",
    professional_name="Fixed Assets",
    icon="archive",
    order=60,
    default_enabled=False,
    permissions=("assets.read", "assets.write", "assets.post"),
    dependencies=("ledger",),
)
```

Use stable module ids because module state, permissions, APIs, audit events and workflow ownership can reference them.

## Service layer rule

Routes, APIs and AI tools must call services rather than duplicate business logic.

For operations that do not need controlled approval:

```text
Browser ─┐
REST API ├─> Module service -> module models / LedgerService where appropriate
AI tool ─┘
```

For controlled financial creation when Workflows is enabled:

```text
Browser ─┐
REST API ├─> Domain validation -> Workflow proposal -> User Actions
AI tool ─┘                                      |
                                                v
                                     Manifest-owned adapter
                                                |
                                                v
                                        Owning module service
                                                |
                                                v
                                           LedgerService
```

There must not be a second posting implementation in the browser, API, AI tool or workflow adapter.

## Required API convention

Functional modules should expose a versioned API beneath `/api/v1/<module-id>/...` and protect operations with `@require_api(...)`.

Resolve organisation scope from `g.access_context`. Never trust an organisation id supplied by request JSON to grant access.

A browser-only module is incomplete where the capability is expected to be integrated or used by LedgerOne AI.

## Financial posting rule

Only the accounting kernel owns general-ledger posting. Financial modules request postings through `LedgerService`.

For a domain document that posts financially:

1. validate domain data and module permissions;
2. when the operation is workflow-controlled, create a proposal instead of a premature financial document/journal;
3. perform review/approval through User Actions;
4. require explicit Post plus the owning domain permission;
5. call the owning module service from the workflow adapter;
6. let the owning service create/flush the document and call `LedgerService(..., commit=False)`;
7. link the resulting journal to the document;
8. commit the business document and journal atomically; and
9. roll back all parts on failure.

A domain posting permission must not become arbitrary manual-journal authority. For example, `purchases.write` can authorise posting an approved Purchase Bill workflow, but not `POST /api/v1/ledger/journals`.

## Workflow-aware modules

A module that owns a workflow-posted entity declares the integration in its manifest:

```python
MANIFEST = ModuleManifest(
    id="purchases",
    # ...
    workflow_entity_type="purchase_bill",
    workflow_adapter="ledgerone.modules.workflows.adapters:PurchaseBillWorkflowAdapter",
    workflow_post_permission="purchases.write",
)
```

`workflow_entity_type` must be unique. The module registry rejects duplicate ownership and lazily imports the adapter only when that entity type is handled.

The common adapter contract is deliberately small:

```text
complete_action(context, action_id, decision, comments)
post_action(context, action_id, payload, channel=...)
browser_message(result)
api_result(result)
```

Modules whose returned payloads can be corrected may additionally expose:

```text
supports_revision = True
revise_action(context, action_id, payload, channel=...)
```

Most modules inherit generic review/approval behaviour and customise only final posting. A module can override `complete_action` when a workflow decision has real domain consequences, as Expense Claims do when Return reopens the claim for editing.

For payload-backed Journal, Purchase Bill and Sales Invoice workflows, the adapter also blocks normal approval of a returned item and routes correction through the replacement workflow service instead.

Adapters are orchestration code. They must call the authoritative domain service instead of reproducing accounting, VAT, numbering or status rules.

## Validate before workflow creation

Reviewers should not receive proposals that can never post. Before creating workflow state, validate all rules that are already knowable, including as applicable:

- required fields and document numbers;
- duplicate/open number reservation;
- account existence, type and active status;
- debit/credit balancing;
- organisation base currency;
- AR/AP/VAT control-account restrictions;
- customer/supplier status;
- tax-code use and amount calculation;
- due-date rules; and
- accounting-period policy, including locked dates.

The owning service must revalidate again at Post because configuration or master data may have changed during review.

The same principle applies to a correction. A revised payload must be revalidated before the historical returned workflow is superseded.

## Returned proposals

A Return means **correct and resubmit**, not “approve the same unchanged payload.”

Expense Claims implement return to editable draft followed by a new submission.

Payload-backed Journal, Purchase Bill and Sales Invoice proposals use replacement workflow instances:

```text
Returned workflow
      |
      v
Correct payload
      |
      v
Domain revalidation
      |
      v
Create replacement workflow
      |
      v
Re-run current workflow-definition selection and approval chain
      |
      v
Mark old workflow superseded
```

The implementation rules are:

- preserve the old workflow and its completed User Actions as history;
- create a new workflow/entity id rather than editing the old reviewed workflow in place;
- link the old and replacement instances through metadata;
- do not create a financial document or journal during correction;
- roll back the complete revision if validation or replacement creation fails;
- resolve the current workflow definition again, because changed values may trigger a different approval requirement;
- do not allow a returned revisable workflow to be approved through the normal decision path;
- require the owning domain permission for revision;
- ensure superseded invoice/bill proposals do not continue reserving their document number; and
- support repeated controlled return/resubmit cycles without losing the historical chain.

The generic REST correction endpoint is:

```text
POST /api/v1/workflows/actions/<action_id>/revise
```

The manifest-owned adapter converts that generic request into the entity-specific correction service.

Do not implement resubmission by mutating `metadata_json` on the returned workflow and then completing its old review task. That would destroy the reviewed history and could let a changed amount bypass an approval threshold.

## Models and organisation isolation

Module-owned records should be organisation-scoped directly or through a parent record. Every service query must constrain access to `context.organisation_id`.

Use UUID string ids through `new_id()` for consistency with the platform.

## Permissions

Use capability-oriented permission names such as:

```text
assets.read
assets.write
assets.post
assets.dispose
```

Avoid UI-oriented permissions. Home/Apprentice and Professional mode change presentation, not the accounting permission model.

A workflow permission does not replace the owning domain permission. Read/review/post/revision paths must enforce both the workflow-level capability where applicable and the business-module authority for the underlying entity.

## Home / Apprentice and Professional UI

Do not build separate business engines. Share routes/services and adapt labels, explanations and visible complexity.

A simpler Home UI must not silently weaken posting, period, control-account or workflow controls.

## AI integration

LedgerOne AI should call narrow service-backed tools rather than SQL or arbitrary Python.

AI writes must obey the requesting user's permissions and the same workflow boundary as browser/API writes. An AI proposal for a journal, bill or invoice must not call a hidden direct-post route merely because the model has identified all required fields.

AI corrections to returned proposals must use the same revision/replacement service as browser/API corrections; the model must not rewrite the reviewed workflow payload in place.

Write configuration such as `LOCAL_AI_ALLOW_WRITES` is an upper bound, not a privilege grant. Consequential AI operations should be auditable and attributable to the requester.

## Audit events

Significant administrative, workflow and financial operations should emit audit events containing organisation, actor, module, action, entity and non-secret detail.

For replacement workflows, record both the generic workflow replacement event and an owning-domain resubmission event with the old/new workflow ids and the material business reference/amount information needed for audit reconstruction.

Do not place credentials, API-key secrets or passwords in audit detail.

## Database migrations

Any model/schema change requires an Alembic revision. Production relies on migrations, not local auto-create behaviour.

Typical workflow:

```bash
flask --app run.py db migrate -m "add fixed assets module"
# inspect the generated migration
flask --app run.py db upgrade
pytest
```

CI must also pass `flask db check` with no unexpected schema drift.

A workflow behaviour change that only uses existing workflow metadata/status fields does not need a migration, but this should be verified with `flask db check` rather than assumed.

## Module completion checklist

A functional module is ready when it has:

- manifest and dependencies;
- browser route(s);
- versioned API route(s);
- capability permission checks;
- organisation isolation;
- one authoritative service layer;
- models/migrations where persistence is required;
- atomic `LedgerService` integration for financial effects;
- workflow manifest ownership/adapter when creation is controlled;
- validation before proposal creation and revalidation at final Post;
- controlled correction/resubmission for returned editable proposals;
- no stale returned-workflow approval path;
- no browser/API/AI workflow bypass;
- Home/Apprentice and Professional presentation consideration;
- narrow AI tools where useful;
- audit logging for consequential operations;
- tests for normal, permission-denied and invalid-data paths;
- tests proving proposals and corrections do not prematurely create journals/AR/AP;
- tests proving revisions can reselect a stronger approval rule; and
- documentation of configuration and workflow behaviour.

## Current acceptance baseline

As of 15 September 2026, the integrated workflow replacement/resubmission baseline passes **160 tests with 3 skipped**, with Python compilation and Alembic migration-drift validation clean.
