# Accounting Audit Remediation Action Register

**Audit:** [2026-09-15 Accounting Practice & Controls Audit](./AUDIT_REPORT.md)  
**Audited baseline:** `226dd44f8096fb54e02914d2e90e420a0bc7f0ef`  
**Register status:** ACTIVE

This is the working remediation register for the audit. Keep the original finding IDs throughout implementation and retesting.

## Status rules

- `OPEN` — no accepted remediation yet.
- `IN PROGRESS` — implementation actively under way.
- `READY FOR RETEST` — code and required automated tests are complete.
- `CLOSED` — independently retested against a recorded commit and acceptance criteria passed.
- `RISK ACCEPTED` — explicitly accepted by the accountable owner with rationale.
- `NOT APPLICABLE` — finding no longer applies, with evidence recorded.

Do not mark an item `CLOSED` solely because code was changed.

---

## Master register

| ID | Severity | Finding | Status | Target phase | Owner | Retest commit |
|---|---|---|---|---|---|---|
| LO-AUD-001 | **CRITICAL** | AI can bypass requesting-user permissions | READY FOR RETEST | AA-1 | Unassigned | `45f99295ac85d92ed0e8bfcba8c6f36d96d236d6` |
| LO-AUD-002 | **CRITICAL** | Foreign currency accepted without proper base-currency accounting | READY FOR RETEST | AA-1 | Unassigned | `45f99295ac85d92ed0e8bfcba8c6f36d96d236d6` |
| LO-AUD-003 | **HIGH** | Control accounts permit direct posting | READY FOR RETEST | AA-1 | Unassigned | `45f99295ac85d92ed0e8bfcba8c6f36d96d236d6` |
| LO-AUD-004 | **HIGH** | Financial reports are not sufficiently period-aware | OPEN | AA-2 | Unassigned | — |
| LO-AUD-005 | **HIGH** | Missing accounting period does not block posting | OPEN | AA-1 | Unassigned | — |
| LO-AUD-006 | **HIGH** | Sales invoice output is not yet a complete UK VAT invoice | OPEN | AA-3 | Unassigned | — |
| LO-AUD-007 | **HIGH** | VAT return lacks complete tax-point/adjustment/MTD controls | OPEN | AA-3 | Unassigned | — |
| LO-AUD-008 | **HIGH** | Posted source documents are not protected like posted journals | OPEN | AA-1 | Unassigned | — |
| LO-AUD-009 | **MEDIUM-HIGH** | Invoice/credit numbering needs controlled sequences | OPEN | AA-2 | Unassigned | — |
| LO-AUD-010 | **MEDIUM-HIGH** | Audit trail is not tamper-evident | OPEN | AA-4 | Unassigned | — |
| LO-AUD-011 | **MEDIUM** | Paid-invoice credit/refund scenarios are restricted | OPEN | AA-2 | Unassigned | — |
| LO-AUD-012 | **MEDIUM** | Account types and posting roles need stronger validation | OPEN | AA-2 | Unassigned | — |
| LO-AUD-013 | **MEDIUM** | API/integration posting lacks strong idempotency | OPEN | AA-2 | Unassigned | — |
| LO-AUD-014 | **MEDIUM** | Banking lacks formal statement-to-GL reconciliation | OPEN | AA-2 | Unassigned | — |
| LO-AUD-015 | **MEDIUM** | Enterprise segregation-of-duties controls incomplete | OPEN | AA-4 | Unassigned | — |

---

# AA-1 — Accounting integrity release blockers

These items should be completed before LedgerOne is treated as suitable for unrestricted production bookkeeping.

## LO-AUD-001 — AI permission inheritance

**Status:** READY FOR RETEST  
**Severity:** CRITICAL

### Implementation checklist

- [x] Pass the requesting `AccessContext` into `LocalAIService.chat()`.
- [x] Remove `AccessContext.system()` as the normal execution identity for user-initiated AI actions.
- [x] Filter available tools by both organisation AI policy **and** caller permission.
- [x] Ensure API-key initiated AI calls retain the key's exact scope.
- [x] Add organisation AI write policies/approval hooks for consequential writes.
- [x] Ensure AI cannot perform a write merely because `LOCAL_AI_ALLOW_WRITES=true`.
- [x] Retain AI/tool audit attribution to both user/API identity and model.

