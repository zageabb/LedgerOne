# Custom workflow designer — staged delivery

## Goal
Let each LedgerOne company define its own approval routing by transaction type,
value band, and responsible people or groups. Do not mix the global user identity,
company access role, and company workflow routing roles.

## Phase 1 — Implemented in this branch
- Extend the existing Approval Rules screen with up to four sequential review/approval
  steps and fields for a named company member **or** a workflow role.
- API supports up to eight sequential stages through the `steps` argument, with
  the same validation.
- Rules continue to select by company, entity type, amount band and priority.
- Assign any number of users to each workflow role; a user may hold up to 12 roles
  within a company and different roles in another company.
- Settings → Team access → Workflow roles manages those company-local allocations.
  Suggested roles: finance, finance_manager, purchasing, sales,
  payment_approver, director, operations. Custom role labels are supported.
- Effective steps are snapshotted at workflow submission. Editing a definition does
  not silently remove a pending approval step.
- Workflow-role membership **only routes tasks**. It does not grant
  `workflows.approve`, `workflows.review`, company access, or accounting write
  permissions.
- A role-targeted task is available to eligible members of that company role;
  the first authorised reviewer/approver to complete the action progresses it.
  No-self-approval and independent named human approval requirements remain.
- Inactive/revoked company membership immediately blocks access to role-targeted
  actions. Role allocations in other companies cannot authorise an action.
- All role allocation changes have a company-local audit trail.

## Phase 2 — Follow-up
- Add a role catalogue page (description, creator, active status and assignment count),
  allowing administrators to retire unused roles safely.
- Add drag-and-drop stage ordering, in-place editing, copy/clone, version publishing,
  route testing/simulation, and a clear visual workflow diagram.
- Add support for all-of/m-of-n group decisions, parallel and sequential branches,
  absence delegation, substitutes, escalation and reminders. Phase 1 is **single
  completion per role-targeted stage**, not collective approval by all members.
- Validate that a new active workflow has at least one eligible approver and flag
  orphaned approvals if all members are removed.
- Formal rule precedence including default/fallback routes, conflicts, ranges,
  project/value/cost-centre/product and vendor/customer predicates.
- Make privileged workflow rule editing auditable with a draft → approval → publish
  lifecycle, avoiding unauthorised weakening of controls.

## Phase 3 — Integrate domain events
The initial designer stores rules by entity type. The following events must be
explicitly connected to the workflow engine; choosing a category **alone** does
not enforce automatic submission:
1. Journals — manual and API journal proposals
2. Purchases — purchase bills, POs, supplier changes
3. Sales — invoices, customer changes and credit notes
4. Supplier creation and amendments
5. Payments — customer/supplier payments, batches and bank transactions
6. Expenses, period reopening, master data, control changes and AI actions

Each path needs service-layer enforcement (prevent direct-post bypass), pending
state, immutable approved payloads, audit evidence and domain regression tests.

## Examples
- Purchase bill under £500: finance review.
- Purchase bill £500–£4,999.99: purchasing review, finance manager approval.
- Purchase bill £5,000 or more: finance manager, then director approval.
- Journal above £1,000: finance manager approval.
- New supplier: purchasing checks details, finance approves (after domain event integration).
- Payment above £10,000: finance manager then director (after domain event integration).

## Release acceptance
- Company administrators allocate roles to active company members only.
- Named user and role-targeted stage restrictions work for ordinary users and owners.
- Review and approval rights remain separate from workflow role assignment.
- Sequential progression, numeric boundaries, company isolation, revoked membership,
  CSRF, audit events, valid Alembic migration and full CI must pass.
- Live UDA smoke test after merge: Settings roles, Approval Rules, Actions and
  company switch; independent accounting control acceptance still required.
