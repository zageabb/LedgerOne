# ERP-000 — Order-to-Cash and Procure-to-Pay (Full Commercial Lifecycle)

**Priority:** Foundation ahead of ERP-001 legacy data assessment. **Status:** Planned / gap assessment completed. This is an application-development programme, not a claim that all features are implemented.

## Outcome

Provide a complete, controlled multi-company document lifecycle from supplier/customer setup to purchase orders, sales orders, goods receipt notes, delivery notes, supplier invoices, customer invoices, credits, returns and payments. Persist document-to-document lineage and part quantities. Reuse existing LedgerOne sales quotes/orders, purchase orders, invoice/bill models, numbering, company security, approval policies, accounting journals and audit services.

### Evidence from current source

Already present:
- `SalesQuoteService`, `SalesOrderService` and conversion to sales invoices.
- `PurchaseOrderService` and conversion to purchase bills.
- Supplier/customer master records with an `email` field.
- Sales invoice and purchase bill service posting, VAT, PDF output and payment allocation.
- Company-specific workflow rules, user roles and maker/checker safeguards.

Not proven present as complete operational lifecycles:
- Linked GRNs, partial line receipts, inspection/rejections or 2-/3-way matching.
- Picking/dispatch and delivery notes with shipment quantities and proof of delivery.
- Multi-line partial invoicing of individual received/delivered quantities with non-overbilling guards.
- Supplier/customer contact-purpose email codes, message templates, approved email sending and delivery audit.
- Unified order-document status, revision history and end-to-end exceptions.

Do not mark these as complete merely because an order can be converted to a bill or invoice.

## ERP-000A — Master data, contacts and document foundations

1. Company-local supplier/customer details, registered/trading names, multiple addresses (registered, billing, delivery), contacts and communication preferences.
2. Supplier/customer contact email codes or purposes such as `ORDERS`, `ACCOUNTS`, `QUOTES`, `RETURNS`, `LOGISTICS`, with one or more verified addresses per code; configurable fallbacks, CC/BCC rules and manual override permissions.
3. Item/service catalogue, UOM, SKU / supplier part number, description, price, VAT code, lead time and optional inventory linkage.
4. Multi-line, quantity-based document model, immutable issued document numbers, versioning, attachments, line statuses and full source-reference lineage.
5. Company-specific configurable numbering and document templates; PDF preview before approval/sending.
6. Role-aware access for drafting, approving, issuing, receiving, dispatching, invoicing, voiding and reversing.

**Acceptance:** No cross-company contacts/items/documents; generated numbers not reused; all issued revisions traceable.

## ERP-000B — Purchasing: requisition to supplier invoice

1. Purchase requisitions (PR) with project/cost centre, budget and approval.
2. Purchase orders (PO): multi-line products/services, tax, currency within supported accounting scope, delivery location/date, supplier quotation reference and terms.
3. Draft → approval required (according to value/category/role) → approved → issued → acknowledged → partially received → received/closed/cancelled.
4. Send PO PDF to appropriate supplier `ORDERS` email code; audit message, template, recipients, attachment hash, authorisation, provider result.
5. GRN: receive against PO lines, date, warehouse/site, quantity accepted/rejected/damaged, lot/serial (where applicable), receiver and evidence; permit partial receipts, multiple GRNs, returns and corrections with safeguards.
6. 2-way match (PO vs invoice) and 3-way match (PO vs GRN vs invoice) with tolerance rules, price/quantity/VAT variance, authorised exception approval and duplicate invoice detection.
7. Supplier invoice intake (document upload/email/OCR optional later), capture supplier invoice *external reference* separately from controlled LedgerOne internal bill number.
8. Bill creation from matched PO/GRN lines with outstanding-quantity checks; integrate AP, VAT, approvals, credits and payment allocation.
9. Receipt accounting / accrual or goods-received-not-invoiced (GRNI) must be explicitly designed and reconciled before being activated.

**Acceptance:** A PO can be split across GRNs and bills without overstating received/invoiced quantities; blocks duplicate receipt, overbill and uncontrolled override.

## ERP-000C — Sales: quote through delivery and collection

1. Quotations: versioning, approved pricing, validity, PDF and optional customer email.
2. Sales orders: multi-line items/services, confirmed delivery address, delivery terms, requested date, project and customer reference.
3. Statuses: draft → approved/confirmed → reserved/allocated (when stock enabled) → picked → partially dispatched → dispatched/partially delivered → delivered → partially invoiced/invoiced → closed.
4. Picking/packing: allocated and shipped quantities; no negative or excess shipment; optional inventory integration.
5. Delivery notes: unique numbering, shipment lines, date, ship-to address, carrier/tracking, signed proof of delivery and PDF/email to configured customer contact.
6. Backorders, partial deliveries, multiple delivery notes, rejected goods, returns and replacement shipments.
7. Create one or more invoices for delivered quantities (or authorised deposits/progress billing) with complete links to the sales order and delivery note; avoid duplicate invoicing.
8. Integrate VAT, payment terms, customer payments, credit notes, debt collection and audit trail.

