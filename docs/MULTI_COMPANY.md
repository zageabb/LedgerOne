# Multi-company accounting — phases 1–5

LedgerOne's existing `Organisation.id` remains the authoritative company/tenant key. Do **not** add duplicate `company_code` columns to journals, invoices, bank transactions or other company-scoped tables.

## Phase 1 — Company master data
- Human-readable unique company code, trading name, legal registration/VAT references, registered address and active status on `Organisation`.
- Existing organisation UUIDs, foreign keys, ledger transactions and organisation-scoped sequences are preserved.
- Existing companies have a nullable company code until the owning administrator assigns one.
- Owners of a company can create another company, which receives its own chart of accounts, settings and owner membership.
- Production upgrade: `flask --app run.py db upgrade` (Alembic revision `0023_multi_company`).

## Phase 2 — Selection and switching
- Multiple active company memberships: user is presented with a company selection screen after sign-in.
- Exactly one active membership: existing direct-to-dashboard experience is retained.
- Switches use the authenticated, active membership and ignore arbitrary non-member organisation IDs.
- The selected company remains in the session; the header shows company code/name.
- A revoked membership or inactive company fails closed rather than continuing access. The user must explicitly reselect another permitted company.

## Phase 3 — Company/user security
- `Membership` already provides role and permission separation per organisation.
- A company's administrator manages only memberships associated with that organisation.
- Global user profile/password updates are deliberately not available through company membership administration.
- API keys must have a real, active company scope. The existing inherited `AccessContext` applies to browser, API and local AI.

## Phase 4 — Boundary regression
`tests/test_multi_company.py` covers selection, denial of non-member switches, revoked memberships, company profile uniqueness, owner-only company creation, shared identity protection and accounting API separation.

Security remains defence-in-depth: all newly introduced modules and APIs must scope queries to the verified AccessContext, validate cross-company foreign references, and be regression tested.

## Phase 5 — Accounting independence
Tests verify separate starter charts, company-scoped journal/account queries and independently assigned owner memberships. Existing banking, VAT, reporting, numbering, periods and workflows remain scoped by organisation IDs. Full test-suite validation and independent audit retest are required before production rollout.

## Migration/release note
This branch adds migration `0022_multi_company` based on `0021_bank_reconciliations`. The existing draft supplier-reference PR #21 also proposes revision 0022. **Do not merge both without reconciling Alembic revision ancestry.** Rebase whichever branch merges second and adjust its revision/down_revision to avoid multiple heads.

## Manual verification checklist
1. Back up the current database, then apply migrations on a disposable copy.
2. Log in with one company; verify direct dashboard access.
3. Create a second company as owner and verify the chooser on next login.
4. Add the same person as a viewer in the second company; confirm their first-company role is unchanged.
5. Switch companies and validate customer/supplier/ledger/bank/VAT/accounting-period/reporting/numbering data remain independent.
6. Revoke a membership and verify page, API, document download, AI and background-task access is denied.
7. Verify UDA subpath navigation, logout, CSRF and API keys.
8. Run `python -m pytest -q` and `flask --app run.py db upgrade` plus Alembic drift checks before merge.

These changes do not introduce group consolidation or cross-company journals; those require separate accounting designs and permissions.
