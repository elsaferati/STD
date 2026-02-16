## React Dashboard (match `front-end/front-end-design.html`) + Backend API Integration

### Summary
Build a client-facing React dashboard (Overview, Orders Workspace, Order Detail, Login) that matches the provided Tailwind template and pulls **real data** from the existing Flask backend (reading `OUTPUT_DIR/*.json` and generated XMLs). Frontend and backend are **separately deployed**, so we add **CORS** + **Bearer-token auth** to `/api/*` and provide API endpoints that the React UI consumes. Dashboard updates via **auto-polling**.

---

## Backend (Flask) — API, Auth, CORS, CSV, File Downloads

### Goals / success criteria
- React can load all screens using only `/api/*` calls + authenticated file downloads.
- `/api/*` is protected with `Authorization: Bearer <token>` (from `DASHBOARD_TOKEN`).
- CORS allows only configured origins (`DASHBOARD_ALLOWED_ORIGINS`) for `/api/*`.
- Existing Jinja dashboard routes remain functional (no breaking changes).

### Changes (in `app.py`)
1. **Add auth utilities**
   - Env var: `DASHBOARD_TOKEN` (required for `/api/*`).
   - Implement `require_auth(request)`:
     - If request is `OPTIONS`: allow (for preflight).
     - Read `Authorization` header; require `Bearer …`.
     - If missing/invalid: return `401` JSON.

2. **Add CORS (specific origins)**
   - Env var: `DASHBOARD_ALLOWED_ORIGINS` as comma-separated list (e.g. `https://dashboard.example.com,http://localhost:5173`).
   - Apply CORS only to `/api/*` responses:
     - `Access-Control-Allow-Origin: <origin-if-allowed>`
     - `Vary: Origin`
     - `Access-Control-Allow-Headers: Authorization, Content-Type`
     - `Access-Control-Allow-Methods: GET, POST, PATCH, OPTIONS`
     - `Access-Control-Max-Age: 86400`
   - Provide a generic `/api/<path:any>` `OPTIONS` handler returning an empty `204`.

3. **Add a lightweight output index cache (for polling)**
   - Build an in-memory index of orders from `OUTPUT_DIR/*.json`.
   - Recompute only when directory contents/mtimes changed (or TTL like 2–5 seconds).
   - This avoids re-parsing hundreds/thousands of files every 10–15 seconds per client.

4. **API endpoints (all require auth)**
   - `GET /api/auth/check`
     - Returns `204` if token valid (used by Login screen).
   - `GET /api/overview`
     - Returns:
       - KPI metrics (total, ok/partial/failed rates) for “today” and/or last 24h (use `received_at` if parseable else file `mtime`).
       - Queue counts: `reply_needed`, `human_review_needed`, `post_case`.
       - `status_by_day` for last 7 days (for stacked bar chart).
       - `processed_by_hour` for last 24h (for “Queue Velocity” line; single series derived from outputs).
       - `latest_orders` list (e.g. 20 most recent).
   - `GET /api/orders`
     - Query params:
       - `q` (search across `ticket_number`, `kom_nr`, `kom_name`, `message_id`, filename)
       - `from` / `to` (YYYY-MM-DD, based on effective received date)
       - `status` (comma list: `ok,partial,failed,unknown`)
       - `reply_needed`, `human_review_needed`, `post_case` (true/false)
       - `page`, `page_size` (server-side pagination)
       - `sort` (`received_at_desc` default)
     - Returns `{ orders, pagination, counts }` where `counts` includes tab totals (all, today, needs reply, manual review).
   - `GET /api/orders/<order_id>`
     - Returns full order payload plus:
       - `order_id`, `parse_error`
       - `xml_files` list (if present)
       - `is_editable` (same rule as current UI: `human_review_needed && !parse_error`)
       - `reply_mailto`
   - `PATCH /api/orders/<order_id>`
     - Only allowed if `is_editable`.
     - Body shape (decision-complete):
       - `{ "header": { "<field>": "<string>" }, "items": { "<index>": { "<field>": "<string>" } } }`
     - Server behavior:
       - Apply `_set_manual_entry` to provided fields only.
       - Run `refresh_missing_warnings(data)`.
       - Save JSON back to disk.
       - Attempt `xml_exporter.export_xmls(...)`.
       - Return updated order + `{ xml_regenerated: true/false }`.
   - `POST /api/orders/<order_id>/export-xml`
     - Regenerates XML and returns `{ xml_files: [...] }`.
   - `GET /api/orders.csv`
     - Honors the same filters as `GET /api/orders` (but ignores pagination unless explicitly provided).
     - Returns CSV download of the current filtered result set with columns aligned to the Workspace table (received_at, status, ticket/kom, customer/store fields, items, warnings, errors, flags).
   - `GET /api/files/<filename>`
     - Auth-protected download for XML (and optionally JSON) from `OUTPUT_DIR`.
     - Uses the existing safe filename validation (no path traversal).
     - React uses this endpoint because cross-origin downloads can’t easily attach `Authorization` headers via plain `<a href>`.

