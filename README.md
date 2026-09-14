# LedgerOne

LedgerOne is a modular Flask/Python accounting platform designed to scale from personal and household accounting through apprentice/small-business use to multi-organisation enterprise accounting.

## Design principles

- **One accounting kernel** — double-entry journals are the source of truth at every scale.
- **Standalone modules** — each business capability is a Flask Blueprint with its own manifest, routes, API, permissions, services, templates and optional models.
- **Two user experiences** — switch between **Home / Apprentice** and **Professional** UI without changing the underlying ledger.
- **API-first modules** — every functional module exposes versioned API routes under `/api/v1/...`.
- **Secure external API** — password/service-key authentication and role/permission checks.
- **Trusted local AI** — the built-in AI uses the same service layer with a system identity. No unauthenticated HTTP back door is required.
- **Scale-ready persistence** — SQLite is supported for easy local deployment; PostgreSQL can be selected through `DATABASE_URL` for larger installations.

## Initial modules

- Core platform / dashboard
- Identity and authentication
- Organisations and memberships
- Ledger / chart of accounts / journals
- Banking
- Sales
- Purchases
- Settings
- AI workspace
- API authentication and discovery

The Banking, Sales and Purchases modules currently provide clean extension points and API/module shells; all accounting postings should flow into the central Ledger service.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env
python run.py
```

Then open `http://127.0.0.1:5000`.

On the first run LedgerOne creates the database and a development administrator using the values from `.env`.

## Default development credentials

Set these in `.env` before first launch:

```dotenv
LEDGERONE_ADMIN_EMAIL=admin@ledgerone.local
LEDGERONE_ADMIN_PASSWORD=change-me-now
```

Do not expose a deployment using the example password.

## Module contract

Modules live under `ledgerone/modules/<module_name>/` and are registered by the module registry. A module normally contains:

```text
module_name/
├── __init__.py
├── manifest.py
├── routes.py
├── api.py
├── services.py
├── permissions.py
├── models.py          # optional
└── templates/
```

A module manifest declares its identity, navigation, permissions and whether it is enabled by default. This allows later modules such as Payroll, Assets, Inventory, Projects, VAT/Tax, Expenses and Procurement to be added without modifying the accounting kernel.

## API security

External integrations use service keys in the `Authorization` header:

```http
Authorization: Bearer <service-key>
```

Human browser/API sessions are authenticated separately. Service keys are stored hashed in the database.

The built-in local AI does **not** need to authenticate back into LedgerOne over HTTP; it receives a trusted system context and calls the same Python service layer as the API. If an out-of-process local AI is required, create a dedicated full-access service key and restrict the listener/network appropriately.

## Example API endpoints

```text
GET  /api/v1/system/health
GET  /api/v1/system/modules
GET  /api/v1/ledger/accounts
POST /api/v1/ledger/accounts
GET  /api/v1/ledger/journals
POST /api/v1/ledger/journals
GET  /api/v1/banking/accounts
GET  /api/v1/sales/status
GET  /api/v1/purchases/status
GET  /api/v1/settings
GET  /api/v1/ai/status
```

## Roadmap

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), [`docs/MODULE_DEVELOPMENT.md`](docs/MODULE_DEVELOPMENT.md) and [`docs/ROADMAP.md`](docs/ROADMAP.md).
