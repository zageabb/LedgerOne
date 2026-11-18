# LedgerOne standard exceptions

| ID | Baseline expectation | LedgerOne decision | Rationale | Revisit |
|---|---|---|---|---|
| EX-001 | React/MUI/FastAPI preferred for new enterprise web apps | Retain Flask/Jinja/Python Blueprints and present SQLAlchemy/Alembic architecture | Existing working P2 application; rewrite has no demonstrated benefit | Significant UI rewrite or service decomposition |
| EX-002 | Use approved Taiju/Akira design tokens where applicable | Keep LedgerOne visual identity and use validated project-specific tokens; corporate screenshot-derived values are not approved | Public accounting repository; no authorised corporate design assets | Approved reference and licensing available |
| EX-003 | Optional enterprise integrations may be documented | No connector enabled merely by adopting standard | Protect organisation data, credentials and approval boundaries | Explicit integration implementation |
| EX-004 | Standard demo route convention | Preserve existing UDA and local-root behaviour | Existing integration and deployment contract | Infrastructure change with regression tests |

These exceptions are architectural policy, not evidence of a runtime test. Any change that affects accounting controls, public exposure or authentication must have a reviewed ADR and test evidence.
