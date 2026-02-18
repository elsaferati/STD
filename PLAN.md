# Export Orders As 2-Sheet Excel (Header + Items)

## Summary
Replace the current “Export CSV” behavior in the Orders UI with an Excel `.xlsx` download containing two worksheets:
- `Header`: one row per order with order-level + header-field values
- `Items`: one row per item across all exported orders, linked back to its order

## User-Facing Behavior (Success Criteria)
- Clicking export on the Orders page downloads `orders.xlsx`.
- The workbook contains exactly 2 sheets named `Header` and `Items`.
- `Header` sheet has one row per order and includes the header fields (values only).
- `Items` sheet has one row per item and includes item fields (values only), plus order identifiers.
- Export respects the same filters as today (query string params on the Orders page).

## Backend Changes (Flask)
### 1. Add a new endpoint
- Add `GET /api/orders.xlsx` in `app.py`.
- It should call `_query_orders(allow_default_pagination=False)` to export all matching orders (same as current CSV export).

### 2. Build an `.xlsx` in memory (openpyxl)
- Use `openpyxl` (already in `requirements.txt`) to generate the workbook.
- Return a `Response` with:
  - `Content-Type`: `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
  - `Content-Disposition`: `attachment; filename=orders.xlsx`
  - Body: workbook bytes (via `io.BytesIO()` + `workbook.save()`)

### 3. Data extraction strategy (values only)
For each order returned by `_query_orders(...)[“orders”]` (these are index rows):
- Read the underlying JSON file directly using `order["file_name"]` and `OUTPUT_DIR` (avoid `_load_order()` because it returns API error tuples on failure).
- Parse:
  - `header`: dict of `{field: {value, source, confidence, ...}}`
  - `items`: list of dicts like `{artikelnummer: {value,...}, ..., line_no: N}`
  - `warnings`, `errors`, `status`, `received_at`, `message_id`
- Convert “entry dicts” to plain values using `entry.get("value", "")` when `entry` is a dict, else stringify safely.

### 4. Sheet schemas (decision complete)
#### `Header` sheet columns
- Fixed meta columns (in this order):
  - `order_id` (index row `id`)
  - `file_name`
  - `message_id`
  - `received_at`
  - `status`
  - `item_count`
  - `warnings_count`
  - `errors_count`
  - `reply_needed`
  - `human_review_needed`
  - `post_case`
  - `warnings` (joined with ` | `)
  - `errors` (joined with ` | `)
  - `parse_error` (JSON read/parse error string, blank if none)
- Header field columns (values only):
  - Ordered as: `EDITABLE_HEADER_FIELDS` first (from `app.py`), then any remaining header keys seen in exported orders sorted alphabetically.
  - Exclude duplicates of the fixed meta flags if they also appear in the header dict (`reply_needed`, `human_review_needed`, `post_case`) to avoid double columns.

One row per order.

#### `Items` sheet columns
- Fixed columns (in this order):
  - `order_id`
  - `ticket_number` (pulled from the order header value)
  - `kom_nr` (pulled from the order header value)
  - `kom_name` (pulled from the order header value)
  - `line_no` (from item dict, fallback to 1-based index)
- Item field columns (values only):
  - Ordered as: `EDITABLE_ITEM_FIELDS` first, then any remaining item keys (excluding `line_no`) sorted alphabetically.

One row per item across all exported orders.

### 5. Minimal Excel usability tweaks
- Freeze header rows: `Header!A2`, `Items!A2`.
- Write the first row as column headers.
- No styling beyond that (keeps implementation small and robust).

### 6. Keep existing CSV route for compatibility
- Leave `GET /api/orders.csv` as-is (legacy), but the UI will switch to `.xlsx`.

## Frontend Changes (React)
### 1. Switch export to the new endpoint
In `front-end/my-react-app/src/pages/OrdersPage.jsx`:
- Update the export handler to fetch `/api/orders.xlsx` (preserving the existing query string).
- Download filename: `orders.xlsx`.
- Change the busy-action key from `"csv"` to `"excel"` (or keep `"csv"` but recommended to rename for clarity).

### 2. Update UI label and error messages
In `front-end/my-react-app/src/i18n/translations.js`:
- Add `common.exportExcel` for `en` and `de`.
- Add `orders.excelExportFailed` for `en` and `de`.
In `front-end/my-react-app/src/pages/OrdersPage.jsx`:
- Button text uses `t("common.exportExcel")`.
- Error fallback uses `t("orders.excelExportFailed")`.

## Public Interfaces / API Changes
- New: `GET /api/orders.xlsx` returns an `.xlsx` with sheets `Header` and `Items`.
- Existing: `GET /api/orders.csv` remains unchanged but is no longer used by the UI after this change.

## Test Plan (Manual)
1. Start backend and frontend as you do today.
2. In the Orders page, set filters (date range, status, q search).
3. Click export and verify `orders.xlsx` downloads.
4. Open `orders.xlsx` and verify:
   - Two sheets exist named `Header` and `Items`.
   - `Header` has one row per order and contains expected header fields (values, not dicts).
   - `Items` has multiple rows per order where applicable and includes `order_id`, `ticket_number`, `kom_nr`, `line_no`, and item fields.
5. Spot-check an order with missing fields and verify blanks rather than crashes.
6. Export with no matching orders and verify you still get a valid workbook with headers and zero data rows.

## Assumptions (Locked)
- “2 sheets” means a real Excel workbook (`.xlsx`), not a CSV trick.
- “Displayed data” means field values only (no `source`/`confidence` columns).
- The export should cover the current filtered result set, not just the current page.
