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