5. **Error handling contract**
   - All API errors return JSON: `{ error: { code, message } }` with appropriate status.
   - `401` on auth failures; `404` for missing orders/files; `403` for non-editable orders.

### Backend env vars to document
- `DASHBOARD_TOKEN=...` (required)
- `DASHBOARD_ALLOWED_ORIGINS=https://dashboard.example.com,http://localhost:5173`
- Existing: `OUTPUT_DIR`, `DASHBOARD_HOST`, `DASHBOARD_PORT`

---

## Frontend (React/Vite) — Template-Matched UI + API Integration

### Goals / success criteria
- UI closely matches the Tailwind template (colors, fonts, layout, components).
- All displayed data comes from backend APIs (no hardcoded demo rows).
- Works with separate deploy via `VITE_API_BASE_URL` and Bearer token auth.
- Auto-refreshes Overview + Orders list every ~15s.

### Project changes (`front-end/my-react-app`)
1. **Styling: Tailwind (build-time)**
   - Install Tailwind + PostCSS + Autoprefixer + `@tailwindcss/forms`.
   - Create Tailwind config matching template tokens:
     - colors: `primary`, `primary-dark`, `background-light`, `background-dark`, `surface-light`, `surface-dark`, `success`, `warning`, `danger`
     - fonts: `Space Grotesk` (and IBM Plex Sans for Login if desired; otherwise keep Space Grotesk consistently)
   - Update `src/index.css` to include Tailwind directives and any small custom utilities (e.g. scrollbar hide).

2. **Routing**
   - Add `react-router-dom`.
   - Routes:
     - `/login` → Login page (template)
     - `/` → Overview dashboard (template “Operations Overview Dashboard”)
     - `/orders` → Orders Workspace (template “Orders Management Workspace”)
     - `/orders/:orderId` → Order Detail (template “Order Extraction Detail View”)

3. **Auth + API client**
   - Add `VITE_API_BASE_URL` (defaults to empty string if same-origin; otherwise required for separate deploy).
   - Implement:
     - `src/api/http.js`: `fetchJson(path, { token, ... })` adding `Authorization: Bearer …` and handling `401` centrally.
     - `src/auth/AuthContext.jsx`: stores token in `localStorage`, exposes `login(token)`, `logout()`.
     - ProtectedRoute wrapper: redirects to `/login` if no token or `/api/auth/check` fails.

4. **Polling**
   - Overview page polls `GET /api/overview` every 15 seconds (and on demand “Refresh” button).
   - Orders Workspace polls `GET /api/orders` every 15 seconds (keeps current filters + pagination).
   - Order Detail does **not** auto-poll while editing; polls only when not in edit mode (or manual refresh).

