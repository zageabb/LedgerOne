# LedgerOne Accounting Practice & Controls Audit Report

**Audit date:** 15 September 2026  
**Repository:** `zageabb/LedgerOne`  
**Audited code baseline:** `226dd44f8096fb54e02914d2e90e420a0bc7f0ef`  
**Audit type:** Accounting-system design, implementation and control review  
**Overall result:** **Conditional Fail for unrestricted production accounting**  
**Enterprise readiness:** **Not yet approved**

---

## 1. Executive summary

LedgerOne has a sound architectural foundation for an accounting system. Its central ledger is based on double-entry journals, uses a common posting service, enforces balanced entries, prevents ordinary mutation of posted journals and supports accounting periods, reversals, opening balances, recurring journals, sales, purchases, banking, VAT, source documents and an audit trail.

The core accounting engine is therefore **substantially correct in its basic double-entry behaviour**.

However, this audit identified control weaknesses around that engine which can allow LedgerOne to contain a technically balanced general ledger while still being operationally, legally or financially incorrect. The most significant risks are:

1. the AI execution path can elevate an ordinary user to a full-access system accounting identity;
2. foreign-currency documents are accepted without a genuine base-currency translation model;
3. control accounts such as Accounts Receivable, Accounts Payable and VAT can be posted to outside the corresponding subledger workflow;
4. financial reporting is not yet sufficiently period-aware for professional accounting;
5. accounting periods can be bypassed where no period record exists;
6. posted commercial documents do not yet have the same immutability protection as the journals they generated;
7. VAT invoicing and VAT-period controls are not yet sufficient to describe LedgerOne as UK VAT/MTD-compliant software;
8. invoice numbering, idempotency, bank reconciliation and enterprise segregation-of-duties controls need further strengthening.

The recommendation is **not** to redesign the accounting architecture. The existing central `LedgerService` and module boundaries are appropriate. The priority should instead be an **Accounting Assurance remediation phase** that hardens the control environment around the existing ledger before significant new functional scope is added.

---

## 2. Scope

The review covered the accounting and control behaviour of the current LedgerOne implementation, with particular attention to:

- chart of accounts;
- double-entry journal posting;
- journal immutability and reversals;
- accounting periods and period locking;
- opening balances and recurring journals;
- sales invoices, receipts and allocations;
- purchase bills, payments and allocations;
- credit notes;
- banking and reconciliation;
- VAT/tax configuration and VAT return logic;
- expense claims;
- source documents and audit evidence;
- financial reporting;
- API authentication and authorisation;
- local AI accounting tools;
- database constraints, migrations and CI tests;
- separation between the general ledger and operational subledgers.

The audit was a **code and accounting-control design review**. It was not a statutory financial-statement audit, penetration test, HMRC software accreditation, legal opinion, or certification of production readiness.

---

## 3. Audit criteria

The implementation was assessed against commonly accepted accounting-system principles and control expectations, including:

- double-entry bookkeeping integrity;
- transaction completeness and accuracy;
- control-account and subledger reconciliation principles;
- period cut-off and close controls;
- immutable posted accounting records and correction by reversal/credit;
- separation of duties and least privilege;
- audit trail completeness and provenance;
- reliable period-based financial reporting;
- defensible API/integration posting controls;
- UK VAT invoice and digital-record requirements where LedgerOne provides UK VAT functionality.

Relevant official UK references include:

- HMRC VAT Notice 700, including VAT invoice requirements:  
  https://www.gov.uk/guidance/vat-guide-notice-700
- VAT Notice 700/21, VAT record keeping:  
  https://www.gov.uk/guidance/record-keeping-for-vat-notice-70021
- VAT Notice 700/22, Making Tax Digital for VAT:  
  https://www.gov.uk/government/publications/vat-notice-70022-making-tax-digital-for-vat/vat-notice-70022-making-tax-digital-for-vat
- GOV.UK VAT record-keeping guidance:  
  https://www.gov.uk/charge-reclaim-record-vat/keeping-vat-records

---

## 4. Overall assessment

| Area | Rating | Audit view |
|---|---:|---|
| Core double-entry ledger | **8/10** | Strong foundation; balanced posting and immutability controls are good. |
| Day-to-day bookkeeping controls | **6/10** | Functional but requires tighter control-account, document and period discipline. |
| UK VAT / compliance readiness | **4/10** | Useful initial implementation but not yet sufficient for a compliance claim. |
| Enterprise accounting controls | **3/10** | Approval, SoD, FX, close governance and integration controls remain incomplete. |
| Architecture / extensibility | **8/10** | Central ledger service and modular boundaries are appropriate. |

