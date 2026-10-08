# LedgerOne Development

**Repository:** `zageabb/LedgerOne`  
**Source-of-truth review:** 3 October 2026  
**Reviewed main:** `8c32db7fd9aa2b0287095b9edfe3050b6f253498`

This file is the persistent development queue for LedgerOne. It is intentionally based on the current implementation on `main`, current open pull requests, tests, the audit action register, `docs/TODO.md`, and `docs/ROADMAP.md`.

## Working rules

- Treat the current implementation and passing tests as stronger evidence than stale status text.
- Do not reimplement features already present on `main`.
- Complete and verify the highest-priority incomplete item before starting unrelated work.
- For audit findings, implementation is not CLOSED until evidence is recorded and an independent retest has been completed.
- Update this file whenever work is merged, superseded, deferred, or shown by source evidence to already exist.

---

## 1. Source-of-truth corrections found during this review

The older `docs/TODO.md` snapshot is no longer fully representative of `main`.

### Already implemented on main — do not add as new development

- [x] AI caller permission inheritance and per-message write approval.
- [x] Persistent AI conversations and chat workspace.
- [x] Organisation-scoped Knowledge/RAG workspace with local retrieval and provenance.
- [x] Base-currency posting gate.
- [x] Control-account protection and AR/AP/VAT reconciliation controls.
- [x] Mandatory accounting-period policy with soft/hard close controls.
- [x] Posted commercial-document immutability.
- [x] Period-aware Trial Balance, P&L, Balance Sheet and General Ledger reporting.
- [x] UK VAT invoice identity/tax-point improvements and VAT return lifecycle controls.
- [x] Tamper-evident audit hash chain and integrity verification.
- [x] Controlled numbering infrastructure on `main`, including migration `0015_number_sequences.py`, atomic allocation, retained issued/void history, yearly reset support, gap reporting, immutable allocation history and concurrency tests.
- [x] Same-account customer/supplier payment protection implemented as part of control-account hardening.

### Status/documentation cleanup still required

- [ ] Reconcile `docs/TODO.md` with the actual features now present on `main`.
- [ ] Reconcile the audit action register with the current numbering implementation and any other findings whose engineering work is already complete.
- [ ] Close or supersede stale PR #3 after confirming all useful numbering work is represented by the implementation already on `main`.
- [ ] Record independent retest evidence for findings currently marked READY FOR RETEST before changing them to CLOSED.
- [ ] After retest, update `docs/ROADMAP.md`, `docs/TODO.md`, and the audit closure summary together.

---

## 2. Highest-priority active development

### DEV-001 — Complete paid-document credits and refunds / LO-AUD-011

**Status:** ENGINEERING COMPLETE — merged to `main`, awaiting independent audit retest

- [x] Review PR #9 against current `main`.
- [x] Confirm no code rebase was required; intervening `main` changes were development/agent documentation only.
- [x] Verify paid invoice -> credit -> unapplied customer credit.
- [x] Verify customer credit -> another invoice allocation.
- [x] Verify customer credit -> cash refund.
- [x] Verify equivalent supplier-credit/refund paths.
- [x] Verify refund records remain immutable audit evidence.
- [x] Merge PR #9 to `main`.
- [x] Run clean migration validation through `0018_credit_refunds`.
- [x] Run the complete merged-main regression suite.
- [x] Update LO-AUD-011 evidence and submit it for independent retest.
- [ ] Independent audit retest and formal finding closure.

**Completion evidence:** merge commit `0388f1b592a64a704172078aee67b2421d2e0043`; LedgerOne CI run #442; clean migration upgrade; 215 tests passed, 3 skipped.

### DEV-002 — Finish account classification and posting-role validation / LO-AUD-012

**Status:** ENGINEERING COMPLETE — merged to `main`, awaiting independent audit retest

- [x] Restrict account type values to the supported classification set at service and database levels.
- [x] Validate parent/child account classification where applicable.
- [x] Define/configure central default system posting accounts and seed starter-chart defaults.
- [x] Make sales/purchase posting paths consume central defaults when an explicit account is not supplied.
- [x] Validate sales revenue/income account roles.
- [x] Validate purchase expense/asset account roles.
- [x] Ensure banking account links reject incompatible, inactive and control ledger accounts and revalidate at posting time.
- [x] Define audited, permission-controlled overrides for legitimate exceptional non-control account-type cases.
- [x] Keep AR/AP/control-account ownership rules non-overridable.
- [x] Add regression tests for invalid classifications and sales, purchase and bank account-role combinations.
- [x] Add migration `0019_account_roles` and verify no missing Alembic operations.
- [x] Record implementation/retest evidence in the audit register.
- [ ] Independent audit retest and formal finding closure.

