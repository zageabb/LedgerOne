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
| LO-AUD-004 | **HIGH** | Financial reports are not sufficiently period-aware | READY FOR RETEST | AA-2 | Unassigned | `703b2e2bf1df751ba7290de4f38b3be3c5f7e878` |
| LO-AUD-005 | **HIGH** | Missing accounting period does not block posting | READY FOR RETEST | AA-1 | Unassigned | `703b2e2bf1df751ba7290de4f38b3be3c5f7e878` |
| LO-AUD-006 | **HIGH** | Sales invoice output is not yet a complete UK VAT invoice | OPEN | AA-3 | Unassigned | — |
| LO-AUD-007 | **HIGH** | VAT return lacks complete tax-point/adjustment/MTD controls | OPEN | AA-3 | Unassigned | — |
| LO-AUD-008 | **HIGH** | Posted source documents are not protected like posted journals | READY FOR RETEST | AA-1 | Unassigned | `703b2e2bf1df751ba7290de4f38b3be3c5f7e878` |
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
Test/retest notes: `Requester-scoped permissions, per-message write approval and tool filtering are implemented. Independent audit retest is still required before CLOSED.`

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
Test/retest notes: `Central base-currency enforcement is integrated across browser/service/API/AI paths. Independent audit retest is still required before CLOSED.`

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

**Status:** READY FOR RETEST  
**Severity:** HIGH

### Implementation checklist

- [x] Introduce organisation posting-period policy.
- [x] Required/production policy requires the posting date to belong to a defined period.
- [x] Support `open`, `soft_closed`, `hard_closed` states; legacy `locked` is treated as hard closed.
- [x] Add dedicated `ledger.periods.override` permission for soft-close posting.
- [x] Require reason for override/reopen.
- [x] Audit all overrides and reopen actions.
- [x] Ensure recurring journals use the same control.
- [x] Ensure sales/purchases/banking/expenses/API/AI use the same central control.

### Required tests

- [x] Undefined period date rejected under required policy.
- [x] Open period accepted.
- [x] Soft-closed period rejected without override permission and reason.
- [x] Hard-closed period rejected even with override authority.
- [x] Reopened period records actor, timestamp and reason.
- [x] Sales and recurring posting paths share the central policy.
- [x] Period-policy/status API transitions are covered.

### Closure evidence

Implementation commit: `c31068f0775f8bc95364fdaa1a3cbc69fa5bfe9c`  
Retest candidate: `703b2e2bf1df751ba7290de4f38b3be3c5f7e878`  
Test/retest notes: `Organisation-level period policy is enforced beneath LedgerService, with required/optional policy modes, open/soft/hard close semantics, audited override/reopen controls and shared enforcement for all posting channels. The integrated candidate passed CI #378: compile and clean migration checks succeeded; 168 tests passed, 3 skipped. Independent audit retest is still required before CLOSED.`

---

## LO-AUD-008 — Posted financial-document immutability

**Status:** READY FOR RETEST  
**Severity:** HIGH

### Implementation checklist

- [x] Protect posted sales invoice accounting fields against update.
- [x] Protect posted sales invoice lines against update/delete/addition.
- [x] Protect posted purchase bill accounting fields against update.
- [x] Protect posted purchase bill lines against update/delete/addition.
- [x] Apply equivalent protection to posted credit notes and posted expense claims where appropriate.
- [x] Explicitly allow settlement-status lifecycle changes while protecting financial/source-document evidence.
- [x] Protect partially credited (`part_credited`) invoices and bills as posted evidence.
- [x] Ensure corrections use credit/reversal/supported correction flows rather than silent mutation.

### Required tests

- [x] Direct ORM modification of posted invoice header fails.
- [x] Direct ORM modification/deletion/addition of posted invoice line fails.
- [x] Direct ORM modification of posted bill header fails.
- [x] Direct ORM modification/deletion of posted bill line fails.
- [x] Posted sales/purchase credit notes are immutable.
- [x] Posted expense claim header/lines are immutable.
- [x] Partially credited invoice/bill header and line mutation fails.
- [x] Draft records remain editable where intended.

### Closure evidence

Implementation commit: `d309c0ab43796a9a45e31fc9bbda980093ba0bce`  
Follow-up control-state fix: `4aa86b8c87503f75ff782fbf25c795c87b21e34e`  
Retest candidate: `703b2e2bf1df751ba7290de4f38b3be3c5f7e878`  
Test/retest notes: `SQLAlchemy before-flush guards protect posted invoice, bill, credit-note and expense-claim evidence while retaining legitimate settlement status transitions. The part_credited state is explicitly protected. CI #366 passed 161 tests, 3 skipped; the later integrated candidate passed CI #378 with 168 tests, 3 skipped and clean compile/migration checks. Independent audit retest is still required before CLOSED.`

---

# AA-2 — Professional bookkeeping controls

