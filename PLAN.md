## Enable `AIKO - ORDER` Through the Same BG Special Path

### Summary
Broaden the existing `momax_bg` special-case flow so both `MOMAX/MOEMAX - ORDER` and `AIKO - ORDER` Bulgarian documents use the same extraction pipeline (`momax_bg.extract_momax_bg` + BG post-processing).  
This fixes the current AIKO failure mode where docs fall back to the generic extractor and lose `kom_nr` plus item code fidelity.

Chosen defaults:
- Detection scope: `MOMAX+AIKO` (same BG path for both brands).
- `store_name` policy: brand-aware format using detected brand (`<DetectedBrand> BULGARIA - <Store>`).

---

### Public APIs / Interfaces
1. No external API contract changes.
2. Internal behavior change:
   - `momax_bg.is_momax_bg_two_pdf_case(...)` semantics become “BG split-order detector for MOMAX/MOEMAX/AIKO formats,” while keeping function name for compatibility.
3. Prompt contract change:
   - `prompts_momax_bg.py` updated from MOMAX-only language to BG-brand-aware (MOMAX/MOEMAX/AIKO).

---

### Implementation Plan

1. **Detection logic: include AIKO in BG trigger**
- File: `momax_bg.py`
- Update `is_momax_bg_two_pdf_case(...)` heuristics to pass when all are true:
  1. Brand marker present: `moemax|momax|aiko` (with or without `bulgaria`).
  2. Order title marker: `<brand> - ORDER`.
  3. Delivery marker: `Term for delivery` or `Term of delivery`.
  4. Order-id/date pattern exists (`<digits>/<dd.mm.yy>`) via existing `_BG_KOM_WITH_DATE_RE`.
- Keep fail-closed behavior (`False` on parsing errors).
- Keep current regex-based `extract_momax_bg_kom_nr` / `extract_momax_bg_order_date` (already compatible with AIKO header lines like `...88801739/29.10.25...`).

2. **BG prompt: generalize from MOMAX-only to BG-brand-aware**
- File: `prompts_momax_bg.py`
- Replace MOMAX-only references with “MOMAX/MOEMAX/AIKO BG order.”
- Explicitly include `AIKO - ORDER` in table/title examples.
- Update `store_name` instruction to:
  - `MOMAX BULGARIA - <Store>` for MOMAX/MOEMAX docs.
  - `AIKO BULGARIA - <Store>` for AIKO docs.
- Expand `Code/Type` parsing rules with AIKO-style whitespace pair:
  - If code looks like `<NUMERIC> <ALPHA>` (e.g., `30156 OJOO`), set `artikelnummer=NUMERIC`, `modellnummer=ALPHA`.

3. **Pipeline routing remains same entrypoint, now catches AIKO**
- File: `pipeline.py`
- No structural flow change needed; once detector returns `True`, existing special path is used:
  - BG extraction prompt path.
  - `kom_name` policy override.
  - `kom_nr` / order-date fallback repair from PDF text.
- Verify no accidental behavior drift for non-BG docs.

4. **Deterministic BG item-code normalization safety net**
- File: `normalize.py`
- Add BG-only post-normalization helper for `artikelnummer`/`modellnummer` to enforce code split rules when model output is inconsistent:
  - Slash rule: last segment as `artikelnummer`, preceding segments compacted to `modellnummer`.
  - Hyphen rule: standard plus reversed accessory pattern.
  - Whitespace pair rule: `<NUMERIC> <ALPHA>` => article/model split.
- Apply only when `is_momax_bg=True` to avoid non-BG side effects.
- Keep existing model compaction behavior.

5. **Tests: add AIKO special-path coverage + regressions**
- File: `verify_momax_bg.py`
- Add tests:
  1. AIKO detection test (`AIKO - ORDER` + term + kom/date) returns `True`.
  2. AIKO pipeline test ensures special path is used (`extractor._create_response` called; generic `extract` not used).
  3. AIKO `kom_nr` recovery test when LLM misses `kom_nr`, filled from PDF suffix.
  4. AIKO item parsing test for `Code/Type: 30156 OJOO` -> `artikelnummer=30156`, `modellnummer=OJOO`.
  5. Existing MOMAX BG tests remain passing.
  6. Non-BG regression remains passing (standard extractor path unaffected).

6. **Acceptance run**
- Run `python verify_momax_bg.py`.
- Confirm AIKO scenario now resolves:
  - non-empty `kom_nr`,
  - correct item split,
  - BG customer/tour resolution via `Kunden_Bulgarien.xlsx` using brand-aware `store_name`.

---

### Test Cases and Scenarios

1. **AIKO order page only**
- Input includes `AIKO - ORDER`, `Burgas - 88801739/29.10.25`, `Term of delivery`.
- Expected:
  - BG path active.
  - `kom_nr=88801739`.
  - `bestelldatum=29.10.25`.

2. **AIKO item code whitespace pair**
- `Code/Type = 30156 OJOO`.
- Expected:
  - `artikelnummer=30156`,
  - `modellnummer=OJOO`.

3. **MOMAX/MOEMAX existing behavior unchanged**
- Current MOMAX BG tests still pass (including slash-code parsing and model compaction).

4. **Non-BG document**
- Should not activate BG path; standard extraction remains unchanged.

---

### Assumptions and Defaults
1. `AIKO - ORDER` pages are part of the same BG document family and should share the same extraction path as MOMAX BG.
2. Detection should be broad enough to catch AIKO variants even when explicit “Bulgaria” text is absent, but still require order + term + kom/date markers to control false positives.
3. `store_name` should preserve brand signal (`AIKO` vs `MOMAX`) because BG customer disambiguation depends on it.
4. Function/module names (`momax_bg`) remain unchanged for now to avoid unnecessary refactor risk; behavior expands internally.
