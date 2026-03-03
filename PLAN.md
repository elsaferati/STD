Plan: Unified Status System (Replace partial + flags with single status)                          │
│                                                                                                   │
│ Context                                                                                           │
│                                                                                                   │
│ Currently orders have a two-layer system: a primary status (ok/partial/failed) plus separate      │
│ boolean flags (reply_needed, human_review_needed, post_case). "Partial" dominates (143/150        │
│ orders) and the flags appear as stacked badges on top, which is redundant and confusing. The new  │
│ system collapses everything into one unified status field — the flags still exist in the header   │
│ JSON (pipeline logic unchanged) but the status field is now derived from the flags directly, and  │
│ the UI shows only the status badge (flags column removed).                                        │
│                                                                                                   │
│ New status values and priority:                                                                   │
│ reply → human_in_the_loop → post → ok                                                             │
│ (failed stays separate — set when the pipeline produces no structure and no items at all)         │
│                                                                                                   │
│ ---                                                                                               │
│ Architecture                                                                                      │
│                                                                                                   │
│ The pipeline flags (reply_needed, human_review_needed, post_case) are still set exactly as today  │
│ — no pipeline logic changes. Only the STATUS DERIVATION changes: instead of computing status from │
│  missing-field counts, we derive it from the flags after they're set.                             │
│                                                                                                   │
│ ---                                                                                               │
│ Changes Required                                                                                  │
│                                                                                                   │
│ 1. normalize.py — Two locations                                                                   │
│                                                                                                   │
│ A. normalize_output() (~line 1544–1551)                                                           │
│                                                                                                   │
│ Add a not items → reply_needed trigger (currently missing), then replace the partial/ok           │
│ assignment with flag-driven logic:                                                                │
│                                                                                                   │
│ # ADD: ensure reply_needed when no items extracted                                                │
│ if not items:                                                                                     │
│     _set_reply_needed_from_derived(header)                                                        │
│                                                                                                   │
│ # REPLACE the old partial/ok block:                                                               │
│ def _flag_true(h: dict, key: str) -> bool:                                                        │
│     e = h.get(key)                                                                                │
│     return (e.get("value") is True) if isinstance(e, dict) else (e is True)                       │
│                                                                                                   │
│ if not had_structure and not items:                                                               │
│     data["status"] = "failed"                                                                     │
│ elif _flag_true(header, "reply_needed"):                                                          │
│     data["status"] = "reply"                                                                      │
│ elif _flag_true(header, "human_review_needed"):                                                   │
│     data["status"] = "human_in_the_loop"                                                          │
│ elif _flag_true(header, "post_case"):                                                             │
│     data["status"] = "post"                                                                       │
│ else:                                                                                             │
│     data["status"] = "ok"                                                                         │
│                                                                                                   │
│ Note: _flag_true can be a module-level private helper or inlined — either is fine.                │
│                                                                                                   │
│ B. refresh_missing_warnings() (~line 1618–1622)                                                   │
│                                                                                                   │
│ Same replacement — it already calls _set_reply_needed_from_derived() for missing fields, just     │
│ change the status assignment:                                                                     │
│                                                                                                   │
│ # REPLACE:                                                                                        │
│ if missing_header or critical_missing_items or not items:                                         │
│     data["status"] = "partial"                                                                    │
│ else:                                                                                             │
│     data["status"] = "ok"                                                                         │
│                                                                                                   │
│ # WITH (using same _flag_true helper):                                                            │
│ if not items:                                                                                     │
│     _set_reply_needed_from_derived(header)                                                        │
│                                                                                                   │
│ if _flag_true(header, "reply_needed"):                                                            │
│     data["status"] = "reply"                                                                      │
│ elif _flag_true(header, "human_review_needed"):                                                   │
│     data["status"] = "human_in_the_loop"                                                          │
│ elif _flag_true(header, "post_case"):                                                             │
│     data["status"] = "post"                                                                       │
│ else:                                                                                             │
│     data["status"] = "ok"                                                                         │
│                                                                                                   │
│ ---                                                                                               │
│ 2. app.py — Six locations                                                                         │
│                                                                                                   │
│ A. VALID_STATUSES (~line 93)                                                                      │
│ # OLD:                                                                                            │
│ VALID_STATUSES = {"ok", "partial", "failed", "unknown"}                                           │
│ # NEW (keep "partial" + "unknown" for reading old JSON files):                                    │
│ VALID_STATUSES = {"ok", "reply", "human_in_the_loop", "post", "failed", "partial", "unknown"}     │
│                                                                                                   │
│ B. _normalize_status() (~lines 203–207)                                                           │
│ Map legacy values so old files display correctly:                                                 │
│ def _normalize_status(value: Any) -> str:                                                         │
│     status = str(value or "ok").strip().lower()                                                   │
│     if status == "partial":                                                                       │
│         return "reply"   # backwards compat                                                       │
│     if status == "unknown":                                                                       │
│         return "ok"      # backwards compat                                                       │
│     if status not in VALID_STATUSES:                                                              │
│         return "ok"                                                                               │
│     return status                                                                                 │
│                                                                                                   │
│ C. _status_counts() (~line 304)                                                                   │
│ counts = {"ok": 0, "reply": 0, "human_in_the_loop": 0, "post": 0, "failed": 0}                    │
│                                                                                                   │
│ D. Dashboard day_buckets initialization (~line 1474)                                              │
│ day_buckets[bucket_day] = {                                                                       │
│     "date": bucket_day.isoformat(),                                                               │
│     "label": bucket_day.strftime("%a"),                                                           │
│     "ok": 0,                                                                                      │
│     "reply": 0,                                                                                   │
│     "human_in_the_loop": 0,                                                                       │
│     "post": 0,                                                                                    │
│     "failed": 0,                                                                                  │
│     "total": 0,                                                                                   │
│ }                                                                                                 │
│                                                                                                   │
│ E. Excel status fills (~line 996)                                                                 │
│ status_fills = {                                                                                  │
│     "ok":               PatternFill(fill_type="solid", fgColor="C6EFCE"),  # green                │
│     "reply":            PatternFill(fill_type="solid", fgColor="FCE4D6"),  # orange               │
│     "human_in_the_loop": PatternFill(fill_type="solid", fgColor="FFEB9C"), # yellow               │
│     "post":             PatternFill(fill_type="solid", fgColor="DDEBF7"),  # blue                 │
│     "failed":           PatternFill(fill_type="solid", fgColor="F8CBAD"),  # red                  │
│ }                                                                                                 │
│                                                                                                   │
│ F. queue_counts in dashboard (~line 1462)                                                         │
│ Change from flag-based to status-based counts:                                                    │
│ queue_counts = {                                                                                  │
│     "reply": 0,                                                                                   │
│     "human_in_the_loop": 0,                                                                       │
│     "post": 0,                                                                                    │
│ }                                                                                                 │
│ # And in the accumulation loop, count by status instead of by flag booleans                       │
│                                                                                                   │
│ ---                                                                                               │
│ 3. StatusBadge.jsx                                                                                │
│                                                                                                   │
│ const STYLES = {                                                                                  │
│   ok:               "bg-success/10 text-success border-success/20",                               │
│   reply:            "bg-red-50 text-red-700 border-red-200",                                      │
│   human_in_the_loop: "bg-orange-50 text-orange-700 border-orange-200",                            │
│   post:             "bg-slate-100 text-slate-600 border-slate-200",                               │
│   failed:           "bg-danger/10 text-danger border-danger/20",                                  │
│   // legacy fallbacks                                                                             │
│   partial:          "bg-red-50 text-red-700 border-red-200",                                      │
│   unknown:          "bg-slate-100 text-slate-600 border-slate-200",                               │
│ };                                                                                                │
│                                                                                                   │
│ ---                                                                                               │
│ 4. OrdersPage.jsx                                                                                 │
│                                                                                                   │
│ A. STATUS_OPTIONS (line 12)                                                                       │
│ const STATUS_OPTIONS = ["ok", "reply", "human_in_the_loop", "post", "failed"];                    │
│                                                                                                   │
│ B. activeTab logic (lines 81–92) — switch from flag params to status params:                      │
│ if (searchParams.get("status") === "reply") return "needs_reply";                                 │
│ if (searchParams.get("status") === "human_in_the_loop") return "manual_review";                   │
│                                                                                                   │
│ C. applyTab() (lines 134–148) — use ?status= instead of flag params:                              │
│ if (tab === "needs_reply") {                                                                      │
│     updateParams({ status: "reply", human_review_needed: null, reply_needed: null });             │
│     return;                                                                                       │
│ }                                                                                                 │
│ if (tab === "manual_review") {                                                                    │
│     updateParams({ status: "human_in_the_loop", reply_needed: null, human_review_needed: null }); │
│     return;                                                                                       │
│ }                                                                                                 │
│                                                                                                   │
│ D. Remove replyNeededParam / humanReviewParam / postCaseParam state variables (lines 77–79) — no  │
│ longer needed for tab detection.                                                                  │
│                                                                                                   │
│ E. Remove the Flags column from the table header and rows (lines ~569–578). The <th> for flags    │
│ and the <td> with FlagPill rendering are removed entirely.                                        │
│                                                                                                   │
│ ---                                                                                               │
│ 5. OverviewPage.jsx                                                                               │
│                                                                                                   │
│ A. getBucketTotals() (lines 70–76) — replace partial/unknown with new statuses:                   │
│ const ok    = toNumber(bucket?.ok);                                                               │
│ const reply = toNumber(bucket?.reply);                                                            │
│ const humanInTheLoop = toNumber(bucket?.human_in_the_loop);                                       │
│ const post  = toNumber(bucket?.post);                                                             │
│ const failed = toNumber(bucket?.failed);                                                          │
│ const total = ok + reply + humanInTheLoop + post + failed;                                        │
│ return { ok, reply, humanInTheLoop, post, failed, total };                                        │
│                                                                                                   │
│ B. Bar chart legend (lines ~239–242) — replace partial/unknown dots with new statuses.            │
│                                                                                                   │
│ C. Bar heights (lines ~251–258) — calculate height for each new status.                           │
│                                                                                                   │
│ D. Bar rendering (lines ~277–280) — render new stacked bars.                                      │
│                                                                                                   │
│ E. Tooltip (lines ~255–259) — update text.                                                        │
│                                                                                                   │
│ F. Selected bucket display (line ~308) — update to new statuses.                                  │
│                                                                                                   │
│ G. Queue cards (lines ~212–226) — change keys from queue_counts.reply_needed /                    │
│ .human_review_needed / .post_case to queue_counts.reply / .human_in_the_loop / .post.             │
│                                                                                                   │
│ H. MetricCard for partial rate (~line 196) — remove or rename to "Reply Rate" / overall quality   │
│ metric. (Remove partialRate/partialCount cards since "partial" no longer exists.)                 │
│                                                                                                   │
│ I. Flags column in overview table (line ~373) — remove the <th> flags header and the <td> flag    │
│ rendering (~lines 395–400).                                                                       │
│                                                                                                   │
│ ---                                                                                               │
│ 6. format.js — statusLabel()                                                                      │
│                                                                                                   │
│ Add new status labels:                                                                            │
│ if (normalized === "reply") return t("status.reply", null, "Reply");                              │
│ if (normalized === "human_in_the_loop") return t("status.human_in_the_loop", null, "Human in the  │
│ Loop");                                                                                           │
│ if (normalized === "post") return t("status.post", null, "Post");                                 │
│ // keep ok/failed; remove partial/unknown                                                         │
│                                                                                                   │
│ ---                                                                                               │
│ 7. translations.js — EN + DE                                                                      │
│                                                                                                   │
│ Add to status section:                                                                            │
│ // EN:                                                                                            │
│ status: {                                                                                         │
│   ok: "OK",                                                                                       │
│   reply: "Reply",                                                                                 │
│   human_in_the_loop: "Human in the Loop",                                                         │
│   post: "Post",                                                                                   │
│   failed: "Failed",                                                                               │
│ }                                                                                                 │
│ // DE:                                                                                            │
│ status: {                                                                                         │
│   ok: "OK",                                                                                       │
│   reply: "Antwort",                                                                               │
│   human_in_the_loop: "Menschliche Überprüfung",                                                   │
│   post: "Post",                                                                                   │
│   failed: "Fehlgeschlagen",                                                                       │
│ }                                                                                                 │
│                                                                                                   │
│ Remove: status.partial, status.unknown, common.partial, overview.partialRate,                     │
│ overview.partialCount keys.                                                                       │
│                                                                                                   │
│ Update overview.queueReplyNeeded → overview.queueReply, overview.queueReview →                    │
│ overview.queueHumanInTheLoop.                                                                     │
│                                                                                                   │
│ ---                                                                                               │
│ Critical Files                                                                                    │
│                                                                                                   │
│ - normalize.py — normalize_output() and refresh_missing_warnings()                                │
│ - app.py — 6 locations listed above                                                               │
│ - front-end/my-react-app/src/components/StatusBadge.jsx                                           │
│ - front-end/my-react-app/src/pages/OrdersPage.jsx                                                 │
│ - front-end/my-react-app/src/pages/OverviewPage.jsx                                               │
│ - front-end/my-react-app/src/utils/format.js                                                      │
│ - front-end/my-react-app/src/i18n/translations.js                                                 │
│                                                                                                   │
│ Out of Scope                                                                                      │
│                                                                                                   │
│ - Pipeline flag-setting logic (unchanged — flags are still set exactly as today)                  │
│ - OrderDetailPage.jsx — HIDDEN_HEADER_FIELDS already hides flags, no change needed                │
│ - API flag query params (?reply_needed=true) — keep them working for backwards compat but they    │
│ are no longer used by the frontend                                                                │
│                                                                                                   │
│ ---                                                                                               │
│ Verification                                                                                      │
│                                                                                                   │
│ 1. Start the Flask server and load http://127.0.0.1:5000                                          │
│ 2. Confirm no "Partial" badges appear anywhere                                                    │
│ 3. Confirm status column shows only: OK / Reply / Human in the Loop / Post / Failed               │
│ 4. Confirm "Needs Reply" tab filters correctly to status=reply orders                             │
│ 5. Confirm "Manual Review" tab filters correctly to status=human_in_the_loop orders               │
│ 6. Confirm Flags column is gone from both OrdersPage and OverviewPage tables                      │
│ 7. Confirm OverviewPage bar chart shows new status colors (no orange "partial" bar)               │
│ 8. Confirm old JSON files with status="partial" still display as "Reply" (backwards compat)       │
│ 9. Run python verify_human_review.py — should still pass (flag-setting logic unchanged)