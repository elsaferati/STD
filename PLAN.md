# MOMAX BG Item-Code Repair And Backfill

## Summary
1. Confirmed the agent output is wrong for your five scanned PDFs, and the errors are persisted in output JSON/XML.
2. Confirmed root cause is rule logic, not just UI rendering: current MOMAX BG logic assumes slash-last-segment is always `artikelnummer` and lacks strict `artikelnummer` validation, causing swaps and bad XB/XP placement.
3. Implement a deterministic MOMAX BG strict code-correction layer, then backfill existing output files and regenerate XML.

## Confirmed Wrong Behavior
1. `3386460` (Ticket 1): `artikelnummer=74430XB`, `modellnummer=CQ9191` should become `artikelnummer=74430`, `modellnummer=CQ9191XB`. Evidence: [CAJgTRbVy...json](c:/Users/Admin/Documents/GitHub/STD/output/CAJgTRbVyDFUFHqWW1XEQa_2rhQtYuybSJ2i-w8-5XPhS9jEc0Q_mail.gmail.com.json:115).
2. `3424290` (Ticket 2): `artikelnummer=CQ1616`, `modellnummer=42821KXB` should become `artikelnummer=42821K`, `modellnummer=CQ1616XB`. Evidence: [CAJgTRbUq3...json](c:/Users/Admin/Documents/GitHub/STD/output/CAJgTRbUq3Vqx88_AkQWrJLEW4QbK7Txu4U-O__B6atsaZR_yOg_mail.gmail.com.json:115).
3. `3413460` (Ticket 4): `artikelnummer=CQ9191`, `modellnummer=74405XB` should become `artikelnummer=74405`, `modellnummer=CQ9191XB`. Evidence: [CAJgTRbUpm...json](c:/Users/Admin/Documents/GitHub/STD/output/CAJgTRbUpmXe_8q6Vyu43LGxFXGRC3O5MVi0N5smN7qo_stnPYw_mail.gmail.com.json:115).
4. `3413160` (Ticket 5): `artikelnummer=XP`, `modellnummer=CQ222206363` should become `artikelnummer=06363`, `modellnummer=CQ2222XP`. Evidence: [CAJgTRbVbJ...json](c:/Users/Admin/Documents/GitHub/STD/output/CAJgTRbVbJFpHCszfvVRq0VQrKfmquHZ5ohCfdLt3RYSZROCaZA_mail.gmail.com.json:115).
5. `3402830` (Ticket 6): outputs like `artikelnummer=91`, `modellnummer=60812XPCQSN` should become `artikelnummer=60812`, `modellnummer=CQSN91XP`. Evidence: [CAJgTRbX_0...json](c:/Users/Admin/Documents/GitHub/STD/output/CAJgTRbX_0UXFw1LUVkPJ5NKtzHn1AAW8-4-LMuf8SB_eDUvReg_mail.gmail.com.json:115).
6. Current rules enforcing problematic behavior are in [prompts_momax_bg.py](c:/Users/Admin/Documents/GitHub/STD/prompts_momax_bg.py:83), [prompts_verify_items.py](c:/Users/Admin/Documents/GitHub/STD/prompts_verify_items.py:87), and [normalize.py](c:/Users/Admin/Documents/GitHub/STD/normalize.py:402).

## Important Interface/Type Changes
1. Add exported helper in [normalize.py](c:/Users/Admin/Documents/GitHub/STD/normalize.py): `apply_momax_bg_strict_item_code_corrections(data: dict[str, Any]) -> int` returning number of corrected lines.
2. Add new `derived_from` values on corrected fields: `momax_bg_strict_code_parser` and `momax_bg_suffix_relocation`.
3. Add new maintenance CLI script [backfill_momax_bg_codes.py](c:/Users/Admin/Documents/GitHub/STD/backfill_momax_bg_codes.py) with args: `dir`, `--dry-run`, `--only-id`.

## Implementation Plan
1. In [normalize.py](c:/Users/Admin/Documents/GitHub/STD/normalize.py), enforce strict `artikelnummer` format for MOMAX BG: `^\d{5}[A-Z]?$` (leading zero allowed), and forbid `XB/XP` as standalone article.
2. Add deterministic correction rules in this order for each MOMAX BG item:
3. Rule A: If `artikelnummer` is `^\d{5}(XB|XP)$`, split suffix to `modellnummer` tail.
4. Rule B: If `artikelnummer` looks model-like (`CQ*`, `OJ*`, `0J*`) and `modellnummer` looks article-like plus optional `XB/XP`, swap and relocate suffix.
5. Rule C: If `artikelnummer` is only `XB|XP` and `modellnummer` ends with 5-digit article tail, extract tail as article and keep suffix on model.
6. Rule D: If `artikelnummer` is short numeric (like `91`) and `modellnummer` starts with 5-digit article then `XB|XP`, rebuild as article=leading 5-digit token, model=`alpha_parts + old_short_numeric + suffix`.
7. Rule E: For slash tokens, pick article token by strict article regex, then build model as `alpha tokens + numeric tail tokens + XP/XB suffix` (selected policy).
8. Keep existing MOMAX BG corrections (wrapped article merge, slash compaction) but execute strict correction after them and again after item-verification apply in [pipeline.py](c:/Users/Admin/Documents/GitHub/STD/pipeline.py:446) to guarantee final consistency.
9. Update MOMAX BG prompt text in [prompts_momax_bg.py](c:/Users/Admin/Documents/GitHub/STD/prompts_momax_bg.py) and verifier prompt in [prompts_verify_items.py](c:/Users/Admin/Documents/GitHub/STD/prompts_verify_items.py) to match strict article/model constraints and XP/XB behavior.

## Test Cases And Scenarios
1. Add regression tests in [verify_momax_bg.py](c:/Users/Admin/Documents/GitHub/STD/verify_momax_bg.py) for the five exact ticket patterns above.
2. Add test for slash reorder behavior: `60812/XP/CQSN/91 -> artikel=60812, modell=CQSN91XP`.
3. Add test for `06363` leading-zero preservation.
4. Add test ensuring existing wrapped-article correction (`180 98 -> 18098`) still passes.
5. Add pipeline-level test ensuring strict correction remains true even when verifier returns conflicting fields with confidence >= threshold.
6. Run full MOMAX BG test suite and confirm no regressions in existing cases.

## Backfill And Rollout
1. Implement [backfill_momax_bg_codes.py](c:/Users/Admin/Documents/GitHub/STD/backfill_momax_bg_codes.py) to process existing `output/*.json`.
2. Detect MOMAX BG records via routing warning or `kom_name.derived_from == momax_bg_policy`.
3. Apply strict corrections, refresh warnings/status, write JSON only if changed, regenerate XML with current exporter.
4. Run first in `--dry-run`, then apply to all affected orders including both `3402830` outputs (`1000006` and `1000010`).

## Assumptions And Defaults Chosen
1. Scope is global for all MOMAX BG orders, not only these five.
2. Slash model build policy is `alpha+numeric then XP/XB suffix`.
3. Existing bad outputs will be auto-backfilled and XML regenerated.
4. Ticket 1 canonical correction is `artikelnummer=74430`, `modellnummer=CQ9191XB`.
