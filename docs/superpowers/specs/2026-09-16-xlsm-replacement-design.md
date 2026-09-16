# XLSM Replacement Design

## Goal

Replace the operational Excel macro with a trusted import-inventory ledger and an export matching workbench while preserving the macro's familiar concatenated result format.

## Confirmed workflow

1. Upload an import workbook and review new, duplicate, conflicting, and invalid rows.
2. Confirm valid new import lots into the cumulative inventory ledger.
3. Upload an export workbook and process it in the background.
4. Review each export row with its planned FIFO allocations and any `NO MATCH` shortage.
5. Confirm the export file in one transaction.
6. Download a workbook containing concatenated export/import evidence plus the current inventory balance.
7. Revert the confirmed export file as one unit when necessary.

## Matching rules

- Normalize Part Number by removing spaces, non-breaking spaces, tabs, carriage returns, and line feeds, then uppercase it.
- Equal normalized Part Number is the only eligibility condition.
- Require positive remaining quantity.
- Order candidates by import accepted date, declaration number, line number, and row number.
- Do not use origin, date, HS code, specification, unit, price, or amount as match keys.
- Copy the selected import lot's HS code and specification into each allocation result.
- Allocate across multiple lots until the export quantity is satisfied or inventory is exhausted.
- Preserve successful allocations and append one `NO MATCH` row for any shortage.

## Data and transaction boundaries

- Import uploads add new lots. An exact duplicate is ignored. A same-key/different-value conflict blocks the batch.
- An import lot business key is declaration number, line number, row number, normalized Part Number, and origin.
- `remaining_qty` in the source is the opening balance when present; otherwise opening balance equals import quantity.
- Preview never mutates inventory.
- Export confirmation recomputes the inventory fingerprint and rejects a stale preview.
- Confirmation and export-file reversion are atomic SQLite transactions.
- Reversion restores allocation quantities and keeps the batch, requirements, and allocations as history.
- Confirmed import batches cannot be reverted in the UI.

## UI

- The primary page is an operations workbench with separate `수입 재고 추가` and `수출 매칭 시작` actions.
- Navigation is limited to workbench, inventory, and history.
- Uploads show queued, processing, review-ready, failed, confirmed, and reverted states.
- Export review groups rows by the original export line; expanding a row shows its import allocations and shortage.
- All large tables use server-side search, filters, ordering, and 50-row pagination.
- The interface is desktop-first, keyboard accessible, and remains usable on narrow screens.

## Files, output, and security

- Accept `.xlsx`, `.xlsm`, and `.csv`; never execute VBA.
- Store the original file under `/data/uploads/<uuid>/` with its hash and safe filename.
- The result workbook uses two header rows: source groups on top, then the exact ten source column names from `수출 문서.xlsx` and `수입 문서.xlsx`; shortages use `NO MATCH`.
- Each allocation exposes `차감 전 수량`, `차감 수량`, and `차감 후 잔량`; shortages expose `미배정 수량`.
- The second workbook sheet contains the exact ten import source columns plus `차감 수량` and `차감 후 잔량`.
- Preserve price and amount when supplied but never use them for matching.
- Protect every non-health route with one shared environment-configured account.
- Use a signed HTTPS-only session cookie, CSRF protection, PBKDF2 password verification, and login throttling.
- Background workers create their own database sessions and persist progress so page requests stay responsive.

## Explicit exclusions

- No manual row entry or browser spreadsheet editing.
- No individual accounts or roles.
- No evidence-document attachments, UNI-PASS integration, OCR, or AI decisions.
- No import-batch reversion and no automatic shortage retry.

## Release

- Deploy through the existing `main` CI/CD pipeline.
- Back up the current remote SQLite file, reset demo data, run an end-to-end check with the supplied workbooks, and reset again so the live demo starts empty.