**Completion evidence:** PR #10; merge commit `bc0906d86dd969861f52f6897e726f3dfc95a7e7`; LedgerOne CI run #450; clean migration through `0019_account_roles`; 223 tests passed, 3 skipped.

### DEV-003 — Add replay-safe API/integration idempotency / LO-AUD-013

**Status:** ENGINEERING COMPLETE — merged to `main`, awaiting independent audit retest

- [x] Define an optional `Idempotency-Key` contract for authenticated write endpoints.
- [x] Persist organisation, operation, idempotency key, request fingerprint, response/result reference and lifecycle timestamps.
- [x] Reserve the key before business execution so concurrent duplicate requests cannot both create accounting side effects.
- [x] Return the original successful status/body for an identical replay and mark it with `Idempotency-Replayed: true`.
- [x] Reject reuse of the same key with a different payload using HTTP 409 `idempotency_conflict`.
- [x] Support `X-Source-System` + `X-Source-Reference` uniqueness as a second integration replay guard.
- [x] Define a 90-day retention policy and cleanup service.
- [x] Apply the guard centrally through `require_api` to authenticated POST/PUT/PATCH/DELETE operations, covering journals, invoices, bills, payments, banking, workflows and other consequential writes.
- [x] Add replay, conflict, source-reference and organisation-isolation tests.
- [x] Add migration `0020_api_idempotency` and verify no missing Alembic operations.
- [x] Document the integration contract in `docs/API_IDEMPOTENCY.md`.
- [x] Record implementation/retest evidence in the audit register.
- [ ] Independent audit retest and formal finding closure.

**Completion evidence:** PR #11; merge commit `bc3a704ae51705598f7a42f89590d18e6c9ed7a6`; LedgerOne CI run #454; clean migration through `0020_api_idempotency`; 228 tests passed, 3 skipped.

### DEV-004 — Formal statement-to-GL bank reconciliation / LO-AUD-014

**Status:** ENGINEERING COMPLETE — merged to `main`, awaiting independent audit retest

- [x] Add retained reconciliation header/entity.
- [x] Capture statement start/end dates.
- [x] Capture statement opening/closing balance.
- [x] Calculate cumulative linked-bank ledger balance at statement cut-off.
- [x] Retain statement transaction snapshot, unmatched statement items and statement-period outstanding book items.
- [x] Calculate unmatched/outstanding totals, explained difference, adjusted statement balance and residual difference.
- [x] Prevent finalisation while an unexplained residual remains.
- [x] Record prepared-by and approved-by identities/timestamps.
- [x] Lock finalised reconciliations against service and direct ORM mutation/deletion.
- [x] Provide browser retained evidence plus CSV export and matching API evidence.
- [x] Add zero-balance fixture, residual-blocking, explanation-resolution and immutability tests.
- [x] Add migration `0021_bank_reconciliations` and verify no missing Alembic operations.
- [x] Record implementation/retest evidence in the audit register.
- [ ] Independent audit retest and formal finding closure.

**Completion evidence:** PR #12; merge commit `7a80676613cff76ade4b41737b56e3093e4e7c4d`; LedgerOne CI run #460; clean migration through `0021_bank_reconciliations`; 231 tests passed, 3 skipped.

### DEV-005 — Maker/checker and segregation of duties / LO-AUD-015

- [x] Fix approval-request JSON metadata serialisation for date/datetime/Decimal values and add regression coverage (branch commits `fd5583e`, `223c429`).
- [x] PR #13 CI #468 green and merged to main (`3287c759`).
- [ ] Independent audit retest and closure of LO-AUD-015.

**Status:** OPEN

