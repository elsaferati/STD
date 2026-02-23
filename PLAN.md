## Add new client extraction branch: **Porta** (email + PDF)

### Summary
Add a new extraction branch `porta` with Porta-specific prompts and routing hints. Porta messages are routed via the existing LLM router using “Porta” signals in sender/subject/PDF preview text. After the main extraction, run a **second pass** that **verifies & corrects item codes** (`artikelnummer`/`modellnummer`, optionally `menge`) from the PDF, then **auto-corrects** mismatches and **forces `human_review_needed=true`** with clear warnings.

---

## Decisions locked in (from you)
- **Output:** Reuse existing JSON schema + existing XML exporters (`OrderInfo_*.xml`, `OrderArticleInfo_*.xml`).
- **Routing:** Classifier + PDF hints (no risky hard-force detector until we have real samples).
- **Second pass goal:** Verify & correct item codes.
- **Mismatch handling:** Auto-correct + flag human review.

---

## Changes (repo-level)

### 1) Create Porta main prompt module
**Add file:** `prompts_porta.py`
- Define `PORTA_SYSTEM_PROMPT` (or `SYSTEM_PROMPT_PORTA`) explicitly mentioning **Porta** (avoid “XXXLutz/Mömax” wording).
- Implement `build_user_instructions_porta(source_priority: list[str]) -> str`:
  - State: Porta orders always arrive with **email + PDF**.
  - Enforce the same required German field names + JSON structure the pipeline expects.
  - Include the “PDF digital text is ONLY for verifying code fields” rule:
    - Use PDF extracted text to confirm/correct `items[*].modellnummer` and `items[*].artikelnummer`
    - Quantity/row-count must come from the image table
  - Provide **generic** label heuristics (since samples come later):
    - `kundennummer`: “Kundennr / Kunden-Nr / Debitor / Konto”
    - `kom_nr`: “Auftragsnr / Bestellnr / Order / Kommission”
    - `bestelldatum`: “Bestelldatum / Datum”
    - `liefertermin/wunschtermin`: “Liefertermin / Wunschliefertermin”
    - `lieferanschrift`: “Lieferadresse / Lieferanschrift / Empfänger”
    - `store_name/store_address/seller`: from letterhead/signature if present

### 2) Register the new branch
**Update:** `extraction_branches.py`
- Add a new `ExtractionBranch` entry:
  - `id="porta"`, `label="Porta"`, `description="Porta orders (email + PDF)…"`
  - `system_prompt=prompts_porta.<porta system prompt>`
  - `build_user_instructions=prompts_porta.build_user_instructions_porta`
- Extend the `ExtractionBranch` dataclass with a new flag:
  - `enable_item_code_verification: bool = False`
- Set `enable_item_code_verification=True` for `porta`.

### 3) Add routing “Porta hint” (classifier-only, not forced)
**Update:** `extraction_router.py`
- In `_build_router_user_text(...)`, compute `porta_hint` using conservative checks:
  - case-insensitive match of `\bporta\b` in:
    - `message.sender`, `message.subject`, `email_body_preview`
    - any `pdf_first_page_previews[*].first_page_text`
- Include `porta_hint` in the JSON payload sent to the router LLM.
- Update `_build_router_system_prompt()` rules to add:
  - “If `porta_hint` is true, prefer `branch_id="porta"` with high confidence (unless a forced detector applies).”
- Keep `momax_bg` hard-detector rule as highest priority.

### 4) Implement the Porta verification pass (second extraction call)
**Add file:** `prompts_verify_items.py`
- Define:
  - `VERIFY_ITEMS_SYSTEM_PROMPT` (generic, not client-branded)
  - `build_verify_items_instructions() -> str`:
    - Goal: verify/correct **only** item identifiers (and optionally `menge`)
    - Input includes:
      - The **current extracted items list** (line_no + current codes)
      - PDF pages (image + extracted digital text)
    - Output schema (strict JSON):
      ```json
      {
        "verified_items": [
          {
            "line_no": 1,
            "modellnummer": "string",
            "artikelnummer": "string",
            "menge": 1,
            "confidence": 0.0,
            "reason": "short"
          }
        ],
        "warnings": []
      }
      ```
    - Rules:
      - Keep the **same number of items** as provided; don’t invent/remove rows.
      - If uncertain for a line: echo original values with low confidence.

**Update:** `openai_extract.py`
- Add a new method, e.g. `verify_items_from_pdf(...)`:
  - Inputs: `images`, `items_snapshot`, `page_text_by_image_name`
  - Uses `prompts_verify_items.VERIFY_ITEMS_SYSTEM_PROMPT` + `build_verify_items_instructions()`
  - Sends items snapshot as `input_text` before images (same image+page_text pattern as other calls)
  - Returns raw text for `parse_json_response`.

**Update:** `pipeline.py`
- After `normalized = normalize_output(...)`, add:
  - If `branch.enable_item_code_verification`:
    - Select `pdf_images` only (same list already computed for detail extraction).
    - Build a compact `items_snapshot` list from `normalized["items"]`:
      - `line_no`, current `modellnummer.value`, `artikelnummer.value`, `menge.value`
    - Call `extractor.verify_items_from_pdf(...)`.
    - Parse JSON and apply corrections via a small helper function (new private helper in `pipeline.py` or a new module like `item_code_verification.py`):
      - For each `verified_item` matched by `line_no`:
        - If confidence >= **0.75** and value differs:
          - Overwrite the item field as:
            - `source="derived"`, `confidence=<verification confidence>`, `derived_from="porta_item_code_verification"`
          - Record a warning describing the change.
      - If any correction applied:
        - Set `header.human_review_needed=true` with `derived_from="porta_item_code_verification"`
- Ensure this verification step is **Porta-only** (does not change current XXXLutz/Mömax behavior).

### 5) Add scaffolding for Porta samples (no real PDFs yet)
**Add:**
- `CLIENT CASES/porta/README.md` describing the expected sample layout:
  - `ORDER 1/Email Body.txt`
  - `ORDER 1/<pdf>.pdf`
- (Optional) `.gitkeep` files so directories exist in git.

### 6) Tests / verification scripts
**Update:** `verify_routing.py`
- Add a test that mocks router output to `{"branch_id":"porta","confidence":0.99,...}` and confirms:
  - Routing warning shows `selected=porta` and `fallback=false`.

**Add:** `verify_porta_verification.py` (unit-ish)
- Test the “apply corrections” helper directly (no Poppler/PyMuPDF dependency):
  - Given normalized items with known codes + verified_items with one changed code at high confidence:
    - item value updated
    - `human_review_needed` forced true
    - warning added

### 7) Acceptance criteria (what “done” means)
- Router can select `porta` and pipeline runs end-to-end without exceptions.
- Porta main extraction uses Porta prompts (no XXXLutz wording).
- Second pass runs for Porta when PDF pages exist and:
  - produces no changes when identical
  - auto-corrects mismatches at confidence >= 0.75
  - sets `human_review_needed=true` and adds a human-readable warning on any correction
- Existing branches (`xxxlutz_default`, `momax_bg`) behavior unchanged.

---


## Assumptions (explicit)
- Porta still outputs the same JSON header/item schema and uses the same XML exporters.
- No dedicated Porta-only output directory or filename conventions are required.
- Until samples arrive, routing and prompts use conservative generic Porta identifiers (“porta” token in sender/subject/PDF text).
