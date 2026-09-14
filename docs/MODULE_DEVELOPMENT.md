# LedgerOne Module Development

LedgerOne modules are intended to be self-contained business capabilities. A new module should be installable by adding its package beneath `ledgerone/modules/` without adding hard-coded registration logic to the application factory.

## Standard module layout

```text
ledgerone/modules/example/
├── __init__.py
├── manifest.py
├── routes.py
├── api.py
├── services.py
├── permissions.py      # optional when permissions are small
├── models.py           # optional
└── templates/          # module-specific templates may also use shared template roots
```

The package `__init__.py` exposes a `register(app)` function. It should import any model module before schema metadata is used so migrations and local schema creation can see the module's tables.

Example:

```python
from ledgerone.modules.example import models  # noqa: F401
from ledgerone.modules.example.api import api_bp
from ledgerone.modules.example.routes import bp


def register(app):
    app.register_blueprint(bp)
    app.register_blueprint(api_bp)
```

## Manifest

Every module requires `manifest.py` containing `MANIFEST = ModuleManifest(...)`.

Typical fields:

```python
from ledgerone.module_registry import ModuleManifest

MANIFEST = ModuleManifest(
    id="assets",
    name="Fixed Assets",
    home_name="Assets",
    professional_name="Fixed Assets",
    description="Asset register and depreciation.",
    icon="archive",
    order=60,
    default_enabled=False,
    permissions=(
        "assets.read",
        "assets.write",
        "assets.post",
    ),
    dependencies=("ledger",),
)
```

Use stable module ids because module state, permissions, API paths, audit events and future migration metadata can reference them.

## Required API convention

Functional modules should expose a versioned API beneath:

```text
/api/v1/<module-id>/...
```

A module is not considered complete when it only has browser routes. Its useful operations should also be accessible through authenticated APIs so integrations and LedgerOne AI can use the same business capability.

Use `@require_api("permission.name")` on API endpoints. Resolve the active organisation from `g.access_context`; do not trust an organisation id supplied in request JSON to grant access.

## Service layer rule

Routes, APIs and AI tools should call services rather than duplicate business logic.

Preferred flow:

```text
Browser route ─┐
REST API ──────┼─> Module service ─> LedgerService / module models
AI tool ───────┘
```

This gives all interfaces the same validation and transaction behaviour.

## Financial posting rule

Only the accounting kernel owns general-ledger posting. Financial modules request postings through `LedgerService`.

For a domain document that posts financially:

1. Validate module-specific data.
2. Create/flush the module document.
3. Call `LedgerService.post_journal(..., commit=False, enforce_permission=False)` only after the module has already checked its own posting permission.
4. Link the returned journal to the domain document.
5. Commit the entire transaction once.
6. On any error, roll back everything.

This prevents an invoice, bill, payroll run or asset depreciation record from existing without its accounting entry—or vice versa.

Do not grant a Sales clerk arbitrary manual-journal permission just because Sales needs to create accounting entries internally.

## Models and organisation isolation

Module-owned records should be organisation-scoped directly or through a parent record. Common patterns are:

```python
organisation_id = db.Column(
    db.String(36),
    db.ForeignKey("organisations.id"),
    nullable=False,
    index=True,
)
```

Every service query must constrain records to `context.organisation_id`.

Use UUID string ids through `new_id()` for consistency with the current platform.

## Permissions

Use capability-oriented names such as:

```text
assets.read
assets.write
assets.post
assets.dispose
```

Avoid UI-oriented names such as `can_click_asset_button`. Permissions describe business capability, not presentation.

Owners/admins currently receive full access; scoped memberships and service keys can carry explicit permissions.

## Home / Apprentice and Professional UI

Do not build separate business engines for the two UI modes. A route/service should be shared, while templates or labels adapt presentation.

Examples:

- Home: `Money owed to you`
- Professional: `Accounts Receivable`
- Home: `Money you owe`
- Professional: `Accounts Payable`

A feature available only to professional users should be hidden or simplified in Home mode, not stored differently.

## AI integration

LedgerOne AI should call explicit tool functions that wrap services. Do not expose unrestricted SQL execution or arbitrary Python execution to the model.

A module that wants AI support should provide narrow operations, for example:

```text
list_assets
get_asset
create_asset
run_depreciation
```

Write operations should validate configuration such as `LOCAL_AI_ALLOW_WRITES` and be logged through the audit layer.

## Audit events

Significant administrative and financial operations should emit audit events containing:

- organisation;
- actor type/id;
- module id;
- action;
- entity type/id;
- non-secret detail.

Never place passwords, API-key secrets or other credentials in audit detail.

## Database migrations

Any model change requires an Alembic revision. Development may auto-create an empty SQLite schema, but production relies on migrations.

Workflow:

```bash
flask --app run.py db migrate -m "add fixed assets module"
# inspect generated migration carefully
flask --app run.py db upgrade
pytest
```

Module migrations should be backwards-compatible where practical. Large data transformations should be staged instead of combining destructive schema and data changes in one step.

## Module completion checklist

A new functional module is ready when it has:

- manifest and dependency declaration;
- browser route(s);
- `/api/v1/<module>/...` API route(s);
- permission checks;
- organisation isolation;
- service-layer validation;
- models/migration when persistence is required;
- atomic ledger integration when financially relevant;
- Home/Apprentice and Professional presentation consideration;
- AI tools where useful;
- audit logging for consequential actions;
- tests for normal, permission-denied and invalid-data paths;
- documentation of any configuration values.
