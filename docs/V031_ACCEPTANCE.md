# v0.3.1 — Multi-company acceptance & workflow approval controls

Status: Engineering changes proposed on branch `feature/v031-tenant-approval-controls`. **Live UDA acceptance remains outstanding.**

## Company-specific approvals
LedgerOne uses the existing `Organisation` and `Membership` boundaries. A company administrator with `workflows.manage` can configure an optional positive amount threshold in Workflow & Approvals → Approval Rules. The value is stored in existing `settings` (scope `approval_controls`, key `threshold`) and audited; no new migration is required.

For a **workflow-enabled** transaction with a known amount at or above the threshold, the engine adds an approval step if no approval step is already present. A separate signed-in individual must approve. The policy is company-scoped. Submission records a snapshot of required steps, so later edits to a reusable rule cannot remove required approvals for in-flight work.

An approval role can be specified, but assignment, permissions and membership are enforced by the existing workflow authorisation. Standard browser/API permissions remain necessary. Service identities without an attributed human may not issue a human approval. Legacy workflow rules that previously allowed self-approval cannot waive this independent-checker requirement.

**Important limitation:** This control applies to transactions submitted through the WorkflowService; direct-post endpoints and certain domain-specific approval adapters may have separate paths. It is *not* a blanket high-value direct posting gate. The v0.3.1 controls must not be represented as complete enterprise segregation of duties (LO-AUD-015).

## Automated acceptance
- Named maker vs named checker for high-value workflow
- Equality and below-threshold boundary tests
- Cannot self approve even if an old rule sets `separate_approver=false`
- Cannot approve through unattributed service identity
- Rule edits cannot remove an in-flight approval requirement
- Company-specific policy does not leak into another company
- Non-managers cannot edit approval policy
- Existing LedgerOne test suite and schema migration/drift check must remain green

## Live UDA acceptance still needed
1. Verify `main` commit, UDA deployment health, actual Alembic head.
2. As a company owner, configure threshold in Company A, confirm it is absent in B.
3. Submit below/equal/above threshold transaction through workflow, with distinct maker and checker accounts.
4. Reject maker self-approval (including owner and API identities).
5. Verify only a separate authorised manager can approve; then post once.
6. Switch companies and check ledger, banking, tax, documents, reporting, AI, exports, APIs and audit boundaries.
7. Verify CSRF, UDA proxy subpath, browser sign-in/out and member revocation.
8. Have an independent accounting reviewer perform a retest before closing LO-AUD-015.

No direct production database manipulation or bypass of UDA is included in this change.