### Audit opinion

**LedgerOne should not yet be approved for unrestricted production business accounting or enterprise accounting.**

It may continue to be used for development, testing and controlled single-currency scenarios while the Critical and High findings are remediated.

---

## 5. Positive controls observed

### 5.1 Double-entry integrity

The posting service validates each journal line and:

- requires at least two lines for a normal journal;
- quantises monetary values to two decimal places;
- rejects negative debit and credit values;
- rejects a line containing both a debit and a credit;
- rejects empty lines;
- rejects unbalanced journals;
- rejects a balanced zero-value journal;
- verifies that accounts belong to the current organisation;
- rejects inactive accounts.

Evidence: [`ledgerone/services/ledger.py`](../../ledgerone/services/ledger.py)

This is a good implementation of the fundamental accounting invariant that total debits must equal total credits.

### 5.2 Posted journal immutability

`Journal` and `JournalLine` use SQLAlchemy mutation hooks to reject updates and deletes once persistent. Corrections are performed through reversal journals rather than editing the original accounting record.

Evidence: [`ledgerone/models/ledger.py`](../../ledgerone/models/ledger.py)

This is appropriate accounting practice.

### 5.3 Reversal accounting

The reversal workflow:

- prevents reversal of non-posted journals;
- prevents a reversal journal being reversed through the same workflow;
- prevents duplicate reversal of the same original journal;
- swaps debits and credits;
- preserves dimensions and links back to the original journal.

Evidence: [`ledgerone/services/ledger.py`](../../ledgerone/services/ledger.py)

### 5.4 Sales and purchase double-entry

The simple sales invoice flow posts:

- Dr Accounts Receivable — gross;
- Cr Revenue — net;
- Cr Output VAT — VAT.

The purchase bill flow posts:

- Dr Expense — net;
- Dr Input VAT — VAT;
- Cr Accounts Payable — gross.

Evidence:

- [`ledgerone/modules/sales/services.py`](../../ledgerone/modules/sales/services.py)
- [`ledgerone/modules/purchases/services.py`](../../ledgerone/modules/purchases/services.py)

These are correct basic accounting treatments for the implemented scenarios.

### 5.5 Payment allocations

Customer and supplier allocations are constrained so that allocations cannot exceed the available payment or the outstanding document amount and must belong to the correct counterparty.

Evidence:

- [`ledgerone/modules/sales/services.py`](../../ledgerone/modules/sales/services.py)
- [`ledgerone/modules/purchases/services.py`](../../ledgerone/modules/purchases/services.py)

### 5.6 Evidence and provenance

Source documents store metadata including SHA-256 hashes, ownership and accounting-object linkage. The current audited commit also contains a transaction audit-trace service that can trace from business document through journal and ledger accounts to supporting evidence and audit events.

Evidence:

- [`ledgerone/modules/documents/services.py`](../../ledgerone/modules/documents/services.py)
- [`ledgerone/services/audit_trace.py`](../../ledgerone/services/audit_trace.py)

This is a strong basis for accounting provenance.

### 5.7 CI and migration controls

The repository CI:

- compiles Python source;
- upgrades a clean database using Alembic;
- runs migration drift checking;
- executes the pytest suite.

Evidence: [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml)

The CI run for the audited baseline completed successfully.

---

# 6. Findings

## LO-AUD-001 — AI accounting actions can bypass the requesting user's permissions

**Severity:** CRITICAL  
**Status:** OPEN  
**Risk domain:** Authorisation / fraud / segregation of duties

### Observation

The local AI chat receives the requesting user's ID but creates an `AccessContext.system(organisation_id)` for tool execution. `AccessContext.system()` is full access with `*` permission.

As a result, a user who is allowed to use the AI workspace can potentially cause an AI write tool to perform an accounting operation that the user would not be authorised to execute directly.

Evidence:

- [`ledgerone/modules/ai/services.py`](../../ledgerone/modules/ai/services.py)
- [`ledgerone/services/context.py`](../../ledgerone/services/context.py)
- [`ledgerone/modules/ai/routes.py`](../../ledgerone/modules/ai/routes.py)
- [`ledgerone/modules/ai/api.py`](../../ledgerone/modules/ai/api.py)