**Acceptance:** Delivered and invoiced quantities reconcile to ordered quantities, with explicit exceptions and traceable partial shipments.

## ERP-000D — Document email and outbound communications

1. Company-scoped outbound provider abstraction (SMTP / approved email API) with encrypted secrets; separate from login identity.
2. Purpose-coded recipients resolved from supplier/customer contact directory; support To/CC/BCC, approved manual recipient change and fallback when code unavailable.
3. Templates by document type and company, merge fields, email signatures, locale, subject/body, attachments and PDF preview.
4. Draft message → preview → approval (if required) → explicit send; no automatic email simply because a PO/invoice is saved.
5. Reliable dispatch via queued delivery, idempotency key, retry/backoff and explicit failed/unknown statuses; audit operator, recipient, message-id and sent document revision.
6. Record supplier PO acknowledgements and replies when a supported inbound-mail connection is deliberately enabled. Never claim sending or receiving without a configured provider and verified result.
7. Exclude personal or sensitive data from logs; honour permission/retention policies, delivery failures and manual resend safeguards.

**Acceptance:** Sending uses the correct purpose-coded supplier contact, requires authorised operator or approved automated rule, prevents duplicate sends on retry, retains full audit trail.

## ERP-000E — Common workflow, screens, reports and exceptions

- Unified navigation: Purchasing / Sales / Fulfilment / Invoices / Communications.
- Dashboards and work queues for pending approval, orders to issue, overdue acknowledgements, overdue deliveries, GRNs to process, received-not-invoiced, delivery-not-invoiced, invoices unpaid, failed emails.
- Document chain viewer, e.g. PR → PO → GRN → supplier bill → payment, and Quote → SO → Delivery note → invoice → receipt.
- Company-specific custom workflow triggers: document type, amount bands, supplier/customer, project, product class, exception category, approver group/individual. Preserve independent checker and immutable approved content.
- Reports: order commitments, outstanding PO/SO, received-vs-invoiced reconciliation, GRNI, fulfilment performance, partial delivery, vendor lead time, rejected stock, financial audit history.
- Public API contracts, event/outbox design and repeatable browser/API/service regression tests.

## Proposed delivery increments

| ID | Work item | Release gate |
| --- | --- | --- |
| ERP-000.1 | Gap audit, lifecycle data model, line-level traceability, API and UX specification | No data loss, backward-compatible migrations |
| ERP-000.2 | Supplier/customer contact purpose codes, document settings and templates | Company-bound recipients, safe preview |
| ERP-000.3 | Multi-line PO + PR, approvals, PDF issuance | Approval before issue, document revision and numbering |
| ERP-000.4 | GRN and line-level partial receipt, return/rejection | Reconcile received/accepted/rejected PO quantities |
| ERP-000.5 | PO/GRN/Invoice matching and supplier bills | 2-/3-way match, duplicate/variance exceptions |
| ERP-000.6 | SO multi-line fulfilment, picking and delivery notes | Partial dispatch and quantity reconciliation |
| ERP-000.7 | Delivery-linked sales invoicing and credit/returns | No double invoice; tax/payment flows tested |
| ERP-000.8 | Provider-backed supplier/customer email communication | Explicit approval, idempotency, failure/audit |
| ERP-000.9 | End-to-end UI, reports, integration and UDA acceptance | Full CI, accounting reconciliation and independent sign-off |

## Dependency and sequencing

- **ERP-000 is a new operational ERP workstream**, separate from `legacy_import/cashlink`, but comes **before ERP-001** in recommended development order.
- Existing quote/order/bill/invoice functions are the initial codebase to extend.
- Phase ERP-000.1 should determine precisely which tables, screens, APIs and conversions can be reused before migrations start.
- Custom workflows DEV-014 supplies configurable approval roles and thresholds; document actions must be wired to its service layer to prevent bypasses.
- The future Inventory module v0.6 can expand receiving/picking/stock valuation but ERP-000 must define clear minimum GRN and delivery-note records first.
- External email dispatch requires an approved configured provider and credentials: build a dry-run/outbox preview first.
- Legacy data import ERP-001–006 should map into the final operational document model, not bypass it.

## Definition of done

- One company cannot view/change another's operational records, contacts, messages or orders.
- Multiple documents and lines are related by stable IDs and immutable source references.
- Every stage has authorised actions, audit history, meaningful statuses, correction and cancellation handling.
- Quantity/value invariants tested with partial receipts, partial deliveries, returns, VAT and duplicate attempts.
- No direct posting bypass of configured approval rules; no direct email dispatch bypass of authorisation.
- CI green before merging, clean migration validation, and UDA live acceptance separately verified.
