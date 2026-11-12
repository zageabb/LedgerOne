# LedgerOne — Design Intent & Decisions

**Baseline:** [Application-Standard](https://github.com/zageabb/Application-Standard), v1.0 (adopted 12 November 2026). This record supplements, rather than replaces, `docs/ARCHITECTURE.md`.

## Intent
Deliver an auditable modular double-entry accounting platform suitable for staged evolution from home use to professional multi-organisation accounting, without weakening ledger integrity or access controls.

## Decisions
- **Existing stack retained (accepted):** Flask Blueprints/Jinja, Python, SQLAlchemy/Alembic, SQLite locally and PostgreSQL where configured. The reference standard explicitly allows existing Flask apps; adoption does not require a React/MUI/FastAPI rewrite.
- **Financial truth (accepted):** All postings go through the shared accounting service. No module, API or AI tool may introduce independent ledger posting rules.
- **Security (accepted):** Organisation isolation, caller-scoped permissions, explicit AI write approval and auditable consequential actions are mandatory. Production readiness additionally requires independent accounting audit acceptance.
- **UI (adopted forward-looking):** Preserve the existing Home/Apprentice and Professional modes; prefer shared semantic tokens, consistent layout, accessible forms/tables, responsive states and optional light/dark variants. Do not copy confidential Taiju/Akira assets or invent approved corporate colours.
- **UDA (accepted):** Keep proxy routing configuration-driven; document and tag local proxy-specific changes `LOCAL_UBUNTU_PROXY_COMPAT` as appropriate. Test root and `/apps/ledgerone/` paths, including session, auth, uploads, API and redirects.
- **Integrations (adopted):** Optional external services must explicitly distinguish `not_configured`, inaccessible, empty and successful states. Never fabricate connected data.
- **Shared code (adopted):** Evaluate compatible maintained packages in [shared-capabilities](https://github.com/zageabb/shared-capabilities) before duplication. Check licence, provenance, security and pinned versions.
- **Change control (adopted):** Use PRs, green applicable CI, migration verification, manual checks and separate user/business acceptance. Document consequential architecture exceptions and rollback.

## Open decisions
- Approved LedgerOne semantic colour/type tokens and measured accessibility evidence.
- Scope and acceptance criteria for light/dark appearance in both UI modes.
- Final deployment and business approval for unrestricted accounting use.

## Decision records
New material decisions: `docs/adr/ADR-NNNN-*.md`. Use `docs/ADR_TEMPLATE.md`; record alternatives, implications, validation and approval.