### Risk

This violates least privilege and segregation-of-duties principles. In a production accounting environment it could permit unauthorised journal, invoice, bill or master-data changes.

### Recommendation

AI must execute using the **effective permission context of the requesting identity**. The AI configuration may further restrict that context, but must never expand it.

For consequential accounting writes, add an explicit approval/confirmation policy, ideally supporting organisation-level rules such as:

- read-only AI;
- prepare/draft only;
- post up to an approval threshold;
- require approval for all journals;
- prohibit control-account or period-close operations;
- prohibit self-approval.

### Acceptance criteria

- A user without `ledger.journals.post` cannot cause AI to post a journal.
- A user without `sales.write` cannot cause AI to create/post a sales invoice.
- A user without `purchases.write` cannot cause AI to create/post a purchase bill.
- API-key AI users are restricted by the API key's permissions.
- Automated tests prove both allowed and denied AI operations.

---

## LO-AUD-002 — Foreign-currency transactions can be posted without base-currency translation

**Severity:** CRITICAL  
**Status:** OPEN  
**Risk domain:** Financial-statement accuracy / currency accounting

### Observation

LedgerOne stores a three-character currency on organisations, accounts, invoices, bills and journal lines. Sales and purchases accept a currency and then post the document amounts directly as general-ledger debit/credit values.

Although `JournalLine` includes `currency` and `foreign_amount`, there is no complete exchange-rate/base-amount model in the current accounting flow.

Evidence:

- [`ledgerone/models/core.py`](../../ledgerone/models/core.py)
- [`ledgerone/models/ledger.py`](../../ledgerone/models/ledger.py)
- [`ledgerone/modules/sales/services.py`](../../ledgerone/modules/sales/services.py)
- [`ledgerone/modules/purchases/services.py`](../../ledgerone/modules/purchases/services.py)

### Risk

A USD 1,000 invoice can effectively become GBP 1,000 in a GBP ledger. The journal still balances, but the financial statements are materially wrong.

### Recommendation

Until full multi-currency accounting is implemented, **hard-restrict all accounting documents and journals to the organisation's base currency**.

Future multi-currency support should explicitly store:

- transaction currency;
- transaction amount;
- exchange rate and rate source/date;
- base-currency debit/credit;
- settlement exchange differences;
- period-end revaluation;
- realised/unrealised FX gains and losses.

### Acceptance criteria

- A GBP organisation rejects USD/EUR financial postings until the multi-currency feature is enabled.
- Journal reporting is always in a defined base currency.
- Regression tests demonstrate rejection of non-base-currency posting.

---

## LO-AUD-003 — Control accounts are not protected from direct posting

**Severity:** HIGH  
**Status:** OPEN  
**Risk domain:** Subledger integrity / reconciliation

### Observation

The model contains `Account.is_control_account`, and seeded functionality creates or uses Accounts Receivable, Accounts Payable, VAT and employee reimbursement accounts. However, the central ledger posting service does not prohibit ordinary direct journals to a control account.

Banking can also create offset postings to an arbitrary valid ledger account.

Evidence:

- [`ledgerone/models/ledger.py`](../../ledgerone/models/ledger.py)
- [`ledgerone/services/ledger.py`](../../ledgerone/services/ledger.py)
- [`ledgerone/modules/banking/services.py`](../../ledgerone/modules/banking/services.py)
- [`ledgerone/modules/tax/services.py`](../../ledgerone/modules/tax/services.py)
- [`ledgerone/modules/expense_claims/services.py`](../../ledgerone/modules/expense_claims/services.py)

### Risk

The Accounts Receivable general-ledger balance can differ from customer outstanding balances while the trial balance remains perfectly balanced. The same risk exists for AP, VAT and other control accounts.

This is a serious accounting-system control weakness.

### Recommendation

Create an explicit control-account framework. At minimum:

- mark AR/AP/VAT/reimbursement control accounts as control accounts;
- associate each control account with an owning module/control type;
- reject ordinary manual/API/AI postings to control accounts;
- permit posting only from authorised module workflows;
- provide a controlled adjustment permission/process for exceptional corrections;
- create reconciliation reports comparing GL control account balances to the corresponding subledger.

### Acceptance criteria

- Direct journal to AR/AP/VAT control account is rejected.
- Sales module can post to AR and output VAT.
- Purchases module can post to AP and input VAT.
- Dedicated reconciliation reports prove subledger total = GL control account.

