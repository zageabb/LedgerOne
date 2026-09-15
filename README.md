# LedgerOne

LedgerOne is a modular Flask/Python accounting platform designed to scale from personal and household accounting through apprentice/small-business use to multi-organisation enterprise accounting.

## Design principles

- **One accounting kernel** — double-entry journals are the source of truth at every scale.
- **Standalone modules** — each business capability is a Flask Blueprint with its own manifest, routes, API, permissions, services, templates and optional models.
- **Two user experiences** — switch between **Home / Apprentice** and **Professional** UI without changing the underlying ledger.
- **API-first modules** — functional modules expose versioned API routes under `/api/v1/...`.
- **Secure external API** — service-key/session authentication and role/permission checks.
- **Permission-bound local AI** — the built-in AI calls the same service layer under the requesting user/API key's exact access context. AI policy can restrict access further but never expands caller permissions.
- **Organisation-scoped Knowledge** — business manuals, procedures and process guidance can be indexed locally and retrieved only within the owning organisation.
- **Scale-ready persistence** — SQLite is supported for easy local deployment; PostgreSQL can be selected through `DATABASE_URL` for larger installations.
- **Migration-controlled production schema** — Flask-Migrate/Alembic is the production upgrade path.

## Current modules

- Core platform / dashboard
- Identity, authentication, organisations, memberships and role/permission administration
- Ledger / chart of accounts / immutable journals / periods / opening balances / recurring journals
- Banking / bank accounts / imported transactions / reconciliation
- Sales / customers / invoices / customer payments and allocations
- Purchases / suppliers / bills / supplier payments and allocations
- Reports
- Audit Trail with filters, API and CSV export
- Source Documents with file uploads, hashes and external evidence references
- Settings / module controls / API key expiry, rotation and revocation
- LedgerOne AI chat workspace with persistent conversations, caller-scoped audited tools and organisation Knowledge
- API authentication and discovery

Banking, Sales and Purchases own their own domain records but do not create a parallel accounting engine. Financial effects are posted through the central `LedgerService`.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python run.py
```

Then open `http://127.0.0.1:5000`.

In development, `AUTO_CREATE_SCHEMA=true` gives a zero-setup first run. LedgerOne creates an empty schema and seeds the development administrator and initial chart of accounts from `.env`.

## Default development credentials

Set these in `.env` before first launch:

```dotenv
LEDGERONE_ADMIN_EMAIL=admin@ledgerone.local
LEDGERONE_ADMIN_PASSWORD=change-me-now
```

Do not expose a deployment using the example password.

## Production database setup

Production defaults to `AUTO_CREATE_SCHEMA=false`. Apply migrations before starting the web process:

```bash
export FLASK_ENV=production
flask --app run.py db upgrade
```

After the schema exists, normal startup can seed the initial organisation/admin when `AUTO_SEED_DEFAULTS=true`. For an established installation, manage users/organisations explicitly and set that flag to suit the deployment process.

## Module contract

Modules live under `ledgerone/modules/<module_name>/` and are registered by the module registry. A module normally contains:

```text
module_name/
├── __init__.py
├── manifest.py
├── routes.py
├── api.py
├── services.py
├── permissions.py       # optional
├── models.py            # optional
└── templates/
```

A module manifest declares its identity, navigation, permissions and dependencies. This allows later modules such as Payroll, Assets, Inventory, Projects, VAT/Tax, Expenses and Procurement to be added without modifying the accounting kernel.

See [`docs/MODULE_DEVELOPMENT.md`](docs/MODULE_DEVELOPMENT.md) for the full contract.

## API security

External integrations use service keys in the `Authorization` header:

```http
Authorization: Bearer <service-key>
```

Human browser/API sessions are authenticated separately. Service keys are stored hashed in the database, can be scoped to an organisation/permission set, can have an expiry date and can be rotated without changing their access scope. Revoked or expired keys are rejected automatically.

The built-in local AI does **not** authenticate back into LedgerOne over HTTP. Instead, the browser session or API key's resolved `AccessContext` is passed into the AI service and every tool is filtered and executed under that exact context. A user with `ai.use` but without `sales.write`, `purchases.write` or `ledger.journals.post` cannot gain those permissions through the AI.

Organisation-level `LOCAL_AI_ALLOW_WRITES` is only an upper bound. A write-capable AI request also needs explicit per-message approval and the caller must already hold the underlying module permission. Tool calls retain requester identity in the audit trail.

## Example API endpoints

```text
GET  /api/v1/system/health
GET  /api/v1/system/modules
GET  /api/v1/ledger/accounts?q=bank&account_type=asset&page=1&per_page=50
POST /api/v1/ledger/accounts
GET  /api/v1/ledger/journals?source_module=sales&from_date=2026-09-01
POST /api/v1/ledger/journals
GET  /api/v1/ledger/trial-balance
GET  /api/v1/banking/accounts
GET  /api/v1/banking/transactions
GET  /api/v1/sales/invoices
GET  /api/v1/purchases/bills
GET  /api/v1/audit
GET  /api/v1/audit/export
GET  /api/v1/documents
POST /api/v1/documents/upload
POST /api/v1/documents/reference
GET  /api/v1/settings/members
POST /api/v1/settings/api-keys/<key-id>/rotate
GET  /api/v1/ai/status
GET  /api/v1/ai/conversations
POST /api/v1/ai/chat
GET  /api/v1/ai/knowledge
POST /api/v1/ai/knowledge
```

