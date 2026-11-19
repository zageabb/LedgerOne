# LedgerOne — UDA V2 review (DEV-020)

**Candidate only; accounting data and production deployment are NOT authorised.**

This draft was grounded in `README.md`, `requirements.txt`,
`run.py`, `ledgerone/__init__.py` and `ledgerone/config.py`.

- Flask application factory `ledgerone.create_app()`, exposed by `run.py`.
  The repository's documented development server listens on port **5000**,
  but this is **not proof of the current Ubuntu port, executable or unit**.
  The review-only V2 candidate binds loopback and deliberately disables
  automatic V2 updates/rollback until the production topology is checked.
- Health endpoint `/api/v1/system/health` is documented in the README;
  independent runtime probing is outstanding.
- `create_app()` calls `bootstrap_database` at application construction
  with `AUTO_CREATE_SCHEMA` and `AUTO_SEED_DEFAULTS`. The source defaults
  are **true in development** and production defaults to false for schema
  creation; automatic seeding remains configurable. Do **not** assume either
  setting has been safely disabled in the deployed environment.
- Production migrations must be managed explicitly via Flask-Migrate/Alembic,
  with verified schema revision, accounting-period/ledger integrity,
  database backup and restore. The V2 candidate provides no migration command
  or database-write capability.
- Database location is `DATABASE_URL`, defaulting in development to
  `ledgerone.db` (SQLite). External PostgreSQL is also supported.
  Confirm the actual production engine and location read-only before adding
  a V2 database declaration.
- Financial document attachments are stored separately under
  `LEDGERONE_DOCUMENT_STORAGE_DIR`. Preserve them alongside the accounting
  database and the journal/audit evidence.
- Development configuration includes placeholder administrator credentials
  and secret-key defaults. These are **not production-safe**. The V2 candidate
  requires named external secrets, not stored values.
- The candidate Flask CLI entrypoint is deliberately a review-only
  loopback command; it is **not a verified production WSGI deployment**.
  Confirm actual Gunicorn/other WSGI invocation and its ownership first.
- External login/auth, cookie scoping under `/apps/ledgerone/`, API key
  behavior and UDA group routing need end-to-end checks before release.

## Blocking acceptance gates

- [ ] Canonical V2 schema and semantic check with immutable source SHA.
- [ ] Read-only inspect the effective Ubuntu systemd service, port, user,
      database URL *scheme only* (not credentials), storage and Caddy/UDA.
- [ ] Verify `FLASK_ENV=production`, `AUTO_CREATE_SCHEMA=false` and
      `AUTO_SEED_DEFAULTS=false` for an established production database.
      Do not change those values on the live service from this PR.
- [ ] Refine executable entrypoint to the confirmed production WSGI runner.
- [ ] Confirm independent database backup/restore, migrations, journal
      immutability and document-store retention.
- [ ] Independent disposable test suite using test database, plus login,
      protected API and path-prefixed session checks.
- [ ] Explicit owner and accounting-data migration approvals before any
      merge/deployment/recovery.

This PR changes no production database, ledger, company, document, user,
systemd unit, reverse proxy or UDA registry.
