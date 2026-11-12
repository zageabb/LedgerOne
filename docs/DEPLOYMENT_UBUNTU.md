# Ubuntu / UDA deployment checklist

LedgerOne runs as a Flask application. This document records deployment acceptance steps, not evidence that a production service is active. Consult existing `docs/SCHEDULED_JOBS.md` and `README.md` for documented runtime configuration.

1. Configure secrets using the approved environment/secrets mechanism; never commit `.env`, production credentials or customer data.
2. Back up the database and externally stored documents; verify rollback procedure.
3. Set production schema creation appropriately and apply reviewed Alembic upgrades before application startup.
4. Bind backend to controlled loopback/container network; configure UDA/Caddy proxy prefix `/apps/ledgerone/` with only trusted forwarded headers. Keep Flask business logic independent of URL prefixes.
5. Verify app root/LAN access as intended and authenticated prefixed access. Check redirect, login/logout, navigation, session/cookies, CSRF, static resources, API, health, upload/download and financial PDF exports.
6. Test anonymous access denial, disallowed forwarded-header spoofing and organisation isolation.
7. Confirm scheduled jobs, persistent storage, log redaction, permissions and backups; document actual deployment ID/commit and rollback evidence.

All new proxy-specific code should identify its rationale with `LOCAL_UBUNTU_PROXY_COMPAT`; existing working code does not need churn for a comment-only change. Live acceptance for PR #22: **not performed**.
