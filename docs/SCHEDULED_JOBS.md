# Scheduled recurring-work generation

LedgerOne exposes a safe, idempotent Flask CLI command for generating due
recurring transaction work items:

```bash
./venv/bin/flask --app run.py generate-recurring-transactions
```

The command creates User Actions for human review. It deliberately does **not**
post accounting entries. Home and Professional/Expert workflows retain their
normal review, approval, and posting controls.

On a server managed by the Universal Deployment Agent (UDA), add the following
to LedgerOne's application entry in the host-local UDA registry:

```json
"scheduled_jobs": [
  {
    "name": "recurring-transactions",
    "description": "Generate LedgerOne recurring transaction work items",
    "enabled": true,
    "schedule": "daily",
    "time": "06:00",
    "persistent": true,
    "command": [
      "./venv/bin/flask",
      "--app",
      "run.py",
      "generate-recurring-transactions"
    ]
  }
]
```

UDA uses the application's `repo_path` as the working directory and generates
an independent oneshot service and timer. The job therefore runs without a web
login and never starts another LedgerOne web process. The existing once-per-day
first-authenticated-request fallback may remain in place.

After updating UDA and its host-local registry, run UDA once normally, then
verify:

```bash
systemctl --user status uda-ledgerone-recurring-transactions.timer
systemctl --user status uda-ledgerone-recurring-transactions.service
journalctl --user -u uda-ledgerone-recurring-transactions.service
```
