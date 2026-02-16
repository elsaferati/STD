"""
Prompts for detailed XXLUTZ furnplan article extraction (second GPT call).
Extracts manufacturer info, full article IDs, descriptions, dimensions, 
hierarchical positions, and configuration remarks from PDF attachments.
"""

DETAIL_SYSTEM_PROMPT = (
    "You are an expert at extracting detailed furniture article data from XXLUTZ furnplan PDF documents. "
    "You extract structured data about articles including full article IDs, descriptions, dimensions, "
    "and configuration details. Output ONLY valid JSON."
)


# Manufacturer ILN lookup table (Staud is the primary manufacturer for XXLUTZ orders)
MANUFACTURER_ILN_MAP = {
    "staud": "4039262000004",
    "rauch": "4003769000008",
    "nolte": "4022956000006",
    "wimex": "4011808000003",
    "express": "4013227000009",
}


def build_detail_user_instructions() -> str:
    """Build user instructions for XXLUTZ furnplan detail extraction."""
    return (
        "=== TASK ===\n"
        "Extract DETAILED article information from the XXLUTZ furnplan PDF images.\n"
        "These are typically furniture order specifications for wardrobes, beds, and accessories.\n"
        "\n"
        "=== WHAT TO EXTRACT ===\n"
        "\n"
        "PROGRAM INFO (from PDF header, applies to all items):\n"
        "- manufacturer_name: Usually 'Staud' for XXLUTZ orders (visible in header)\n"
        "- program_name: Product line name (e.g., 'System One', 'Sinfonie Plus', 'Includo')\n"
        "- furncloud_id: Code in brackets like '[yif3 aqz7]' (often at page bottom or in header)\n"
        "  May appear sideways/rotated - look carefully in corners!\n"
        "\n"
        "PER ARTICLE (from table rows):\n"
        "- pos_nr: Position number from 'Pos.' or '(FPos:)' column (e.g., '1', '1.1', '1.2', '2')\n"
        "  Note: Dot notation indicates hierarchy (1.1 is sub-item of 1)\n"
        "- article_id: FULL article code (e.g., 'CQ9606XA-60951')\n"
        "  DO NOT split this - keep the COMPLETE code including prefix and suffix!\n"
        "  \n"
        "  CRITICAL - ZERO vs LETTER O:\n"
        "  Article codes use the NUMBER ZERO (0), NOT the letter O!\n"
        "  - ZB00-38337 = ZB + zero + zero + hyphen + 38337 (CORRECT)\n"
        "  - OJ00-13200 = OJ + zero + zero + hyphen + 13200 (CORRECT)\n"
        "  - ZBO0-38337 = WRONG (letter O instead of zero)\n"
        "  Common patterns: ZB00, ZB99, OJ00, OJ99, SI1818XA - these use number zeros.\n"
        "\n"
        "- description: Full article description (e.g., 'Drehtüren-Grundelement Dekor, Ausf. 1')\n"
        "- dimensions: Extract H/B/T values (Height/Width/Depth in cm)\n"
        "  - height: first dimension value (e.g., 221.1)\n"
        "  - width: second dimension value (e.g., 42.8)\n"
        "  - depth: third dimension value (e.g., 63)\n"
        "  Format often: '221.1x42.8x63' or '221.1 / 42.8 / 63'\n"
        "  If dimensions show as '0' or not available, use 0.0\n"
        "- quantity: Usually 1 for XXLUTZ orders (from 'X x' prefix or 'Menge' column)\n"
        "- remarks: Configuration details, extract as list. Look for lines like:\n"
        "  - 'Innendekor: Texline'\n"
        "  - 'Frontgruppe Drehtüren: 01-29'\n"
        "  - 'Frontausführung Drehtüren: Dekor'\n"
        "  - 'Frontfarbe Drehtüren: Dekor Weiß'\n"
        "  - 'Griff Variante Drehtüren: Griffleiste'\n"
        "  - 'Griff/Zierleisten Drehtüren: schmal alufarbig'\n"
        "  - 'Korpus Drehtüren: Dekor Sonoma Eiche'\n"
        "  - Any other configuration/variant text\n"
        "\n"
        "=== POSITION HIERARCHY ===\n"
        "Items with dot notation are SUB-ITEMS belonging to parent position:\n"
        "- pos_nr='1' → parent_pos_nr=null (main item, no parent)\n"
        "- pos_nr='1.1' → parent_pos_nr='1' (sub-item/accessory of item 1)\n"
        "- pos_nr='1.2' → parent_pos_nr='1' (another sub-item of item 1)\n"
        "- pos_nr='2' → parent_pos_nr=null (main item, no parent)\n"
        "- pos_nr='2.1' → parent_pos_nr='2' (sub-item of item 2)\n"
        "\n"
        "In XXLUTZ orders, sub-items are often accessories like:\n"
        "- Hosenhalter (trouser rack)\n"
        "- Fachboden (shelf)\n"
        "- Schubkasteneinsatz (drawer insert)\n"
        "- Tür-Öffnungs- und Schließdämpfer (door dampers)\n"
        "\n"
        "=== MANUFACTURER ILN LOOKUP ===\n"
        "Use these ILN codes based on manufacturer name:\n"
        "- Staud → 4039262000004 (primary for XXLUTZ)\n"
        "- Rauch → 4003769000008\n"
        "- Nolte → 4022956000006\n"
        "- Wimex → 4011808000003\n"
        "- Express → 4013227000009\n"
        "If manufacturer not found, default to Staud ILN for XXLUTZ orders.\n"
        "\n"
        "=== PROGRAM ID DERIVATION ===\n"
        "Derive prog_id from program name:\n"
        "\n"
        "FOR TWO-WORD NAMES: First 3 letters of first word + First letter of second word\n"
        "- 'System One' → 'SYS' + 'O' = 'SYSO'\n"
        "- 'Sinfonie Plus' → 'SIN' + 'P' = 'SINP'\n"
        "\n"
        "FOR SINGLE-WORD NAMES: First 4 letters\n"
        "- 'Includo' → 'INCL'\n"
        "- 'Sigma' → 'SIGM'\n"
        "\n"
        "Always uppercase.\n"
        "\n"
        "=== IMPORTANT RULES ===\n"
        "1. Extract ALL articles from ALL pages - don't stop after first page!\n"
        "2. Keep article_id COMPLETE - don't split on hyphen for this output\n"
        "3. If a field is not visible, use null for strings, 0.0 for numbers, [] for arrays\n"
        "4. Remarks should be individual lines, not joined together\n"
        "5. If furncloud_id appears ANYWHERE (rotated, in corner), capture it\n"
        "6. Items marked 'mit:' indicate the following items are accessories (sub-items)\n"
        "\n"
        "=== OUTPUT STRUCTURE ===\n"
        "Return ONLY valid JSON with this exact structure:\n"
        "\n"
        "{\n"
        '  "program": {\n'
        '    "manufacturer_name": "Staud",\n'
        '    "manufacturer_iln": "4039262000004",\n'
        '    "prog_id": "SYSO",\n'
        '    "program_name": "System One",\n'
        '    "furncloud_id": "yif3 aqz7"\n'
        '  },\n'
        '  "articles": [\n'
        '    {\n'
        '      "pos_nr": "1",\n'
        '      "parent_pos_nr": null,\n'
        '      "article_id": "CQ9606XA-60951",\n'
        '      "description": "Drehtüren-Grundelement Dekor, Ausf. 1 1-türig, Türanschlag links",\n'
        '      "height": 221.1,\n'
        '      "width": 42.8,\n'
        '      "depth": 63.0,\n'
        '      "quantity": 1,\n'
        '      "remarks": [\n'
        '        "Innendekor: Texline",\n'
        '        "Frontgruppe Drehtüren: 01-29",\n'
        '        "Frontausführung Drehtüren: Dekor",\n'
        '        "Frontfarbe Drehtüren: Dekor Weiß",\n'
        '        "Griff Variante Drehtüren: Griffleiste",\n'
        '        "Griff/Zierleisten Drehtüren: schmal alufarbig",\n'
        '        "Korpus Drehtüren: Dekor Sonoma Eiche"\n'
        '      ]\n'
        '    },\n'
        '    {\n'
        '      "pos_nr": "1.1",\n'
        '      "parent_pos_nr": "1",\n'
        '      "article_id": "OJ00-13200",\n'
        '      "description": "Hosenhalter",\n'
        '      "height": 16.0,\n'
        '      "width": 47.0,\n'
        '      "depth": 47.5,\n'
        '      "quantity": 1,\n'
        '      "remarks": []\n'
        '    }\n'
        '  ]\n'
        '}\n'
        "\n"
        "REMEMBER: Output ONLY the JSON, no explanations or markdown formatting.\n"
    )
