# Security expectations

LedgerOne handles financial records and document evidence. Maintain organisation isolation and least-privilege access across browser, API, background work and local AI tools. AI actions inherit requester permissions; accounting writes require explicit applicable approval and audit attribution.

- Never commit passwords, API keys, customer financial data, private enterprise screenshots or source archives. The repository is public.
- Prefer environment/secret manager configuration; rotate exposed credentials and avoid sensitive logs.
- Apply access checks within services, not only views; validate CSRF, API keys, key expiry/revocation, document ownership and download access.
- Review security impact of migrations and every new integration; optional connections must distinguish `not_configured` from empty success.
- Protect immutable postings, control accounts, currencies, periods, reconciliation, audit trails and evidence links.
- Treat local models and uploaded Knowledge as untrusted content; no additional permissions from model output.
- For defects affecting unrestricted bookkeeping, follow the independent audit process in `audit_assurance/`.

This document defines expectations, not proof of penetration testing or certification.
