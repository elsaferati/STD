"""
Second-pass prompts for digital-text-only PDF item code verification.
"""

from __future__ import annotations


VERIFY_ITEMS_SYSTEM_PROMPT = (
    "You verify item identifiers using digital PDF text only. "
    "Only verify/correct the requested item fields for the active profile. "
    "Return strict JSON only."
)


def _build_porta_verify_items_instructions() -> str:
    return (
        "=== TASK ===\n"
        "Verify and correct Porta item identifiers from digital PDF text only.\n"
        "Input contains current extracted items and digital PDF text by page.\n"
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
        "4. Use only provided digital PDF text + current item snapshot; do not infer from images.\n"
        "5. If uncertain for a line, echo original values with low confidence.\n"
        "6. Confidence must be in [0.0, 1.0].\n"
        "7. reason should be short and specific.\n"
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
        "Verify and correct MOMAX BG item identifiers from digital PDF text only.\n"
        "Input contains current extracted items and digital PDF text by page.\n"
        "\n"
        "=== SCOPE ===\n"
        "- Verify/correct only: modellnummer and artikelnummer\n"
        "- Do not modify unrelated fields.\n"
        "\n"
        "=== MOMAX BG CODE RULES (STRICT) ===\n"
        "1) artikelnummer must match '^\\\\d{5}[A-Z]?$' (leading zero allowed).\n"
        "   Never output standalone artikelnummer='XB' or artikelnummer='XP'.\n"
        "2) XB/XP is a modellnummer suffix. Relocate suffix from artikel tokens when needed.\n"
        "   - '74430XB' + 'CQ9191' -> artikel='74430', modell='CQ9191XB'\n"
        "3) If article/model look swapped, swap deterministically:\n"
        "   - artikel looks CQ*/OJ*/0J* and modell looks article(+optional XB/XP)\n"
        "   - Example: artikel='CQ1616', modell='42821KXB' -> artikel='42821K', modell='CQ1616XB'\n"
        "4) Slash tokens: pick artikel token by strict artikel regex (not necessarily last token).\n"
        "   Build modellnummer from remaining tokens as alpha tokens + numeric tail tokens + XB/XP suffix.\n"
        "   Example: '60812/XP/CQSN/91' -> artikel='60812', modell='CQSN91XP'\n"
        "5) Wrapped digit artifact must merge: '.../180 98' -> artikel='18098'.\n"
        "6) Hyphen/whitespace fallback:\n"
        "   - Standard 'MODEL-ARTICLE' split\n"
        "   - Reversed accessory '<NUMERIC>-<ALPHA>'\n"
        "   - '<NUMERIC> <ALPHA>'\n"
        "7) modellnummer must be compact (remove '/' and spaces).\n"
        "8) Preserve leading zeros and uppercase exactly as shown.\n"
        "\n"
        "=== RULES ===\n"
        "1. Keep the exact same number of item lines as provided.\n"
        "2. Never invent rows and never remove rows.\n"
        "3. Match output lines by line_no.\n"
        "4. Use only provided digital PDF text + current item snapshot; do not infer from images.\n"
        "5. If uncertain for a line, echo original values with low confidence.\n"
        "6. Confidence must be in [0.0, 1.0].\n"
        "7. reason should be short and specific.\n"
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


def _build_braun_verify_items_instructions() -> str:
    return (
        "=== TASK ===\n"
        "Verify and correct Braun item identifiers from digital PDF text only.\n"
        "Input contains current extracted items and digital PDF text by page.\n"
        "\n"
        "=== SCOPE ===\n"
        "- Primary: modellnummer and artikelnummer\n"
        "- Optional: menge (only if clearly visible and certain)\n"
        "- Do not modify unrelated fields.\n"
        "\n"
        "=== BRAUN GENERIC VERIFICATION RULES ===\n"
        "1) Keep the exact same number of item lines as provided.\n"
        "2) Never invent rows and never remove rows.\n"
        "3) Match output lines by line_no.\n"
        "4) Use only provided digital PDF text + current item snapshot; do not infer from images.\n"
        "5) Use digital PDF text to confirm exact characters for code fields.\n"
        "6) Preserve leading zeros exactly.\n"
        "7) Preserve O vs 0 exactly as shown (do not normalize).\n"
        "8) If uncertain for a line, echo original values with low confidence.\n"
        "9) Confidence must be in [0.0, 1.0].\n"
        "10) reason should be short and specific.\n"
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


def build_verify_items_instructions(verification_profile: str = "porta") -> str:
    profile = (verification_profile or "").strip().lower()
    if profile == "momax_bg":
        return _build_momax_bg_verify_items_instructions()
    if profile == "braun":
        return _build_braun_verify_items_instructions()
    return _build_porta_verify_items_instructions()