## LO-AUD-004 — Period-aware financial reporting

**Status:** READY FOR RETEST  
**Severity:** HIGH

### Implementation checklist

- [x] Trial Balance `as_of` date.
- [x] Trial Balance period movement option.
- [x] Profit & Loss `from_date` / `to_date`.
- [x] Balance Sheet `as_of` date.
- [x] General Ledger activity report with brought-forward/movement/carried-forward.
- [x] Current/unclosed earnings presentation within Balance Sheet equity.
- [x] Comparative prior period/year support.
- [x] UI/API date parameters use common report services.
- [x] Legacy browser Trial Balance route redirects into the dated Reports surface.

### Required tests

- [x] Transactions before/inside/after period produce expected P&L.
- [x] Balance Sheet excludes post-as-of transactions.
- [x] Trial Balance remains balanced at each requested date.
- [x] Trial Balance period-movement totals are balanced.
- [x] General Ledger opening/movement/closing and running balances are correct.
- [x] Prior-period comparative values remain stable after later transactions.
- [x] Reports REST endpoints use the same date-aware services.
- [x] Browser financial reports, Trial Balance and General Ledger render with date controls.

### Closure evidence

Implementation commit: `9312ecd2e018ed680430e816789f617395e3bbd7`  
Retest candidate: `703b2e2bf1df751ba7290de4f38b3be3c5f7e878`  
Test/retest notes: `FinancialReportingService now provides dated TB, P&L, Balance Sheet and General Ledger calculations from posted journals. Balance Sheet is cumulative as-of; P&L is period movement; GL carries brought-forward/movement/carried-forward; current/unclosed earnings are included in equity; prior-year comparisons are explicit. CI #375 passed 167 tests, 3 skipped on the core service/API implementation. Exact integrated candidate CI #378 passed compile, clean migration validation and 168 tests with 3 skipped. Independent audit retest is still required before CLOSED.`

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
Test/retest notes: `Open PR #3 contains an older numbering implementation but is not mergeable with current main and uses a conflicting 0013 migration. Useful parts must be selectively ported onto the current migration/workflow architecture rather than merged blindly.`

---

## LO-AUD-011 — Paid-invoice credits and refunds

**Status:** READY FOR RETEST  
**Severity:** MEDIUM

### Implementation checklist

- [x] Separate original invoice/bill value, cash settlements, credit notes, allocations and refunds in settlement logic.
- [x] Allow valid credit notes after an invoice or bill is fully paid, without rewriting the original payment history.
- [x] Create explicit reusable customer and supplier unallocated credit balances.
- [x] Allow customer/supplier credit allocation to another invoice/bill through the existing settlement allocation model.
- [x] Allow customer credit refund posting as Dr AR / Cr bank with immutable refund evidence.
- [x] Mirror supplier-credit/refund scenarios as Dr bank / Cr AP when cash is refunded by the supplier.
- [x] Include credit refunds in AR/AP control-account reconciliation.

### Required tests

- [x] Fully paid invoice -> credit -> customer credit.
- [x] Customer credit -> allocation to another invoice.
- [x] Residual customer credit -> cash refund.
- [x] Fully paid supplier bill -> supplier credit -> allocation/refund.
- [x] AR/AP subledgers reconcile to their control accounts after credit allocation and refund.
- [x] Refund amounts cannot exceed available credit and posted refund evidence is immutable.

### Closure evidence

Implementation commit: `a0934f819c907234a98522379c47ed03c8c6743c`  
Test/retest notes: PR #9 CI run #437 passed compile, clean migration validation and the full regression suite: 215 passed, 3 skipped. Awaiting independent audit retest before closure.

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

**Status:** READY FOR RETEST  
**Severity:** HIGH

### Implementation checklist

- [x] Organisation legal/trading name fields as required.
- [x] Organisation registered/principal address.
- [x] VAT registration number pulled into invoice output.
- [x] Invoice issue date.
- [x] Separate VAT tax point/time of supply.
- [x] Customer name and address.
- [x] Line description, quantity/extent and unit price.
- [x] VAT rate clearly shown per applicable line/supply.
- [x] Net/gross/VAT totals correctly displayed.
- [x] Total VAT is shown in sterling for the currently supported GBP-only accounting scope; foreign-currency accounting remains blocked until the multicurrency phase.
- [x] Sequential controlled invoice numbering is implemented through the controlled numbering service.

### Required tests

- [x] Rendered standard-rated VAT invoice contains required supplier/customer identity, VAT number, tax point, VAT rate and sterling VAT total.
- [x] Non-VAT organisation cannot present a document as a VAT invoice.
- [x] VAT number and retained tax point are used by the issued invoice renderer.

### Closure evidence

Implementation commit: `8a8cf7c9aa3df08a8de27811e6202c00a9c58916`  
Test/retest notes: PR #7 CI run #425 passed compile, clean migration validation and the full regression suite: 200 passed, 3 skipped. Awaiting independent audit retest before closure.

