"""
Zubehör (accessories) catalog lookup.

Loads 24374_ZB_Beispiel_2025-12-17.csv once and provides a fast O(1)
artikelnummer → modellnummer lookup used by all client pipelines.

CSV format: semicolon-delimited, row 1 = header
  Col A  Modellname  — "Zubehör"
  Col B  C6MDNP      — modellnummer  (e.g. "ZB00")
  Col C  C6ARTP      — artikelnummer (e.g. "00666", "77296")
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

_CSV_PATH = Path(__file__).parent / "24374_ZB_Beispiel_2025-12-17.csv"

# artikelnummer (both raw and int-stripped) → modellnummer
_ZB_LOOKUP: dict[str, str] | None = None


def _load() -> dict[str, str]:
    global _ZB_LOOKUP
    if _ZB_LOOKUP is not None:
        return _ZB_LOOKUP

    result: dict[str, str] = {}
    with open(_CSV_PATH, newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh, delimiter=";")
        next(reader, None)  # skip header row
        for row in reader:
            if len(row) < 3:
                continue
            modellnummer = row[1].strip()
            artikelnummer_raw = row[2].strip()
            if not artikelnummer_raw or not modellnummer:
                continue
            # Store raw key (e.g. "00666")
            result[artikelnummer_raw] = modellnummer
            # Store int-stripped key (e.g. "666") — handles leading-zero ambiguity
            try:
                stripped = str(int(artikelnummer_raw))
                if stripped != artikelnummer_raw:
                    result[stripped] = modellnummer
            except ValueError:
                pass

    _ZB_LOOKUP = result
    return _ZB_LOOKUP


def find_modellnummer_by_artikelnummer(artikelnummer: str) -> str | None:
    """Return modellnummer for artikelnummer, or None if not found."""
    lookup = _load()
    key = artikelnummer.strip()
    if key in lookup:
        return lookup[key]
    # Try int-stripped (removes leading zeros)
    try:
        stripped = str(int(key))
        return lookup.get(stripped)
    except ValueError:
        return None


def apply_zb_modellnummer_lookup(data: dict[str, Any], warnings: list[str]) -> bool:
    """
    For each item where modellnummer is empty, look up artikelnummer in the ZB catalog.

    Fills modellnummer with source="derived", derived_from="zb_catalog_lookup".
    Appends a warning per item filled.
    Returns True if any item was changed.
    """
    items = data.get("items")
    if not isinstance(items, list):
        return False

    changed = False
    for item in items:
        if not isinstance(item, dict):
            continue

        # Check if modellnummer is already filled
        modell_entry = item.get("modellnummer")
        if isinstance(modell_entry, dict):
            existing = str(modell_entry.get("value", "") or "").strip()
        else:
            existing = str(modell_entry or "").strip()
        if existing:
            continue  # already has a value — skip

        # Get artikelnummer
        artnr_entry = item.get("artikelnummer")
        if isinstance(artnr_entry, dict):
            artnr = str(artnr_entry.get("value", "") or "").strip()
        else:
            artnr = str(artnr_entry or "").strip()
        if not artnr:
            continue

        found = find_modellnummer_by_artikelnummer(artnr)
        if found is None:
            continue

        # Fill modellnummer
        item["modellnummer"] = {
            "value": found,
            "source": "derived",
            "confidence": 1.0,
            "derived_from": "zb_catalog_lookup",
        }

        line_no = item.get("line_no", "?")
        warnings.append(
            f"modellnummer for artikelnummer '{artnr}' (line {line_no}) "
            f"filled from Zubehör catalog: '{found}'"
        )
        changed = True

    return changed
