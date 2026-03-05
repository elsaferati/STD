# DB-Only Storage Cutover (Remove JSON Completely)

## Summary
Migrate the app to a strict database-only model for order payloads and metadata, with no JSON file reads/writes/fallbacks. Keep legacy Flask HTML routes, but rewrite them to use DB APIs internally. Disable JSON file downloads. Use fail-fast behavior if DB is unavailable. Delete existing `output/*.json` immediately after cutover.

## Public API / Interface Changes
1. `GET /api/files/<filename>`
- Change allowed extensions from `{".xml", ".json"}` to `{".xml"}` only.
- `.json` requests return `403 forbidden` (or `404` if preferred for concealment; use `403` consistently with current style).

2. Legacy HTML routes remain same paths:
- `/`
- `/order/<order_id>`
- `/order/<order_id>/export-xml`
- `/order/<order_id>/delete`
- Internal implementation changes to DB-backed logic.

3. Runtime config behavior
- Remove runtime JSON fallback behavior from code paths.
- Treat DB as mandatory data source for dashboard and legacy pages.
- Keep `ORDER_DB_ENABLED` in env only if needed for boot compatibility, but code should no longer branch to file-backed mode.

## Implementation Plan

### 1. Make ingestion DB-only (stop JSON file creation)
1. Update `main.py` ingestion loop:
- Remove JSON file write (`json.dump` to `output/*.json`).
- Keep `order_store.upsert_order_payload(...)` as the source of truth.
- Keep XML generation (`xml_exporter.export_xmls(...)`) and XML file registration in `order_files`.
- Remove registration of `file_type="json"` entries.

2. Keep XML artifacts on disk for downstream download/export workflows.

### 2. Remove JSON fallback from API/backend core
1. In `app.py`, refactor `_get_order_index()`:
- Remove `_list_orders(OUTPUT_DIR)` fallback.
- Always fetch summaries from `order_store.list_order_summaries()`.
- Keep in-memory cache TTL if desired for performance, but cache DB results only.

2. Refactor `_load_order(order_id)`:
- Remove file-path branch (`OUTPUT_DIR/<id>.json`).
- Always load via `order_store.get_order_detail()` with UUID validation.

3. Refactor export helpers:
- `_load_order_export_data()` must always source payload from DB (`order_store.get_order_detail` / `get_order_payload_map`).
- Remove file read branch for payload export.

4. Keep fail-fast policy:
- DB errors should return API errors (`500 db_error`) with no filesystem fallback.

### 3. Rewrite legacy Flask HTML routes to DB-backed behavior
1. `index()`:
- Replace `_list_orders(OUTPUT_DIR)` with `_get_order_index()`.

2. `order_detail()`:
- Replace direct JSON file open/write with `_load_order()` and `order_store.save_manual_revision(...)`.
- Maintain existing template context shape (`header_rows`, `item_rows`, `warnings`, `errors`, `raw_json`), where `raw_json` comes from DB payload serialization.
- Preserve editability checks and reply/post flags from DB-backed payload/status.

3. `export_order_xml()`:
- Load payload from DB, generate XML from payload, register resulting XML files in DB events/files metadata.

4. `delete_order()`:
- Use `order_store.soft_delete_order(...)` consistently (no JSON unlink/delete path).

### 4. Tighten download policy
1. Update `ALLOWED_DOWNLOAD_EXTENSIONS` to XML only.
2. Keep current file-serving behavior for XML files in `output/`.
3. Ensure order detail and API surfaces never advertise JSON files as downloadable artifacts.

### 5. Clean up file-based order code paths
1. Remove or isolate unused file-order helpers once references are gone:
- `_list_orders(...)`
- `_build_output_signature(...)` if no longer needed
- Any direct `path.write_text(...json...)` branches for order persistence
2. Keep non-order file serving for XML only.

### 6. Data cutover and cleanup
1. Pre-cutover:
- Run `backfill_orders_db.py` to ensure DB has all historical payloads.
- Validate parity: total order count and spot-check random order payloads.
2. Cutover deploy:
- Deploy DB-only code.
3. Immediate cleanup (per chosen policy):
- Delete `output/*.json` files after successful deploy validation.
- Keep XML files intact.

## Test Cases and Scenarios

1. Ingestion
- New incoming email creates/updates DB order and revision.
- No `output/<something>.json` is created.
- XML files are still generated and downloadable.

2. API list/detail
- `GET /api/orders`, `GET /api/overview`, `GET /api/orders/<id>` return expected data with DB-only mode.
- Behavior remains correct with filters/search/sort/pagination.

3. Mutations
- `PATCH /api/orders/<id>` persists edits in DB and regenerates XML.
- `DELETE /api/orders/<id>` soft-deletes in DB and disappears from list APIs.

4. Export/download
- `GET /api/orders.csv` and `GET /api/orders.xlsx` export from DB payloads.
- `GET /api/files/<xml>` works.
- `GET /api/files/<json>` is rejected.

5. Legacy pages
- `/` loads from DB data.
- `/order/<id>` displays and edits DB payload.
- Legacy XML export/delete actions operate correctly without JSON files.

6. Failure mode
- Simulated DB outage returns server errors; no silent fallback to files.

## Rollout and Monitoring
1. Deploy during low-traffic window.
2. Monitor:
- API 5xx rate
- DB query latency for order list/detail/overview
- XML generation failures
3. Keep DB backup before cutover.
4. Post-cutover verification checklist:
- No new JSON files created.
- No code paths reference JSON order files.
- All UI pages (React + legacy) function with DB-only data.

## Assumptions and Defaults (Locked)
1. Keep legacy Flask pages and make them DB-backed.
2. Ingestion switches to immediate DB-only writes (no dual-write period).
3. JSON downloads are disabled.
4. DB outage policy is fail-fast (no JSON fallback).
5. Existing `output/*.json` files are deleted immediately after successful cutover validation.