## Local AI

The local AI endpoint is Ollama-compatible by default:

```dotenv
LOCAL_AI_ENABLED=true
LOCAL_AI_BASE_URL=http://127.0.0.1:11434
LOCAL_AI_MODEL=qwen3:14b
LOCAL_AI_ALLOW_WRITES=true
LEDGERONE_KNOWLEDGE_MAX_BYTES=10485760
```

These defaults can be overridden per organisation from **Settings → LedgerOne AI** without restarting Flask. The model list is discovered from the configured Ollama-compatible server.

The AI workspace keeps conversations in a left-hand history panel, uses a scrollable central message pane, and keeps the prompt composer at the bottom. Previous pre-conversation browser interactions are adopted into one-message conversations for the same signed-in user.

When AI writes are disabled, write tools are removed from the tool registry. When writes are enabled, they are still hidden unless the current message explicitly approves writes, and the caller must hold each tool's required permission.

## Organisation Knowledge

The AI Knowledge workspace can store organisation-specific manuals, procedures, process notes, policies, FAQs and similar guidance. Supported source types include plain text/Markdown/CSV/JSON/YAML plus PDF and DOCX.

Knowledge is:

- isolated by organisation;
- searchable/browsable independently of the AI chat;
- chunked locally into compact retrieval passages;
- retrieved locally before a prompt is sent to the configured local model;
- permission-controlled through `ai.knowledge.read` and `ai.knowledge.manage`;
- auditable for create, re-index, enable/disable and delete actions;
- source-attributed in AI answers/tooling metadata.

The initial retrieval implementation uses deterministic local lexical ranking. This is deliberately lightweight for small/offline deployments and can later be extended with local embeddings without changing the organisation/security boundary.

LedgerOne service data and accounting controls remain authoritative when narrative Knowledge conflicts with live accounting data or a posting rule.

## Source document storage

Supporting files are stored outside the accounting database. The database stores only metadata, linkage, size and SHA-256 integrity information.

```dotenv
LEDGERONE_DOCUMENT_STORAGE_DIR=./data/documents
LEDGERONE_DOCUMENT_MAX_BYTES=26214400
```

Files and external references can be attached to journals, sales invoices, purchase bills and imported bank transactions. The module validates organisation ownership before creating a link.

## Testing

Install development dependencies and run the suite:

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

The committed tests cover the accounting/security invariants and major workflows, including:

- fresh app/database bootstrap and migration drift;
- login and UI-mode switching;
- API authentication, expiry and key rotation;
- organisation members, role/permission controls and last-owner protection;
- balanced/unbalanced journals and cross-organisation isolation;
- accounting period locks, reversals and immutable postings;
- opening balances and recurring journals;
- Sales/Purchases posting and payment allocations;
- banking reconciliation;
- audit trail and CSV export;
- ledger API pagination/filtering;
- source-document upload/download/reference isolation;
- local AI configuration and read-only tool enforcement;
- AI caller-permission inheritance and per-message write approval;
- persistent AI conversations and requester isolation;
- organisation-isolated Knowledge retrieval and source provenance;
- CashLink legacy importer behaviour.

GitHub Actions compiles the source, upgrades a clean database through every committed Alembic revision, checks for migration drift and runs pytest.

## CashLink legacy migration

LedgerOne includes a standalone recovery component for legacy CashLink Accountant data under `legacy_import/cashlink`.

Current capabilities include:

- reading CashLink UCSD p-System volumes;
- listing/extracting embedded logical files;
- decoding purchase, sales and nominal account masters;
- preserving raw source files and fixed records in SQLite;
- source SHA-256 traceability;
- auditing legacy module-password fields without disclosing them;
- converting confirmed CashLink module passwords directly to modern salted scrypt hashes so users can continue using the same passwords after migration.

Example commands:

```bash
python -m legacy_import.cashlink scan JOURNAL.VOL JOURNAL.BAK
python -m legacy_import.cashlink extract JOURNAL.VOL --out recovered/journal
python -m legacy_import.cashlink export-accounts JOURNAL.VOL --out recovered/csv
python -m legacy_import.cashlink security-audit JOURNAL.VOL JOURNAL.BAK JOURNAL.OLD
python -m legacy_import.cashlink to-sqlite recovered/cashlink.sqlite JOURNAL.VOL JOBCOST.DAT
python -m legacy_import.cashlink to-sqlite recovered/cashlink.sqlite JOURNAL.VOL --migrate-legacy-passwords
```

See [`docs/CASHLINK_FORMAT.md`](docs/CASHLINK_FORMAT.md) for the reverse-engineering notes and confirmed record structures.

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — platform layers, security, persistence and accounting invariants.
- [`docs/MODULE_DEVELOPMENT.md`](docs/MODULE_DEVELOPMENT.md) — standalone module/API/service contract.
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — staged path from the v0.1 foundation to enterprise capabilities.
- [`docs/TODO.md`](docs/TODO.md) — master delivery and accounting-assurance backlog.
- [`docs/CASHLINK_FORMAT.md`](docs/CASHLINK_FORMAT.md) — legacy CashLink reverse-engineering notes.
