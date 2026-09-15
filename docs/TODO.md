# LedgerOne Master TODO and Delivery Status

**Status snapshot:** 15 September 2026  
**Repository:** `zageabb/LedgerOne`  
**Reviewed against `main` through:** `570c0ab93381e2123253a32f8b72808985ec7fb5`  
**Purpose:** One place to see what is complete, what is in progress, and what remains outstanding.

> **Status rule:** `[x]` means the capability is implemented and published on `main`. `[ ]` means it is not yet complete on `main`, even where partial work exists on a branch or pull request.

Related documents:

- [Product roadmap](./ROADMAP.md)
- [Audit & Assurance workspace](../audit_assurance/README.md)
- [Accounting Practice & Controls Audit Report](../audit_assurance/2026-09-15-accounting-practice-review/AUDIT_REPORT.md)

---

## 1. Executive status

| Complete | Area | Status | Notes |
|---|---|---|---|
| [x] | v0.1 Foundation | Complete | 18/18 roadmap items published |
| [x] | v0.2 Accounting controls | Complete | 19/19 roadmap items published |
| [ ] | v0.3 Tax and day-to-day business | In progress | 9/11 roadmap items published; numbering in PR #3; contact/address improvements outstanding |
| [x] | Transaction audit provenance | Complete | Full record -> journal -> accounts -> evidence -> audit-event trace published |
| [x] | Audit assurance workspace/report | Complete | Audit workspace and 15-finding accounting/control review published |
| [ ] | Accounting Assurance remediation | Not complete | 15 audit findings remain open; Critical/High items block unrestricted production use |
| [ ] | v0.4 Bank/document automation | Not started as a release | 8 roadmap items outstanding |
| [ ] | v0.5 Projects/jobs/costing | Not started as a release | 8 roadmap items outstanding |
| [ ] | v0.6 Fixed assets/inventory | Not started as a release | 8 roadmap items outstanding |
| [ ] | v0.7 Payroll/workforce | Not started as a release | 6 roadmap items outstanding |
| [ ] | v0.8 Enterprise capabilities | Not started as a release | 12 roadmap items outstanding |
| [ ] | v0.9 Analytics/AI | Not started as a release | 8 roadmap items outstanding |
| [ ] | v1.0 Stable platform criteria | Not complete | Production hardening and release criteria remain |

### Current accounting assurance position

The Accounting Practice & Controls Audit concludes that the central double-entry architecture is sound, but LedgerOne is currently a **Conditional Fail for unrestricted production accounting** and **not yet approved for enterprise accounting** until the Critical and High control findings are remediated.

---

## 2. v0.1 — Foundation — COMPLETE

| Complete | Capability | Status / evidence |
|---|---|---|
| [x] | Flask application factory and modular registry | Published |
| [x] | Multi-organisation users and memberships | Published |
| [x] | Home / Apprentice and Professional UI modes | Published |
| [x] | Chart of accounts | Published |
| [x] | Double-entry journals | Published through central `LedgerService` |
| [x] | Trial balance | Published; period-awareness improvements are separately tracked under audit finding LO-AUD-004 |
| [x] | Banking module | Published |
| [x] | Sales / customers / invoices module | Published |
| [x] | Purchases / suppliers / bills module | Published |
| [x] | Reports module | Published |
| [x] | Settings and module administration | Published |
| [x] | Versioned REST APIs | Published |
| [x] | Hashed service/API keys | Published |
| [x] | Local AI workspace with audited tool access | Published; permission inheritance remediation is required under LO-AUD-001 |
| [x] | Per-organisation local AI settings and Ollama model discovery | Published |
| [x] | SQLite and PostgreSQL configuration | Published |
| [x] | CashLink legacy recovery/import tooling | Published |
| [x] | Flask-Migrate / Alembic baseline | Published |
| [x] | CI and smoke tests | Published; CI compiles, migrates clean DB, checks drift and runs pytest |

---

## 3. v0.2 — Accounting controls — COMPLETE

