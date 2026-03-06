from __future__ import annotations

import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from config import Config
from lookup import load_data
from xml_exporter import (
    _delivery_week_to_xml_format,
    _sanitize_for_filename,
    generate_article_info_xml,
    generate_order_info_xml,
)


def _parse_artikel(value: str) -> tuple[str, str]:
    """Split 'SI00 44001' on first space -> ('SI00', '44001')."""
    s = str(value or "").strip()
    if " " in s:
        idx = s.index(" ")
        return s[:idx], s[idx + 1:].strip()
    return s, ""


def _delivery_week_with_year(value: str) -> str:
    """If 'Woche 12' (no year present), append current year -> 'Woche 12/2026'."""
    if not value or not str(value).strip():
        return ""
    s = str(value).strip()
    # Already has a 4-digit year — pass through to existing converter
    if re.search(r"\d{4}", s):
        return s
    # "Woche 12" or "KW 12" without year
    m = re.match(r"(Woche|KW)\s*(\d{1,2})$", s, re.IGNORECASE)
    if m:
        year = datetime.now().year
        prefix = m.group(1)
        return f"{prefix} {m.group(2)}/{year}"
    return s


def _lookup_primex_row(kundennummer: str, adressnummer: str, df: pd.DataFrame) -> dict:
    """Filter Primex df by kundennummer + adressnummer; return dict with Name1/Strasse/Postleitzahl/Ort."""
    if df is None or df.empty:
        return {}

    kd_clean = str(kundennummer).strip().replace(".0", "")
    adr_clean = str(adressnummer).strip().replace(".0", "")

    if "Kundennummer" not in df.columns:
        return {}

    mask = (
        df["Kundennummer"]
        .astype(str)
        .str.replace(".0", "", regex=False)
        .str.strip()
        == kd_clean
    )
    subset = df[mask]

    if subset.empty:
        return {}

    # Filter by adressnummer when present
    if "Adressnummer" in subset.columns and adr_clean:
        adr_mask = (
            subset["Adressnummer"]
            .astype(str)
            .str.replace(".0", "", regex=False)
            .str.strip()
            == adr_clean
        )
        adr_subset = subset[adr_mask]
        if not adr_subset.empty:
            subset = adr_subset

    row = subset.iloc[0]
    plz = str(row.get("Postleitzahl", "") or "").replace(".0", "").strip()
    return {
        "Name1": str(row.get("Name1", "") or "").strip(),
        "Strasse": str(row.get("Strasse", "") or "").strip(),
        "Postleitzahl": plz,
        "Ort": str(row.get("Ort", "") or "").strip(),
    }


def build_order_data(row: dict, primex_row: dict) -> dict:
    """Build data dict matching what xml_exporter functions expect."""
    store_name = primex_row.get("Name1", "")
    strasse = primex_row.get("Strasse", "")
    plz = primex_row.get("Postleitzahl", "")
    ort = primex_row.get("Ort", "")
    address_parts = [p for p in [strasse, plz, ort] if p]
    store_address = " ".join(address_parts)

    delivery_raw = _delivery_week_with_year(str(row.get("liefertermin", "") or ""))

    header = {
        "ticket_number": str(row.get("ticketnummer", "") or ""),
        "kundennummer": str(row.get("epkdnr", "") or ""),
        "kom_nr": str(row.get("kom_nr", "") or ""),
        "kom_name": str(row.get("kom_name", "") or ""),
        "delivery_week": delivery_raw,
        "store_name": store_name,
        "store_address": store_address,
        "seller": "",
        "lieferanschrift": store_address,
    }

    items: list[dict[str, Any]] = []
    for menge_key, artikel_key in [("menge1", "artikel1"), ("menge2", "artikel2")]:
        artikel_val = str(row.get(artikel_key, "") or "").strip()
        if not artikel_val:
            continue
        model, article = _parse_artikel(artikel_val)
        menge_val = row.get(menge_key, "")
        try:
            qty = float(menge_val)
        except (ValueError, TypeError):
            qty = 1.0
        items.append({
            "modellnummer": model,
            "artikelnummer": article,
            "menge": qty,
            "furncloud_id": "",
        })

    return {"header": header, "items": items}


def generate_xmls_from_excel(excel_file_stream, output_dir: Path) -> list[Path]:
    """Read Excel, generate OrderInfo + OrderArticleInfo XML for each row, return all paths."""
    output_dir.mkdir(parents=True, exist_ok=True)

    xls = pd.ExcelFile(excel_file_stream)
    sheet_name = "Tabelle2" if "Tabelle2" in xls.sheet_names else xls.sheet_names[0]
    df_input = pd.read_excel(xls, sheet_name=sheet_name, header=0).fillna("")

    df_primex = load_data()
    cfg = Config.from_env()
    generated_paths: list[Path] = []

    for _, excel_row in df_input.iterrows():
        def get_col(idx: int) -> str:
            if idx < len(excel_row):
                return str(excel_row.iloc[idx]).strip()
            return ""

        epkdnr = get_col(0)
        menge1 = get_col(1)
        artikel1 = get_col(2)
        menge2 = get_col(3)
        artikel2 = get_col(4)
        adressnummer = get_col(5)
        liefertermin = get_col(6)
        ticketnummer = get_col(7)
        kom_name = get_col(8)
        kom_nr = get_col(9)

        # Skip completely empty rows
        if not ticketnummer and not epkdnr and not artikel1:
            continue

        row_data = {
            "epkdnr": epkdnr,
            "menge1": menge1,
            "artikel1": artikel1,
            "menge2": menge2,
            "artikel2": artikel2,
            "adressnummer": adressnummer,
            "liefertermin": liefertermin,
            "ticketnummer": ticketnummer,
            "kom_name": kom_name,
            "kom_nr": kom_nr,
        }

        primex_row: dict = {}
        if df_primex is not None and epkdnr:
            primex_row = _lookup_primex_row(epkdnr, adressnummer, df_primex)

        data = build_order_data(row_data, primex_row)
        base_name = (
            _sanitize_for_filename(ticketnummer)
            or _sanitize_for_filename(epkdnr)
            or "unknown"
        )

        p1 = generate_order_info_xml(data, base_name, cfg, output_dir)
        p2 = generate_article_info_xml(data, base_name, output_dir)
        generated_paths.extend([p1, p2])

    return generated_paths
