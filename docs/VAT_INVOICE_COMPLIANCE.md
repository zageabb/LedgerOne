# VAT invoice compliance controls

This note documents the first LedgerOne remediation slice for audit finding `LO-AUD-006`.

## Implemented

- A dedicated **Business Profile** workspace stores organisation legal identity, registered/principal address and customer-document contact details.
- VAT registration remains owned by the Tax module (`TaxProfile`) so LedgerOne keeps one source of truth for VAT status and registration number.
- VAT-registered sales invoices use a VAT-aware PDF renderer that includes:
  - controlled sequential invoice number;
  - tax point / supply date;
  - issue date;
  - supplier registered/legal name, address and VAT registration number;
  - customer name and address;
  - item description and quantity / extent;
  - unit price;
  - VAT rate per line;
  - net, VAT and gross totals;
  - VAT total explicitly expressed in GBP;
  - existing LedgerOne audit and provenance appendix.
- VAT invoice generation fails closed when required supplier address, VAT registration number or customer address is missing.
- Historical/non-VAT invoices remain renderable and continue to include the audit appendix.

## Tax point handling

For existing invoices, the invoice date is used as the tax point and issue date unless the invoice metadata contains explicit ISO dates under `tax_point` and/or `issue_date`.

A fully queryable tax-point field and VAT-return lifecycle remain part of `LO-AUD-007`; this slice does not claim that work is complete.

## UK basis

The renderer is designed around HMRC/GOV.UK requirements in VAT Notice 700/21 and VAT Notice 700, including sequential identification, time of supply, issue date where different, supplier and customer identity, VAT rate, net values and VAT total in sterling.
