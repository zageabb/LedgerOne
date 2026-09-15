# LedgerOne Audit & Assurance

This directory is the permanent home for independent/internal audit reviews, assurance reports, remediation registers, and follow-up evidence for LedgerOne.

It is intentionally separate from product documentation so that audit findings and remediation history remain visible and are not mixed with feature-roadmap material.

## Directory convention

Each audit should use its own immutable dated folder:

```text
audit_assurance/
├── README.md
└── YYYY-MM-DD-<audit-scope>/
    ├── AUDIT_REPORT.md
    └── ACTION_REGISTER.md
```

Additional evidence may be stored alongside the report when required, for example:

```text
    ├── EVIDENCE.md
    ├── RETEST_REPORT.md
    └── supporting/
```

## Audit lifecycle

1. **Audit** — assess the implementation and record findings.
2. **Triage** — assign severity, owner, target release and acceptance criteria.
3. **Remediate** — implement the control or accounting correction.
4. **Test** — add automated regression tests where practical.
5. **Retest** — independently verify the finding against the relevant commit.
6. **Close** — mark the action closed only when its acceptance criteria are evidenced.

## Severity scale

| Severity | Meaning |
|---|---|
| Critical | Can permit unauthorised accounting changes, materially incorrect books, or a fundamental integrity failure. Release blocker for affected use. |
| High | Can cause materially incorrect accounting, broken subledger/control-account integrity, statutory non-compliance, or unreliable financial reporting. |
| Medium | Important control, reconciliation, auditability or robustness weakness that should be remediated before broad production use. |
| Low | Improvement to governance, usability, documentation or defensive control. |

## Status scale

Use one of these values in action registers:

- `OPEN`
- `IN PROGRESS`
- `READY FOR RETEST`
- `CLOSED`
- `RISK ACCEPTED`
- `NOT APPLICABLE`

`CLOSED` should only be used after the implementation and the required test/retest evidence exist.

## Finding IDs

Accounting-control findings use the prefix `LO-AUD-` followed by a three-digit number. IDs should not be reused even after a finding is closed.

## Current audits

- [2026-09-15 Accounting Practice & Controls Review](./2026-09-15-accounting-practice-review/AUDIT_REPORT.md)
  - [Remediation Action Register](./2026-09-15-accounting-practice-review/ACTION_REGISTER.md)