---

## LO-AUD-004 — Financial reports are not sufficiently period-aware

**Severity:** HIGH  
**Status:** OPEN  
**Risk domain:** Financial reporting

### Observation

`trial_balance()` aggregates posted journal lines without an `as_of` date. The report summary then derives assets, liabilities, equity, income and expenses from the all-time trial balance.

Evidence:

- [`ledgerone/services/ledger.py`](../../ledgerone/services/ledger.py)
- [`ledgerone/modules/reports/services.py`](../../ledgerone/modules/reports/services.py)

### Risk

Professional accounting requires financial reports to be anchored to a period or date. Without that:

- a P&L cannot reliably represent a month/year;
- a balance sheet cannot reliably represent a reporting date;
- prior-period comparative reporting is not reliable;
- year-end/current earnings presentation is incomplete.

### Recommendation

Implement at minimum:

- Trial Balance **as at date** and optionally period movement;
- Profit & Loss **from/to date**;
- Balance Sheet **as at date**;
- General Ledger account activity **from/to** with brought-forward and carried-forward balances;
- current-year earnings/retained earnings treatment;
- comparative period support.

### Acceptance criteria

Automated tests create transactions before, inside and after a reporting period and verify correct TB/P&L/Balance Sheet inclusion.

---

## LO-AUD-005 — Accounting-period controls are bypassed when no period exists

**Severity:** HIGH  
**Status:** OPEN  
**Risk domain:** Cut-off / close governance

### Observation

Posting-date validation searches for a period containing the date whose status is `locked`. If no accounting period exists for that date, the posting is allowed.

Evidence: [`ledgerone/services/ledger.py`](../../ledgerone/services/ledger.py)

### Risk

A user can post outside the configured accounting calendar or into a date that finance did not intend to be open.

### Recommendation

For professional/business mode:

- require every posting date to belong to exactly one valid accounting period;
- distinguish `open`, `soft_closed` and `hard_closed` states;
- allow soft-close overrides only with a dedicated permission and audit reason;
- require higher privilege and reason to reopen a hard-closed period;
- optionally support adjustment periods.

Home/personal mode can retain a simplified policy if desired, but the accounting kernel should expose an explicit period policy rather than implicitly allowing gaps.

### Acceptance criteria

- Posting outside all configured periods is rejected under professional policy.
- Hard-closed period cannot be posted to through UI, API, module, recurring journal or AI.
- Reopen events are fully audited.

---

## LO-AUD-006 — Sales invoice output is not yet a complete UK VAT invoice

**Severity:** HIGH  
**Status:** OPEN  
**Risk domain:** UK VAT invoicing / statutory records

### Observation

The PDF service includes useful commercial information such as organisation name, invoice number/date, customer details, line amounts and tax totals. However, the current organisation model/PDF path does not reliably include all information required for a full UK VAT invoice, including the supplier's registered address and VAT registration number and a separate tax point/issue date where appropriate.

Evidence:

- [`ledgerone/services/pdf_documents.py`](../../ledgerone/services/pdf_documents.py)
- [`ledgerone/models/core.py`](../../ledgerone/models/core.py)
- [`ledgerone/modules/tax/models.py`](../../ledgerone/modules/tax/models.py)

### Risk

A LedgerOne invoice could be commercially useful but not meet all requirements of a VAT invoice.

### Recommendation

Extend the organisation/legal-entity and invoice models so the generated invoice can include all required fields, including:

- sequential unique invoice number;
- supplier legal/trading name as applicable;
- supplier registered/principal address;
- VAT registration number;
- customer name and address;
- time of supply/tax point;
- invoice issue date where different;
- sufficient description;
- quantity/extent of service;
- unit price;
- net value;
- VAT rate;
- gross value;
- total VAT expressed in sterling where required.

Reference: HMRC VAT Notice 700 section 16.3.1.

### Acceptance criteria

A VAT-invoice compliance test fixture renders a sample standard-rated invoice and verifies every required field.

---

## LO-AUD-007 — VAT return model needs tax-point, adjustment and MTD controls

**Severity:** HIGH  
**Status:** OPEN  
**Risk domain:** VAT reporting / MTD

### Observation

The current VAT-return implementation is intentionally limited to GB standard VAT accounting. It derives source documents primarily by sales invoice date, purchase bill date and credit-note date.

