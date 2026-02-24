"""
Second-pass prompts for PDF-based item code verification.
"""

from __future__ import annotations


VERIFY_ITEMS_SYSTEM_PROMPT = (
    "You verify item identifiers against PDF pages. "
    "Only verify/correct the requested item fields for the active profile. "
    "Return strict JSON only."
)


def _build_porta_verify_items_instructions() -> str:
    return (
        "=== TASK ===\n"
        "Verify and correct Porta item identifiers from PDF pages.\n"
        "Input contains current extracted items and PDF pages (image + digital text).\n"
        "\n"
        "=== SCOPE ===\n"
        "- Primary: modellnummer and artikelnummer\n"
        "- Optional: menge (only if clearly visible and certain)\n"
        "- Do not modify unrelated fields.\n"
        "\n"
        "=== PORTA CODE SPLIT RULES (STRICT) ===\n"
        "0) Ignore ANY PDF table 'Artikel-Nr' value (often like '4609952 / 88' or '1005141 / 88'). "
        "This is a store-internal number and must NEVER be used as artikelnummer or modellnummer. "
        "Do NOT split it, normalize it, or use it as a fallback.\n"
        "   Example (NEGATIVE): Artikel-Nr: 1005141 / 88 -> IGNORE ENTIRELY\n"
        "1) 'Auf. CQ 1616 TP-67430' style main code:\n"
        "   -> artikelnummer='67430', modellnummer='CQ1616'\n"
        "   If current snapshot has them reversed, swap to match the rule above.\n"
        "2) For '<PREFIX>-<NUMERIC>' where PREFIX starts with 0J or OJ:\n"
        "   -> modellnummer='<PREFIX>' (NO trailing dash), artikelnummer='<NUMERIC>'\n"
        "   Examples:\n"
        "   - OJ99-14323 -> modellnummer='OJ99', artikelnummer='14323'\n"
        "   - OJ00-66017 -> modellnummer='OJ00', artikelnummer='66017'\n"
        "   - 0J00-30156 -> modellnummer='0J00', artikelnummer='30156'\n"
        "   - 0J00-15237 -> modellnummer='0J00', artikelnummer='15237'\n"
        "3) Standard hyphen split (not 'Auf.' line and not 0J/OJ accessory pattern):\n"
        "   -> modellnummer=part BEFORE hyphen\n"
        "   -> artikelnummer=part AFTER hyphen\n"
        "   Example: CQ1616XP-00943 -> modellnummer='CQ1616XP', artikelnummer='00943'\n"
        "4) Preserve leading zeros and uppercase exactly.\n"
        "5) Preserve O vs 0 exactly as seen (do not normalize).\n"
        "6) Do not keep combined token in one field when it clearly splits.\n"
        "7) If no other valid code patterns or tokens exist in the item block, "
        "set artikelnummer and modellnummer to empty strings with low confidence (0.0).\n"
        "\n"
        "=== RULES ===\n"
        "1. Keep the exact same number of item lines as provided.\n"
        "2. Never invent rows and never remove rows.\n"
        "3. Match output lines by line_no.\n"
        "4. If uncertain for a line, echo original values with low confidence.\n"
        "5. Confidence must be in [0.0, 1.0].\n"
        "6. reason should be short and specific.\n"
        "\n"
        "=== REQUIRED OUTPUT JSON ===\n"
        "{\n"
        '  "verified_items": [\n'
        "    {\n"
        '      "line_no": 1,\n'
        '      "modellnummer": "string",\n'
        '      "artikelnummer": "string",\n'
        '      "menge": 1,\n'
        '      "confidence": 0.0,\n'
        '      "reason": "short"\n'
        "    }\n"
        "  ],\n"
        '  "warnings": []\n'
        "}\n"
    )


def _build_momax_bg_verify_items_instructions() -> str:
    return (
        "=== TASK ===\n"
        "Verify and correct MOMAX BG item identifiers from PDF pages.\n"
        "Input contains current extracted items and PDF pages (image + digital text).\n"
        "\n"
        "=== SCOPE ===\n"
        "- Verify/correct only: modellnummer and artikelnummer\n"
        "- Do not modify unrelated fields.\n"
        "\n"
        "=== MOMAX BG CODE RULES (STRICT) ===\n"
        "1) Slash pattern: last segment is artikelnummer, previous segments form modellnummer.\n"
        "   - 'ZB99/76403' -> modellnummer='ZB99', artikelnummer='76403'\n"
        "   - 'SN/SN/71/SP/91/181' -> modellnummer='SNSN71SP91', artikelnummer='181'\n"
        "   - Wrapped final segment must be merged (line-break artifact):\n"
        "     'SN/SN/71/SP/91/180 98' -> artikelnummer='18098'\n"
        "2) Hyphen pattern:\n"
        "   - Standard: 'MODEL-ARTICLE' -> modellnummer=before '-', artikelnummer=after '-'\n"
        "   - Reversed accessory: '<NUMERIC>-<ALPHA>' -> artikelnummer=numeric, modellnummer=alpha\n"
        "3) Whitespace pair '<NUMERIC> <ALPHA>' -> artikelnummer=numeric, modellnummer=alpha\n"
        "4) modellnummer must be compact (remove '/' and spaces).\n"
        "5) Preserve leading zeros and uppercase exactly as shown.\n"
        "\n"
        "=== RULES ===\n"
        "1. Keep the exact same number of item lines as provided.\n"
        "2. Never invent rows and never remove rows.\n"
        "3. Match output lines by line_no.\n"
        "4. If uncertain for a line, echo original values with low confidence.\n"
        "5. Confidence must be in [0.0, 1.0].\n"
        "6. reason should be short and specific.\n"
        "\n"
        "=== REQUIRED OUTPUT JSON ===\n"
        "{\n"
        '  "verified_items": [\n'
        "    {\n"
        '      "line_no": 1,\n'
        '      "modellnummer": "string",\n'
        '      "artikelnummer": "string",\n'
        '      "confidence": 0.0,\n'
        '      "reason": "short"\n'
        "    }\n"
        "  ],\n"
        '  "warnings": []\n'
        "}\n"
    )


def build_verify_items_instructions(verification_profile: str = "porta") -> str:
    profile = (verification_profile or "").strip().lower()
    if profile == "momax_bg":
        return _build_momax_bg_verify_items_instructions()
    return _build_porta_verify_items_instructions()
