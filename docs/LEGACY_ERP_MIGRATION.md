# Legacy ERP Migration — reusable import framework (DEV-015)

**Status:** Planned. CashLink is the first source adapter. No direct posting into LedgerOne is implemented by this workstream yet.

## Purpose

Move legacy accounting data into a selected LedgerOne company through a repeatable, audited, **read-only discovery → staging → mapping → reconciliation → approval → controlled import** process. The framework should support future CSV, Excel, SQLite and database-export adapters without rebuilding the import workflow.

## Existing foundations (already implemented)

- `legacy_import/cashlink` scans UCSD p-System block volumes, extracts logical files, exports recovered customer/supplier and nominal account fields to CSV, and preserves raw records plus decoded fields in SQLite.
- `docs/CASHLINK_FORMAT.md` documents confirmed container format, known fixed record sizes, surviving source generations and unresolved fields.
- CashLink module password inspection and optional direct rehashing have their own controls. **Legacy passwords must not be exposed through migration previews or logs.**
- CashLink import tests depend partly on optional binary fixtures; green CI alone does not validate a production migration from these files.

## Phase 1 — Read-only source assessment (NEXT)

1. Identify source data generation(s) and preserve original files unchanged. Record SHA-256 hashes, size, file name, extraction timestamp and selected company. Do not mix 2000/2002/2020/2022 backups without explicit selection.
2. Validate UCSD volume completeness and report truncated or inconsistent files.
3. Decode nominal transactions (`TRANS.NOM`), sales/purchase entries (`TRANS.SALES`, `TRANS.PURCH`) and relationships to account masters. Mark decoded vs uncertain fields; preserve raw bytes and original record identifiers.
4. Produce a staged, read-only SQLite assessment with source lineage and exception lists; no LedgerOne database writes.
5. Produce inventory and sample preview: accounts, customer/supplier masters, transaction dates, currencies, VAT codes, transaction count, debit/credit totals, unmatched references, and suspected duplicates.
6. Build a repeatable CLI assessment report (JSON + CSV/HTML) and deterministic tests with synthetic fixtures. Real legacy fixture validation is a separate acceptance gate.

**Acceptance:** Source files unchanged; every staged record traceable to source volume + logical file + record index; incomplete/unknown fields reported rather than invented; report counts reproducible; no passwords exposed.

## Phase 2 — Company-specific mapping and dry run

1. Choose one LedgerOne company; forbid cross-company identifier mapping and staging leaks.
2. Map nominal codes → chart of accounts and opening-balance dimensions. Map customer and supplier masters; preserve legacy IDs as external references.
3. Decide import cutover date, opening balances vs historical transactions, VAT period treatment, prior payments/outstanding AR/AP, control-account reconciliation and currency policy.
4. Dry-run validation for duplicates, missing mappings, locked periods, unbalanced journals, VAT differences, orphaned transactions and unsupported types.
5. Produce trial balance / control-account / AR-AP aging reconciliation, source-to-target totals and exception sign-off.

**Acceptance:** Nothing posts without a reviewed mapping and reconciliation summary. Differences above tolerances block posting. Old and new records can be cross-referenced.

## Phase 3 — Controlled import

1. Import approved company masters before financial records using the existing accounting services and permissions (do not bypass journal, VAT, period or approval safeguards).
2. Stage imports with immutable batch ID, deterministic idempotency key, source lineage, status and operator history.
3. Maker/checker approval of batch, balanced opening journals, atomic failure behaviour, restart/resume support, audit trail and no duplicate postings on retry.
4. Back up the target database and document a tested recovery/reversal strategy **before** production execution.
5. Confirm post-import trial balance, receivables/payables, VAT and reports against signed-off source figures.

**Acceptance:** Independent approval and a full reconciliation with retained evidence; no partial silent imports; duplicate retries are safe.

## Phase 4 — Generalise adapters

- Common adapter interface: discover sources → decode → canonical staged entities → map → validate → reconcile → import.
- CashLink binary adapter first; CSV/Excel import next; configurable SQLite/database exports after that.
- Versioned templates, source-field lineage and adapter-specific exception reports.

## Phase 5 — CashLink Job Cost integration

- Decode `JOBCOST.DAT` and related entries, confirm projects/jobs and costing transaction structure, map to the v0.5 Projects/Jobs model.
- Reconcile legacy job balances and project totals independently from general-ledger balances.

## Risks and non-goals

- A recoverable raw record is **not necessarily a verified decoded transaction**.
- Historical VAT, currencies, payments, corrections and period closure rules must be signed off by an accounting reviewer.
- Importing old passwords or access roles into modern authorisation is not part of the general import wizard.
- Direct production ingestion from untrusted uploaded binaries is prohibited until scanning, size/type limits, isolation and access controls have been designed and tested.
- Automatic migration of all historic transactions is not promised; opening balances and outstanding items may be the safer approved cutover.

## Development increments

| ID | Increment | Outcome |
| --- | --- | --- |
| ERP-001 | Read-only assessment CLI + decoder coverage | Source inventory, decode confidence, counts, anomalies, source lineage |
| ERP-002 | Canonical staging schema and adapter interface | Reusable format for accounts, contacts, journals and references |
| ERP-003 | Mapping UI / dry-run reconciliation | Preview target codes, balances and blocking exceptions |
| ERP-004 | Approved, auditable and idempotent import batches | Controlled LedgerOne data creation |
| ERP-005 | CashLink Job Cost decoder + Projects mapping | Reconciled historical project data |
| ERP-006 | Generic CSV/Excel/SQLite adapters | Other ERP source systems supported |

## Release gates

- PR CI green, clean migrations, fixture coverage and security checks.
- Live UDA checks and independent accounting reconciliation acceptance before any production posting.
- Keep `DEVELOPMENT.md` and `docs/ROADMAP.md` current as increments close.
