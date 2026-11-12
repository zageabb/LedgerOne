# Library and dependency governance

- Source of truth for Python dependencies: `requirements.txt` and `requirements-dev.txt`; runtime versions must be verified from installed environment or lockfile, not guessed.
- Internal component reuse: inspect [shared-capabilities](https://github.com/zageabb/shared-capabilities), licences, provenance, packaging, tests, stable API and CI **before** adoption.
- Domain services: retain LedgerOne's accounting kernel as the sole financial posting authority. Do not replace it with a generic library.
- UI: keep existing Flask/Jinja UI; reuse project components first. External component libraries require security, maintenance, licensing and accessibility review.
- Record a new significant dependency with version/pin, purpose, alternatives, security/licence risk, owner, test evidence and rollback in `DEVELOPMENT.md` or an ADR.
- No new runtime package is introduced by Application-Standard documentation adoption.