Evidence: [`ledgerone/modules/tax/services.py`](../../ledgerone/modules/tax/services.py)

The tax profile contains scheme and frequency but the system does not yet implement a complete VAT-return lifecycle or HMRC MTD submission/audit model.

### Risk

Invoice date and VAT tax point are not always interchangeable. VAT adjustments, reverse-charge/import scenarios, partial exemption and other cases are also outside the current implementation.

### Recommendation

Add:

- explicit VAT tax-point fields;
- VAT return periods with draft/final/submitted states;
- locking of transactions to a submitted VAT return where required;
- VAT adjustments with reason/evidence;
- supported reverse-charge/import treatment before claiming such support;
- digital links/MTD submission integration if LedgerOne is to submit returns;
- immutable submission payload and HMRC receipt/correlation evidence.

### Acceptance criteria

- VAT report uses tax point rather than assuming document date.
- Finalised return can be reproduced exactly from retained source data.
- Adjustments are separately identified and audited.

---

## LO-AUD-008 — Posted sales/purchase documents are not protected as strongly as posted journals

**Severity:** HIGH  
**Status:** OPEN  
**Risk domain:** Record integrity / audit trail

### Observation

Posted journals and journal lines are protected by mutation listeners. Equivalent model-level protection is not evident for posted sales invoices, invoice lines, purchase bills and bill lines.

Evidence:

- [`ledgerone/models/ledger.py`](../../ledgerone/models/ledger.py)
- [`ledgerone/modules/sales/models.py`](../../ledgerone/modules/sales/models.py)
- [`ledgerone/modules/purchases/models.py`](../../ledgerone/modules/purchases/models.py)

### Risk

If a posted business document is changed without a matching journal change, the subledger/document may no longer agree with the immutable general ledger.

### Recommendation

Once a financial document is issued/posted:

- protect accounting-relevant fields against mutation;
- prevent deletion;
- use credit note/reversal/cancellation documents for correction;
- retain original document numbers and evidence;
- permit only explicitly non-financial metadata changes where justified.

### Acceptance criteria

Tests directly attempt ORM updates/deletes on posted invoice/bill headers and lines and confirm rejection.

---

## LO-AUD-009 — Invoice and credit-note numbering needs controlled sequences

**Severity:** MEDIUM-HIGH  
**Status:** OPEN  
**Risk domain:** Completeness / statutory invoicing / duplicate prevention

### Observation

Sales invoice numbers are user-supplied and uniqueness is enforced within an organisation. The roadmap already identifies configurable numbering sequences as future work.

Evidence:

- [`ledgerone/modules/sales/models.py`](../../ledgerone/modules/sales/models.py)
- [`ledgerone/modules/sales/services.py`](../../ledgerone/modules/sales/services.py)
- [`docs/ROADMAP.md`](../../docs/ROADMAP.md)

### Risk

Manual numbering can produce gaps, inconsistent series or weak completeness evidence.

### Recommendation

Implement configurable, concurrency-safe numbering sequences with:

- one or more document series;
- prefix/suffix/year rules where configured;
- immutable assigned number;
- gap detection/reporting;
- cancellation/void record rather than reuse;
- separate document-type sequences as appropriate.

### Acceptance criteria

Concurrent document creation cannot produce duplicate numbers and used numbers cannot be reused.

---

## LO-AUD-010 — Audit events are not yet tamper-evident

**Severity:** MEDIUM-HIGH  
**Status:** OPEN  
**Risk domain:** Audit trail / forensic integrity

### Observation

The audit-event model records actor, module, action, entity, detail and timestamp, which is useful. However, there is no equivalent immutability listener/database rule/hash-chain control evident on the audit-event table itself.

Evidence: [`ledgerone/models/audit.py`](../../ledgerone/models/audit.py)

### Risk

A sufficiently privileged database/application path could alter or delete historical audit events without detection.

### Recommendation

Use layered controls:

- application-level update/delete prohibition;
- restricted DB permissions in production;
- append-only semantics;
- optional hash chaining or signed checkpoints for tamper evidence;
- backup/retention controls;
- audit of audit-export/admin activity.

### Acceptance criteria

Ordinary application services cannot update/delete an `AuditEvent`, and a tamper-detection verification test is available if hash chaining is implemented.

---

## LO-AUD-011 — Credit-note workflow cannot adequately handle all paid-invoice credits/refunds

