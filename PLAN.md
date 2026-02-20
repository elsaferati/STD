# Make `kom_name` empty for `momax_bg` (no missing-field warning)

## Summary
For the `momax_bg` special-case flow, force `header.kom_name` to always be empty (`""`) and treat it as **optional** so it does not degrade `status` or add “Missing header fields: kom_name …” warnings. Enforce this both in the BG-specific prompt and in backend post-processing so it’s deterministic even if the LLM outputs a value.

## Scope / Success criteria
- When `pipeline.process_message()` runs with `use_momax_bg == True`:
  - `result.data["header"]["kom_name"]["value"] == ""`
  - `result.data["header"]["kom_name"]["source"] == "derived"`
  - `result.data["header"]["kom_name"]["confidence"] == 0.0`
  - `result.data["header"]["kom_name"]["derived_from"] == "momax_bg_policy"` (marker for UI refresh)
- `normalize.normalize_output(..., is_momax_bg=True)` must **not** count `kom_name` as missing when computing:
  - `data["status"]`
  - “Missing header fields: …” warnings
- `normalize.refresh_missing_warnings(data)` must also not re-add `kom_name` as missing for saved `momax_bg` orders (identified via the marker above).
- Non-`momax_bg` behavior is unchanged.

## Implementation details

### 1) Prompt change (LLM guidance)
File: `prompts_momax_bg.py`
- In `build_user_instructions_momax_bg()`:
  - Replace the current mapping line:
    - `- kom_name: use the store/city short name from 'Store:' ...`
  - With:
    - `- kom_name: leave empty '' (not used for Momax BG)`
  - Keep `kom_name` in the required header field list (schema still expects the key).

### 2) Backend enforcement (deterministic output)
File: `pipeline.py`
- After `parsed = parse_json_response(response_text)` and before calling `normalize_output(...)`:
  - If `use_momax_bg` and `parsed["header"]` is a dict:
    - Set `parsed["header"]["kom_name"] = {"value": "", "source": "derived", "confidence": 0.0, "derived_from": "momax_bg_policy"}`
    - If present, delete `parsed["header"]["kom_name_pdf"]` to avoid any kom_name mismatch warning path.

Rationale: this guarantees the output is empty even if the model fills it, and it injects a durable marker that survives persistence.

### 3) Treat `kom_name` as optional for momax_bg during missing-field computations
File: `normalize.py`
- In `normalize_output(..., is_momax_bg: bool = False)`:
  - After computing `missing_header = [...]`, if `is_momax_bg`:
    - Remove `"kom_name"` from `missing_header` before:
      - computing `missing_header_no_ticket`
      - status selection (`failed/partial/ok`)
      - appending “Missing header fields: …”
- In `refresh_missing_warnings(data)`:
  - Add a small detector, e.g.:
    - `is_momax_bg = header.get("kom_name", {}).get("derived_from") == "momax_bg_policy"`
  - If detected, remove `"kom_name"` from `missing_header` before status/warning recomputation.

Note: this won’t retroactively change already-saved orders unless they have the marker (newly processed ones will).

## Tests / Verification
File: `verify_momax_bg.py`
- Extend `test_momax_bg_two_pdf_special_case()`:
  - Assert `header["kom_name"]["value"] == ""`
  - Assert no warning string contains `"Missing header fields:"` **and** `"kom_name"` (or more directly, that `kom_name` is not listed among missing header fields).
- Run: `python verify_momax_bg.py`

## Assumptions
- “Momax BG” is exactly the `use_momax_bg` path (as detected by `momax_bg.is_momax_bg_two_pdf_case()`), including the single-PDF detection behavior.
- Keeping `kom_name` present-but-empty is acceptable for downstream consumers; we are not removing the key from the schema.
