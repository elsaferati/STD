## Frontend Redesign: Fixed Nav Sidebar + Simpler Dashboard

### Summary
Update the authenticated React UI (`front-end/my-react-app`) to use a **fixed left navigation sidebar** with **Dashboard / Orders / Clients / Settings**. Redesign the **Dashboard (Overview)** statistics to be **simpler and more user friendly**: **4 KPI cards + 1 small 24h sparkline**, keeping the “Latest Orders” table. `Clients` and `Settings` will be **placeholder pages** for now.

---

## Decisions Locked In (from you)
- Sidebar behavior: **Fixed** (always visible).
- Sidebar items: **Dashboard + Orders + Clients + Settings**.
- Clients page: **Placeholder only** (no backend/API work).
- Dashboard stats: **4 KPIs + 1 sparkline**.

---

## Implementation Plan

### 1) Add shared app shell + sidebar nav (new components)
**Create** `front-end/my-react-app/src/components/SidebarNav.jsx`
- Renders:
  - Logo block (reuse existing “XXLUTZ Agent” styling from `OrdersPage.jsx`).
  - Nav list using `NavLink`:
    - Dashboard → `/`
    - Orders → `/orders` (active for `/orders` and `/orders/:orderId`)
    - Clients → `/clients`
    - Settings → `/settings`
- Active styling: primary text + subtle background (Tailwind classes consistent with existing palette).
- Icons: Material Icons (already loaded in `index.html`).

**Create** `front-end/my-react-app/src/components/AppShell.jsx`
- Layout (right side is the scroll container):
  - Outer: `min-h-screen flex overflow-hidden bg-background-light font-display text-slate-800`
  - Left: fixed `aside` (`w-72`, border, shadow) containing:
    - `SidebarNav`
    - Optional `sidebarContent` slot (shown below nav; used by Orders filters)
  - Right: `div.flex-1.flex.flex-col.min-w-0`
    - Top bar header (height `h-16`): global search + Logout button
      - Search submit navigates to `/orders?q=...` (empty => `/orders`)
    - Main content: `main.flex-1.overflow-auto` with standard padding (e.g. `p-6`)
- Uses `useAuth()` for `logout`.
- Keeps UI consistent across Overview / Orders / Order Detail / placeholder pages.

### 2) Add placeholder pages + routes
**Create** `front-end/my-react-app/src/pages/ClientsPage.jsx`
- Wrap in `AppShell`.
- Simple header (“Clients”) + empty-state card (“Coming soon”).

**Create** `front-end/my-react-app/src/pages/SettingsPage.jsx`
- Wrap in `AppShell`.
- Simple header (“Settings”) + empty-state card (“Coming soon”).

**Update** `front-end/my-react-app/src/main.jsx`
- Add protected routes:
  - `/clients` → `ClientsPage`
  - `/settings` → `SettingsPage`

### 3) Refactor existing pages to use `AppShell` (so sidebar appears everywhere)
**Update** `front-end/my-react-app/src/pages/OrdersPage.jsx`
- Remove its current outer page layout (`<aside>...<header>...`) and instead:
  - `return <AppShell sidebarContent={...filters...}> ...orders workspace... </AppShell>`
- Move the existing filter UI (Extraction Date / Status / Workflow Flags) into `sidebarContent`.
- Remove page-level search + logout (top bar now provides both).
- Keep existing tabs, export CSV, table, pagination behavior unchanged.

**Update** `front-end/my-react-app/src/pages/OverviewPage.jsx`
- Replace its current top header with `AppShell` (no `sidebarContent`).
- Keep the same polling + `fetchJson("/api/overview")`.
- Redesign stats to match: **4 KPIs + 1 sparkline**
  - KPIs:
    1) **Today Orders** (`overview.today.total`)
    2) **OK Rate** (`overview.today.ok_rate`)
    3) **Needs Attention** (sum of `queue_counts.reply_needed + human_review_needed + post_case`)
       - Subtitle: `Reply x · Review y · Post z`
    4) **Last 24h Orders** (`overview.last_24h.total`)
  - Sparkline panel:
    - Reuse existing `buildLineSeries()` + `processed_by_hour` to render the small 24h trend.
  - Remove the 7-day stacked status chart section (to keep it simpler).
- Keep “Latest Orders” table (as the main actionable area).

**Update** `front-end/my-react-app/src/pages/OrderDetailPage.jsx`
- Wrap page content in `AppShell` so the nav sidebar exists here too.
- Keep the existing order header (breadcrumbs + actions) but move it into the scrollable content area (no conflict with the AppShell top bar).
- Preserve current behavior: polling when not editing, edit mode bar, XML downloads, etc.

### 4) Acceptance checks (manual + build)
- Navigation:
  - Sidebar visible on `/`, `/orders`, `/orders/:id`, `/clients`, `/settings`
  - Active highlighting works (Orders stays active on order detail)
- Search:
  - Submitting search from any page routes to `/orders?q=...`
- Dashboard:
  - Exactly 4 KPI cards + 1 24h sparkline + Latest Orders table
  - No 7-day chart
- Orders:
  - Filters still work (query params update, polling continues)
- Build/lint:
  - `cd front-end/my-react-app; npm run build`
  - `cd front-end/my-react-app; npm run lint`

---

## Assumptions
- No backend changes needed (Clients/Settings are placeholders).
- Desktop-first fixed sidebar is acceptable; mobile behavior remains basic for now (no hamburger/drawer work).