| Complete | Capability | Status / evidence |
|---|---|---|
| [x] | Accounting periods and period locking | Published; mandatory-period policy still requires hardening under LO-AUD-005 |
| [x] | Journal reversal workflow | Published |
| [x] | Immutable posted journals and journal lines | Published |
| [x] | Opening-balance wizard | Published |
| [x] | Recurring journals | Published |
| [x] | Organisation-level AI connection/model/write-safety settings | Published |
| [x] | Bank reconciliation workflow | Published; formal statement reconciliation remains under LO-AUD-014 |
| [x] | Customer/supplier payment allocation with partial settlement | Published |
| [x] | Adoption of existing bank/reconciliation journals without duplicate cash posting | Published |
| [x] | Outstanding receivable/payable balances | Published |
| [x] | Audit viewer, filters, API and CSV export | Published |
| [x] | Broader audit coverage across ledger, sales, purchases, banking, settings and AI configuration | Published |
| [x] | Source-document files and external evidence references | Published |
| [x] | Record-level document links for journals, invoices, bills and bank transactions | Published |
| [x] | Organisation member/role/permission administration | Published |
| [x] | Last-owner and self-deactivation safeguards | Published |
| [x] | API-key expiry, last-used visibility, rotation and revocation | Published |
| [x] | SQLite/PostgreSQL-safe API-key expiry validation | Published |
| [x] | Pagination and filtering on ledger account/journal APIs | Published |

---

## 4. v0.3 — Tax and day-to-day business — IN PROGRESS

| Complete | Capability | Status / remaining work |
|---|---|---|
| [x] | VAT/tax codes and tax accounts | Published |
| [x] | UK VAT return support | Published for GB standard VAT accounting; broader VAT lifecycle/compliance remains under LO-AUD-006/007 |
| [x] | Sales credit notes | Published |
| [x] | Purchase credit notes | Published |
| [x] | Sales quotes -> invoices | Published; conversion uses standard invoice posting service |
| [x] | Sales orders -> invoices | Published; Draft/Confirmed/Cancelled/Converted lifecycle |
| [x] | Purchase orders -> bills | Published; approval required before conversion |
| [x] | Expense claims | Published with submit/approve/reject/post workflow and VAT support |
| [x] | Payment terms | Published with organisation defaults, contact overrides and explicit due-date precedence |
| [x] | Aged receivables/payables | Published with historical `as_of` handling and currency-separated totals |
| [x] | Invoice/bill PDF output | Published using ReportLab |
| [ ] | Configurable numbering sequences | **IN PROGRESS — PR #3, not merged.** See section 5 |
| [ ] | Contact/address improvements | Not yet implemented as the remaining v0.3 product item |

### v0.3 completion gate

v0.3 should not be marked complete until configurable numbering is fully merged/tested and contact/address improvements are implemented. In addition, the audit report identifies accounting-control work that should take priority over broadening feature scope.

---

## 5. Configurable numbering sequences — IN PROGRESS, NOT PUBLISHED

Current branch/PR: `numbering-sequences-v03`, PR #3. The branch has diverged from current `main`, so it must be reconciled with the newer audit-provenance changes before merge.

| Complete | Numbering task | Status |
|---|---|---|
| [x] | `number_sequences` model created on PR branch | Implemented on branch only |
| [x] | Alembic migration `0013_number_sequences` created on PR branch | Implemented on branch only |
| [x] | Configurable prefix, suffix, next value and padding | Implemented on branch only |
| [x] | Settings browser UI for numbering | Implemented on branch only |
| [x] | Settings API for numbering | Implemented on branch only |
| [x] | Transaction-aware allocation so failed posting can roll back number consumption | Implemented/tested on branch only |
| [x] | Auto-number sales invoices | Implemented on branch only |
| [x] | Auto-number purchase bills | Implemented on branch only |
| [x] | Auto-number sales quotes | Implemented on branch only |
| [x] | Auto-number sales orders | Implemented on branch only |
| [x] | Auto-number purchase orders | Implemented on branch only |
| [x] | Explicit manual number override without consuming auto sequence | Implemented/tested on branch only |
| [x] | Collision skipping | Implemented on branch only |
| [ ] | Rebase/merge PR #3 onto latest `main` | Branch is behind current main/audit work |
| [ ] | Auto-number sales credit notes | Outstanding |
| [ ] | Auto-number purchase credit notes | Outstanding |
| [ ] | Auto-number expense claims | Outstanding |
| [ ] | Prove concurrency safety under simultaneous document creation | Audit acceptance criterion not yet demonstrated by current tests |
| [ ] | Add gap detection/reporting | Required by LO-AUD-009 recommendation |
| [ ] | Add void/cancelled-number retention policy and prevent number reuse | Required by LO-AUD-009 recommendation |
| [ ] | Final full CI on reconciled branch | Required before merge |
| [ ] | Merge to `main` and update ROADMAP | Required before marking complete |

---

## 6. Document audit/provenance — COMPLETE