### Required tests

- [x] User with `ai.use` but no `ledger.journals.post` cannot AI-post a journal.
- [x] User with `ai.use` but no `sales.write` cannot AI-create an invoice.
- [x] User with `ai.use` but no `purchases.write` cannot AI-create a bill.
- [x] Appropriately authorised user can perform each permitted action.
- [x] Read-only AI policy removes/rejects every write tool.

### Closure evidence

Implementation commit: `9e9ba07c`  
Retest candidate: `45f99295ac85d92ed0e8bfcba8c6f36d96d236d6`  
Test/retest notes: `Requester-scoped permissions, per-message write approval and tool filtering are implemented. The integrated candidate also passes the complete current suite. Independent audit retest is still required before CLOSED.`

---

## LO-AUD-002 — Base-currency safety / multi-currency gate

**Status:** READY FOR RETEST  
**Severity:** CRITICAL

### Immediate implementation checklist

- [x] Create central validation comparing transaction currency to `Organisation.base_currency`.
- [x] Apply it to journals, sales, purchases, payments, credits, expenses and bank posting workflows.
- [x] Reject journal lines that attempt unsupported foreign-currency accounting.
- [x] Make UI/API error explicit: multi-currency accounting is not yet enabled.
- [x] Keep `foreign_amount` dormant or clearly defined until the full FX model exists.

### Required tests

- [x] GBP organisation accepts GBP transaction.
- [x] GBP organisation rejects USD/EUR invoice, bill and manual journal.
- [x] Banking cannot bypass the currency gate.
- [x] AI/API cannot bypass the currency gate.

### Future multi-currency work before removing the gate

- [ ] Exchange-rate master/source/date.
- [ ] Transaction and base amounts.
- [ ] Realised FX gains/losses.
- [ ] Unrealised revaluation.
- [ ] Settlement differences.
- [ ] Foreign-currency AR/AP ageing.

### Closure evidence

Implementation commit: `9e28b2479be427ba9ccff3d07bea4306976382bb`  
Retest candidate: `45f99295ac85d92ed0e8bfcba8c6f36d96d236d6`  
Test/retest notes: `Central base-currency enforcement is integrated across browser/service/API/AI paths. The integrated candidate passes the complete current suite. Independent audit retest is still required before CLOSED.`

---

## LO-AUD-003 — Control-account protection and reconciliation

**Status:** READY FOR RETEST  
**Severity:** HIGH

### Implementation checklist

- [x] Add control-account type/owner metadata rather than only a boolean.
- [x] Mark AR, AP, output VAT, input VAT and employee reimbursement controls appropriately.
- [x] Central ledger service rejects ordinary/manual posting to control accounts.
- [x] Allow authorised module-origin postings to the module's own control account.
- [x] Prevent banking offset posting directly to AR/AP/VAT without the matching subledger workflow.
- [x] Add controlled adjustment workflow/permission with mandatory reason where exceptional posting is needed.
- [x] Add AR control reconciliation report.
- [x] Add AP control reconciliation report.
- [x] Add VAT control reconciliation report where supported.

### Required tests

- [x] Manual/API journal to AR is rejected.
- [x] Manual/API journal to AP is rejected.
- [x] Manual/API journal to VAT control is rejected.
- [x] Sales invoice/customer payment can update AR correctly.
- [x] Purchase bill/supplier payment can update AP correctly.
- [x] `AR GL == customer subledger` in test fixture.
- [x] `AP GL == supplier subledger` in test fixture.
- [x] Customer payment cannot use the same account for bank and AR and leaves no payment/journal side effects.
- [x] Supplier payment cannot use the same account for bank and AP and leaves no payment/journal side effects.

### Closure evidence

Implementation commit: `8a74122ec047df262c7460f4c0e9632a403157f9`  
Retest candidate: `45f99295ac85d92ed0e8bfcba8c6f36d96d236d6`  
Test/retest notes: `Follow-up integration fixes moved cross-module guard installation after module discovery, seeded control ownership efficiently, aligned old tests to valid subledger workflows and added exact same-account payment regressions. LedgerOne CI run #264 passed compile, clean migration upgrade/check and the complete automated suite: 114 passed, 3 skipped. Independent audit retest is still required before CLOSED.`

