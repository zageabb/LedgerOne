# AGENTS.md

## Project
Repository: `zageabb/LedgerOne`

This file is the persistent working agreement for ChatGPT, Codex, and other coding agents operating on this repository.

## Start here
Before changing code:
1. Read this file.
2. Read the root `DEVELOPMENT.md`. It is the primary development queue and should be treated as the current source of truth for development order and incomplete work.
3. Read the repository README and relevant documentation.
4. Read `docs/TODO.md`, `docs/ROADMAP.md`, audit/action-register material, design notes, phase notes, and other development documentation where relevant.
5. Inspect the existing implementation, tests, migrations, open pull requests, and current branch state before proposing replacement architecture or trusting displayed status text.
6. Verify behaviour from source and tests rather than assuming a checkbox, PR description, or older documentation entry is still accurate.
7. Continue the highest-priority incomplete item in `DEVELOPMENT.md` unless the user explicitly asks for something else.

## Development rules
- Preserve the existing architecture, UI conventions, and working behaviour unless a change is required.
- Prefer extending existing modules over rewriting working code.
- Keep modules focused and independently testable; avoid unnecessary monolithic files.
- Maintain backwards compatibility where practical.
- Keep business logic separate from UI, storage, integration, and transport layers.
- Do not hard-code passwords, tokens, API keys, server addresses, ports, or environment-specific paths when configuration can be used.
- Put secrets in environment/configuration mechanisms and never commit production secrets.
- Keep configuration explicit and documented.
- Update README/docs/TODO when implementation changes make them inaccurate.
- Clearly mark scaffolds, placeholders, limitations, and unfinished features.

## Reuse before duplication
Before building a capability from scratch, inspect relevant existing repositories and reuse proven patterns or modules where appropriate, especially:
- `context-studio`
- `general-search`
- `tender_designer`
- `should-cost-intelligence`
- `should-cost-price-estimator`
- `system-knowledge-designer`
- `olladex`
- `AI_Spreadsheet`

Reuse should preserve module boundaries and licensing/attribution requirements. Do not copy code blindly when a shared abstraction or adaptation is cleaner.

## Testing and quality
- Run the relevant automated tests before committing.
- Add or update tests for material behaviour changes.
- Run build, lint, type-check, migration, or validation commands used by this repository when available.
- Do not claim a feature is complete if tests fail or only a scaffold exists.
- Fix regressions introduced by the change before moving on.

## Git workflow
- Default branch is normally `main`; verify before acting.
- Do not force-push the default branch.
- Do not rewrite published history unless the user explicitly requests it.
- Keep commits focused and use clear commit messages.
- Do not push a change that is known to fail the repository's relevant tests/build unless the user explicitly requests a work-in-progress commit.

## Deployment
Many of these projects use GitHub as the source for automatic deployment to an Ubuntu server, often as Docker containers or services.
- Inspect the repository's actual deployment configuration before changing it.
- Preserve existing ports, volumes, environment variables, health checks, and service names unless the requested change requires otherwise.
- Do not assume every repository is Dockerised.
- Avoid introducing deployment-only dependencies into core application logic.
- Keep local development possible where the existing project supports it.

## Agent behaviour
- Make the smallest coherent change that fully satisfies the task.
- Prefer implementation over speculative redesign.
- Use repository evidence as the source of truth.
- If documentation and code disagree, identify the mismatch and update the appropriate source.
- Do not invent completed work, test results, files, endpoints, or integrations.
- When work spans phases, complete and verify the current phase before starting the next.
- Keep `DEVELOPMENT.md` current as implementation evidence changes. Add newly discovered outstanding work, mark completed work only when verified, and remove or supersede stale development instructions rather than allowing parallel contradictory backlogs.
- Do not stop after a single implementation step if the current objective still has clear, safe, unambiguous work remaining.
- Continue autonomously until one of these conditions is reached:
  1. the current objective is complete and verified;
  2. a genuinely ambiguous product decision is required;
  3. progress is blocked by something outside the repository or unavailable credentials/services;
  4. continuing would risk destructive or irreversible changes.
