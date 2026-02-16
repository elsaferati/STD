"""
AI fallback for customer/address matching when rule-based logic did not match 100%.
Uses curated shortlists from Primex and ILN Excel; does not modify existing lookup logic.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from lookup import (
    _city_tokens,
    _filter_by_verband,
    _normalize_address_token,
    _plz_digits_only,
    load_data,
    load_iln_data,
)

try:
    from rapidfuzz import fuzz as _fuzz
except ImportError:
    _fuzz = None

# Trigger keywords in warnings
_TRIGGER_WARNING_100 = "not 100% identical"
_TRIGGER_WARNING_ILN = "ILN fallback"
_CONFIDENCE_THRESHOLD = 0.7
_PRIMEX_SHORTLIST_LIMIT = 40
_ILN_SHORTLIST_LIMIT = 25

_PRIMEX_COLS = ("Kundennummer", "Name1", "Name2", "Name3", "Strasse", "Ort", "Postleitzahl", "Adressnummer", "Tour", "Verband")
_ILN_COLS_ORDER = ("ILN", "PLZ", "Ort", "Gesellschaft", "Filiale/Lager")
_ILN_STREET_KEYS = ("Straße", "Strasse")


def _header_val(header: dict, key: str) -> str:
    v = header.get(key)
    if isinstance(v, dict):
        return str(v.get("value", "") or "").strip()
    return str(v or "").strip()


def should_try_ai_customer_match(header: dict, warnings: list) -> bool:
    """True if Kundennummer is empty, or derived_from is iln_fallback, or a trigger warning exists."""
    if not isinstance(header, dict):
        return False
    kdn = header.get("kundennummer", {})
    if isinstance(kdn, dict):
        derived = (kdn.get("derived_from") or "").strip()
        val = str(kdn.get("value", "") or "").strip()
    else:
        derived = ""
        val = str(kdn or "").strip()

    if not val:
        return True
    if derived == "iln_fallback":
        return True
    if not isinstance(warnings, list):
        return False
    for w in warnings:
        s = str(w)
        if _TRIGGER_WARNING_100 in s or _TRIGGER_WARNING_ILN in s:
            return True
    return False


def _build_order_search_string(header: dict) -> str:
    """Build normalized order string for fuzzy matching (address, plz, ort, store name)."""
    store_addr = _header_val(header, "store_address") or _header_val(header, "lieferanschrift")
    strasse = _header_val(header, "strasse")
    plz = _header_val(header, "plz")
    ort = _header_val(header, "ort")
    store_name = _header_val(header, "store_name")
    addr_raw = store_addr or f"{strasse} {plz} {ort}"
    addr_clean = _normalize_address_token(addr_raw)
    plz_d = _plz_digits_only(plz) if plz else ""
    ort_tok = " ".join(sorted(_city_tokens(ort))) if ort else ""
    name_clean = _normalize_address_token(store_name) if store_name else ""
    parts = [addr_clean, plz_d, ort_tok, name_clean]
    return " ".join(p for p in parts if p)


def _build_primex_shortlist(header: dict, limit: int = _PRIMEX_SHORTLIST_LIMIT) -> list[dict]:
    """Return candidate rows from Primex (Verband + Adressnummer 0) via fuzzy matching. Read-only."""
    df = load_data()
    if df is None or df.empty:
        return []
    subset = df[
        df["Adressnummer"].astype(str).str.replace(".0", "", regex=False).str.strip() == "0"
    ]
    subset = _filter_by_verband(subset)
    if subset is None or subset.empty:
        return []

    order_str = _build_order_search_string(header)
    plz_d = _plz_digits_only(_header_val(header, "plz")) if _header_val(header, "plz") else ""

    if _fuzz is not None and order_str:
        # Fuzzy scoring: score all rows, sort descending, take top limit
        candidates = []
        for _, row in subset.iterrows():
            row_strasse = str(row.get("Strasse", ""))
            row_plz = _plz_digits_only(str(row.get("Postleitzahl", "")).replace(".0", "").strip())
            row_ort = str(row.get("Ort", ""))
            row_n1 = str(row.get("Name1", ""))
            row_n2 = str(row.get("Name2", ""))
            row_n3 = str(row.get("Name3", ""))
            row_str = " ".join([
                _normalize_address_token(row_strasse),
                row_plz,
                " ".join(sorted(_city_tokens(row_ort))),
                _normalize_address_token(row_n1),
                _normalize_address_token(row_n2),
                _normalize_address_token(row_n3),
            ]).strip()
            score = _fuzz.token_set_ratio(order_str, row_str)
            if plz_d and row_plz == plz_d:
                score += 15
            candidates.append((score, row))
        candidates.sort(key=lambda x: x[0], reverse=True)
    else:
        # Fallback: strict scoring when rapidfuzz not available
        store_addr = _header_val(header, "store_address") or _header_val(header, "lieferanschrift")
        ort = _header_val(header, "ort")
        strasse = _header_val(header, "strasse")
        addr_clean = _normalize_address_token(store_addr or f"{strasse} {plz_d} {ort}")
        ort_tokens = _city_tokens(ort) if ort else set()
        candidates = []
        for _, row in subset.iterrows():
            row_ort = str(row.get("Ort", ""))
            row_plz = _plz_digits_only(str(row.get("Postleitzahl", "")))
            row_strasse = str(row.get("Strasse", ""))
            strasse_clean = _normalize_address_token(row_strasse)
            row_ort_tokens = _city_tokens(row_ort)
            score = 0
            if ort_tokens and row_ort_tokens and (ort_tokens & row_ort_tokens):
                score += 30
            if plz_d and row_plz == plz_d:
                score += 20
            if strasse_clean and strasse_clean in addr_clean:
                score += 40
            elif addr_clean and strasse_clean and addr_clean in strasse_clean:
                score += 10
            if score == 0 and (ort_tokens or plz_d):
                continue
            if score == 0:
                score = 5
            candidates.append((score, row))
        candidates.sort(key=lambda x: x[0], reverse=True)

    out = []
    for _, row in candidates[:limit]:
        out.append({c: str(row.get(c, "")).replace(".0", "").strip() for c in _PRIMEX_COLS})
    return out


def _build_iln_shortlist(header: dict, limit: int = _ILN_SHORTLIST_LIMIT) -> list[dict]:
    """Return candidate rows from ILN Excel via fuzzy matching (Filiale/Lager, Straße, PLZ, Ort, Gesellschaft). Read-only."""
    df = load_iln_data()
    if df is None or df.empty:
        return []

    order_str = _build_order_search_string(header)
    iln_anl = _header_val(header, "iln_anl")
    iln_fil = _header_val(header, "iln_fil")
    iln = _header_val(header, "iln")

    if _fuzz is not None and order_str:
        # Fuzzy scoring: score all ILN rows by Straße, PLZ, Ort, Gesellschaft, Filiale/Lager
        candidates = []
        for _, row in df.iterrows():
            row_strasse = str(row.get("Straße", row.get("Strasse", "")))
            row_plz = _plz_digits_only(str(row.get("PLZ", "")).replace(".0", "").strip())
            row_ort = str(row.get("Ort", ""))
            row_ges = str(row.get("Gesellschaft", ""))
            row_filiale = str(row.get("Filiale/Lager", ""))
            row_str = " ".join([
                _normalize_address_token(row_strasse),
                row_plz,
                " ".join(sorted(_city_tokens(row_ort))),
                _normalize_address_token(row_ges),
                _normalize_address_token(row_filiale),
            ]).strip()
            score = _fuzz.token_set_ratio(order_str, row_str)
            row_iln = str(row.get("ILN", "")).replace(".0", "").strip()
            if iln and row_iln and (iln in row_iln or row_iln in iln):
                score += 25
            if iln_anl and row_iln == iln_anl or (iln_fil and row_iln == iln_fil):
                score += 25
            candidates.append((score, row))
        candidates.sort(key=lambda x: x[0], reverse=True)
    else:
        # Fallback: strict scoring when rapidfuzz not available
        store_addr = _header_val(header, "store_address") or _header_val(header, "lieferanschrift")
        plz = _header_val(header, "plz")
        ort = _header_val(header, "ort")
        addr_clean = _normalize_address_token(store_addr or f"{_header_val(header, 'strasse')} {plz} {ort}")
        plz_d = _plz_digits_only(plz) if plz else ""
        ort_tokens = _city_tokens(ort) if ort else set()
        candidates = []
        for _, row in df.iterrows():
            row_iln = str(row.get("ILN", "")).replace(".0", "").strip()
            row_ort = str(row.get("Ort", ""))
            row_plz = _plz_digits_only(str(row.get("PLZ", "")))
            strasse_db = str(row.get("Straße", row.get("Strasse", "")))
            strasse_clean_db = _normalize_address_token(strasse_db)
            row_ort_tokens = _city_tokens(row_ort)
            score = 0
            if iln and row_iln and (iln in row_iln or row_iln in iln):
                score += 50
            if iln_anl and row_iln == iln_anl or (iln_fil and row_iln == iln_fil):
                score += 50
            if ort_tokens and row_ort_tokens and (ort_tokens & row_ort_tokens):
                score += 25
            if plz_d and row_plz == plz_d:
                score += 15
            if strasse_clean_db and strasse_clean_db in addr_clean:
                score += 30
            if score == 0 and (ort_tokens or plz_d or addr_clean):
                continue
            if score == 0:
                score = 5
            candidates.append((score, row))
        candidates.sort(key=lambda x: x[0], reverse=True)

    out = []
    for _, row in candidates[:limit]:
        d = {}
        for c in _ILN_COLS_ORDER:
            d[c] = str(row.get(c, "")).replace(".0", "").strip()
        street = ""
        for k in _ILN_STREET_KEYS:
            val = row.get(k, "")
            if val not in (None, "") and str(val).strip():
                street = str(val).replace(".0", "").strip()
                break
        d["Straße"] = street
        out.append(d)
    return out


def _build_order_context(header: dict) -> str:
    """One short text summarizing order for the AI."""
    parts = [
        f"Store name: {_header_val(header, 'store_name')}",
        f"Strasse: {_header_val(header, 'strasse')}",
        f"PLZ: {_header_val(header, 'plz')}",
        f"Ort: {_header_val(header, 'ort')}",
        f"ILN-Anl: {_header_val(header, 'iln_anl')}",
        f"ILN-Fil: {_header_val(header, 'iln_fil')}",
        f"ILN: {_header_val(header, 'iln')}",
        f"Current Kundennummer: {_header_val(header, 'kundennummer')}",
        f"Current Tour: {_header_val(header, 'tour')}",
        f"Current Adressnummer: {_header_val(header, 'adressnummer')}",
    ]
    return "\n".join(parts)


_SYSTEM_PROMPT_AI_MATCH = """You are an expert at matching orders to customer and address data from two reference tables (Primex customers and ILN list).

