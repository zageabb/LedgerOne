# VAT Making Tax Digital Integration Architecture

## Status

This document defines the future HMRC Making Tax Digital (MTD) boundary for LedgerOne.

The current LedgerOne Tax & VAT module supports a controlled **GB standard VAT** accounting scope:

- explicit VAT tax points on sales invoices, purchase bills and credit notes;
- tax-point-based VAT return calculation;
- separately identified VAT adjustments with reason and evidence reference;
- non-overlapping VAT return periods;
- draft, final and submitted lifecycle states;
- a frozen source-population and box-total snapshot when a return is finalised;
- retained manual submission reference and filing note;
- prevention of later VAT postings or adjustments into a final/submitted VAT period.

This does **not** make LedgerOne HMRC-compatible filing software yet. LedgerOne does not currently authenticate to HMRC or transmit a VAT return through the HMRC VAT (MTD) API.

## Regulatory design basis

LedgerOne's VAT design should continue to follow current HMRC guidance and API documentation.

Key current references:

- VAT Notice 700/22 — Making Tax Digital for VAT:
  https://www.gov.uk/government/publications/vat-notice-70022-making-tax-digital-for-vat/vat-notice-70022-making-tax-digital-for-vat
- HMRC VAT (MTD) API:
  https://developer.service.hmrc.gov.uk/api-documentation/docs/api/service/vat-api/1.0
- HMRC Developer Hub reference guide, including fraud-prevention headers:
  https://developer.service.hmrc.gov.uk/api-documentation/docs/reference-guide
- HMRC Developer Hub getting started / OAuth and production access:
  https://developer.service.hmrc.gov.uk/api-documentation/docs/using-the-hub

VAT Notice 700/22 requires the electronic account to retain digital designatory data and VAT transaction data including the time of supply (tax point), net value and VAT rate. Where more than one software product forms the electronic account, transfers that continue the digital VAT journey must use permitted digital links rather than manual copy/paste.

## Current LedgerOne digital record boundary

The following LedgerOne records form the VAT calculation evidence set:

- organisation/business profile;
- TaxProfile and TaxCode;
- SalesInvoice and SalesInvoiceLine;
- PurchaseBill and PurchaseBillLine;
- SalesCreditNote and PurchaseCreditNote;
- VATAdjustment;
- VATReturnPeriod;
- posted journals and audit events;
- retained source-document/evidence references.

A finalised VAT return stores the exact record identifiers used for the calculation together with the resulting box totals. This ensures that the return can be reproduced after finalisation without recalculating against later transactions.

## HMRC integration target

When HMRC submission is implemented it should be isolated behind a dedicated service boundary, for example:

```
LedgerOne VAT records
        |
        v
VATReturnPeriod frozen snapshot
        |
        v
HMRC VAT service adapter
  |-- OAuth 2.0 authorisation
  |-- VAT obligations retrieval
  |-- VAT return submission
  |-- VAT return retrieval
  |-- liabilities/payments retrieval where required
  |-- mandatory fraud-prevention headers
        |
        v
HMRC VAT (MTD) API
```

The adapter must not recalculate the VAT return from mutable live records. Its submission payload must be generated from the frozen `VATReturnPeriod.snapshot_json`.

## Future submission record

Before enabling HMRC submission, add a dedicated immutable submission entity (for example `VATSubmission`) associated with one final VATReturnPeriod.

At minimum retain:

- VAT return period ID;
- HMRC obligation/period key;
- request payload or canonical payload hash;
- HMRC API version;
- environment (sandbox or production);
- submission attempt timestamp;
- submitting user/service identity;
- HTTP status;
- HMRC response body required for audit evidence;
- HMRC receipt/correlation/reference identifiers;
- success/failure state;
- failure/error details;
- subsequent retrieval/verification response where applicable.

Do not store OAuth access or refresh tokens in this audit entity. Credentials/tokens must use an appropriate protected secrets/credential store.

