from prompts_segmuller import build_user_instructions_segmuller


def test_segmuller_prompt_contract() -> None:
    prompt = build_user_instructions_segmuller(["pdf", "email", "image"])

    assert "=== DOCUMENT ROLE DETECTION ===" in prompt
    assert "Scan all pages across all PDF attachments. Do not rely only on the first PDF." in prompt
    assert "Furnplan/scanned pages are valid item-code sources even when digital text on those pages is sparse or empty." in prompt

    assert "=== SEGMULLER ITEM PRIORITY (STRICT) ===" in prompt
    assert "Priority 1: Furnplan/scanned item rows" in prompt
    assert "Priority 2: Order-table rows only if Furnplan codes are missing or unreadable." in prompt
    assert "modellnummer <- ArtNr token (example: S1111XA)" in prompt
    assert "artikelnummer <- code-like token in/next to Beschreibung (example: 18801)" in prompt
    assert "Do not invent short weak article codes if Furnplan provides a clearer code." in prompt

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

    assert "status must be one of: ok, partial, failed." in prompt
    print("SUCCESS: Segmuller prompt contract includes furnplan priority, strict address rules, and ILN block mapping.")


if __name__ == "__main__":
    test_segmuller_prompt_contract()
