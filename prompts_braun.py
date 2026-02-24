"""
Prompts for Braun order extraction (email + PDF).
"""

from __future__ import annotations


BRAUN_SYSTEM_PROMPT = (
    "You are a strict Braun purchase-order extraction engine. "
    "Extract one order from email + PDF into the required JSON schema. "
    "Return JSON only (no markdown, no commentary). "
    "Use only German field names exactly as requested."
)


def build_user_instructions_braun(source_priority: list[str]) -> str:
    return (
        "=== TASK ===\n"
        "Extract one Braun order from email + PDF pages.\n"
        f"SOURCE TRUST PRIORITY: {', '.join(source_priority).upper()}\n"
        "When sources conflict, follow the priority above.\n"
        "\n"
        "=== REQUIRED KEYS (EXACT NAMES) ===\n"
        "Header keys:\n"
        "ticket_number, kundennummer, adressnummer, kom_nr, kom_name, "
        "liefertermin, wunschtermin, bestelldatum, lieferanschrift, tour, "
        "store_name, store_address, seller, iln, iln_anl, iln_fil, "
        "human_review_needed, reply_needed, post_case\n"
        "Item keys:\n"
        "artikelnummer, modellnummer, menge, furncloud_id\n"
        "No English aliases.\n"
        "\n"
        "=== FIELD OBJECT FORMAT ===\n"
        "Each header/item field must be an object:\n"
        '{"value":"...", "source":"pdf|email|image|derived", "confidence":0.0-1.0}\n'
        "Always include every required key, even if value is empty.\n"
        "\n"
        "=== PDF INPUT USAGE ===\n"
        "Each PDF page includes image + digital text.\n"
        "Use the IMAGE to determine table structure, number of rows, and item quantities (menge).\n"
        "Use digital PDF text only to confirm/correct code fields and OCR ambiguities:\n"
        "- items[*].modellnummer\n"
        "- items[*].artikelnummer\n"
        "Preserve exact characters, including leading zeros and O vs 0.\n"
        "\n"
        "=== ROW EXTRACTION ===\n"
        "Create one output item per explicit order row in reading order.\n"
        "Assign line_no sequentially starting at 1.\n"
        "Do not reorder rows.\n"
        "\n"
        "=== HEADER EXTRACTION HINTS ===\n"
        "kundennummer: Kundennr/Kunden-Nr/Debitor/Konto\n"
        "kom_nr: Auftragsnr/Bestellnr/Order/Kommission\n"
        "bestelldatum: Bestelldatum/Datum\n"
        "liefertermin or wunschtermin: Liefertermin/Wunschliefertermin\n"
        "lieferanschrift: Lieferadresse/Lieferanschrift/Empfaenger block\n"
        "ILN from Anlieferung block: If the 'Anlieferung' section contains a 13-digit ILN/GLN "
        "(often starting with 40 or 90), extract it into BOTH iln_anl and iln.\n"
        "Do NOT include that 13-digit ILN line inside lieferanschrift.\n"
        "GLN Haus / Fuer Haus is NOT the delivery ILN. Do NOT map GLN Haus to iln or iln_anl.\n"
        "If both GLN Haus and Anlieferung ILN appear, always use the Anlieferung number.\n"
        "Keep iln_fil empty unless explicitly present elsewhere.\n"
        "\n"
        "=== OUTPUT CONTRACT ===\n"
        "Return strict JSON with top-level keys:\n"
        "message_id, received_at, header, items, status, warnings, errors\n"
        "status must be one of: ok, partial, failed.\n"
    )
