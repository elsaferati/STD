from prompts_segmuller import build_user_instructions_segmuller


def test_segmuller_prompt_contract() -> None:
    prompt = build_user_instructions_segmuller(["pdf", "email", "image"])

    assert "=== DOCUMENT ROLE DETECTION ===" in prompt
    assert "Scan all pages across all PDF attachments. Do not rely only on the first PDF." in prompt
    assert "Furnplan/scanned pages are valid item-code sources even when digital text on those pages is sparse or empty." in prompt

    assert "=== ARTICLE CODE PATTERNS ===" in prompt
    assert "Standard hyphenated codes like 'CQ9606XA-60951' -> SPLIT on hyphen:" in prompt
    assert "REVERSED hyphen pattern (CRITICAL - accessory codes):" in prompt
    assert "If code matches <NUMERIC>-<ALPHA> format (e.g., '56847-ZB99', '12345-AB12'):" in prompt
    assert "This is the REVERSE of the standard MODEL-ARTICLE pattern!" in prompt
    assert "'OJ99-61469' -> artikelnummer='61469', modellnummer='OJ99' (standard)" in prompt
    assert "'56847-ZB99' -> artikelnummer='56847', modellnummer='ZB99' (REVERSED)" in prompt

    assert "=== SEGMULLER ITEM SOURCES ===" in prompt
    assert "Priority 1: Furnplan/scanned item rows" in prompt
    assert "Priority 2: Order-table rows only if Furnplan codes are missing or unreadable." in prompt
    assert "Article codes from Furnplan rows -> same split rules as above" in prompt
    assert "From order-table fallback rows: use only as fallback; prefer richer code fields from Furnplan." in prompt
    assert "### PDF/TIF Attachment (furnplan style):" in prompt
    assert "'Menge' or quantity column -> menge" in prompt
    assert "'[xxxx xxxx]' bracket codes (may be sideways/rotated) -> furncloud_id" in prompt
    assert "Extract ALL items from ALL pages - don't stop after first table!" in prompt

    assert "=== SEGMULLER FURNCLOUD_ID ===" in prompt
    assert "Find furncloud_id anywhere in email or PDF (all pages, including scanned/drawing pages)." in prompt
    assert "If a valid furncloud_id is found once, apply the same furncloud_id to all items." in prompt

    assert "=== SEGMULLER ADDRESS RULES ===" in prompt
    assert "line 1 = street + house number" in prompt
    assert "line 2 = PLZ + city" in prompt
    assert "Drop recipient/company line from lieferanschrift." in prompt
    assert "store_name: company entity from Auftragsbestaetigungsanschrift or Rechnungsanschrift block." in prompt
    assert "store_address: only street + house number + PLZ/city lines from Auftragsbestaetigungsanschrift or Rechnungsanschrift block." in prompt

    assert "=== SEGMULLER ILN MAPPING ===" in prompt
    assert "Delivery block ILN/GLN -> iln_anl and iln." in prompt
    assert "Store/billing ILN from Auftragsbestaetigungsanschrift or Rechnungsanschrift -> iln_fil." in prompt
    assert "Do not swap delivery/store ILN mappings." in prompt
    assert "kom_name: only the name part (example: '22300 NUESSLER' -> 'NUESSLER')." in prompt

    assert "status must be one of: ok, partial, failed." in prompt
    print("SUCCESS: Segmuller prompt contract includes article-pattern rules, furnplan PDF extraction, and ILN/address mapping.")


if __name__ == "__main__":
    test_segmuller_prompt_contract()
