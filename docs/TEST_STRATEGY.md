# Test strategy — LedgerOne

## Automated checks
Use `pip install -r requirements-dev.txt` and `python -m pytest -q`. CI additionally compiles Python, upgrades a clean database through Alembic revisions and checks for migration drift (see existing GitHub workflows). Record actual commands, results, SHA and skips; never infer a pass from configuration alone.

## Regression coverage
Prioritise posting balance, journal immutability, accounting periods, base-currency gate, account roles, AR/AP/VAT reconciliations, VAT invoices/returns, numbering collisions, idempotent API writes, organisation isolation, role/AI write permissions, audit integrity, migration upgrade and CashLink import. Add tests for changed behaviour; never weaken these to make CI pass.

## Manual
For impacted screens use `docs/SCREEN_QA_CHECKLIST.md` and `docs/SCREEN_SPEC_TEMPLATE.md`. For infrastructure changes validate both local root and UDA `/apps/ledgerone/` including login, logout, redirect, CSRF, static resources, API, files, session cookie and forwarded-header trust.

## Release gate
Green relevant CI before normal merge; deployment smoke tests, user acceptance and independent accounting audit approval must be recorded separately. Existing audit findings are not auto-closed by passing tests.