- A completed sub-step, commit, test run, or green CI check is not by itself a reason to stop when the objective still contains unfinished work.
- When CI fails, inspect the actual failing job/log, fix the underlying cause, run the relevant local validation, push the fix, and recheck CI. Do not merely report that CI failed when the cause can be addressed in the repository.
- Before starting unrelated work, finish or explicitly document the current highest-priority objective and its remaining blockers.
- Where independent tasks can safely be developed in parallel without touching conflicting files or shared migration history, parallel work is allowed, but each workstream must still satisfy the same testing, documentation, and evidence requirements before being marked complete.


## Development tracking and evidence

`DEVELOPMENT.md` is the persistent development control document for LedgerOne.

For every material development item:
- give it a stable identifier where practical;
- state its current status;
- record the expected outcome and completion evidence;
- update the entry when source inspection shows that older TODO/roadmap information is stale;
- reference relevant audit finding IDs, pull requests, migrations, tests, and commits where useful;
- do not mark an item complete solely because code exists on a branch or pull request;
- require merge to `main`, applicable migrations, relevant regression coverage, and green final CI before normal development completion;
- for audit-linked items, retain the stricter audit rule: implementation evidence plus independent retest before the finding is marked CLOSED.

When the user asks to "continue development", "continue", or gives an equivalent instruction without naming a different objective, resume from the highest-priority incomplete item in `DEVELOPMENT.md`.

## Application-Standard adoption (12 November 2026)

This repository follows [Application-Standard](https://github.com/zageabb/Application-Standard) v1.0 as a **P2 existing Flask web application**, with project-specific decisions in `DID.md`, `STANDARD_VERSION.md` and `docs/EXCEPTIONS.md`. Do not rewrite Flask/Jinja to React/MUI merely for template compliance. For substantial design or architectural changes, read `docs/ADR_TEMPLATE.md` and record an ADR.

### Screen design and accessibility gate
Before modifying a user-facing page, consult `DID.md`, `docs/SCREEN_QA_CHECKLIST.md` and `docs/SCREEN_SPEC_TEMPLATE.md`. Reuse LedgerOne's current dual UI modes and shared components. Specify responsive widths, keyboard/focus, accessibility, empty/loading/error/permission states, accurate financial figures and any optional light/dark behaviour. Validate what is implemented; do not claim official corporate brand or Figma parity from draft templates.

### User manual maintenance (mandatory)
For each user-visible feature, workflow, setting, installation or troubleshooting change, review and update the corresponding user-facing manual in the **same PR**. If no manual exists, create one where warranted or record the explicit documentation gap. Record manual paths, updated sections, tests and unresolved validation in `DEVELOPMENT.md`. Do not mark a user-visible change complete while affected guidance is stale.

### Shared capability reuse gate
Before implementing a significant reusable capability, check the current [shared-capabilities registry](https://github.com/zageabb/shared-capabilities) and the [Application-Standard reuse policy](https://github.com/zageabb/Application-Standard/blob/main/docs/SHARED_CAPABILITIES_POLICY.md). Confirm runtime fit, security, API compatibility, provenance, licence, maintenance and verified CI. Pin an approved version. Never copy unapproved corporate material or assume a listed candidate is an available package. Document reuse/rejection in the related DEV item.

### UDA, integrations and sensitive information
Use `LOCAL_UBUNTU_PROXY_COMPAT` for newly introduced proxy-specific code paths, keeping the original working convention intact. Test both local root paths and `/apps/ledgerone/`, including authentication, redirects, API, static files, uploads/exports and forwarded-header spoofing where relevant. Optional integrations must distinguish `not_configured` from legitimate empty results. Never commit production credentials, customer records or private template assets into this public repository.

### Evidence and PR gate
For each change record source implementation, local test results, GitHub CI, migration impact, manual changes, deployment verification and user/business acceptance **separately**. CI success is required before normal merge; when CI is blocked, keep work in PR and report the blocker. Formal independent accounting audit retest is still required for audit closure.
