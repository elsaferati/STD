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
        "1) 'Auf. CQ 1616 TP-67430' style main code:\n"
        "   -> artikelnummer='CQ1616', modellnummer='67430'\n"
        "2) For '<PREFIX>-<NUMERIC>' where PREFIX starts with 0J:\n"
        "   -> modellnummer='<PREFIX>-', artikelnummer='<NUMERIC>'\n"
        "   Examples:\n"
        "   - 0J99-14323 -> modellnummer='0J99-', artikelnummer='14323'\n"
        "   - 0J00-66017 -> modellnummer='0J00-', artikelnummer='66017'\n"
        "   - 0J00-30156 -> modellnummer='0J00-', artikelnummer='30156'\n"
        "   - 0J00-15237 -> modellnummer='0J00-', artikelnummer='15237'\n"
        "3) Preserve leading zeros and uppercase exactly.\n"
        "4) Do not keep combined token in one field when it clearly splits.\n"
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
