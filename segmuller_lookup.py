"""
Segmuller Kundennummer lookup based on Kommissions-Nr (kom_nr) prefix.

Loads 'Kundennummern SEGMULLER.xlsx' once and maps the leading digits of a
Segmuller kom_nr to the correct Kundennummer.

Excel column layout:
  Col A  Beginn Kom.-Nr.  — pattern like '-55-', '-55- MR', '-55- JO'
  Col B  Kundennummer     — integer customer number
  Col C  Ort              — city name
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

import openpyxl

_EXCEL_PATH = Path(__file__).parent / "Kundennummern SEGMULLER.xlsx"


@lru_cache(maxsize=1)
def _load_mapping() -> list[tuple[str, str, str, str]]:
    """Return list of (prefix_digits, suffix, kundennummer_str, ort).

    prefix_digits — e.g. '55', '94', '85'
    suffix        — e.g. '', 'MR', 'JO'
    """
    wb = openpyxl.load_workbook(_EXCEL_PATH, data_only=True)
    ws = wb.active
    rows: list[tuple[str, str, str, str]] = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if len(row) < 2:
            continue
        pattern_cell = row[0]
        kundennummer_cell = row[1]
        ort_cell = row[2] if len(row) > 2 else None
        if pattern_cell is None or kundennummer_cell is None:
            continue
        pattern_str = str(pattern_cell).strip()
        m = re.match(r"^-(\d+)-\s*(.*)$", pattern_str)
        if not m:
            continue
        prefix = m.group(1).strip()
        suffix = m.group(2).strip().upper()
        try:
            kdnr = str(int(float(str(kundennummer_cell))))
        except (ValueError, TypeError):
            kdnr = str(kundennummer_cell).strip()
        ort = str(ort_cell).strip() if ort_cell is not None else ""
        rows.append((prefix, suffix, kdnr, ort))
    return rows


def get_kundennummer_by_kom_nr(kom_nr: str) -> Optional[tuple[str, str]]:
    """Return (kundennummer, ort) for the given Segmuller kom_nr, or None.

    Matches the leading digits of kom_nr against the Excel prefix patterns.
    Prefers MR/JO variant rows when the kom_nr text contains those markers;
    falls back to the base (no-suffix) row.
    """
    if not kom_nr:
        return None
    kom_stripped = str(kom_nr).strip()
    digits = re.sub(r"\D", "", kom_stripped)
    if not digits:
        return None

    kom_upper = kom_stripped.upper()
    has_mr = "MR" in kom_upper
    has_jo = "JO" in kom_upper

    mapping = _load_mapping()
    base_match: Optional[tuple[str, str]] = None

    for prefix, suffix, kundennummer, ort in mapping:
        if not digits.startswith(prefix):
            continue
        if suffix == "MR" and has_mr:
            return (kundennummer, ort)
        if suffix == "JO" and has_jo:
            return (kundennummer, ort)
        if suffix == "" and base_match is None:
            base_match = (kundennummer, ort)

    return base_match