| Complete | Capability | Status |
|---|---|---|
| [x] | Trace accounting record to posted journal | Published |
| [x] | Show journal source module/source reference | Published |
| [x] | Expand every journal line to account code/name/type | Published |
| [x] | Show debit, credit, currency, dimensions and record location | Published |
| [x] | Trace converted Invoice back to Quote or Sales Order | Published |
| [x] | Trace converted Bill back to Purchase Order | Published |
| [x] | Show exact source-document file storage key or external reference URL | Published |
| [x] | Show evidence SHA-256, size, uploader and timestamp | Published |
| [x] | Show full record IDs rather than abbreviated-only IDs | Published |
| [x] | Full related audit-event listing with actor/action/entity/detail | Published |
| [x] | No arbitrary 1,000-event cap on transaction audit trace | Published |
| [x] | Documents screen audit trace | Published |
| [x] | REST audit-trace endpoint | Published |
| [x] | Invoice/Bill PDF Audit & Provenance appendix | Published |
| [x] | Organisation-boundary and provenance regression tests | Published |

---

## 7. Audit & Assurance governance — PARTLY COMPLETE

| Complete | Governance item | Status |
|---|---|---|
| [x] | Permanent `audit_assurance/` workspace | Published |
| [x] | Audit lifecycle and severity/status conventions | Published |
| [x] | 2026-09-15 Accounting Practice & Controls Audit Report | Published |
| [x] | Audit finding IDs `LO-AUD-001` through `LO-AUD-015` | Published |
| [ ] | `ACTION_REGISTER.md` referenced by the audit README/report | **Missing from repository at this snapshot; create authoritative remediation register** |
| [ ] | Assign owner and target release to every audit finding | Outstanding |
| [ ] | Record implementation commit and regression-test evidence per finding | Outstanding |
| [ ] | Independent retest before changing a finding to CLOSED | Outstanding |

---

## 8. Accounting Assurance remediation — 15 OPEN FINDINGS

These findings are separate from ordinary feature-roadmap completion. They determine whether LedgerOne is safe for unrestricted production accounting.

| Complete | Finding | Severity | Gate | Required outcome |
|---|---|---:|---|---|
| [ ] | **LO-AUD-001 — AI accounting actions can bypass requesting-user permissions** | CRITICAL | A | AI must use the effective permissions of the requesting user/API key and never elevate to system full access; add write-approval policy/tests |
| [ ] | **LO-AUD-002 — Foreign-currency postings lack base-currency translation** | CRITICAL | A | Until full FX exists, hard-restrict postings to organisation base currency; later implement exchange rates, base amounts, settlement differences and revaluation |
| [ ] | **LO-AUD-003 — Control accounts are not protected from direct posting** | HIGH | A | Protect AR/AP/VAT/reimbursement control accounts, restrict posting to owning workflows, and add subledger-to-GL reconciliation |
| [ ] | **LO-AUD-005 — Period controls allow posting where no accounting period exists** | HIGH | A | Require valid posting period under professional policy; add open/soft-close/hard-close governance and audited reopen/override |
| [ ] | **LO-AUD-008 — Posted commercial documents lack journal-level immutability** | HIGH | A | Prevent update/delete of posted invoice/bill headers and lines; correct via credit/reversal/cancellation |
| [ ] | **LO-AUD-004 — Financial reports are not sufficiently period-aware** | HIGH | B | Add TB as-at, P&L from/to, Balance Sheet as-at, GL activity from/to with brought/carried balances and comparatives |
| [ ] | **LO-AUD-009 — Invoice/credit-note numbering needs controlled sequences** | MEDIUM-HIGH | B | Finish and merge numbering; prove concurrency safety, no reuse, gap/void handling and separate series |
| [ ] | **LO-AUD-012 — Account types/posting roles need stronger validation** | MEDIUM | B | Constrain account types and validate module-specific account roles/default control accounts |
| [ ] | **LO-AUD-013 — API/integration posting lacks idempotency protection** | MEDIUM | B | Add idempotency key/source uniqueness and replay-safe posting behavior |
| [ ] | **LO-AUD-014 — Bank reconciliation is not a full statement reconciliation** | MEDIUM | B | Add statement period/opening/closing balances, outstanding items, GL cut-off balance, approval and locked reconciliation report |
| [ ] | **LO-AUD-006 — Invoice output is not yet a complete UK VAT invoice** | HIGH | C | Add supplier legal/address/VAT details, customer address, tax point/issue date and all required VAT invoice content/tests |
| [ ] | **LO-AUD-007 — VAT return model lacks full tax-point/adjustment/MTD controls** | HIGH | C | Add VAT tax point, return lifecycle/locking, adjustments/evidence and reproducible submitted return; MTD only after core lifecycle is robust |
| [ ] | **LO-AUD-010 — Audit events are not tamper-evident** | MEDIUM-HIGH | D | Enforce append-only audit events, restrict DB mutation and consider hash-chain/signed checkpoints plus retention controls |
| [ ] | **LO-AUD-015 — Enterprise segregation-of-duties controls are incomplete** | MEDIUM | D | Add maker/checker, no-self-approval, thresholds and approvals for journals/master data/payments/period reopen/control adjustments/AI writes |
| [ ] | **LO-AUD-011 — Credit notes cannot fully support paid-invoice credit/refund scenarios** | MEDIUM | Supporting | Separate invoice value/payments/credits/customer credit/refunds; support paid invoice -> credit balance -> refund or reallocation |