- [ ] Add organisation-level approval-policy configuration.
- [ ] Support no-self-approval.
- [ ] Add journal approval workflow.
- [ ] Add transaction-value approval thresholds.
- [ ] Add configurable supplier/customer master-data approval.
- [ ] Add payment/bank approval policy.
- [ ] Add period-reopen approval.
- [ ] Add control-account adjustment approval.
- [ ] Add AI-generated accounting write approval policy.
- [ ] Retain preparer, approver, decision, timestamp and reason/comments.
- [ ] Add tests for no-self-approval, threshold routing and retained approval history.

---

## 3. Audit work implemented but still requiring formal closure

These items should not be rebuilt unless independent retest identifies a defect.

- [ ] LO-AUD-001 — independent retest/closure of AI permission inheritance and write approval.
- [ ] LO-AUD-002 — independent retest/closure of the base-currency posting gate.
- [ ] LO-AUD-003 — independent retest/closure of control-account protection/reconciliation.
- [ ] LO-AUD-004 — independent retest/closure of period-aware financial reporting.
- [ ] LO-AUD-005 — independent retest/closure of mandatory accounting-period policy.
- [ ] LO-AUD-006 — independent retest/closure of UK VAT invoice completeness.
- [ ] LO-AUD-007 — independent retest/closure of VAT tax-point/return lifecycle scope.
- [ ] LO-AUD-008 — independent retest/closure of posted-document immutability.
- [ ] LO-AUD-009 — reconcile audit status with the controlled-numbering implementation on `main`, verify all required document integrations, then independently retest.
- [ ] LO-AUD-010 — independent retest/closure of tamper-evident audit integrity.

### Deferred scope explicitly not yet provided

- [ ] Full multi-currency accounting: exchange-rate master, transaction/base amounts, realised FX, unrealised revaluation, settlement differences and foreign-currency ageing.
- [ ] Reverse-charge/import VAT treatment.
- [ ] Direct HMRC MTD API submission plus request/response/receipt retention.
- [ ] Optional externally signed audit checkpoints if enterprise assurance requires evidence beyond the current retained hash-chain head.

---

## 4. v0.3 day-to-day usability gaps still visible in current source

### DEV-006 — Customer/supplier contact and address management

**Status:** ENGINEERING MERGED — PR #14 (`0ee62e94`), CI #483 green; follow-up usability verification as required

Customer and supplier models already contain address data, and VAT output consumes customer address information, but the primary Sales/Purchases browser creation forms still expose only name/email/phone/payment terms.

- [x] Add structured address fields to customer creation UI.
- [x] Add structured address fields to customer edit UI (branch implementation; CI pending).
- [x] Add structured address fields to supplier creation UI.
- [x] Add structured address fields to supplier edit UI (branch implementation; CI pending).
- [x] Add customer/supplier edit screens and register navigation (branch implementation; CI pending).
- [x] Add service-level customer/supplier address create/edit round-trip tests (`tests/test_contact_addresses.py`).
- [ ] Verify latest DEV-006 CI and any failing browser/API regressions, then merge and validate main.
- [x] Include postcode/country and validate structured address objects, supported keys, text fields and maximum lengths (branch implementation; CI pending).
- [x] Add address fields to customer/supplier list/create API, detail GET and PATCH updates (branch implementation; CI pending).
- [x] Add address round-trip and invalid-input tests (branch implementation; CI pending).
- [ ] Mark the remaining v0.3 contact/address roadmap item complete only after the browser workflow is usable.

### DEV-007 — Show useful balances on operational lists

**Status:** IN PROGRESS — PR #15, CI #493 green on earlier commit (`fd429298`); currency-separated party balances added thereafter and latest CI pending. Customer/supplier activity filtering deferred to follow-up.

- [x] Show current cumulative ledger balance on Chart of Accounts (branch implementation, CI pending).
- [x] Show current receivable/outstanding balance on customer lists (branch, CI pending).
- [x] Show current payable/outstanding balance on supplier lists (branch, CI pending).
- [x] Show current ledger/book balance on bank-account lists, with unlinked accounts explicit (branch implementation, CI pending).
- [x] Reuse the existing financial reporting trial-balance calculation for GL and bank book balances; customer/supplier outstanding uses grouped posted document and payment allocation data.
- [x] Separate outstanding receivables/payables by original document currency; do not sum unrelated currencies (branch, CI pending).
- [x] Avoid N+1 queries using grouped invoice/bill and allocation queries (branch, CI pending).
- [x] Link Chart of Accounts names to account-filtered general ledger (branch implementation).
- [ ] Add customer/supplier activity drill-down filters where practical (follow-up).
- [x] Label account and bank balances with report as-of date; customer/supplier lists labelled current (branch, CI pending).

