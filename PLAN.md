## Segmuller Prompt Upgrade for Item + Address Accuracy

### Summary
Use this sample as the canonical Segmuller pattern and update the Segmuller prompt to:
1. Prioritize scanned furnplan (`Skizze/Aufstellung`) item-table codes over coarse order-table codes.
2. Extract delivery/store addresses in strict `street + PLZ/city` format.
3. Split ILNs by block (`delivery` vs `store/billing`) so `iln_anl/iln` and `iln_fil` are filled correctly.

No skill is applied here because the available skills are only for skill creation/installation, not prompt tuning.

### Files to change
- [prompts_segmuller.py](c:/Users/Admin/Documents/GitHub/STD/prompts_segmuller.py)
- Add prompt contract test: [verify_segmuller_prompt_contract.py](c:/Users/Admin/Documents/GitHub/STD/verify_segmuller_prompt_contract.py)

### Implementation plan

1. Update Segmuller prompt sections in `build_user_instructions_segmuller(...)` with explicit multi-document logic.
- Add a `=== DOCUMENT ROLE DETECTION ===` section:
  - Identify primary order pages by `BESTELLUNG` + table headers like `Pos/Upo/Seg-Nr./Ihre Art.-Nr.`.
  - Identify furnplan/scanned pages by `SKIZZE / AUFSTELLUNG`, `furnplan`, rotated drawings, and scanned layouts.
  - State that furnplan pages are valid item-code sources even when digital text is empty.
- Add rule: scan all pages/all attachments; do not rely only on first PDF.

2. Add strict item extraction priority for Segmuller.
- New `=== SEGMULLER ITEM PRIORITY (STRICT) ===` section:
  - Priority 1: furnplan item table rows (`Pos | ArtNr | Beschreibung | ... | Menge`).
  - Priority 2: order table only as fallback when furnplan codes are unclear.
- Mapping rules:
  - From furnplan row: `modellnummer <- ArtNr` token (e.g. `S1111XA`), `artikelnummer <- code-like token in/next to Beschreibung` (e.g. `18801`), `menge <- Menge`.
  - From order fallback row: we will fix later
- Dedup/merge rule:
  - One output item per real occurrence.
  - If order table and furnplan describe the same line (same Seg-Nr / same item context), keep one merged item, preferring furnplan code fields.
- Keep existing `line_no` sequential behavior.

3. Add strict address/store extraction rules.
- New `=== SEGMULLER ADDRESS RULES ===` section:
  - `lieferanschrift`: from `Lieferung an` / `Lieferanschrift` block, output only:
    - Line 1: street + house number
    - Line 2: PLZ + city
  - Explicitly drop recipient/company line from `lieferanschrift` (per your choice).
  - Exclude ILN lines from address fields.
  - `store_name`: company entity from `Auftragsbestätigungsanschrift` / `Rechnungsanschrift`.
  - `store_address`: only street + PLZ/city from those store/billing blocks.
- Add examples directly in prompt:
  - `lieferanschrift`: `Am Rotböll 7\n64331 Weiterstadt`
  - `store_address`: `Münchner Str. 35\n86316 Friedberg`

4. Add strict ILN block mapping instructions.
- New `=== SEGMULLER ILN MAPPING ===` section:
  - Delivery block ILN -> `iln_anl` and `iln`.
  - Store/billing ILN (`Auftragsbestätigungsanschrift`/`Rechnungsanschrift`) -> `iln_fil`.
  - Do not swap these.
  - Do not embed ILN text into address fields.

5. Keep output contract unchanged.
- Retain same required schema/keys/object format.
- Keep status enum unchanged (`ok|partial|failed`).

### Important interfaces/APIs/types
- No Python API/type changes.
- No branch/routing changes.
- Only prompt behavior for existing Segmuller branch is changed.

### Test cases and scenarios

1. Prompt contract test (`verify_segmuller_prompt_contract.py`):
- Assert prompt text contains explicit furnplan-first item priority.
- Assert prompt text contains `street+PLZ only` for `lieferanschrift`.
- Assert prompt text contains `store_name` + `store_address` sourcing from store/billing blocks.
- Assert prompt text contains ILN split rule (`delivery -> iln_anl+iln`, `store/billing -> iln_fil`).

2. Sample-case acceptance scenario (manual/LLM run with provided files):
- Inputs:
  - `CLIENT CASES/segmuller/ORDER 1/Bestellung_850625542001_______.pdf`
  - `CLIENT CASES/segmuller/ORDER 1/E19RGE07.PDF`
  - `CLIENT CASES/segmuller/ORDER 1/Email Body.txt`
- Expected extraction targets:
  - `kom_nr = 850625542001`
  - `lieferanschrift = "Am Rotböll 7\n64331 Weiterstadt"`
  - `store_address = "Münchner Str. 35\n86316 Friedberg"`
  - `store_name` from store/billing block company
  - `iln_anl = iln = 4042861001501`
  - `iln_fil = 4042861000009`
  - Items prefer furnplan-coded row (`S1111XA` + `18801`) over weak `14` token from order row.
- Regression guard:
  - `artikelnummer` must not be `14` when furnplan provides better code.

3. Quick verification command set after implementation:
- `python -m py_compile prompts_segmuller.py verify_segmuller_prompt_contract.py`
- `python verify_segmuller_prompt_contract.py`

### Assumptions and defaults
- Default chosen: scanned furnplan pages are authoritative for item codes when available.
- Default chosen: `lieferanschrift` is `street+PLZ/city` only (no company line).
- Default chosen: ILNs are split by semantic block (delivery vs store/billing).
- If furnplan item row is unreadable, fallback to order table without inventing short weak article codes.
