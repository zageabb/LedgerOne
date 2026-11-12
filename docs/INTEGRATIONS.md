# Integration boundaries

LedgerOne's internal modules use shared domain services and versioned `/api/v1/` routes as documented in README and `docs/ARCHITECTURE.md`. External service integrations are opt-in and must not be assumed active.

| Integration | Current documented path | Rule |
|---|---|---|
| Local AI | Ollama-compatible endpoint via environment or organisation settings | Caller-scoped tools, approval for writes, explicit unavailable state |
| Banking | File import / reconciliation | Confirm input data provenance; no Open Banking connectivity claimed |
| CashLink | `legacy_import/cashlink` | Preserve source hashes, audit and format provenance |
| UDA/Caddy | Reverse proxy under `/apps/ledgerone/` | Trusted forwarding and dual route validation |
| Enterprise identity, EDP, Power BI etc. | Not part of active LedgerOne standard adoption | Must be explicitly designed, approved, secured and tested before enabled |

New adapters must define data source, permissions, auth, contract/version, states (`not_configured`, unavailable, empty, success), retry/idempotency, audit, test fixtures and rollback. Do not use real credentials or customer material in PR examples.