**Severity:** MEDIUM  
**Status:** OPEN  
**Risk domain:** Accounts receivable / customer credits

### Observation

Sales credit-note value is constrained by the invoice's current outstanding amount.

Evidence: [`ledgerone/modules/sales/credits.py`](../../ledgerone/modules/sales/credits.py)

### Risk

A genuine credit may be required after an invoice has already been fully paid. Restricting the credit to unpaid balance prevents a normal customer-credit/refund scenario.

### Recommendation

Separate the concept of:

- invoice original value;
- amounts paid;
- credits applied;
- customer unallocated credit;
- refund paid.

Allow a valid credit note against a paid invoice, resulting in a customer credit balance which can then be refunded or allocated to another invoice.

### Acceptance criteria

Test: fully paid invoice -> credit note -> customer credit balance -> refund or allocation.

---

## LO-AUD-012 — Account types and posting roles need stronger validation

**Severity:** MEDIUM  
**Status:** OPEN  
**Risk domain:** Classification / posting accuracy

### Observation

`Account.account_type` is a free string. Account creation normalises text but does not restrict it to an accounting enum. Sales and purchases validate organisation ownership of account IDs through the ledger, but do not comprehensively prove that the selected accounts are appropriate for their roles.

Evidence:

- [`ledgerone/models/ledger.py`](../../ledgerone/models/ledger.py)
- [`ledgerone/services/ledger.py`](../../ledgerone/services/ledger.py)
- [`ledgerone/modules/sales/services.py`](../../ledgerone/modules/sales/services.py)
- [`ledgerone/modules/purchases/services.py`](../../ledgerone/modules/purchases/services.py)

### Risk

A user could classify accounts inconsistently or configure a sales invoice to post to an inappropriate account while still producing a balanced journal.

### Recommendation

- define supported account-type enum/check constraint;
- add account subtype/role where appropriate;
- centrally configure default AR/AP/bank/VAT/retained-earnings accounts;
- validate module posting roles;
- provide controlled overrides only where accounting logic supports them.

### Acceptance criteria

Invalid account type is rejected and module workflows reject obviously incompatible posting accounts.

---

## LO-AUD-013 — Integration/API posting requires idempotency protection

**Severity:** MEDIUM  
**Status:** OPEN  
**Risk domain:** Completeness / duplicate postings

### Observation

Journals contain `source_module` and `source_reference`, but there is no general strong uniqueness/idempotency guarantee evident for integration retries.

Evidence:

- [`ledgerone/models/ledger.py`](../../ledgerone/models/ledger.py)
- [`ledgerone/modules/ledger/api.py`](../../ledgerone/modules/ledger/api.py)

### Risk

An external system retry or network timeout can result in the same logical transaction being posted twice.

### Recommendation

Add an explicit idempotency model/API contract. Consider:

- `Idempotency-Key` support;
- source-system + source-document unique keys where appropriate;
- safe replay returning the original result rather than creating a second transaction;
- conflict handling if the same key is submitted with different payload data.

### Acceptance criteria

Submitting an identical posting twice with the same idempotency key creates one accounting transaction only.

---

## LO-AUD-014 — Bank reconciliation is transaction matching rather than full statement reconciliation

**Severity:** MEDIUM  
**Status:** OPEN  
**Risk domain:** Cash / reconciliation

### Observation

The current banking service supports matching imported bank transactions to posted journals and can create/post an offset journal when reconciling.

Evidence: [`ledgerone/modules/banking/services.py`](../../ledgerone/modules/banking/services.py)

This is useful, but it does not yet represent a full formal bank-statement reconciliation proving a statement balance to the ledger balance at a cut-off date.

### Risk

Finance may not have a retained reconciliation demonstrating:

`statement closing balance +/- outstanding items = ledger balance`

### Recommendation

Add a reconciliation entity containing:

- bank account;
- statement start/end date;
- statement opening balance;
- statement closing balance;
- ledger balance at cut-off;
- matched/unmatched transactions;
- outstanding receipts/payments;
- reconciliation difference;
- prepared-by / approved-by / timestamps;
- finalised/locked status;
- retained reconciliation report.

### Acceptance criteria

A finalised reconciliation produces zero unexplained difference and is reproducible later.

---

## LO-AUD-015 — Enterprise segregation-of-duties controls are incomplete

**Severity:** MEDIUM  
**Status:** OPEN  
**Risk domain:** Governance / fraud prevention

### Observation