---

## LO-AUD-005 — Mandatory accounting-period policy

**Status:** OPEN  
**Severity:** HIGH

### Implementation checklist

- [ ] Introduce organisation posting-period policy.
- [ ] Professional policy requires the posting date to belong to a defined period.
- [ ] Support `open`, `soft_closed`, `hard_closed` states.
- [ ] Add dedicated override permission for soft-close posting.
- [ ] Require reason for override/reopen.
- [ ] Audit all overrides and reopen actions.
- [ ] Ensure recurring journals use the same control.
- [ ] Ensure sales/purchases/banking/expenses/API/AI use the same control.

### Required tests

- [ ] Undefined period date rejected under professional policy.
- [ ] Open period accepted.
- [ ] Soft-closed period rejected without override permission.
- [ ] Hard-closed period rejected.
- [ ] Reopened period records actor, timestamp and reason.

### Closure evidence

Implementation commit: `—`  
Test/retest notes: `—`

---

## LO-AUD-008 — Posted financial-document immutability

**Status:** OPEN  
**Severity:** HIGH

### Implementation checklist

- [ ] Protect posted sales invoice accounting fields against update.
- [ ] Protect posted sales invoice lines against update/delete.
- [ ] Protect posted purchase bill accounting fields against update.
- [ ] Protect posted purchase bill lines against update/delete.
- [ ] Apply equivalent protection to posted credit notes and posted expense claims where appropriate.
- [ ] Define explicitly editable non-financial metadata, if any.
- [ ] Ensure corrections use credit/reversal flows.

### Required tests

- [ ] Direct ORM modification of posted invoice header fails.
- [ ] Direct ORM modification/deletion of posted invoice line fails.
- [ ] Direct ORM modification of posted bill header fails.
- [ ] Direct ORM modification/deletion of posted bill line fails.
- [ ] Draft records remain editable where intended.

### Closure evidence

Implementation commit: `—`  
Test/retest notes: `—`

---

# AA-2 — Professional bookkeeping controls

## LO-AUD-004 — Period-aware financial reporting

**Status:** OPEN  
**Severity:** HIGH

### Implementation checklist

- [ ] Trial Balance `as_of` date.
- [ ] Trial Balance period movement option.
- [ ] Profit & Loss `from_date` / `to_date`.
- [ ] Balance Sheet `as_of` date.
- [ ] General Ledger activity report with brought-forward/movement/carried-forward.
- [ ] Current earnings / retained earnings presentation.
- [ ] Comparative prior period/year support.
- [ ] UI/API date parameters use common report services.

### Required tests

- [ ] Transactions before/inside/after period produce expected P&L.
- [ ] Balance Sheet excludes post-as-of transactions.
- [ ] Trial Balance remains balanced at each requested date.
- [ ] Prior-period comparative values remain stable after later transactions.

### Closure evidence

Implementation commit: `—`  
Test/retest notes: `—`

---

## LO-AUD-009 — Controlled numbering sequences

**Status:** OPEN  
**Severity:** MEDIUM-HIGH

### Implementation checklist

- [ ] Add numbering-series model.
- [ ] Concurrency-safe next-number allocation.
- [ ] Configurable prefix/suffix/year reset where required.
- [ ] Assigned number immutable after issue/posting.
- [ ] Cancelled/void numbers retained and visible.
- [ ] Gap report.
- [ ] Separate series by document type where appropriate.

### Required tests

- [ ] Concurrent invoice creation cannot duplicate a number.
- [ ] Used number cannot be reused.
- [ ] Cancelled number remains in sequence history.

### Closure evidence

Implementation commit: `—`  
Test/retest notes: `—`

---

## LO-AUD-011 — Paid-invoice credits and refunds

**Status:** OPEN  
**Severity:** MEDIUM

### Implementation checklist

- [ ] Separate original invoice value, payments and credits in settlement logic.
- [ ] Allow valid credit note after invoice is fully paid.
- [ ] Create customer unallocated credit balance.
- [ ] Allow credit allocation to another invoice.
- [ ] Allow customer refund posting.
- [ ] Mirror appropriate supplier-credit/refund scenarios.

