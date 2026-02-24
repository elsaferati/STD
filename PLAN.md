## Remove Detail Extraction + Make Second-Pass Verification Text-Only

### Summary
Implement three coordinated changes:
1. Remove Detailed extraction from the pipeline entirely.
2. Enable Second pass item verification for `xxxlutz_default`.
3. Change Second pass item verification to use only digital PDF text (no images), comparing text evidence against first-pass extracted item fields to detect/correct character mismatches.

Selected behavior for missing digital text: **skip second-pass verification and append a warning**.

### Scope and Intent
- In scope:
  - Backend extraction branch config and pipeline flow.
  - Verifier prompt/input contract and extractor method signatures.
  - Tests for new gating and text-only verification behavior.
- Out of scope:
  - Changing first-pass extraction behavior.
  - Changing correction application thresholds or human-review forcing logic (unless required by failing tests).

### Decision-Complete Implementation Plan

1. **Disable and remove Detailed extraction flow**
- File: `extraction_branches.py`
  - Set `xxxlutz_default.enable_detail_extraction=False`.
- File: `pipeline.py`
  - Remove second extraction block currently labeled `SECOND EXTRACTION CALL`.
  - Remove helper `_merge_article_details(...)` and its callsite.
  - Remove any now-unused imports/variables tied only to detail extraction.
- File: `openai_extract.py`
  - Remove `extract_article_details(...)` method.
- File: `prompts_detail.py`
  - Remove module and references if no longer used anywhere.
- File: any docs/comments referencing detail extraction
  - Update to reflect complete removal.

2. **Enable second-pass item verification for `xxxlutz_default`**
- File: `extraction_branches.py`
  - Set `xxxlutz_default.enable_item_code_verification=True`.
- Keep existing verification flags for `porta`, `braun`, `momax_bg` unless explicitly disabled later.

3. **Convert second-pass verification to text-only**
- File: `pipeline.py`
  - Change verification gate from `branch.enable_item_code_verification and pdf_images` to:
    - branch verification enabled
    - non-empty `items_snapshot`
    - at least one usable digital-text page exists in `pdf_text_by_image_name`
  - Build a text-only payload object from `pdf_text_by_image_name` (ordered by page/index/name for determinism).
  - If no usable digital text:
    - skip verifier call
    - append warning: `<branch label> item verification skipped: no digital PDF text available.`
- File: `openai_extract.py`
  - Replace/rename verifier entrypoint:
    - from `verify_items_from_pdf(images, items_snapshot, page_text_by_image_name, verification_profile)`
    - to text-only API, e.g. `verify_items_from_text(items_snapshot, page_text_by_image_name, verification_profile)`
  - Build request content using:
    - instructions text
    - serialized `items_snapshot`
    - per-page digital text blocks
  - Do **not** append any `input_image`.
- File: `prompts_verify_items.py`
  - Update global and profile-specific prompt wording from “PDF pages (image + digital text)” to “digital PDF text only”.
  - Add explicit rule: verify/correct only from provided text + existing snapshot; do not infer from image evidence.
  - Keep profile-specific code rules (Porta/MOMAX/Braun) unchanged unless contradictory.

4. **Keep correction application behavior stable**
- File: `item_code_verification.py`
  - No logic changes expected.
  - Continue applying high-confidence corrections by `line_no`.
  - Continue forcing `human_review_needed=true` when corrections are applied.

5. **Cleanup/refactor for clarity**
- Rename any misleading symbols/comments mentioning “from_pdf/images” where now text-only (minimally invasive but clear).
- Ensure no dead code remains tied to detail extraction.

### Public APIs / Interfaces / Types Changes
- Internal extractor interface change:
  - Old: `verify_items_from_pdf(images, items_snapshot, page_text_by_image_name, verification_profile)`
  - New: `verify_items_from_text(items_snapshot, page_text_by_image_name, verification_profile)` (or equivalent text-only signature).
- Pipeline behavior contract:
  - Verification no longer requires or sends images.
  - Verification skipped when no digital PDF text exists (non-fatal warning).

### Test Plan

1. **Branch config tests**
- `xxxlutz_default` has:
  - `enable_detail_extraction == False`
  - `enable_item_code_verification == True`

2. **Pipeline verification gating**
- Case A: digital text present + items present -> verifier called.
- Case B: no digital text -> verifier not called, skip warning added.
- Case C: empty items snapshot -> verifier not called.

3. **Verifier payload tests**
- Assert no `input_image` parts are included for second-pass verification requests.
- Assert per-page text is present and item snapshot included.

4. **Behavior regression tests**
- High-confidence correction still updates fields and sets `human_review_needed=true`.
- Low-confidence outputs remain no-op.
- MOMAX special post-processing still runs after verification.

5. **Removal regression**
- No code path invokes detail extraction.
- `program/articles` from former detail pass are not added anymore.

### Acceptance Criteria
- No detailed extraction call exists in runtime pipeline.
- `xxxlutz_default` runs second-pass verification when digital PDF text is available.
- Second-pass verification sends only text (no page images).
- Orders with scanned/no-text PDFs do not fail; verification is skipped with explicit warning.
- Existing correction semantics (confidence threshold, warnings, human review forcing) remain intact.

### Assumptions and Defaults
- “Change Second pass item verification to only text” applies to all verification profiles (`xxxlutz_default`, `porta`, `braun`, `momax_bg`), not only `xxxlutz_default`.
- Missing digital text handling is the chosen default: **skip + warning**.
- No requirement to preserve former detail-extraction outputs (`program`, `articles`) in final normalized payload.