LedgerOne already has granular permissions and the expense-claim workflow separates submit and approve permissions. The roadmap correctly places formal approval workflows and segregation-of-duties rules in later enterprise scope.

Evidence:

- [`ledgerone/modules/expense_claims/services.py`](../../ledgerone/modules/expense_claims/services.py)
- [`docs/ROADMAP.md`](../../docs/ROADMAP.md)

### Risk

For enterprise use, a user may be able to create and approve/post financially significant transactions without independent review.

### Recommendation

Implement configurable maker/checker controls including:

- no self-approval where configured;
- approval thresholds;
- journal approval;
- supplier/customer master changes;
- bank/payment approval;
- period reopen approval;
- control-account adjustment approval;
- AI-generated write approval policy.

### Acceptance criteria

Tests demonstrate that a preparer cannot approve their own transaction where maker/checker is enabled.

---

# 7. Recommended remediation order

The remediation should be treated as a dedicated **Accounting Assurance** programme rather than scattered feature work.

### Gate A — Release blockers

Complete before allowing unrestricted production accounting:

1. `LO-AUD-001` — AI permission inheritance.
2. `LO-AUD-002` — base-currency restriction / FX safety.
3. `LO-AUD-003` — control-account protection and reconciliation.
4. `LO-AUD-005` — mandatory period policy.
5. `LO-AUD-008` — posted business-document immutability.

### Gate B — Professional bookkeeping readiness

6. `LO-AUD-004` — proper period/as-of financial reports.
7. `LO-AUD-009` — controlled document numbering.
8. `LO-AUD-012` — account type/posting-role validation.
9. `LO-AUD-013` — API idempotency.
10. `LO-AUD-014` — formal bank reconciliation.

### Gate C — UK VAT readiness

11. `LO-AUD-006` — VAT invoice content.
12. `LO-AUD-007` — tax point, VAT-period and adjustment model.
13. Extend to HMRC MTD submission only after the accounting records and return lifecycle are robust.

### Gate D — Enterprise readiness

14. `LO-AUD-010` — tamper-evident audit trail.
15. `LO-AUD-015` — maker/checker and formal SoD.
16. Full multi-currency/revaluation rather than lifting the temporary base-currency restriction.

---

# 8. Test strategy recommendation

Each audit finding should be closed with a regression test proving the accounting invariant, not merely a UI change.

Priority invariants should include:

- every posted journal balances;
- no zero-value journal;
- posted journals cannot be changed/deleted;
- posted source documents cannot be changed/deleted;
- every posting is in a permitted accounting period;
- control accounts can only be changed through authorised workflows;
- AR GL = customer subledger total;
- AP GL = supplier subledger total;
- VAT GL = VAT transaction detail subject to timing/adjustments;
- base currency is enforced until FX support exists;
- AI cannot exceed user permissions;
- duplicate integration request cannot duplicate a posting;
- period reports exclude transactions outside the requested date range;
- a finalised reconciliation proves bank statement to GL;
- every privileged override/reopen/approval is auditable.

---

# 9. Audit conclusion

LedgerOne is **not an accounting-engine rewrite candidate**. The central posting architecture is the right design and should be retained.

The repository already demonstrates several strong engineering/accounting practices:

- one accounting kernel;
- module separation;
- immutable posted journal records;
- reversals rather than edits;
- balanced posting enforcement;
- organisation isolation;
- source-document provenance;
- migration-controlled schema;
- automated CI and accounting workflow tests.

The next maturity step is to strengthen the **control environment around the ledger** so that a transaction is not only mathematically balanced but also:

- authorised;
- posted to the correct period;
- posted to the correct account role;
- linked to the appropriate subledger;
- represented in the correct currency;
- supported by immutable source evidence;
- reported in the correct accounting period;
- VAT-treated correctly where applicable;
- protected against duplicate posting;
- independently approvable and auditable.

Subject to remediation of the Critical and High findings, LedgerOne has a credible path from its current development state to a robust SME accounting platform and, subsequently, an enterprise-capable accounting architecture.

---

## 10. Follow-up and closure

The authoritative remediation list for this audit is maintained in:

[ACTION_REGISTER.md](./ACTION_REGISTER.md)

Each item should retain its original finding ID. A finding should move to `READY FOR RETEST` only after implementation and automated tests are committed. It should move to `CLOSED` only after an independent retest confirms the acceptance criteria against a recorded commit SHA.
