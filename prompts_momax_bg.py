"""
BG (Bulgaria) special-case prompts for MOMAX/MOEMAX/AIKO orders.

Important: This prompt must be used ONLY for the BG split-order format where one order
arrives in separate PDFs that belong to the same logical order.
"""

from __future__ import annotations


def build_user_instructions_momax_bg(source_priority: list[str]) -> str:
    return (
        "=== TASK ===\n"
        "This is a special-case MOMAX/MOEMAX/AIKO BG (Bulgaria) order.\n"
        "The order is split across TWO PDF attachments; BOTH PDFs belong to ONE logical order.\n"
        "Extract ONE merged JSON order from BOTH PDFs (merge header + all items).\n"
        f"SOURCE TRUST PRIORITY: {', '.join(source_priority).upper()}\n"
        "If conflicting data exists across sources, strictly TRUST sources in this priority order.\n"
        "\n"
        "=== CRITICAL: OUTPUT FIELD NAMES ===\n"
        "You MUST use these EXACT German field names in your output:\n"
        "  Header: ticket_number, kundennummer, adressnummer, kom_nr, kom_name, liefertermin, wunschtermin, bestelldatum, lieferanschrift, tour, store_name, store_address, seller, iln_anl, iln_fil, human_review_needed, reply_needed, post_case\n"
        "  Items: artikelnummer, modellnummer, menge, furncloud_id\n"
        "Return ONLY valid JSON. Do NOT use English field names.\n"
        "\n"
        "=== BG (Bulgaria) PDF FORMAT ===\n"
        "PDF A (header-like) contains fields like:\n"
        "- Recipient: MOEMAX BULGARIA / MOMAX BULGARIA / AIKO BULGARIA\n"
        "- IDENT No: <digits>\n"
        "- ORDER / No <order number like 1711/12.12.25>\n"
        "- Term for delivery / Term of delivery: <date like 20.03.26>\n"
        "- Store: <city like VARNA>\n"
        "- Address: <store address line>\n"
        "\n"
        "PDF B (items table) contains:\n"
        "- Title like 'MOMAX - ORDER' / 'MOEMAX - ORDER' / 'AIKO - ORDER'\n"
        "- A table with columns like 'Code/Type' and 'Quantity'\n"
        "\n"
        "=== HEADER MAPPING (BG) ===\n"
        "- kundennummer: use IDENT No digits ONLY (e.g. '20197304')\n"
        "- kom_nr: this is the order number and can appear in different places:\n"
        "  - As 'No <digits>/<date>' (e.g. 'No 1711/12.12.25')\n"
        "  - OR directly in the '<BRAND> - ORDER' header line like '<STORE> - <digits>/<date>'\n"
        "    Example: 'VARNA - 88801711/12.12.25' => kom_nr = '88801711' (digits only)\n"
        "  - If both variants exist across the two PDFs, prefer the longer numeric id (e.g. 88801711 over 1711)\n"
        "- bestelldatum: use the date part after '/' from the same order string (e.g. '12.12.25')\n"
        "- liefertermin: use 'Term for delivery' / 'Term of delivery' value (keep raw text)\n"
        "- kom_name: leave empty '' (not used for this BG special case)\n"
        "- store_name:\n"
        "  - MOMAX/MOEMAX documents: 'MOMAX BULGARIA - <Store>'\n"
        "  - AIKO documents: 'AIKO BULGARIA - <Store>'\n"
        "- store_address: use the store address line\n"
        "- lieferanschrift: set equal to store_address unless an explicit different delivery address exists\n"
        "- seller: usually not present; leave empty if missing\n"
        "- adressnummer, iln_anl, iln_fil, tour: usually not present; leave empty if missing\n"
        "- human_review_needed, reply_needed, post_case: default to false unless explicitly indicated\n"
        "\n"
        "=== ITEM EXTRACTION (BG) ===\n"
        "Extract ALL item rows from the '<BRAND> - ORDER' table.\n"
        "- menge: use the Quantity column.\n"
        "- furncloud_id: typically not present; leave empty unless found.\n"
        "\n"
        "CODE/TYPE -> artikelnummer/modellnummer rules:\n"
        "1) If Code/Type contains '/':\n"
        "   - artikelnummer = the LAST segment after the final '/'\n"
        "   - modellnummer = everything BEFORE that last segment, but REMOVE all '/' separators\n"
        "   - Examples:\n"
        "     - 'ZB99/76403' -> modellnummer='ZB99', artikelnummer='76403'\n"
        "     - 'SN/SN/71/SP/91/181' -> modellnummer='SNSN71SP91', artikelnummer='181'\n"
        "2) Else if Code/Type contains '-': apply standard split rules:\n"
        "   - Standard: 'MODEL-ARTICLE' => modellnummer=before '-', artikelnummer=after '-'\n"
        "   - Reversed accessory: '<NUMERIC>-<ALPHA>' => artikelnummer=numeric, modellnummer=alpha\n"
        "3) Else if Code/Type matches '<NUMERIC> <ALPHA>' (e.g. '30156 OJOO'):\n"
        "   - artikelnummer = NUMERIC, modellnummer = ALPHA\n"
        "4) Else: artikelnummer = Code/Type, modellnummer = ''\n"
        "\n"
        "=== REQUIRED OUTPUT STRUCTURE ===\n"
        "Your response must be valid JSON with exactly this top-level structure:\n"
        "{\n"
        '  "message_id": "string",\n'
        '  "received_at": "ISO-8601",\n'
        '  "header": { ... field entries ... },\n'
        '  "items": [ ... ],\n'
        '  "status": "ok|partial|failed",\n'
        '  "warnings": [],\n'
        '  "errors": []\n'
        "}\n"
        "Each header/item field MUST be an object: {\"value\": ..., \"source\": \"pdf|email|image|derived\", \"confidence\": 0.0..1.0}.\n"
        "Include ALL required keys even if empty (use empty string '' and confidence=0.0).\n"
    )
