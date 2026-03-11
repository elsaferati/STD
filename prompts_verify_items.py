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
        "=== PORTA CODE IDENTITY (STRICT) ===\n"
        "modellnummer is the compact uppercase model token for the item.\n"
        "In final values, modellnummer must not contain spaces, slashes, or hyphens.\n"
        "Porta model numbers are usually uppercase alphanumeric tokens such as "
        "'CQEG5899', 'CQEG00', 'CQ1616', 'PD96713696', 'ACAW81AM96'.\n"
        "Observed Porta model-number shapes are mostly 8, 10, or 12 characters with no separators.\n"
        "Rare 4-letter all-alpha model forms can exist (for example 'DMAW', 'DMSN', 'NEAW', 'ZJAW').\n"
        "artikelnummer must be exactly one of these forms: '12345', 'A12345', or '12345A'.\n"
        "Hard negatives: Porta table values like 'Artikel-Nr. 4611217 / 841', dimensions, legal numbers like 'HRB 9684', "
        "descriptor words like 'SONATE', finish/color words like 'matt', quantities like '1 Stk', and furncloud codes are never modellnummer/artikelnummer.\n"
        "Decision rule: if one token is clearly article-shaped and the other is clearly model-shaped, assign them that way. "
        "If both are ambiguous or neither is code-like, leave both empty instead of inventing values.\n"
        "\n"
        "=== PORTA CODE SPLIT RULES (STRICT) ===\n"
        "0) Ignore ANY PDF table 'Artikel-Nr' value (often like '4609952 / 88' or '1005141 / 88'). "
        "This is a store-internal number and must NEVER be used as artikelnummer or modellnummer. "
        "Do NOT split it, normalize it, or use it as a fallback.\n"
        "   Example (NEGATIVE): Artikel-Nr: 1005141 / 88 -> IGNORE ENTIRELY\n"
        "1) Combined 'Ausführung' + 'Art.Nr.' pair inside the same item block:\n"
        "   Example: 'Ausführung: 78706' and 'Art.Nr. PD967136SP96'\n"
        "   -> artikelnummer='78706'\n"
        "   -> modellnummer='PD967136SP96'\n"
        "   IMPORTANT: this 'Art.Nr.' item-code label is valid and is different from the table-column 'Artikel-Nr.'\n"
        "2) 'Auf. CQ 1616 TP-67430' style main code:\n"
        "   -> artikelnummer='67430', modellnummer='CQ1616'\n"
        "   If current snapshot has them reversed, swap to match the rule above.\n"
        "2b) Typ/Ausf paired code lines in the same item block:\n"
        "   Example: 'Typ 77171' and 'Ausf. CQ1616'\n"
        "   -> artikelnummer='77171', modellnummer='CQ1616'\n"
        "   'Typ' is an article label and is NEVER a modellnummer token.\n"
        "   If the model is printed on the next line with spaces, compact it back into one token.\n"
        "   Example: 'Typ 57382' + next line 'PD SL 61 SP 96' -> modellnummer='PDSL61SP96', artikelnummer='57382'\n"
        "   This rule does NOT make table-column 'Artikel-Nr.' valid; keep table 'Artikel-Nr.' ignored.\n"
        "   Positive examples: 'CQEG5899 76808G' and 'CQEG00 09387' are valid model/article pairs.\n"
        "3) For '<PREFIX>-<NUMERIC>' OR '<PREFIX> <NUMERIC>' where PREFIX starts with 0J or OJ:\n"
        "   -> modellnummer='<PREFIX>' (NO trailing dash), artikelnummer='<NUMERIC>'\n"
        "   Examples:\n"
        "   - OJ99-14323 -> modellnummer='OJ99', artikelnummer='14323'\n"
        "   - OJ00-66017 -> modellnummer='OJ00', artikelnummer='66017'\n"
        "   - OJ00 31681 -> modellnummer='OJ00', artikelnummer='31681'\n"
        "   - 0J00-30156 -> modellnummer='0J00', artikelnummer='30156'\n"
        "   - 0J00-15237 -> modellnummer='0J00', artikelnummer='15237'\n"
        "3b) If description text contains a compact token like 'Nr. OJ363612782', split the valid artikelnummer from the end.\n"
        "   -> modellnummer='OJ3636', artikelnummer='12782'\n"
        "4) Standard hyphen split (not 'Auf.' line and not 0J/OJ accessory pattern):\n"
        "   -> modellnummer=part BEFORE hyphen\n"
        "   -> artikelnummer=part AFTER hyphen\n"
        "   Example: CQ1616XP-00943 -> modellnummer='CQ1616XP', artikelnummer='00943'\n"
        "4b) Slash-separated component pair '<MODEL>/<NUMERIC>' is valid item code syntax\n"
        "   (different from the ignored table-column 'Artikel-Nr.').\n"
        "   -> modellnummer=part BEFORE slash\n"
        "   -> artikelnummer=part AFTER slash\n"
        "   Example: PD96713696/54415 -> modellnummer='PD96713696', artikelnummer='54415'\n"
        "4c) Spaced-prefix fused code pattern: if a short alpha prefix is split by a space from a fused model/article token,\n"
        "   join the prefix back into the model and peel the valid artikelnummer from the end.\n"
        "   Example: 'CQ 9696XA56062' -> modellnummer='CQ9696XA', artikelnummer='56062'\n"
        "5) If an item block contains 'bestehend aus je:', interpret it as a component-only block.\n"
        "   Parent row semantics from above the phrase must not be reintroduced.\n"
        "   Keep repeated component occurrences unchanged when they are present in the snapshot.\n"
        "   Repeated identical component rows across pages are valid and must stay repeated.\n"
        "   Do not semantically collapse rows just because modellnummer/artikelnummer are identical.\n"
        "   NEGATIVE EXAMPLE: legal/footer text such as 'Amtsgericht ... HRB 9684' is never an item pair.\n"
        "   Verify/correct characters only (modellnummer/artikelnummer), not row count semantics.\n"
        "6) Preserve leading zeros and uppercase exactly.\n"
        "7) Preserve O vs 0 exactly as seen (do not normalize).\n"
        "8) Do not keep combined token in one field when it clearly splits.\n"
        "8b) If a model/article token starts with a quantity prefix (e.g., '1xPDSL71SP44-57383' or '2xCQ1212-09377G'), "
        "treat '<number>x' as quantity marker and strip it from modellnummer.\n"
        "9) Standalone article-only tokens remain valid Porta item rows when they appear as their own article lines.\n"
        "   - '66015' means artikelnummer='66015', modellnummer=''\n"
        "   - '30156+15237' means two separate article-only rows with empty modellnummer\n"
        "   - Do NOT infer missing model prefixes (for example, never invent OJ/0J when not explicitly shown).\n"
        "9b) Standalone model-only tokens remain valid Porta item rows when they appear as their own component lines.\n"
        "   - '1 Stk Kommode mit 4 Schubkasten OFSN0699' means modellnummer='OFSN0699', artikelnummer=''\n"
        "   - Keep that row consistently; do not drop it on one run and keep it on another.\n"
        "   - Do NOT invent a missing artikelnummer.\n"
        "10) If no other valid code patterns or tokens exist in the item block, "
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
        "- Ignore 'Client order' / order-reference numbers entirely (e.g., '74447604').\n"
        "  They are not artikelnummer/modellnummer.\n"
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
        "   If wrapped across lines, merge first (e.g., '.../180' + '82' -> artikel='18082').\n"
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