5. **Pages (match template, but mapped to real data)**
   - **Login**
     - Token input + “Sign in” button.
     - On submit: store token → call `/api/auth/check` → navigate to `/`.
   - **Overview**
     - Navbar (search box can set `q` and navigate to `/orders?q=...`).
     - KPI cards:
       - Total orders (today)
       - OK/Partial/Failed rates (today)
       - Queue counts (reply needed / review / post case)
     - Charts:
       - Stacked bars from `status_by_day` (7 days)
       - Line from `processed_by_hour` (24h)
     - Latest orders table:
       - Rows from `latest_orders`
       - Actions: “Open” → `/orders/:id`
   - **Orders Workspace**
     - Left sidebar filters:
       - date range (`from/to`)
       - status multi-select
       - workflow flag toggles
     - Tabs with counts from API (`all`, `today`, `needs_reply`, `manual_review`)
     - Table rows from `/api/orders` (replace template “Amount” with a real field, e.g. `delivery_week` or `liefertermin`; decision locked: use `delivery_week` if present else `liefertermin`).
     - Row actions:
       - View details
       - Export XML (calls `/api/orders/:id/export-xml`)
       - Download XML (calls `/api/files/<filename>` via authenticated fetch + blob)
     - “Manual Order” button: hidden/disabled per your choice.
     - “Export CSV” button: triggers download from `/api/orders.csv` with current filters.
   - **Order Detail**
     - Header actions:
       - Regenerate XML
       - Edit fields (only if `is_editable`)
       - Send Reply (open `reply_mailto` in new tab if `reply_needed`)
     - Header fields table:
       - Show `value`, `source`, `confidence`; highlight low-confidence rows (<0.9) when “Highlight Low Conf.” enabled.
       - In edit mode: allow editing only the backend’s editable fields list.
     - Items table:
       - line_no, artikelnummer, modellnummer, menge, furncloud_id
       - In edit mode: editable inputs for those fields.
     - Signals panel:
       - Render `warnings` and `errors` as cards (warning/info/error styling).
     - Contextual footer in edit mode:
       - Discard (re-fetch order)
       - Save & Verify → `PATCH /api/orders/:id` then show success and refreshed XML list.

6. **Assets / icons / fonts**
   - Add Google Fonts + Material Icons links to `front-end/my-react-app/index.html` (as in template).
   - Keep avatar/profile as placeholder static assets (no backend dependency).

7. **Config docs**
   - Add `front-end/my-react-app/.env.example`:
     - `VITE_API_BASE_URL=https://api.example.com`
   - Update root `README.md` with:
     - Backend env: `DASHBOARD_TOKEN`, `DASHBOARD_ALLOWED_ORIGINS`
     - Frontend env: `VITE_API_BASE_URL`
     - Run instructions (dev): `python app.py` + `npm run dev`
     - Deploy notes: set allowed origins to the deployed dashboard URL(s)

---

## Public Interfaces / Contracts (explicit)
- **Auth header**: `Authorization: Bearer <DASHBOARD_TOKEN>`
- **CORS**: only origins in `DASHBOARD_ALLOWED_ORIGINS` can call `/api/*`
- **Primary endpoints**: `/api/overview`, `/api/orders`, `/api/orders/<id>`, `/api/orders.csv`, `/api/files/<filename>`

---

## Test cases / validation
1. **Auth**
   - No token → `/api/overview` returns `401`
   - Valid token → `/api/auth/check` returns `204`
2. **CORS**
   - Request from allowed origin passes preflight + succeeds
   - Request from non-allowed origin lacks `Access-Control-Allow-Origin`
3. **Overview**
   - KPI counts match the same underlying output JSON set as the Flask Jinja dashboard.
4. **Orders Workspace**
   - Filters (status/date/flags/search) change results and pagination correctly.
   - CSV export downloads and contains filtered rows.
5. **Order Detail edit**
   - Non-editable order → edit/save blocked (`403`)
   - Editable order → PATCH updates JSON on disk, warnings refresh, XML regeneration attempted.
6. **File download**
   - XML download via `/api/files/<filename>` works with token and produces correct attachment.

---

## Assumptions (locked defaults)
- “Incoming vs processed” is represented as **processed outputs per hour** (derived from JSON file timestamps / `received_at`), since true “incoming queue” isn’t currently persisted.
- Date bucketing uses `received_at` if valid ISO; otherwise file `mtime`.
- “Manual Order” is not implemented; button is hidden/disabled.
