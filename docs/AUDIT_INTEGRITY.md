# Audit Trail Integrity and Production Control

## Purpose

LedgerOne audit events are application evidence. They must be append-only in normal
application use and independently verifiable for accidental or unauthorised changes.

The audit-integrity control has three layers:

1. **Application immutability** — persisted `AuditEvent` rows cannot be updated or
   deleted through the SQLAlchemy ORM.
2. **Per-organisation hash chain** — every event stores a sequence, previous hash and
   SHA-256 hash over its canonical event content.
3. **Retained chain head** — the latest sequence/hash is stored separately so removal of
   the tail of the chain is detectable as well as edits, gaps or broken links.

The browser and API expose a full-chain verification operation. CSV exports include the
chain fields so external reviewers can retain the event sequence and hashes with the
exported evidence.

## What the hash chain protects

Verification detects:

- modification of a persisted event field or event detail;
- modification of the event timestamp;
- a broken previous-hash link;
- missing sequence numbers;
- deletion of an event in the middle of the chain;
- deletion of the newest event when the retained chain head is unchanged;
- a retained chain head that does not match the actual final event.

Audit export actions are themselves recorded as `audit_exported` events after the
export population is assembled.

## Trust boundary

A SHA-256 chain is **tamper-evident**, not magically tamper-proof.

An unrestricted database administrator who can rewrite every event and also replace the
retained chain head is inside the database trust boundary and could construct a new
internally consistent chain.

Production deployments must therefore combine LedgerOne's application controls with
database and infrastructure controls.

## Recommended production database privilege model

The normal LedgerOne application account should:

- have the table privileges required by the application;
- write audit events only through LedgerOne application code;
- not be shared with human administrators;
- not be used for interactive database maintenance.

Human reporting/support accounts should normally be read-only.

Database owner / migration credentials should be separate from the runtime application
credential and used only for controlled deployment or break-glass administration.

Where the database platform supports it, production hardening should additionally:

- deny routine `UPDATE` and `DELETE` access to `audit_events` for support/reporting
  roles;
- restrict changes to `audit_chain_heads` to the runtime service and controlled
  migration role;
- log privileged database access independently of LedgerOne;
- retain database-native audit logs where available;
- require reviewed migration/change procedures for direct production data changes.

A future PostgreSQL-first deployment may enforce append-only audit events with
database triggers or restricted stored procedures in addition to the ORM guard.

## Integrity verification

LedgerOne verifies one organisation at a time.

Verification walks the chain from sequence 1 and checks:

1. sequence continuity;
2. the stored previous hash;
3. the SHA-256 hash recalculated from canonical event content;
4. the final sequence/hash against `audit_chain_heads`.

The first detected error is returned with its event identifier where applicable.

API:

`GET /api/v1/audit/integrity`

Browser:

`/audit/integrity`

Both require normal audit-read authority.

## Hash input

Chain version 1 hashes a canonical JSON representation containing:

- event ID;
- organisation/scope;
- actor type and actor ID;
- module and action;
- entity type and entity ID;
- event detail;
- UTC-normalised event timestamp;
- chain sequence;
- previous hash;
- chain version.

Canonical JSON is sorted and compact so the verifier can reproduce the same digest.

## Existing data migration

Migration `0017_audit_integrity` backfills historical audit events in deterministic
organisation/timestamp/event-ID order.

It also creates one chain-head row for every existing organisation, including
organisations that currently have no audit events.

Existing data is not deleted or rewritten other than adding the chain metadata required
for verification.

## Retention

LedgerOne does not automatically purge audit events.

Production retention must be aligned with the organisation's accounting, tax, legal,
security and contractual record-retention obligations. Audit evidence should normally
be retained for at least as long as the underlying accounting records it evidences.

A retention decision must not delete audit events from an active chain without an
explicit archival design that preserves:

- the exported event population;
- event hashes and sequence values;
- the closing chain hash;
- archive date and responsible actor;
- integrity evidence for the archived segment.

Until such an archival mechanism exists, automatic audit deletion should remain
disabled.

## Backup and recovery

Database backups containing LedgerOne accounting records must include both:

- `audit_events`;
- `audit_chain_heads`.

After a production restore, the audit-integrity verifier should be run before the
restored system is accepted for accounting use.

Restore testing should confirm that:

1. the audit chain verifies successfully;
2. the chain head matches the restored event tail;
3. business records and audit events remain in the same transactional state;
4. backup retention and encryption controls meet the deployment's security policy.

## Limitations and future hardening

The current design does not use a private signing key. A future high-assurance option
could add externally signed periodic checkpoints or HMAC/signature material stored
outside the primary database trust boundary.

That would improve resistance to a privileged database actor who can rewrite both the
event chain and its local chain head.

Until then, LedgerOne should describe this feature as:

> Append-only application audit events with per-organisation tamper-evident hash-chain
> verification.

It should not claim cryptographic non-repudiation against an unrestricted database
administrator.