### Accounting Assurance release order

| Complete | Gate | Scope | Release condition |
|---|---|---|---|
| [ ] | Gate A | LO-AUD-001, 002, 003, 005, 008 | Complete before unrestricted production accounting |
| [ ] | Gate B | LO-AUD-004, 009, 012, 013, 014 | Complete for professional bookkeeping readiness |
| [ ] | Gate C | LO-AUD-006, 007 plus later HMRC MTD submission | Complete before UK VAT/MTD compliance claims |
| [ ] | Gate D | LO-AUD-010, 015 plus full multi-currency/revaluation | Complete for enterprise readiness |

---

## 9. v0.4 — Bank and document automation — OUTSTANDING

| Complete | Capability | Status |
|---|---|---|
| [ ] | CSV/OFX/QIF bank import adapters | Outstanding |
| [ ] | Open Banking connector abstraction | Outstanding |
| [ ] | Reconciliation suggestions | Outstanding |
| [ ] | Receipt/invoice document ingestion | Outstanding |
| [ ] | OCR/document extraction adapter | Outstanding |
| [ ] | AI-assisted coding suggestions with approval | Outstanding; must respect LO-AUD-001/015 controls |
| [ ] | Duplicate-document detection | Outstanding |
| [ ] | Rules engine for recurring merchants/payees | Outstanding |

---

## 10. v0.5 — Projects, jobs and costing — OUTSTANDING

| Complete | Capability | Status |
|---|---|---|
| [ ] | Projects/Jobs module | Outstanding |
| [ ] | Cost centres and departments | Outstanding |
| [ ] | Reusable accounting dimensions | Outstanding |
| [ ] | Budgets by dimension | Outstanding |
| [ ] | Project profitability | Outstanding |
| [ ] | Job-cost transactions | Outstanding |
| [ ] | Timesheet/cost allocation interfaces | Outstanding |
| [ ] | Migration path for CashLink Job Cost data | Outstanding |

---

## 11. v0.6 — Fixed assets and inventory — OUTSTANDING

| Complete | Capability | Status |
|---|---|---|
| [ ] | Fixed Assets module | Outstanding |
| [ ] | Asset classes and depreciation books | Outstanding |
| [ ] | Acquisition/disposal/depreciation posting | Outstanding |
| [ ] | Inventory module | Outstanding |
| [ ] | Stock items and locations | Outstanding |
| [ ] | Stock movements | Outstanding |
| [ ] | Valuation method abstraction | Outstanding |
| [ ] | Purchase/sales integration | Outstanding |

---

## 12. v0.7 — Payroll and workforce integration — OUTSTANDING

| Complete | Capability | Status |
|---|---|---|
| [ ] | Payroll module boundary | Outstanding |
| [ ] | Employees and pay runs | Outstanding |
| [ ] | Earnings/deductions definitions | Outstanding |
| [ ] | Payroll journal generation | Outstanding |
| [ ] | External payroll import/API adapters | Outstanding |
| [ ] | UK statutory payroll processing | Outstanding; compliance design/review required first |

---

## 13. v0.8 — Enterprise capabilities — OUTSTANDING

| Complete | Capability | Status |
|---|---|---|
| [ ] | Formal role-based access-control administration | Outstanding beyond current member/permission administration |
| [ ] | Approval workflows | Outstanding |
| [ ] | Segregation-of-duties rules | Outstanding; also LO-AUD-015 |
| [ ] | Multi-currency transactions and revaluation | Outstanding; also LO-AUD-002 |
| [ ] | Intercompany accounts and journals | Outstanding |
| [ ] | Consolidated reporting | Outstanding |
| [ ] | Entity hierarchies | Outstanding |
| [ ] | High-volume import/batch jobs | Outstanding |
| [ ] | Background workers/queues | Outstanding |
| [ ] | Webhooks and integration event log | Outstanding |
| [ ] | SSO/OIDC/SAML integration layer | Outstanding |
| [ ] | PostgreSQL-first deployment profile | Outstanding |

---

## 14. v0.9 — Analytics and AI — OUTSTANDING