### Required tests

- [ ] Fully paid invoice -> credit -> customer credit.
- [ ] Customer credit -> refund.
- [ ] Customer credit -> allocation to another invoice.

### Closure evidence

Implementation commit: `—`  
Test/retest notes: `—`

---

## LO-AUD-012 — Account classification and posting-role validation

**Status:** OPEN  
**Severity:** MEDIUM

### Implementation checklist

- [ ] Restrict account types to supported enum/check constraint.
- [ ] Validate parent/child account classification rules where applicable.
- [ ] Configure default/system posting accounts centrally.
- [x] Validate AR posting role/control ownership.
- [x] Validate AP posting role/control ownership.
- [ ] Validate revenue/income posting role.
- [ ] Validate expense/asset posting roles according to supported workflows.
- [x] Reject control accounts as linked bank accounts and reject same-account bank/AR or bank/AP payments.
- [ ] Define controlled overrides where legitimate accounting scenarios require them.

### Required tests

- [ ] Invalid account type rejected.
- [ ] Sales workflow rejects all incompatible AR/revenue account configurations.
- [ ] Purchase workflow rejects all incompatible AP account configurations.
- [x] Same-account customer and supplier payment attempts are rejected before any payment/allocation/journal side effects.
- [ ] Bank account link rejects every incompatible ledger account where policy requires it.

### Closure evidence

Implementation commit: `Partial at 45f99295ac85d92ed0e8bfcba8c6f36d96d236d6`  
Test/retest notes: `Same-account payment and control-account bank-link protection are implemented as part of LO-AUD-003. Remaining account classification and revenue/expense role validation keeps LO-AUD-012 OPEN.`

---

## LO-AUD-013 — API/integration idempotency

**Status:** OPEN  
**Severity:** MEDIUM

### Implementation checklist

- [ ] Define `Idempotency-Key` contract for write endpoints.
- [ ] Persist request key, operation and response/result reference.
- [ ] Repeat of identical request returns original result.
- [ ] Same key with different payload is rejected as conflict.
- [ ] Consider source-system/source-reference uniqueness where business semantics permit it.
- [ ] Add retention policy for idempotency records.

### Required tests

- [ ] Repeated journal POST with same key creates one journal.
- [ ] Repeated invoice/bill creation with same key creates one document.
- [ ] Different payload with same key is rejected.

### Closure evidence

Implementation commit: `—`  
Test/retest notes: `—`

---

## LO-AUD-014 — Formal bank statement reconciliation

**Status:** OPEN  
**Severity:** MEDIUM

### Implementation checklist

- [ ] Add reconciliation header/entity.
- [ ] Statement start/end dates.
- [ ] Statement opening/closing balance.
- [ ] Ledger balance at cut-off.
- [ ] Matched/unmatched item snapshot.
- [ ] Outstanding receipts/payments.
- [ ] Explained difference and final residual difference.
- [ ] Prepared-by / approved-by.
- [ ] Finalised/locked reconciliation.
- [ ] Printable/exportable retained reconciliation report.

### Required tests

- [ ] Known statement fixture reconciles to zero.
- [ ] Unexplained difference prevents finalisation.
- [ ] Finalised reconciliation cannot be silently changed.

### Closure evidence

Implementation commit: `—`  
Test/retest notes: `—`

---

# AA-3 — UK VAT assurance

## LO-AUD-006 — UK VAT invoice completeness

**Status:** OPEN  
**Severity:** HIGH

### Implementation checklist

- [ ] Organisation legal/trading name fields as required.
- [ ] Organisation registered/principal address.
- [ ] VAT registration number pulled into invoice output.
- [ ] Invoice issue date.
- [ ] Separate VAT tax point/time of supply.
- [ ] Customer name and address.
- [ ] Line description, quantity/extent and unit price.
- [ ] VAT rate clearly shown per applicable line/supply.
- [ ] Net/gross/VAT totals correctly displayed.
- [ ] Total VAT sterling requirement handled for foreign-currency invoicing when FX support eventually exists.
- [ ] Sequential controlled invoice number depends on LO-AUD-009.