---

## LO-AUD-007 — VAT tax-point, return lifecycle and adjustments

**Status:** READY FOR RETEST  
**Severity:** HIGH

### Implementation checklist

- [x] Add explicit retained tax point to VAT-relevant sales, purchase and credit-note records.
- [x] VAT return uses tax point rather than assuming document date.
- [x] Add VAT return period entity.
- [x] Draft/final/submitted return lifecycle.
- [x] Retain exact source population and box totals used by final/submitted return.
- [x] Add separately identified VAT adjustments with reason/evidence.
- [x] Define and enforce late-entry handling after a return is final/submitted.
- [ ] Reverse-charge/import treatment remains deliberately unsupported; LedgerOne does not claim this scope and Boxes 2/8/9 remain explicitly excluded.
- [x] Define MTD digital-link/submission architecture in `docs/VAT_MTD_ARCHITECTURE.md`.
- [ ] HMRC API request/response/receipt retention is deferred until HMRC submission integration is introduced; the current lifecycle retains an external submission reference/note only.

### Required tests

- [x] Invoice date and tax point in different periods are handled correctly.
- [x] Credit note affects correct VAT period.
- [x] Adjustment is separately reported and audited.
- [x] Finalised return can be reproduced exactly and frozen evidence is immutable.
- [x] Late postings/adjustments into a finalised VAT period are rejected.

### Closure evidence

Implementation commit: `8a8cf7c9aa3df08a8de27811e6202c00a9c58916`  
Test/retest notes: PR #7 CI run #425 passed compile, clean migration validation and the full regression suite: 200 passed, 3 skipped. Standard GB VAT lifecycle scope is ready for independent retest; reverse-charge/import and direct HMRC MTD submission remain explicitly deferred and unsupported.

---

# AA-4 — Enterprise assurance controls

## LO-AUD-010 — Tamper-evident audit trail

**Status:** READY FOR RETEST  
**Severity:** MEDIUM-HIGH

### Implementation checklist

- [x] Prevent application-level update/delete of persisted audit events through the ORM.
- [x] Document production DB privilege model for append-only audit writes in `docs/AUDIT_INTEGRITY.md`.
- [x] Implement a per-organisation SHA-256 hash chain with retained chain head; externally signed checkpoints remain an optional future hardening layer.
- [x] Add full-chain integrity verification service plus browser and API endpoints.
- [x] Define audit retention, backup, restore and post-restore verification policy.
- [x] Audit privileged CSV exports; existing settings/member/API-key administration actions remain individually audited.

### Required tests

- [x] ORM update/delete attempts are rejected.
- [x] Raw-SQL event alteration is detected by hash verification.
- [x] Raw-SQL deletion of the chain tail is detected by retained-head verification.
- [x] Multiple audit events in one transaction chain consecutively.
- [x] Rolled-back business transactions do not advance the audit chain.
- [x] Legacy/direct AuditEvent constructors are chained at the ORM persistence boundary.

### Closure evidence

Implementation commit: `2289ccaad0bd10c4032b703f52e8fe5c96a4b539`  
Test/retest notes: PR #8 CI run #432 passed compile, clean migration validation and the full regression suite: 210 passed, 3 skipped. Awaiting independent audit retest before closure.

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
| 2026-09-15 | `703b2e2bf1df751ba7290de4f38b3be3c5f7e878` | LO-AUD-004, LO-AUD-005, LO-AUD-008 | Submitted / pending independent retest | Pending independent reviewer | Integrated CI run #378: compile and clean migration checks passed; 168 tests passed, 3 skipped. |
| 2026-09-18 | `8a8cf7c9aa3df08a8de27811e6202c00a9c58916` | LO-AUD-006, LO-AUD-007 | Submitted / pending independent retest | Pending independent reviewer | PR #7 CI run #425: compile and clean migration checks passed; 200 tests passed, 3 skipped. Reverse-charge/import VAT and direct HMRC MTD submission remain outside the supported scope. |
| 2026-09-18 | `2289ccaad0bd10c4032b703f52e8fe5c96a4b539` | LO-AUD-010 | Submitted / pending independent retest | Pending independent reviewer | PR #8 CI run #432: compile and clean migration checks passed; 210 tests passed, 3 skipped. Append-only ORM guard, per-organisation hash chain, retained head, integrity verifier and audited exports implemented. |
| 2026-09-18 | `a0934f819c907234a98522379c47ed03c8c6743c` | LO-AUD-011 | Submitted / pending independent retest | Pending independent reviewer | PR #9 CI run #437: compile and clean migration checks passed; 215 tests passed, 3 skipped. Paid-document credits, reusable customer/supplier credit, cross-document allocation, cash refunds, refund immutability and AR/AP reconciliation implemented. |

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
