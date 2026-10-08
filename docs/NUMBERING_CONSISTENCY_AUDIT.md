# DEV-009 — Controlled numbering consistency audit (initial review)

## Confirmed gaps

1. **Purchase bills:** the browser form at `ledgerone/templates/purchases/index.html` requires a `bill_number`; the API and `PurchasesService.create_bill` require it too. Workflow creation also requires a number. This blocks the blank-for-automatic experience used for sales invoices, despite the existing `purchase_bill` configured number sequence.
2. **Purchase order conversion:** the browser passes `bill_number` through to conversion without offering a controlled automatic allocation explanation. The service path must be checked before relaxing requirements.
3. **Reference distinction:** the supplier's document number and LedgerOne's internal controlled bill number are currently conflated in the bill model and in posted document references. Splitting these requires a migration, invoice PDF/API/workflow compatibility review, and a non-destructive path for historic records. Do not silently overwrite legacy supplier references.

## Existing implementation to reuse

- `ledgerone/services/numbering.py`: per-organisation sequence configuration, atomic allocation, manual override history and immutable issued/void records; `purchase_bill` sequence already defined.
- `ledgerone/modules/sales/numbering.py`: blank sales invoice numbers resolved at *final posting*, not workflow submission; legacy number adoption and collision guards are available as an integration pattern.
- Purchase posting service, workflow post action and purchase-order conversion must all use the same allocation transaction.

## Recommended implementation sequence

1. Extend purchase bill model with a separate optional `supplier_invoice_reference` through migration, keeping existing document IDs and bill numbers intact.
2. Implement purchase-bill numbering allocation in the final posting transaction via the shared number sequence infrastructure, including workflow and purchase-order conversion.
3. Make the browser/internal bill number optional and show it as 'Leave blank for automatic'. Capture required supplier invoice reference separately, according to configuration/policy.
4. Update API request/response compatibility and PDF output with both references. Verify legacy clients.
5. Test sequence allocation concurrency, rollback on posting failure, manual override, cancelled/void history, duplicate supplier invoice reference handling and workflow deferral.
6. Audit quotes, orders, credit notes and expense claims with a path-by-path matrix before changing their UI.

## Audit closure

This document records engineering gaps, **not** a closed audit finding. Do not mark DEV-009 complete until a merged implementation, green CI, audit record update and independent retest where applicable.

## Implemented in PR #17 (awaiting final validation)

- Purchase bill posting invokes the existing controlled numbering helper, preserving next-number, manual override, legacy adoption and posting-time transaction semantics.
- Purchase bill browser and both direct and workflow API paths accept blank internal numbers; the workflow does not consume a number at submission time.
- Purchase-order conversion forms and API also accept blank numbers; the conversion posts through the same purchase bill service.
- The original supplier invoice number is **not yet** a separate field; the existing `bill_number` must still be treated as LedgerOne's currently stored document identifier until migration and historic backfill policy are agreed and implemented.
- CI #507 passed for an earlier commit. Final CI for the latest PR head is still required before merge.

## Additional browser form review

- Sales quote form requires `quote_number` even though the shared `sales_quote` sequence exists.
- Sales order form requires `order_number` even though the shared `sales_order` sequence exists.
- The quote-to-invoice and sales-order-to-invoice conversion forms require an invoice number; review their conversion services and permit blank number where supported by final-post allocation.
- Purchase credit note form requires `credit_number`, whereas the sales credit note form already supports automatic numbering. Inspect purchase-credit service before adjusting its browser/API.
- Purchase order creation requires `order_number`, despite the `purchase_order` sequence being configured.

These are verified user-interface inconsistencies; services, tests and allocation lifecycle still need review before changing their required fields.
