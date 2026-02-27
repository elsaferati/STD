Segmuller orders come with furnplan PDFs — the same format as xxxlutz_default. Currently Segmuller has 
  its own custom splitting rules (trailing 5-digit token = artikelnummer, rest = modellnummer) both in  
 the prompt and in post-processing normalization code. The goal is to replace these with the same       
 article code patterns used by xxxlutz_default for furnplan PDFs:
 - Standard hyphenated split: MODEL-ARTICLE (e.g., CQ9606XA-60951)
 - Reversed pattern: NUMERIC-ALPHA (e.g., 56847-ZB99 → artikel=56847, modell=ZB99)
 - Same PDF text usage rules (confirm/correct codes only, menge from image)

 Changes

 1. prompts_segmuller.py — Replace item code section (lines 53–68)

 Remove the entire === SEGMULLER ITEM PRIORITY (STRICT) === block (the hard rule about trailing 5-digit 
  token, Beschreibung fallback, order-table fallback merging, etc.)

 Replace with the xxxlutz_default article code patterns:

 === ARTICLE CODE PATTERNS ===
 - Standard hyphenated codes like 'CQ9606XA-60951' → SPLIT on hyphen:
     → modellnummer = part BEFORE hyphen (e.g., 'CQ9606XA')
     → artikelnummer = part AFTER hyphen (e.g., '60951')
 - REVERSED hyphen pattern (CRITICAL - accessory codes):
   - If code matches <NUMERIC>-<ALPHA> format (e.g., '56847-ZB99', '12345-AB12'):
     → artikelnummer = NUMERIC part (e.g., '56847')
     → modellnummer = ALPHA part (e.g., 'ZB99')
   - This is the REVERSE of the standard MODEL-ARTICLE pattern!
 - Examples:
   - 'OJ99-61469' → artikelnummer='61469', modellnummer='OJ99' (standard)
   - 'CQ1111XP-67538' → artikelnummer='67538', modellnummer='CQ1111XP' (standard)
   - '56847-ZB99' → artikelnummer='56847', modellnummer='ZB99' (REVERSED)
   - '12345-AB12' → artikelnummer='12345', modellnummer='AB12' (REVERSED)

 === SEGMULLER ITEM SOURCES ===
 Priority 1: Furnplan/scanned item rows (e.g. Pos | ArtNr | Beschreibung | ... | Menge).
 Priority 2: Order-table rows only if Furnplan codes are missing or unreadable.
 - Article codes from Furnplan rows → same split rules as above
 - menge ← Menge column
 - Use Beschreibung token fallback only when ArtNr is missing/unreadable.
 From order-table fallback rows: use only as fallback; prefer richer code fields from Furnplan.
 If order table and Furnplan describe the same real item (same Seg-Nr or same item context), output one 
  merged line and keep Furnplan code fields.

 Also add the PDF furnplan section from xxxlutz_default:
 ### PDF/TIF Attachment (furnplan style):
 - Article codes → same split rules as above
 - 'Menge' or quantity column → menge
 - '[xxxx xxxx]' bracket codes (may be sideways/rotated) → furncloud_id
 - Extract ALL items from ALL pages - don't stop after first table!

 2. normalize.py — Remove Segmuller-specific item code splitting

 Remove these components:
 - _SEGMULLER_MODEL_ARTIKEL_RE regex (line 195–197)
 - _SEGMULLER_ARTIKEL_RE regex (line 198)
 - _SEGMULLER_TRAILING_ARTIKEL_RE regex (line 199)
 - _mark_segmuller_code_derived() function (lines 943–946)
 - _split_segmuller_model_artikel() function (lines 949–977)
 - _normalize_segmuller_item_codes() function (lines 980–1003)
 - The call at line 1087–1088: elif (branch_id or "").strip() == "segmuller":
 _normalize_segmuller_item_codes(item)

 Keep _SEGMULLER_KOM_NAME_PREFIX_RE and _normalize_segmuller_kom_name() — those are unrelated to        
 article codes.

 3. verify_segmuller_item_code_split.py — Update tests

 The existing tests validate the old Segmuller-specific splitting. Either:
 - Remove the file entirely (since there's no normalize-level split logic anymore), or
 - Update the test expectations to reflect that normalize no longer modifies these fields for Segmuller 
  (the prompt handles it now, same as xxxlutz_default)

 Best approach: update tests so they confirm normalize does not alter the values — proving the prompt   
 is trusted to do the splitting (matching xxxlutz_default behavior).

 Files to modify

 1. prompts_segmuller.py — prompt text changes
 2. normalize.py — remove Segmuller item code split logic
 3. verify_segmuller_item_code_split.py — update/simplify tests

 Verification

 - Run python verify_segmuller_item_code_split.py after updating tests
 - Run python verify_segmuller_prompt_contract.py to confirm prompt structure is valid
 - Run any other verify scripts to check for regressions