| Complete | Capability | Status |
|---|---|---|
| [ ] | Natural-language report generation | Outstanding |
| [ ] | Anomaly detection | Outstanding |
| [ ] | Cash-flow forecasting | Outstanding |
| [ ] | Collections/payment prioritisation | Outstanding |
| [ ] | Budget variance explanations | Outstanding |
| [ ] | Explainable coding/reconciliation suggestions | Outstanding |
| [ ] | AI approval policies by tool/action/risk | Outstanding; also required by LO-AUD-001/015 |
| [ ] | Organisation-specific knowledge/RAG sources | Outstanding |
| [ ] | Optional local-model profiles per organisation | Outstanding beyond current single organisation-level AI config |

---

## 15. v1.0 — Stable platform target criteria — OUTSTANDING

| Complete | Target criterion | Status |
|---|---|---|
| [ ] | Migration-safe release process | Alembic + CI exist, but formal release/upgrade process is not yet a completed v1.0 criterion |
| [ ] | Stable public API contract | Outstanding |
| [ ] | Documented module SDK/contract | Outstanding |
| [ ] | Full audit and accounting-period controls | Partly implemented; audit findings LO-AUD-005/010 remain |
| [ ] | Backup/restore documentation and tests | Outstanding |
| [ ] | PostgreSQL production reference deployment | Outstanding |
| [ ] | Security review and dependency scanning | Outstanding as a v1.0 release gate |
| [ ] | Robust test coverage for financial invariants | Significant coverage exists, but audit remediation tests remain |
| [ ] | Upgrade testing from previous releases | Outstanding |
| [ ] | Disaster-recovery procedure | Outstanding |
| [ ] | User/admin documentation | Outstanding as a complete v1.0 documentation set |

---

## 16. Immediate recommended work order

| Priority | Complete | Work item | Why now |
|---:|---|---|---|
| 1 | [ ] | Create the missing Accounting Assurance `ACTION_REGISTER.md` | The audit report and workspace already reference it as the authoritative remediation register |
| 2 | [ ] | LO-AUD-001 — Fix AI permission inheritance | Critical authorisation risk |
| 3 | [ ] | LO-AUD-002 — Enforce base currency until real FX exists | Critical financial-statement risk |
| 4 | [ ] | LO-AUD-003 — Protect control accounts and add subledger reconciliation | High subledger/GL integrity risk |
| 5 | [ ] | LO-AUD-005 — Enforce mandatory accounting-period policy | High period close/cut-off risk |
| 6 | [ ] | LO-AUD-008 — Make posted commercial documents immutable | High audit/subledger integrity risk |
| 7 | [ ] | Reconcile and finish PR #3 numbering work | Completes a v0.3 item and addresses part of LO-AUD-009 |
| 8 | [ ] | LO-AUD-004 — Period-aware TB/P&L/Balance Sheet/GL reports | Required for professional accounting |
| 9 | [ ] | Contact/address improvements | Last ordinary v0.3 product feature and prerequisite for better VAT invoices |
| 10 | [ ] | LO-AUD-006/007 — Complete VAT invoice and VAT-period controls | Required before UK VAT/MTD compliance claims |

---

## 17. Definition of done for future checklist updates

A checkbox should move to `[x]` only when all applicable conditions are satisfied:

| Complete | Completion condition |
|---|---|
| [ ] | Implementation is committed and merged to `main` |
| [ ] | Schema change has an Alembic migration where required |
| [ ] | Browser/API/service paths use the same business/accounting rules |
| [ ] | Relevant regression tests exist |
| [ ] | CI is green on the final merged feature head |
| [ ] | ROADMAP/TODO documentation is updated |
| [ ] | If tied to an audit finding, acceptance criteria are evidenced and the item has been independently retested before being marked CLOSED |

---

## 18. Engineering principles that remain mandatory

These are not optional backlog items; they are constraints for every future change.

| Principle | Requirement |
|---|---|
| One accounting kernel | All financial postings continue through the central double-entry ledger service |
| Modular growth | New capabilities should be modules unless genuinely part of the accounting/security kernel |
| Shared service rules | Browser, REST API and AI must use the same service-layer accounting rules |
| No second enterprise product | Enterprise capability extends organisation/permission/dimension/workflow models |
| Friendly UI without weaker books | Home/Apprentice mode simplifies presentation, not accounting integrity |
| Migration-controlled schema | Every schema change must be migration-controlled |
| Auditable consequential actions | Material actions and overrides must produce retained audit evidence |
| Corrections, not silent edits | Posted accounting records should be corrected by controlled reversal/credit/cancellation workflows |
