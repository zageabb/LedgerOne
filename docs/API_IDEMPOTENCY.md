# API Idempotency

LedgerOne supports replay-safe authenticated API writes through the standard
`Idempotency-Key` request header.

## Contract

- Idempotency applies to authenticated `POST`, `PUT`, `PATCH` and `DELETE` requests.
- The header is optional. Requests without it retain normal API behaviour.
- Keys are scoped by organisation and API operation, so the same key may be used
  safely by different organisations or for different endpoints.
- The maximum key length is 255 characters.
- LedgerOne fingerprints the HTTP method, path, query string and canonical request
  body.
- Repeating the same request with the same key returns the original response body
  and status code and adds `Idempotency-Replayed: true`.
- Reusing the same key with a different request returns HTTP `409` with
  `idempotency_conflict`.
- If an identical request with the same key is already being processed, LedgerOne
  returns HTTP `409` with `idempotency_in_progress` rather than executing the
  accounting action a second time.
- Failed responses (HTTP 4xx/5xx) are not retained as completed idempotency results,
  allowing a corrected retry.

## Source-system references

Integrations may additionally send both:

- `X-Source-System`
- `X-Source-Reference`

The pair is unique per organisation and operation. This provides a second replay
guard for upstream systems that already have stable transaction identifiers. Both
headers must be supplied together.

## Retention

Completed idempotency records are retained for 90 days by the application policy.
The service exposes `IdempotencyService.cleanup_expired()` for scheduled
maintenance. Production deployments should run that cleanup from the normal
maintenance/job mechanism once background job infrastructure is enabled.

## Stored evidence

For each accepted idempotent request LedgerOne retains:

- organisation;
- API operation;
- idempotency key;
- request fingerprint;
- optional source-system/reference pair;
- processing status;
- response status and JSON body;
- resulting entity reference where the response exposes one;
- created/completed timestamps;
- expiry timestamp.

The reservation is persisted before the business operation runs. This prevents
concurrent requests with the same key from both creating journals, invoices,
bills, payments, reconciliations or other API-side effects.
