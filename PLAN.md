## Add new client extraction branch: `braun` (like `porta`)

### Summary
Add a new extraction branch `braun` for **BRAUN Möbel-Center** orders. It will:
- Route to `braun` using **Braun-specific hints** (subject/sender/body + PDF first-page text).
- **Force-route** to `braun` when strong markers like “Braun Möbel-Center” are detected in a PDF (similar to Porta hard-match behavior).
- Run the **second-pass PDF item-code verification** (like `porta`) and force `human_review_needed=true` if corrections are applied.

---

## Decisions locked in (from you)
- Branch ID: `braun`; label: `Braun`.
- Routing signals: match **Braun + Möbel context** (not bare “braun” alone).
- Force routing: if “Braun Möbel(-)Center” markers are found and a PDF is attached, it’s definitely Braun → force `braun`.
- Verification: enabled (same mechanism as Porta), but with **Braun-generic** verification rules (not Porta-specific code mappings).

---

## Repo changes (exact)

### 1) Add Braun prompt module
**Add file:** `prompts_braun.py`
- Define `BRAUN_SYSTEM_PROMPT` similar to `prompts_porta.PORTA_SYSTEM_PROMPT`, but branded for Braun.
- Implement `build_user_instructions_braun(source_priority: list[str]) -> str`:
  - Reuse the same required header/item keys and “field object format” contract used by Porta.
  - State input is **email + PDF**.
  - Keep the same “PDF digital text only for code confirmation” guidance:
    - Use extracted PDF text to confirm/correct `items[*].modellnummer` and `items[*].artikelnummer`.
    - Determine row count + `menge` primarily from the table image.
  - Use generic header label hints (kundennummer/kom_nr/bestelldatum/liefertermin/lieferanschrift/ILN blocks) like Porta.

### 2) Register the new branch
**Update file:** `extraction_branches.py`
- `import prompts_braun`
- Add a new `ExtractionBranch` entry:
  - `id="braun"`
  - `label="Braun"`
  - `description="BRAUN Möbel-Center orders (email + PDF) with second-pass item-code verification."`
  - `system_prompt=prompts_braun.BRAUN_SYSTEM_PROMPT`
  - `build_user_instructions=prompts_braun.build_user_instructions_braun`
  - `enable_detail_extraction=False`
  - `enable_item_code_verification=True`
  - `is_momax_bg=False`

### 3) Add routing hint + hard-match
**Update file:** `extraction_router.py`

#### 3a) Add Braun regex patterns (top of file)
Add:
- `_BRAUN_TOKEN_RE = re.compile(r"\\bbraun\\b", re.IGNORECASE)`
- `_BRAUN_MOEBEL_RE = re.compile(r"m[oö]bel", re.IGNORECASE)`
- `_BRAUN_MOEBELCENTER_RE = re.compile(r"m[oö]bel\\s*[- ]?\\s*center", re.IGNORECASE)`

#### 3b) Implement hint detection
Add:
- `_has_braun_hint(text: str) -> bool` that returns `True` when:
  - text contains `braun` AND (contains `möbel` OR `möbel-center`).
  - (This matches your preference: “Braun Möbel / Braun Möbel-Center etc.”, not bare “braun”.)

#### 3c) Implement forced hard-match (PDF required)
Add:
- `_is_braun_hard_match(message: IngestedEmail, config: Config) -> bool`
  - Require at least one PDF attachment (same safety pattern as Porta).
  - Check strong markers in:
    - combined sender+subject+body preview text, and
    - PDF first-page extracted text (use `_pdf_first_page_text` + `_truncate` like Porta).
  - “Strong marker” condition: `_BRAUN_TOKEN_RE` AND `_BRAUN_MOEBEL_RE` (or `_BRAUN_MOEBELCENTER_RE`).

#### 3d) Add `braun_hint` into router payload
In `_build_router_user_text(...)`, add:
- `"braun_hint": bool(_has_braun_hint(joined email text) or any(_has_braun_hint(pdf first-page preview)))`

