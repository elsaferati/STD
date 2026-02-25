## Add new client branch: `segmuller`

### Summary
Add a new extraction “client branch” named **Segmuller** (parallel to `porta` and `braun`) with its own prompt module, routing hints, and a deterministic hard-match based on **sender domain `@segmueller.de` + PDF attachment**. Per your choice, **disable second-pass item-code verification** for this branch.

---

## Decisions locked in (from you)
- **Branch id:** `segmuller`
- **Routing mode:** add `segmuller_hint` + **hard-match on sender domain**
- **Hard-match requires PDF:** yes (must have ≥1 PDF attachment)
- **Second-pass item verification:** **disabled** for `segmuller`

---

## Code changes (decision-complete)

### 1) New prompt module
**Add file:** `prompts_segmuller.py`
- Mirror `prompts_braun.py` structure:
  - `SEGMULLER_SYSTEM_PROMPT` = “strict Segmuller purchase-order extraction engine… JSON only… German field names…”
  - `build_user_instructions_segmuller(source_priority: list[str]) -> str`
    - Same required header/item keys as Braun/Porta
    - Same “FIELD OBJECT FORMAT” contract
    - Generic PDF usage guidance (like Braun), no Porta-specific code-splitting rules

### 2) Register branch
**Update:** `extraction_branches.py`
- Add `import prompts_segmuller`
- Add `BRANCHES["segmuller"] = ExtractionBranch(...)` with:
  - `id="segmuller"`, `label="Segmuller"`
  - `description` mentioning identifying signals (sender `@segmueller.de`, PDF contains Segmüller/Segmueller text)
  - `system_prompt=prompts_segmuller.SEGMULLER_SYSTEM_PROMPT`
  - `build_user_instructions=prompts_segmuller.build_user_instructions_segmuller`
  - `enable_item_code_verification=False`
  - `is_momax_bg=False`

### 3) Routing: hint + hard-match
**Update:** `extraction_router.py`
- Add regexes:
  - `_SEGMUELLER_TOKEN_RE = re.compile(r"\\bsegm(?:ue|ü|u)ller\\b", re.IGNORECASE)`
  - `_SEGMUELLER_DOMAIN_RE = re.compile(r"(?:@|\\b)(?:[a-z0-9-]+\\.)*segmueller\\.de\\b", re.IGNORECASE)`
- Add:
  - `_has_segmuller_hint(text: str) -> bool`:
    - normalize whitespace
    - return true if token or domain regex matches
  - `_is_segmuller_hard_match(message: IngestedEmail, config: Config) -> bool`:
    - require at least one PDF attachment
    - require sender matches `_SEGMUELLER_DOMAIN_RE`
- In `route_message(...)`, insert hard-match logic (priority):
  1) existing `xxxlutz_default` mail-hint early return (keep)
  2) existing momax_bg hard-matches/detectors (keep)
  3) **if not forced** and `_is_segmuller_hard_match(...)`: force `segmuller`
  4) existing braun/porta hard-matches (keep)
- Extend router classifier guidance:
  - In `_build_router_system_prompt()`, add a rule:
    - “If `segmuller_hint` is true, prefer `branch_id="segmuller"` with high confidence unless a forced detector applies.”
- Extend router input payload:
  - In `_build_router_user_text(...)`, add `"segmuller_hint": ...` computed from joined email text OR any PDF first-page preview text (same pattern as `porta_hint`/`braun_hint`)

### 4) Verification script coverage
**Update:** `verify_routing.py`
Add tests analogous to Porta/Braun:
- `test_routing_segmuller_branch_selected()`
  - classifier returns `{"branch_id":"segmuller","confidence":0.99,...}`
  - assert warnings contain `Routing: selected=segmuller` and `fallback=false`
- `test_segmuller_hint_from_pdf_markers()`
  - patch `extraction_router._pdf_first_page_text` to return text containing “Segmüller” (or “Segmueller”)
  - assert `_build_router_user_text(... )` JSON has `"segmuller_hint": true`
- `test_routing_segmuller_hard_match_from_sender_domain()`
  - message sender like `service@segmueller.de` with a PDF attachment
  - classifier returns `unknown`
  - assert routing warning shows `selected=segmuller`, `forced=true`, `fallback=false`
- Add these to the `__main__` execution list at bottom.

### 5) Sample-case folder scaffold
**Add:** `CLIENT CASES/segmuller/README.md`
- Same structure/guidelines as `CLIENT CASES/porta/README.md` and `CLIENT CASES/braun/README.md`

---

## Public interfaces / behavior changes
- New valid `branch_id`: `segmuller` (available to router classifier and pipeline).
- Routing behavior:
  - Any email **from `@segmueller.de` with ≥1 PDF** is **forced** to `segmuller` (bypasses low-confidence classifier outcomes).
  - Emails/PDFs mentioning Segmüller/Segmueller/Segmuller set `segmuller_hint` to guide the classifier.
- Item-code second-pass verification:
  - **Not executed** for `segmuller` (`enable_item_code_verification=False`).

---

## Test/verification plan
Run locally:
- `python verify_routing.py` (ensures new hint + forced routing works and doesn’t break existing tests)
- Optional quick sanity: `python -m py_compile prompts_segmuller.py extraction_branches.py extraction_router.py`

---

## Assumptions
- Segmuller orders arrive with **PDF attachments** (hard-match requires at least one PDF).
- The authoritative sender domain to force routing is **`segmueller.de`**.
- No special Segmuller-specific item code parsing rules are defined yet; extraction prompt stays generic, and item verification is disabled until real samples are reviewed.
