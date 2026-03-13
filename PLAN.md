# Role-Based Warning/Error Sanitization

## Summary
Implement role-aware sanitization for order detail operational signals so:
- `superadmin` continues to receive and see the exact raw `warnings` and `errors` returned today.
- `admin` and `user` receive client-friendly `warnings` and `errors` with internal/debug content removed.
- Scope is the order detail operational signals panel and its backing `GET /api/orders/<order_id>` payload.

## Implementation Changes
- Add a centralized backend sanitizer for operational signal messages with this contract:
  - Input: `messages`, `level` (`warning` or `error`), `role`
  - Output: same array for `superadmin`
  - Output: sanitized array for `admin`/`user`
- Apply that sanitizer inside the order detail response builder so `/api/orders/<order_id>` keeps the same public fields (`warnings`, `errors`) but makes their contents role-dependent.
- Use a pattern-based sanitizer with actionable-detail preservation:
  - Keep business-relevant messages such as missing fields, missing ticket, missing items, missing line-level data, and similar client-actionable gaps.
  - Strip or rewrite technical details such as stack traces, exception text, DB/table names, service names, routing/debug metadata, internal mapping diagnostics, filenames, and raw infra/tool errors.
  - Convert internal-only signals to friendly templates, for example:
    - routing/debug/internal trigger messages -> “The order was processed with internal review checks.”
    - DB / extraction / conversion failures -> “We could not fully process part of this order automatically. Please review it manually.”
    - internal lookup or mapping failures -> “Some order information could not be matched automatically.”
    - auto-reply/internal email logs -> “A follow-up action was triggered for missing order information.”
  - If a message is unknown and looks technical, collapse it to a generic friendly fallback instead of exposing raw text.
- Add a small frontend display helper in the order detail page that renders `warnings`/`errors` via a single `visibleWarnings` / `visibleErrors` path and uses those arrays for the issue count. This is mostly defensive; the backend remains the source of truth.
- Do not change Gemini validation issues, top-level API error envelopes, or any non-order-detail endpoints in this change.

## Public API / Interface Notes
- `GET /api/orders/<order_id>` keeps the existing shape.
- `warnings: string[]` and `errors: string[]` become role-conditioned in content:
  - `superadmin`: raw current messages
  - `admin` / `user`: sanitized client-facing messages

## Test Plan
- Backend unit-style coverage for the sanitizer:
  - `superadmin` returns exact passthrough
  - `admin`/`user` sanitize known technical patterns
  - actionable missing-data warnings remain specific, including line references where present
  - unknown technical-looking messages fall back to a safe generic string
- Backend API regression coverage for `/api/orders/<id>`:
  - same order, different session roles, verify raw vs sanitized payload content
  - verify response shape is unchanged
- Manual frontend smoke test:
  - log in as `superadmin` and confirm current warning cards are unchanged
  - log in as `admin` and `user` and confirm the same order shows simplified cards and matching issue count
  - confirm no regression when there are zero warnings/errors

## Assumptions
- No DB schema changes or migrations are needed.
- Sanitized messages remain in the current backend-generated language style; this change does not introduce new i18n translation coverage.
- The decision boundary is “hide internals, keep client-actionable order facts,” not “make every message fully generic.”