#### 3e) Teach classifier to prefer Braun when hinted
In `_build_router_system_prompt()` rules section, add a rule similar to Porta’s:
- If `braun_hint` is true, prefer `branch_id="braun"` with high confidence unless a forced detector applies.

#### 3f) Apply forced Braun routing
In `route_message(...)`, after MOMAX BG hard-match handling and before Porta hard-match handling:
- If no `forced_branch_id` yet and `_is_braun_hard_match(...)` is true:
  - set `forced_branch_id = "braun"`
  - set `detector_results["braun"] = True`

### 4) Add Braun verification-profile prompt
**Update file:** `prompts_verify_items.py`
- Add `_build_braun_verify_items_instructions() -> str`:
  - Same output schema as existing verification.
  - Scope: `modellnummer`, `artikelnummer`, optional `menge` if certain.
  - Rules:
    - Keep same number of lines; match by `line_no`; never invent/remove rows.
    - Use PDF digital text to confirm exact characters (preserve leading zeros; preserve O vs 0).
    - If uncertain, echo original values with low confidence.
- Update `build_verify_items_instructions(verification_profile: str)` to return Braun instructions when `profile == "braun"`.

### 5) Make verification warnings read nicely for Braun
**Update file:** `item_code_verification.py`
- In `_profile_label()`, add:
  - `if profile == "braun": return "Braun"`
- No other behavior changes needed (derived_from will naturally become `braun_item_code_verification`).

### 6) Add Braun sample scaffolding
**Add file:** `CLIENT CASES/braun/README.md`
- Mirror `CLIENT CASES/porta/README.md`, but named “Braun Sample Layout”.

### 7) Verification scripts/tests to add/update
**Update file:** `verify_routing.py`
Add tests analogous to Porta:
- `test_routing_braun_branch_selected()`
  - Mock classifier response to `{"branch_id":"braun","confidence":0.99,...}`
  - Assert routing warning shows `selected=braun` and `fallback=false`.
- `test_braun_hint_from_pdf_markers()`
  - Patch `extraction_router._pdf_first_page_text` to return text containing e.g. `BRAUN Möbel-Center`
  - Call `extraction_router._build_router_user_text(...)`
  - Assert payload `braun_hint` is `True`.
- `test_routing_braun_hard_match_forces_branch()`
  - Create message with a PDF attachment
  - Patch `_pdf_first_page_text` to include strong markers
  - Mock classifier to return `unknown`
  - Assert pipeline routes with `forced=true` and `selected=braun`.

**Add file:** `verify_braun_verification.py` (or extend `verify_porta_verification.py`)
- Create a small unit-style test calling `apply_item_code_verification(...)` with:
  - `verification_profile="braun"`
  - One high-confidence correction
- Assert:
  - corrected field(s) have `derived_from == "braun_item_code_verification"`
  - `header.human_review_needed.value == True` and `derived_from == "braun_item_code_verification"`
  - warnings contain “Braun verification …”

---

## Acceptance criteria
- `extraction_branches.BRANCHES` includes `braun` and pipeline runs end-to-end without exceptions.
- Routing:
  - `braun_hint` becomes `true` for PDFs/emails that contain “Braun Möbel / Braun Möbel-Center”.
  - Hard-match forces `selected=braun` when strong markers are found and a PDF is attached.
- Verification:
  - Runs for `braun` when PDF pages exist.
  - Applies corrections only when confidence is high, and forces human review when it changes anything.
- Existing branches (`xxxlutz_default`, `momax_bg`, `porta`) unchanged.

---

## Assumptions / defaults
- Braun orders are effectively **email + PDF** (Porta-like); hard-match requires a PDF attachment to avoid misrouting on random text.
- Until real Braun samples/rules exist, Braun item-code verification uses **generic “verify against PDF” rules**, not client-specific code-mapping logic.