Candidates are pre-ranked by fuzzy matching: address, names, and company fields may have slight spelling or formatting differences but can still refer to the same location. Use all provided columns together to decide.

You will receive:
1. Order context: store name, address (Strasse, PLZ, Ort), ILN fields, and current Kundennummer/Tour/Adressnummer if any.
2. A shortlist of candidate rows from Primex with columns: Kundennummer, Name1, Name2, Name3, Strasse, Ort, Postleitzahl, Adressnummer, Tour, Verband.
3. A shortlist of candidate rows from the ILN list with columns: ILN, Straße, PLZ, Ort, Gesellschaft, Filiale/Lager.

Your task: Using ALL columns from both tables together (address, city, postal code, company names, branch/Filiale, Verband, etc.), choose the single best-matching Kundennummer for this order, and the corresponding Adressnummer, Tour, and optionally ILN. If the order already has a Kundennummer from rules, you may confirm it or suggest a better match.

Output ONLY valid JSON with no other text. Use exactly these keys:
- "kundennummer": string (or null if no good match)
- "adressnummer": string (or null)
- "tour": string (or null)
- "iln": string (or null, optional)
- "confidence": number between 0 and 1 (0 = no match, 1 = certain match)

If no good match exists, set "confidence" to 0 and use null for kundennummer."""


def _format_table_primex(rows: list[dict]) -> str:
    if not rows:
        return "(no rows)"
    lines = [" | ".join(_PRIMEX_COLS)]
    for r in rows:
        line = " | ".join(str(r.get(c, "")) for c in _PRIMEX_COLS)
        lines.append(line)
    return "\n".join(lines)


def _format_table_iln(rows: list[dict]) -> str:
    if not rows:
        return "(no rows)"
    cols = ("ILN", "Straße", "PLZ", "Ort", "Gesellschaft", "Filiale/Lager")
    lines = [" | ".join(cols)]
    for r in rows:
        line = " | ".join(str(r.get(c, "")) for c in cols)
        lines.append(line)
    return "\n".join(lines)


def _call_ai_match(
    order_context: str,
    primex_rows: list[dict],
    iln_rows: list[dict],
    extractor: Any,
) -> str:
    """Build prompt, call extractor.complete_text, return raw response text."""
    user_text = (
        "Order context:\n"
        + order_context
        + "\n\n---\nPrimex candidates:\n"
        + _format_table_primex(primex_rows)
        + "\n\n---\nILN candidates:\n"
        + _format_table_iln(iln_rows)
        + "\n\nRespond with JSON only (kundennummer, adressnummer, tour, iln, confidence)."
    )
    return extractor.complete_text(_SYSTEM_PROMPT_AI_MATCH, user_text)


def _parse_ai_match_response(text: str) -> Optional[dict]:
    """Parse JSON from AI response; return dict with kundennummer, adressnummer, tour, iln, confidence or None."""
    if not text or not text.strip():
        return None
    try:
        data = json.loads(text.strip())
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                data = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None
        else:
            return None
    if not isinstance(data, dict):
        return None
    confidence = data.get("confidence")
    if confidence is not None:
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.0
    else:
        confidence = 0.0
    kdn = data.get("kundennummer")
    if kdn is not None:
        kdn = str(kdn).strip()
    return {
        "kundennummer": kdn or "",
        "adressnummer": str(data.get("adressnummer") or "").strip(),
        "tour": str(data.get("tour") or "").strip(),
        "iln": str(data.get("iln") or "").strip(),
        "confidence": confidence,
    }


def try_ai_customer_match(
    header: dict,
    warnings: list,
    extractor: Any,
    config: Any,
) -> None:
    """
    If trigger applies: build shortlists, call AI, parse response. If confidence >= threshold,
    overwrite header kundennummer/adressnummer/tour (and optionally iln) and append warning.
    Mutates header and warnings in place.
    """
    if not should_try_ai_customer_match(header, warnings):
        return
    order_context = _build_order_context(header)
    primex_rows = _build_primex_shortlist(header, limit=_PRIMEX_SHORTLIST_LIMIT)
    iln_rows = _build_iln_shortlist(header, limit=_ILN_SHORTLIST_LIMIT)
    try:
        response_text = _call_ai_match(order_context, primex_rows, iln_rows, extractor)
    except Exception:
        return
    result = _parse_ai_match_response(response_text)
    if not result or result.get("confidence", 0) < _CONFIDENCE_THRESHOLD:
        return
    kdn = result.get("kundennummer")
    if not kdn:
        return
    header["kundennummer"] = {
        "value": kdn,
        "source": "derived",
        "confidence": result.get("confidence", 0.8),
        "derived_from": "ai_assisted_match",
    }
    header["adressnummer"] = {
        "value": result.get("adressnummer", ""),
        "source": "derived",
        "confidence": result.get("confidence", 0.8),
        "derived_from": "ai_assisted_match",
    }
    header["tour"] = {
        "value": result.get("tour", ""),
        "source": "derived",
        "confidence": result.get("confidence", 0.8),
        "derived_from": "ai_assisted_match",
    }
    if result.get("iln"):
        header["iln"] = {
            "value": result["iln"],
            "source": "derived",
            "confidence": result.get("confidence", 0.8),
            "derived_from": "ai_assisted_match",
        }
    warnings.append(
        "Kundennummer/match chosen by AI (rules did not match 100%); please verify."
    )