A successfully submitted VAT return must be immutable. A retry must be idempotent and must not create an accidental duplicate filing.

## HMRC obligations

Before a return can be transmitted, the integration should retrieve the organisation's VAT obligations from HMRC and bind the LedgerOne VATReturnPeriod to the HMRC period key.

The application should prevent submission when:

- the HMRC obligation does not match the LedgerOne period;
- the obligation is already fulfilled, unless the HMRC API explicitly supports the requested correction route;
- the LedgerOne return is not in the required final state;
- required organisation/VAT identity data is incomplete.

## User declaration and final submission

The submission workflow should present the frozen return to an authorised user and require the user to make the declaration/confirmation required by the HMRC journey immediately before submission.

The user action, declaration, timestamp and exact submitted payload must be retained in LedgerOne audit evidence.

## Fraud-prevention headers

HMRC states that fraud-prevention header data is mandatory for the VAT (MTD) API.

The future adapter must therefore have a dedicated fraud-prevention-header builder with:

- documented source for every required value;
- validation before an API request is sent;
- separate sandbox conformance testing;
- no silent fallback to invented or placeholder production values.

Header construction should be tested independently from VAT calculations.

## Digital links

LedgerOne should preserve a digital link whenever VAT electronic-account data moves between systems.

Acceptable architecture includes:

- API integration;
- automated imports;
- CSV/XML import/export with retained source provenance;
- linked/automated spreadsheet interfaces where applicable.

Do not design a VAT submission flow that requires a user to copy/paste VAT box totals from LedgerOne into separate filing software and still describe that flow as an MTD digital link.

For imported data LedgerOne should retain, where available:

- source system;
- source reference;
- import batch/file identifier;
- original document/evidence reference;
- imported timestamp;
- mapping/transformation version.

## Adjustments and late entries

Final/submitted VAT periods are locked.

A later transaction with a tax point inside a locked period is rejected by the normal posting path. The user must use the supported correction/adjustment process in accordance with the accounting and HMRC treatment applicable to that correction.

VATAdjustment records are explicit and audited. They must not overwrite the original VAT transaction.

When more sophisticated HMRC correction rules are implemented, LedgerOne should distinguish:

- current-period permitted adjustments;
- prior-period error corrections;
- corrections that require a separate HMRC disclosure/process.

## Reverse charge and import VAT

LedgerOne does **not** currently claim support for reverse-charge VAT, import VAT or other treatments requiring Boxes 2, 8 or 9 or specialised VAT rules.

Do not map an ordinary domestic TaxCode to these treatments as a shortcut.

Before support is enabled, add:

- explicit tax treatments;
- clear source-document data requirements;
- correct box mappings;
- journal/control-account rules;
- VAT return tests covering credits/corrections;
- user-facing wording explaining the treatment.

## Cash Accounting and Flat Rate Scheme

TaxProfile can retain these scheme values, but the current return engine intentionally rejects schemes other than standard VAT accounting.

Dedicated calculation logic and tests are required before either scheme is described as supported.

## Testing gates before HMRC production access

Before any HMRC production submission capability is enabled:

1. VAT calculation and frozen-return regression suite must pass.
2. HMRC sandbox end-to-end tests must pass.
3. OAuth/token lifecycle tests must pass.
4. Fraud-prevention-header validation must pass.
5. Submission retry/idempotency tests must pass.
6. Request/response audit-retention tests must pass.
7. Permission and maker/checker rules for submission must pass.
8. Production credentials must be separately configured from sandbox credentials.
9. No HMRC credential or bearer token may appear in normal application logs.
10. A failed or ambiguous submission must be recoverable by checking HMRC state before any retry.

## Scope statement

Until the HMRC adapter and its production assurance gates are implemented, LedgerOne should describe this capability as:

> GB standard VAT accounting, tax-point calculation, return preparation and retained filing evidence.

It should **not** describe itself as HMRC MTD-compatible VAT filing software or claim that it submits VAT returns to HMRC.
