# LedgerOne Roadmap

LedgerOne starts with a production-shaped accounting kernel and modular boundaries, then grows outward without replacing the core ledger.

## v0.1 — Foundation

Status: **complete**

- Flask application factory and modular registry
- multi-organisation users/memberships
- Home / Apprentice and Professional UI modes
- chart of accounts
- double-entry journals and trial balance
- Banking module
- Sales/customers/invoices module
- Purchases/suppliers/bills module
- Reports module
- Settings/module administration
- versioned REST APIs
- hashed service/API keys
- local AI workspace with audited tool access
- per-organisation local AI settings with Ollama model discovery
- SQLite and PostgreSQL configuration
- CashLink legacy recovery/import tooling
- Flask-Migrate baseline
- CI and smoke tests

## v0.2 — Accounting controls

Status: **complete**

- accounting periods and period locking
- journal reversal workflow
- immutable posted journals and journal lines
- opening-balance wizard
- recurring journals
- organisation-level AI connection/model/write-safety settings
- bank reconciliation workflow
- customer/supplier payment allocation with partial settlement
- adoption of existing bank/reconciliation journals without duplicate cash posting
- outstanding receivable/payable balances
- audit viewer, filters, API and CSV export
- broader audit coverage across ledger, sales, purchases, banking, settings and AI configuration
- source-document files and external evidence references
- record-level document links for journals, invoices, bills and bank transactions
- organisation member/role/permission administration
- last-owner and self-deactivation safeguards
- API key expiry, last-used visibility, rotation and revocation
- SQLite/PostgreSQL-safe API key expiry validation
- pagination and filtering on ledger account/journal APIs

## v0.3 — Tax and day-to-day business

Status: **in progress**

- VAT/tax codes and tax accounts — implemented
- UK VAT return support as first tax implementation — implemented for GB standard VAT accounting
- credit notes — implemented for sales and purchases
- sales quotes leading to invoices — implemented
- sales orders leading to invoices — implemented
- purchase orders leading to bills — implemented
- expense claims — implemented
- payment terms and aged receivables/payables — implemented
- invoice/bill PDF output
- configurable numbering sequences
- contact/address improvements

## v0.4 — Bank and document automation

- CSV/OFX/QIF bank import adapters
- Open Banking connector abstraction
- reconciliation suggestions
- receipt/invoice document ingestion
- OCR/document extraction adapter
- AI-assisted coding suggestions with approval
- duplicate-document detection
- rules engine for recurring merchants/payees

## v0.5 — Projects, jobs and costing

- Projects/Jobs module
- cost centres and departments
- reusable accounting dimensions
- budgets by dimension
- project profitability
- job-cost transactions
- timesheet/cost allocation interfaces
- migration path for CashLink Job Cost data

## v0.6 — Fixed assets and inventory

- Fixed Assets module
- asset classes and depreciation books
- acquisition/disposal/depreciation posting
- Inventory module
- stock items and locations
- stock movements
- valuation method abstraction
- purchase/sales integration

## v0.7 — Payroll and workforce integration

- Payroll module boundary
- employees and pay runs
- earnings/deductions definitions
- payroll journal generation
- external payroll import/API adapters
- UK-specific statutory processing only after compliance design/review

## v0.8 — Enterprise capabilities

- formal role-based access control administration
- approval workflows
- segregation-of-duties rules
- multi-currency transactions and revaluation
- intercompany accounts and journals
- consolidated reporting
- entity hierarchies
- high-volume import/batch jobs
- background workers/queues
- webhooks and integration event log
- SSO/OIDC/SAML integration layer
- PostgreSQL-first deployment profile

## v0.9 — Analytics and AI

- natural-language report generation
- anomaly detection
- cash-flow forecasting
- collections/payment prioritisation
- budget variance explanations
- explainable coding/reconciliation suggestions
- AI approval policies by tool/action/risk
- organisation-specific knowledge/RAG sources
- optional local-model profiles per organisation

## v1.0 — Stable platform

Target criteria rather than a date:

- migration-safe release process
- stable public API contract
- documented module SDK/contract
- full audit and accounting-period controls
- backup/restore documentation and tests
- PostgreSQL production reference deployment
- security review and dependency scanning
- robust test coverage for financial invariants
- upgrade testing from previous releases
- disaster-recovery procedure
- user/admin documentation

## Engineering principles throughout the roadmap

1. New capabilities should be modules unless they are genuinely part of the accounting/security kernel.
2. All financial postings continue to use the same double-entry ledger service.
3. APIs and AI use the same service-layer rules as the browser UI.
4. Enterprise features extend organisation, permission, dimension and workflow models rather than creating a second product.
5. Home / Apprentice mode remains approachable by presentation and guided workflows, not by weakening accounting integrity.
6. Every schema change is migration-controlled and every consequential action should become auditable.