### DEV-008 — Accounting workflow guidance for non-accountants

**Status:** IN PROGRESS — full Mermaid workflow guide and authenticated in-app help page added; CI verification pending.

- [x] Create `docs/ACCOUNTING_WORKFLOWS.md`.
- [x] Add Mermaid flows for quote/order -> invoice -> payment/allocation.
- [x] Add supplier PO -> bill -> payment/allocation.
- [x] Add expense claim -> approval -> posting/reimbursement.
- [x] Add bank receipt/payment and bank transfer.
- [x] Add sales/purchase credit note and refund.
- [x] Add manual journal, opening balance and recurring journal.
- [x] Add VAT-related transaction path.
- [x] Explain the accounting effect in plain English and debit/credit terms where useful.
- [x] Clearly direct users toward Sales/Purchases/Banking workflows instead of manual AR/AP/VAT postings.
- [x] Include supported correction paths: reversal, credit, refund and cancellation.
- [x] Link the guide from Home/Apprentice UI and Help/documentation.

### DEV-009 — Numbering UX/integration consistency review

**Status:** IN PROGRESS — implemented blank purchase bill numbering across browser, API, workflow and final posting on PR #17; latest CI pending. Separate supplier external invoice reference and other document-type review remain outstanding.

Controlled numbering is implemented on `main`, but browser behaviour should be reviewed across every supported document type.

