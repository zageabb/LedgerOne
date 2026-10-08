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