### Required tests

- [ ] Rendered standard-rated VAT invoice contains every required test field.
- [ ] Non-VAT organisation cannot present a document as a VAT invoice.
- [ ] VAT number and tax point are retained with issued invoice evidence.

### Closure evidence

Implementation commit: `—`  
Test/retest notes: `—`

---

## LO-AUD-007 — VAT tax-point, return lifecycle and adjustments

**Status:** OPEN  
**Severity:** HIGH

### Implementation checklist

- [ ] Add explicit tax point to VAT-relevant sales/purchase records.
- [ ] VAT return uses tax point rather than assuming document date.
- [ ] Add VAT return period entity.
- [ ] Draft/final/submitted return lifecycle.
- [ ] Retain exact source population used by final/submitted return.
- [ ] Add separately identified VAT adjustments with reason/evidence.
- [ ] Define late-entry handling after a return is final/submitted.
- [ ] Add supported reverse-charge/import treatment before claiming support.
- [ ] Define MTD digital-link/submission architecture.
- [ ] Retain submission request/response/receipt if HMRC API integration is introduced.

### Required tests

- [ ] Invoice date and tax point in different periods are handled correctly.
- [ ] Credit note affects correct VAT period.
- [ ] Adjustment is separately reported and audited.
- [ ] Finalised return can be reproduced exactly.

### Closure evidence

Implementation commit: `—`  
Test/retest notes: `—`

---

# AA-4 — Enterprise assurance controls

## LO-AUD-010 — Tamper-evident audit trail

**Status:** OPEN  
**Severity:** MEDIUM-HIGH

### Implementation checklist

- [ ] Prevent application-level update/delete of audit events.
- [ ] Document production DB privilege model for append-only audit writes.
- [ ] Evaluate per-organisation hash chain or signed audit checkpoints.
- [ ] Add integrity verification command/service if hash chaining is selected.
- [ ] Define audit retention and backup policy.
- [ ] Audit privileged audit-export/administration actions.

### Required tests

- [ ] ORM update/delete attempt is rejected.
- [ ] Tamper-verification test detects altered/deleted link if hash chaining is implemented.

### Closure evidence

Implementation commit: `—`  
Test/retest notes: `—`

---

## LO-AUD-015 — Maker/checker and segregation of duties

**Status:** OPEN  
**Severity:** MEDIUM

### Implementation checklist

- [ ] Organisation-level approval-policy configuration.
- [ ] No self-approval option.
- [ ] Journal approval workflow.
- [ ] Transaction-value approval thresholds.
- [ ] Supplier/customer master change approval as configured.
- [ ] Payment/bank approval policy.
- [ ] Period reopen approval.
- [ ] Control-account adjustment approval.
- [ ] AI-generated accounting write approval policy.
- [ ] Record preparer, approver, decision, date/time and reason/comments.

### Required tests

- [ ] Preparer cannot approve own transaction when SoD enabled.
- [ ] Below/above-threshold transactions follow configured route.
- [ ] Approval history remains attached to final accounting record.

### Closure evidence

Implementation commit: `—`  
Test/retest notes: `—`

---

# Retest log

Add a row whenever one or more findings are submitted for retest.

| Date | Commit | Findings retested | Result | Retested by | Notes |
|---|---|---|---|---|---|
| 2026-09-15 | `45f99295ac85d92ed0e8bfcba8c6f36d96d236d6` | LO-AUD-001, LO-AUD-002, LO-AUD-003 | Submitted / pending independent retest | Pending independent reviewer | Integrated CI run #264: compile and clean migration checks passed; 114 tests passed, 3 skipped. |

---

# Closure summary

| Severity | Total | Closed | Remaining |
|---|---:|---:|---:|
| Critical | 2 | 0 | 2 |
| High | 6 | 0 | 6 |
| Medium-High | 2 | 0 | 2 |
| Medium | 5 | 0 | 5 |
| **Total** | **15** | **0** | **15** |

**Production assurance gate:** NOT PASSED  
**UK VAT assurance gate:** NOT PASSED  
**Enterprise assurance gate:** NOT PASSED