- [ ] Verify automatic numbering is reachable from browser, API and workflow paths for invoices, bills, sales/purchase credit notes, quotes, sales orders, purchase orders and expense claims.
- [x] Identify purchase bill manual-number requirement in browser/API/service/workflow and document safe migration/compatibility plan.
- [x] Allow blank bill numbers on Purchases browser form and API/workflow, assigning the controlled purchase-bill number only at final posting (PR #17, CI pending).
- [x] Support blank bill number on purchase-order conversion browser/API, while preserving final-post controlled allocation (branch; CI pending).
- [x] Review remaining sales quote/order, invoice-conversion, purchase credit note and purchase order browser forms; document the required-number gaps in `docs/NUMBERING_CONSISTENCY_AUDIT.md`.
- [x] Implement purchase credit-note controlled numbering at posting for browser/API, including transactional rollback (PR #17, latest CI pending).
- [x] Add controlled numbering to sales quotes, sales orders and purchase orders on creation, with optional browser/API number entry (branch; CI pending).
- [x] Make quote/order conversion invoice-number fields optional in browser/API; reuse final invoice posting allocator (CI pending).
- [ ] Verify expense claim numbering, external supplier invoice reference separation and complete regression coverage.
- [x] Add a separate nullable supplier invoice reference with migration 0022, browser/API/workflow plumbing (follow-up branch; CI pending).
- [x] Display both the LedgerOne document number and separate supplier reference on purchase bill PDFs (branch; CI pending).
- [ ] Decide historical source-reference backfill policy: do not infer supplier invoice numbers from legacy internal numbers.
- [ ] Verify cancelled/void document flows preserve number history.
- [ ] Ensure the audit action register reflects the actual implementation and tests.

---

## 5. v0.4 — Bank and document automation

**Status:** NOT STARTED AS A RELEASE

- [ ] CSV/OFX/QIF bank import adapters.
- [ ] Open Banking connector abstraction.
- [ ] Reconciliation suggestions.
- [ ] Receipt/invoice document ingestion.
- [ ] OCR/document extraction adapter.
- [ ] AI-assisted coding suggestions with approval controls.
- [ ] Duplicate-document detection.
- [ ] Rules engine for recurring merchants/payees.

---

## 6. v0.5 — Projects, jobs and costing

**Status:** NOT STARTED AS A RELEASE

- [ ] Projects/Jobs module.
- [ ] Cost centres and departments.
- [ ] Reusable accounting dimensions.
- [ ] Budgets by dimension.
- [ ] Project profitability.
- [ ] Job-cost transactions.
- [ ] Timesheet/cost allocation interfaces.
- [ ] CashLink Job Cost migration path.

---

## 7. v0.6 — Fixed assets and inventory

**Status:** NOT STARTED AS A RELEASE

- [ ] Fixed Assets module.
- [ ] Asset classes and depreciation books.
- [ ] Acquisition/disposal/depreciation posting.
- [ ] Inventory module.
- [ ] Stock items and locations.
- [ ] Stock movements.
- [ ] Valuation-method abstraction.
- [ ] Purchase/sales integration.

---

## 8. v0.7 — Payroll and workforce integration

**Status:** NOT STARTED AS A RELEASE

- [ ] Payroll module boundary.
- [ ] Employees and pay runs.
- [ ] Earnings/deductions definitions.
- [ ] Payroll journal generation.
- [ ] External payroll import/API adapters.
- [ ] UK statutory payroll processing only after compliance design/review.

---

## 9. v0.8 — Enterprise capabilities

**Status:** OUTSTANDING

- [ ] Formal RBAC administration beyond current member/permission administration.
- [ ] General approval workflows beyond the current transaction workflows.
- [ ] Segregation-of-duties policy engine.
- [ ] Full multi-currency transactions and revaluation.
- [ ] Intercompany accounts and journals.
- [ ] Consolidated reporting.
- [ ] Entity hierarchies.
- [ ] High-volume import/batch jobs.
- [ ] Background workers/queues.
- [ ] Webhooks and integration event log.
- [ ] SSO/OIDC/SAML integration layer.
- [ ] PostgreSQL-first production deployment profile.

---

## 10. v0.9 — Analytics and AI

**Status:** OUTSTANDING

The base local-AI chat and organisation Knowledge capabilities already exist. Remaining higher-level analytics/AI work is:

- [ ] Natural-language report generation.
- [ ] Anomaly detection.
- [ ] Cash-flow forecasting.
- [ ] Collections/payment prioritisation.
- [ ] Budget variance explanations.
- [ ] Explainable coding/reconciliation suggestions.
- [ ] Configurable AI approval policies by tool/action/risk.
- [ ] Optional local-model profiles beyond the current single organisation-level configuration.
- [ ] Optional local embedding/vector retrieval while preserving the existing organisation/security boundary.

---

## 11. v1.0 production/stable-platform gates

**Status:** OUTSTANDING

- [ ] Formal migration-safe release/upgrade process.
- [ ] Stable public API contract/versioning policy.
- [ ] Documented module SDK/extension contract.
- [ ] All applicable accounting assurance findings CLOSED or explicitly excluded from the supported product scope.
- [ ] Backup/restore documentation and tested restore procedure.
- [ ] PostgreSQL production reference deployment.
- [ ] Security review and dependency/vulnerability scanning.
- [ ] Financial-invariant regression coverage maintained as modules grow.
- [ ] Upgrade tests from prior supported releases.
- [ ] Disaster-recovery procedure.
- [ ] Complete user/admin documentation.
- [ ] Supported-scope statement covering currencies, VAT/MTD, payroll and enterprise controls.

---

## 12. Recommended development order

1. DEV-005 — LO-AUD-015 maker/checker and segregation of duties.
2. Independently retest and close engineering-complete audit findings, including DEV-001/LO-AUD-011, DEV-002/LO-AUD-012, DEV-003/LO-AUD-013, DEV-004/LO-AUD-014, and reconciling LO-AUD-009 numbering evidence.
3. DEV-006 — finish customer/supplier address management and close the remaining v0.3 usability gap.
4. DEV-007 — operational-list balances.
5. DEV-008 — accounting workflow guide and in-app links.
6. DEV-009 — numbering UX/integration consistency pass.
7. Begin v0.4 only after the professional-bookkeeping assurance backlog above is stable.

---

## 13. Definition of done

A development item is complete only when all applicable evidence exists:

- [ ] implementation merged to `main`;
- [ ] schema changes have Alembic migrations;
- [ ] browser/API/service paths apply the same business rules;
- [ ] relevant regression tests exist;
- [ ] final candidate CI is green;
- [ ] documentation/status is updated;
- [ ] audit-linked work has implementation evidence and independent retest before CLOSED;
- [ ] no stale PR or older TODO entry still presents superseded work as the active implementation.
