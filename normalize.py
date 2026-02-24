from __future__ import annotations

from typing import Any, Optional
import re

from dateutil.parser import parse, ParserError
import datetime

import lookup


HEADER_FIELDS = [
    "ticket_number",
    "kundennummer",
    "adressnummer",
    "kom_nr",
    "kom_name",
    "liefertermin",
    "wunschtermin",
    "bestelldatum",
    "lieferanschrift",
    "tour",
    "store_name",
    "store_address",
    "seller",
    "delivery_week",
    "iln",
    "iln_anl",
    "iln_fil",
    "human_review_needed",
    "reply_needed",
    "post_case",
]
ITEM_FIELDS = ["artikelnummer", "modellnummer", "menge", "furncloud_id"]
ALLOWED_SOURCES = {"pdf", "email", "image", "derived"}

# Mapping of English/alternative field names to standard German field names
# This acts as a fallback when the LLM returns non-standard field names
HEADER_FIELD_ALIASES = {
    # ticket_number aliases
    "ticketnumber": "ticket_number",
    "ticket_no": "ticket_number",
    "ticket_id": "ticket_number",
    "order_id": "ticket_number",
    # kundennummer aliases
    "customer_number": "kundennummer",
    "customernumber": "kundennummer",
    "customer_no": "kundennummer",
    "customerno": "kundennummer",
    "supplier_number": "kundennummer",
    "suppliernumber": "kundennummer",
    "lieferantennummer": "kundennummer",
    "kd_nr": "kundennummer",
    "kdnr": "kundennummer",
    # adressnummer aliases
    "address_number": "adressnummer",
    "addressnumber": "adressnummer",
    "address_no": "adressnummer",
    "gln": "iln",
    "delivery_address_number": "adressnummer",
    # iln_anl aliases (delivery location ILN)
    "delivery_iln": "iln_anl",
    "delivery_location_iln": "iln_anl",
    # iln_fil aliases (store/branch ILN)
    "store_iln": "iln_fil",
    "branch_iln": "iln_fil",
    "filiale_iln": "iln_fil",
    # kom_nr aliases
    "project_number": "kom_nr",
    "projectnumber": "kom_nr",
    "project_no": "kom_nr",
    "projectno": "kom_nr",
    "commission_number": "kom_nr",
    "commissionnumber": "kom_nr",
    "commission_no": "kom_nr",
    "kommission": "kom_nr",
    "kommissions_nr": "kom_nr",
    "order_number": "kom_nr",
    # kom_name aliases (short commission/person name only; not full company name)
    "project_name": "kom_name",
    "projectname": "kom_name",
    "commission_name": "kom_name",
    "commissionname": "kom_name",
    "kommissionsname": "kom_name",
    # store_name aliases (full company/branch name; customer_name goes here, not kom_name)
    "customer_name": "store_name",
    # liefertermin aliases
    "delivery_date": "liefertermin",
    "deliverydate": "liefertermin",
    "delivery_term": "liefertermin",
    "lieferdatum": "liefertermin",
    "lieferwoche": "liefertermin",
    # wunschtermin aliases
    "requested_date": "wunschtermin",
    "requesteddate": "wunschtermin",
    "desired_date": "wunschtermin",
    "wunschdatum": "wunschtermin",
    # lieferanschrift aliases
    "delivery_address": "lieferanschrift",
    "deliveryaddress": "lieferanschrift",
    "shipping_address": "lieferanschrift",
    "empfänger": "lieferanschrift",
    "warenempfänger": "lieferanschrift",
    "bestellanschrift": "lieferanschrift",
    # bestelldatum aliases
    "order_date": "bestelldatum",
    "orderdate": "bestelldatum",
    "datum": "bestelldatum",
    "belegdatum": "bestelldatum",
    "document_date": "bestelldatum",
    # tour aliases
    "route": "tour",
    # human_review_needed aliases
    "human_review": "human_review_needed",
    "review_needed": "human_review_needed",
}

ITEM_FIELD_ALIASES = {
    # artikelnummer aliases
    "item_number": "artikelnummer",
    "itemnumber": "artikelnummer",
    "item_no": "artikelnummer",
    "itemno": "artikelnummer",
    "article_number": "artikelnummer",
    "articlenumber": "artikelnummer",
    "article_no": "artikelnummer",
    "art_nr": "artikelnummer",
    "artnr": "artikelnummer",
    "artikel_nr": "artikelnummer",
    "sku": "artikelnummer",
    "product_number": "artikelnummer",
    # modellnummer aliases
    "model_number": "modellnummer",
    "modelnumber": "modellnummer",
    "model_no": "modellnummer",
    "modelno": "modellnummer",
    "model": "modellnummer",
    "modell": "modellnummer",
    "type": "modellnummer",
    "typ": "modellnummer",
    # menge aliases
    "quantity": "menge",
    "qty": "menge",
    "amount": "menge",
    "count": "menge",
    "anzahl": "menge",
    "stueck": "menge",
    "stk": "menge",
    # furncloud_id aliases
    "furncloud": "furncloud_id",
    "furncloudid": "furncloud_id",
    "fc_id": "furncloud_id",
    "fcid": "furncloud_id",
}

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_REPLY_CASE_RE = re.compile(r"\bstatt\b.{0,200}?\bbitte\b.{0,200}", re.IGNORECASE | re.DOTALL)
_REPLY_FOOTER_RE = re.compile(
    r"(\*\*\*\s*ende\s*mail\s*\*\*\*|-{3,}|_{3,}|\*{4,}|mit\s+freundlichen\s+gr[uü]ßen|best\s+regards|kind\s+regards)",
    re.IGNORECASE,
)
_REPLY_HEADER_STOP_RE = re.compile(
    r"\b(KDNR|Komm|Liefertermin|Wunschtermin|ILN|Bestelldatum)\b",
    re.IGNORECASE,
)
TICKET_MISSING_WARNING = "ticket number is missing"
# Header fields that should automatically trigger reply_needed when missing.
# Extend this list (e.g. "liefertermin", "kundennummer") to add more triggers.
CRITICAL_REPLY_FIELDS = ["kom_nr", "kundennummer"]
CRITICAL_ITEM_REPLY_FIELDS = ["artikelnummer", "modellnummer"]
MISSING_CRITICAL_REPLY_PREFIX = "Missing critical header fields:"
MISSING_CRITICAL_ITEM_REPLY_PREFIX = "Missing critical item fields:"
_ADDRESS_PLZ_RE = re.compile(r"\b\d{5}\b")
_ADDRESS_GLUE_PLZ_RE = re.compile(r"(\d{1,4}[A-Za-z]?)(\d{5})\b")
_ILN_TOKEN_RE = re.compile(r"\b\d{13}\b")
_ILN_GLN_LABEL_RE = re.compile(r"\b(?:iln|gln)\b", re.IGNORECASE)
_LIEFER_STREET_PATTERN = (
    r"(?:\b(?:[A-Za-z0-9][A-Za-z0-9.\-]*\s+){0,4}"
    r"(?:Str\.?|Strasse|Straße|Weg|Platz|Allee|Chaussee|Ring|Gasse|Damm|Ufer|Pfad|Steig|Kai|Markt|Berg|Stieg)\s+"
    r"\d{1,4}[A-Za-z]?(?:\s*[-/]\s*\d{1,4}[A-Za-z]?)?\b)"
    r"|"
    r"(?:\b[A-Za-z0-9][A-Za-z0-9.\-]*"
    r"(?:str\.?|strasse|straße|weg|platz|allee|chaussee|ring|gasse|damm|ufer|pfad|steig|kai|markt|berg|stieg)\s+"
    r"\d{1,4}[A-Za-z]?(?:\s*[-/]\s*\d{1,4}[A-Za-z]?)?\b)"
)
_LIEFER_STREET_LOOKAHEAD_RE = re.compile(rf"(?=({_LIEFER_STREET_PATTERN}))", re.IGNORECASE)
_LIEFER_STREET_RE = re.compile(_LIEFER_STREET_PATTERN, re.IGNORECASE)
_COMPANY_LEGAL_TOKEN_RE = re.compile(r"^(?:&|co\.?kg|co\.?|kg|gmbh|mbh|ag|ohg|ek|e\.k\.)$", re.IGNORECASE)
_STREET_KEYWORD_START_RE = re.compile(
    r"^(?:Str\.?|Strasse|Straße|Weg|Platz|Allee|Chaussee|Ring|Gasse|Damm|Ufer|Pfad|Steig|Kai|Markt|Berg|Stieg)\b",
    re.IGNORECASE,
)


def _format_german_address_lines(value: str) -> str:
    """
    Enforce a 2-line German address format:
    Line 1: Street + HouseNo
    Line 2: PLZ + City
    """
    if not value:
        return value
    s = str(value).replace("\r\n", "\n").replace("\r", "\n").strip()
    if not _ADDRESS_PLZ_RE.search(s):
        return s
    # Collapse existing line breaks to re-apply a single PLZ line break.
    s = re.sub(r"\s*\n\s*", " ", s)
    # Split glued house+PLZ tokens (e.g., "10133332" -> "101 33332").
    s = _ADDRESS_GLUE_PLZ_RE.sub(r"\1 \2", s)
    # Insert newline before the first PLZ.
    s = _ADDRESS_PLZ_RE.sub(r"\n\g<0>", s, count=1)
    # Clean up spaces around newline.
    s = re.sub(r"[ \t]*\n[ \t]*", "\n", s)
    return s


def _format_lieferanschrift_lines(value: str) -> str:
    """
    Preserve multi-line delivery addresses while ensuring a PLZ line break.
    Allows 3+ lines when company names are present.
    """
    if not value:
        return value
    s = str(value).replace("\r\n", "\n").replace("\r", "\n").strip()
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in s.splitlines() if line.strip()]
    # OCR sometimes glues legal form + street start (e.g. "Co.KGDelitzscher").
    lines = [
        re.sub(
            r"\b(Co\.?KG|GmbH|mbH|AG|OHG|KG)(?=[A-ZÄÖÜ][a-zäöü])",
            r"\1 ",
            line,
        )
        for line in lines
    ]
    filtered_lines = []
    for line in lines:
        has_iln = bool(_ILN_TOKEN_RE.search(line))
        only_iln_digits = bool(re.fullmatch(r"\d{13}", re.sub(r"\D", "", line)))
        labeled_iln = bool(_ILN_GLN_LABEL_RE.search(line))
        if has_iln and (only_iln_digits or labeled_iln):
            continue
        filtered_lines.append(line)
    lines = filtered_lines
    if not lines:
        return ""
    if not any(_ADDRESS_PLZ_RE.search(line) for line in lines):
        return "\n".join(lines)

    def _split_company_street(left_text: str) -> tuple[str, str] | None:
        left = left_text.strip(" ,")
        if not left:
            return None
        street_match = None
        street_match_len = -1
        for candidate in _LIEFER_STREET_LOOKAHEAD_RE.finditer(left):
            first_token = (candidate.group(1).split() or [""])[0].strip(".,")
            if _COMPANY_LEGAL_TOKEN_RE.fullmatch(first_token):
                continue
            cand_street = candidate.group(1).strip(" ,")
            cand_len = len(cand_street)
            if cand_len > street_match_len:
                street_match = candidate
                street_match_len = cand_len
        if not street_match:
            return None
        company = left[: street_match.start(1)].strip(" ,")
        street = street_match.group(1).strip(" ,")
        # If street starts with only a street-type token ("Str. 6"),
        # pull the trailing token from company into the street line.
        if company and _STREET_KEYWORD_START_RE.match(street):
            company_tokens = company.split()
            if company_tokens:
                street = f"{company_tokens[-1]} {street}".strip()
                company = " ".join(company_tokens[:-1]).strip(" ,")
        if not company or not street:
            return None
        return company, street

    if len(lines) == 1:
        one_line = lines[0]
        # Remove inline ILN/GLN tokens before address splitting.
        one_line = _ILN_TOKEN_RE.sub(" ", one_line)
        one_line = re.sub(r"\s+", " ", one_line).strip()
        plz_match = _ADDRESS_PLZ_RE.search(one_line)
        if not plz_match:
            return one_line

        left = one_line[: plz_match.start()].strip(" ,")
        plz_city = one_line[plz_match.start() :].strip()
        company_street = _split_company_street(left)
        if company_street:
            company, street = company_street
            return f"{company}\n{street}\n{plz_city}"
        return f"{left}\n{plz_city}" if left else plz_city

    plz_idx = next(i for i, line in enumerate(lines) if _ADDRESS_PLZ_RE.search(line))
    plz_line = lines[plz_idx]
    formatted = _format_german_address_lines(plz_line)
    if "\n" in formatted:
        street, plzcity = formatted.split("\n", 1)
        prefix = " ".join(lines[:plz_idx]).strip()
        company_street = _split_company_street(prefix) if prefix else None
        if company_street:
            company, street_line = company_street
            new_lines = [company, street_line, plzcity] + lines[plz_idx + 1 :]
        elif street.strip():
            new_lines = lines[:plz_idx] + [street, plzcity] + lines[plz_idx + 1 :]
        else:
            new_lines = lines[:plz_idx] + [plzcity] + lines[plz_idx + 1 :]
        return "\n".join(new_lines)
    return "\n".join(lines)


def _strip_company_from_lieferanschrift_for_porta(value: str) -> str:
    """
    Porta-only cleanup: keep address lines (street + PLZ/city), drop company/label prefix lines.
    Fallback: if no clear street+PLZ is detected, preserve raw input unchanged.
    """
    if not value:
        return value

    raw_value = str(value)
    formatted = _format_lieferanschrift_lines(raw_value)
    lines = [
        _ADDRESS_GLUE_PLZ_RE.sub(
            r"\1 \2",
            re.sub(
                r"\b((?:str\.?|strasse|straße|weg|platz|allee|chaussee|ring|gasse|damm|ufer|pfad|steig|kai|markt|berg|stieg))(?=\d)",
                r"\1 ",
                re.sub(
                r"([a-zäöüß])([A-ZÄÖÜ])",
                r"\1 \2",
                re.sub(r"[ \t]+", " ", line).strip(),
                ),
                flags=re.IGNORECASE,
            ),
        )
        for line in formatted.splitlines()
        if line.strip()
    ]
    if len(lines) < 2:
        if len(lines) != 1:
            return raw_value
        single_line = lines[0]
        plz_match = _ADDRESS_PLZ_RE.search(single_line)
        if not plz_match:
            return raw_value
        left = single_line[: plz_match.start()].strip(" ,")
        plz_city = single_line[plz_match.start() :].strip()
        street_match = None
        for candidate in _LIEFER_STREET_LOOKAHEAD_RE.finditer(left):
            first_token = (candidate.group(1).split() or [""])[0].strip(".,")
            if _COMPANY_LEGAL_TOKEN_RE.fullmatch(first_token):
                continue
            street_match = candidate
        if not street_match:
            return raw_value
        street = street_match.group(1).strip(" ,")
        if not street:
            return raw_value
        if _STREET_KEYWORD_START_RE.match(street):
            prefix_tokens = left[: street_match.start(1)].split()
            if prefix_tokens:
                street = f"{prefix_tokens[-1]} {street}".strip()
        return f"{street}\n{plz_city}"

    plz_idx = next((i for i, line in enumerate(lines) if _ADDRESS_PLZ_RE.search(line)), -1)
    if plz_idx <= 0:
        return raw_value

    street_idx = -1
    for i in range(plz_idx):
        if _LIEFER_STREET_RE.search(lines[i]):
            street_idx = i
    if street_idx < 0:
        return raw_value

    stripped_lines = lines[street_idx:]
    if not stripped_lines:
        return raw_value
    return "\n".join(stripped_lines)


def _wrap_as_field_entry(value: Any, source: str = "derived") -> dict[str, Any]:
    """Wrap a raw value in the standard field entry structure."""
    if isinstance(value, dict) and "value" in value:
        # Already in correct format
        return value
    return {
        "value": value if value is not None else "",
        "source": source,
        "confidence": 0.9 if value else 0.0,
    }


def _remap_dict_keys(obj: dict[str, Any], aliases: dict[str, str], wrap_values: bool = True) -> dict[str, Any]:
    """Remap keys in a dictionary using alias mapping and optionally wrap values."""
    result = {}
    for key, value in obj.items():
        # Normalize key for lookup (lowercase, no spaces/hyphens)
        lookup_key = key.lower().replace("-", "_").replace(" ", "_")
        
        # Check if this is an alias that needs remapping
        if lookup_key in aliases:
            target_key = aliases[lookup_key]
        elif key.lower() in aliases:
            target_key = aliases[key.lower()]
        else:
            target_key = key
        
        # Wrap value if needed
        if wrap_values and target_key in HEADER_FIELDS + ITEM_FIELDS:
            result[target_key] = _wrap_as_field_entry(value)
        else:
            result[target_key] = value
    
    return result


def _remap_response(data: dict[str, Any]) -> dict[str, Any]:
    """
    Remap English/alternative field names to standard German field names.
    
    This is a fallback safety net that ensures data isn't lost when the LLM
    returns non-standard field names like 'customer_number' instead of 'kundennummer'.
    """
    if not data:
        return data
    
    result = dict(data)
    
    # Remap header fields
    header = result.get("header")
    if isinstance(header, dict):
        result["header"] = _remap_dict_keys(header, HEADER_FIELD_ALIASES, wrap_values=True)
    
    # Remap item fields
    items = result.get("items")
    if isinstance(items, list):
        remapped_items = []
        for item in items:
            if isinstance(item, dict):
                remapped_item = _remap_dict_keys(item, ITEM_FIELD_ALIASES, wrap_values=True)
                remapped_items.append(remapped_item)
            else:
                remapped_items.append(item)
        result["items"] = remapped_items
    
    return result


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    text = _CONTROL_RE.sub("", text)
    # Preserve newlines but normalize other whitespace
    lines = []
    for line in text.splitlines():
        cleaned_line = re.sub(r"[ \t]+", " ", line).strip()
        if cleaned_line:
            lines.append(cleaned_line)
    return "\n".join(lines)


def _extract_reply_cases(email_body: str) -> list[str]:
    if not email_body:
        return []
    cleaned = _clean_text(email_body)
    if not cleaned:
        return []
    joined = " ".join(part for part in cleaned.splitlines() if part)
    matches = _REPLY_CASE_RE.findall(joined)
    cases: list[str] = []
    seen = set()
    for match in matches:
        trimmed = match
        footer_match = _REPLY_FOOTER_RE.search(trimmed)
        if footer_match:
            trimmed = trimmed[: footer_match.start()]
        else:
            header_stop = _REPLY_HEADER_STOP_RE.search(trimmed)
            if header_stop:
                trimmed = trimmed[: header_stop.start()]
        compact = re.sub(r"\s+", " ", trimmed).strip()
        if not compact:
            continue
        if len(compact) > 300:
            compact = compact[:300].rstrip()
        key = compact.lower()
        if key in seen:
            continue
        seen.add(key)
        cases.append(compact)
    return cases


def _missing_critical_fields(missing_header: list[str]) -> list[str]:
    missing = set(missing_header or [])
    return [field for field in CRITICAL_REPLY_FIELDS if field in missing]


def _missing_critical_reply_warning(missing_fields: list[str]) -> str:
    return f"Reply needed: {MISSING_CRITICAL_REPLY_PREFIX} {', '.join(missing_fields)}"


def _missing_critical_item_fields(missing_items: list[tuple[int, str]]) -> list[tuple[str, list[int]]]:
    lines_by_field: dict[str, list[int]] = {}
    for line_no, field in missing_items:
        if field not in CRITICAL_ITEM_REPLY_FIELDS:
            continue
        if field not in lines_by_field:
            lines_by_field[field] = []
        if line_no not in lines_by_field[field]:
            lines_by_field[field].append(line_no)
    result: list[tuple[str, list[int]]] = []
    for field in CRITICAL_ITEM_REPLY_FIELDS:
        if field in lines_by_field:
            result.append((field, sorted(lines_by_field[field])))
    return result


def _missing_critical_item_reply_warning(missing_fields: list[tuple[str, list[int]]]) -> str:
    parts: list[str] = []
    for field, lines in missing_fields:
        if lines:
            joined_lines = ", ".join(str(line) for line in lines)
            parts.append(f"{field} (line {joined_lines})")
        else:
            parts.append(field)
    return f"Reply needed: {MISSING_CRITICAL_ITEM_REPLY_PREFIX} {', '.join(parts)}"


def _set_reply_needed_from_derived(header: dict[str, Any]) -> None:
    reply_entry = _ensure_field(header, "reply_needed")
    reply_entry["value"] = True
    if not str(reply_entry.get("source") or "").strip():
        reply_entry["source"] = "derived"
    confidence = reply_entry.get("confidence")
    if not isinstance(confidence, (int, float)) or float(confidence) <= 0.0:
        reply_entry["confidence"] = 1.0


def _append_unique_warning(warnings: list[str], message: str) -> None:
    if not message:
        return
    if message not in warnings:
        warnings.append(message)


def _normalize_date(value: Any, dayfirst: bool) -> tuple[str, bool]:
    text = _clean_text(value)
    if not text:
        return "", True
    try:
        parsed = parse(text, dayfirst=dayfirst, fuzzy=True)
        return parsed.date().isoformat(), True
    except Exception:
        return text, False


def _normalize_quantity(value: Any) -> tuple[Any, bool]:
    if value is None:
        return "", True
    if isinstance(value, (int, float)):
        return int(value) if float(value).is_integer() else value, True
    text = _clean_text(value)
    if not text:
        return "", True

    compact = text.replace(" ", "")
    if "," in compact and "." not in compact:
        compact = compact.replace(",", ".")
    else:
        compact = compact.replace(",", "")
    try:
        number = float(compact)
    except ValueError:
        return text, False
    if number.is_integer():
        return int(number), True
    return number, True


def _normalize_momax_bg_modellnummer(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    # Momax BG expects compact model codes without slash separators.
    return re.sub(r"[/\s]+", "", text)


def _normalize_momax_bg_artikelnummer(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    # Wrapped Code/Type tails can produce "180 98"; collapse digit-only groups.
    if re.fullmatch(r"\d+(?:\s+\d+)+", text):
        return re.sub(r"\s+", "", text)
    return text


_BG_NUMERIC_ALPHA_PAIR_RE = re.compile(r"^(\d{2,12})\s+([A-Za-z][A-Za-z0-9]*)$")
_BG_SUFFIX_ONLY_RE = re.compile(r"^(XB|XP)$", re.IGNORECASE)
_BG_ARTIKEL_STRICT_RE = re.compile(r"^\d{5}[A-Z]?$")
_BG_ARTIKEL_WITH_TRAILING_SUFFIX_RE = re.compile(r"^(\d{5})(XB|XP)$", re.IGNORECASE)
_BG_ARTIKEL_LIKE_WITH_SUFFIX_RE = re.compile(r"^(\d{5}[A-Z]?)(XB|XP)?$", re.IGNORECASE)
_BG_MODEL_LIKE_RE = re.compile(r"^(?:CQ|OJ|0J)[A-Z0-9]+$", re.IGNORECASE)
_BG_SHORT_NUMERIC_RE = re.compile(r"^\d{1,4}$")
_BG_LEADING_ARTIKEL_SUFFIX_MODEL_RE = re.compile(
    r"^(\d{5})(XB|XP)([A-Z0-9]+)$",
    re.IGNORECASE,
)


def _split_momax_bg_code(raw: Any) -> tuple[str, str] | None:
    text = _clean_text(raw)
    if not text:
        return None

    # Slash rule: last segment is article; prior segments compact into model.
    if "/" in text:
        parts = [segment.strip() for segment in text.split("/") if segment.strip()]
        if len(parts) >= 2:
            return parts[-1], "".join(parts[:-1])

    # Hyphen rule: standard MODEL-ARTICLE, with reversed accessory NUMERIC-ALPHA.
    if "-" in text:
        left, right = [part.strip() for part in text.rsplit("-", 1)]
        if left and right:
            if left.isdigit() and re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", right):
                return left, right
            return right, left

    # Whitespace-pair rule: "<NUMERIC> <ALPHA>".
    match = _BG_NUMERIC_ALPHA_PAIR_RE.fullmatch(text)
    if match:
        return match.group(1), match.group(2)

    return None


def _mark_momax_bg_code_derived(entry: dict[str, Any]) -> None:
    entry["source"] = "derived"
    entry["confidence"] = 1.0
    entry["derived_from"] = "momax_bg_code_normalization"


def _mark_momax_bg_strict_derived(entry: dict[str, Any], derived_from: str) -> None:
    entry["source"] = "derived"
    entry["confidence"] = 1.0
    entry["derived_from"] = derived_from


def _append_unique_suffix(modell: str, suffix: str) -> str:
    base = _normalize_momax_bg_modellnummer(modell)
    suffix_text = str(suffix or "").upper()
    if not suffix_text:
        return base
    if base.upper().endswith(suffix_text):
        return base
    return f"{base}{suffix_text}"


def _is_momax_bg_model_like(value: str) -> bool:
    text = _normalize_momax_bg_modellnummer(value)
    return bool(_BG_MODEL_LIKE_RE.fullmatch(text))


def _extract_artikel_and_suffix(value: str) -> tuple[str, str] | None:
    text = _normalize_momax_bg_artikelnummer(value).upper()
    match = _BG_ARTIKEL_LIKE_WITH_SUFFIX_RE.fullmatch(text)
    if not match:
        return None
    artikel = match.group(1)
    suffix = (match.group(2) or "").upper()
    return artikel, suffix


def _strict_artikel_token(value: str) -> str:
    return _normalize_momax_bg_artikelnummer(value).upper()


def _build_momax_bg_codes_from_slash_tokens(
    artikel: str,
    modell: str,
) -> tuple[str, str] | None:
    clean_modell = _clean_text(modell)
    clean_artikel = _clean_text(artikel)
    if "/" not in clean_modell and "/" not in clean_artikel:
        return None

    tokens: list[str] = []
    if clean_modell:
        for token in clean_modell.split("/"):
            cleaned = _normalize_momax_bg_artikelnummer(token)
            if cleaned:
                tokens.append(cleaned)
    if clean_artikel:
        if "/" in clean_artikel:
            for token in clean_artikel.split("/"):
                cleaned = _normalize_momax_bg_artikelnummer(token)
                if cleaned:
                    tokens.append(cleaned)
        else:
            tokens.append(_normalize_momax_bg_artikelnummer(clean_artikel))
    if len(tokens) < 2:
        return None

    article_idx = -1
    article_token = ""
    for idx, token in enumerate(tokens):
        candidate = token.upper()
        if _BG_ARTIKEL_STRICT_RE.fullmatch(candidate):
            article_idx = idx
            article_token = candidate
            break
    if article_idx < 0 or not article_token:
        return None

    suffix_token = ""
    model_tokens: list[str] = []
    for idx, token in enumerate(tokens):
        if idx == article_idx:
            continue
        upper_token = token.upper()
        if not suffix_token and _BG_SUFFIX_ONLY_RE.fullmatch(upper_token):
            suffix_token = upper_token
            continue
        model_tokens.append(token)

    alpha_tokens = [token for token in model_tokens if re.search(r"[A-Za-z]", token)]
    numeric_tokens = [token for token in model_tokens if not re.search(r"[A-Za-z]", token)]
    model_text = _normalize_momax_bg_modellnummer("".join(alpha_tokens + numeric_tokens))
    if suffix_token:
        model_text = _append_unique_suffix(model_text, suffix_token)
    return article_token, model_text


def _apply_momax_bg_strict_item_code_correction(item: dict[str, Any]) -> bool:
    artikel_entry = _ensure_field(item, "artikelnummer")
    modell_entry = _ensure_field(item, "modellnummer")

    old_artikel = _clean_text(artikel_entry.get("value"))
    old_modell = _clean_text(modell_entry.get("value"))
    artikel = _normalize_momax_bg_artikelnummer(old_artikel)
    modell = _clean_text(old_modell)

    derived_from = ""
    rule_applied = False
    upper_artikel = _strict_artikel_token(artikel)

    # Rule A: article token carries XB/XP suffix that belongs to model.
    match_a = _BG_ARTIKEL_WITH_TRAILING_SUFFIX_RE.fullmatch(upper_artikel)
    if match_a:
        artikel = match_a.group(1)
        modell = _append_unique_suffix(modell, match_a.group(2).upper())
        derived_from = "momax_bg_suffix_relocation"
        rule_applied = True

    # Rule B: swapped model/article values with optional model suffix on article token.
    if not rule_applied:
        model_candidate = _extract_artikel_and_suffix(modell)
        if _is_momax_bg_model_like(artikel) and model_candidate:
            new_artikel, suffix = model_candidate
            new_modell = _normalize_momax_bg_modellnummer(artikel)
            if suffix:
                new_modell = _append_unique_suffix(new_modell, suffix)
                derived_from = "momax_bg_suffix_relocation"
            else:
                derived_from = "momax_bg_strict_code_parser"
            artikel = new_artikel
            modell = new_modell
            rule_applied = True

    # Rule C: standalone XP/XB article; extract trailing strict article from model.
    if not rule_applied:
        suffix_only = _BG_SUFFIX_ONLY_RE.fullmatch(upper_artikel)
        if suffix_only:
            compact_model = _normalize_momax_bg_modellnummer(modell)
            tail_match = re.fullmatch(r"(.+?)(\d{5})", compact_model)
            if tail_match:
                artikel = tail_match.group(2)
                modell = _append_unique_suffix(tail_match.group(1), suffix_only.group(1).upper())
                derived_from = "momax_bg_suffix_relocation"
                rule_applied = True

    # Rule D: short numeric article moved from model tail in slash-compact patterns.
    if not rule_applied:
        compact_artikel = _normalize_momax_bg_artikelnummer(artikel)
        compact_model = _normalize_momax_bg_modellnummer(modell)
        match_d = _BG_LEADING_ARTIKEL_SUFFIX_MODEL_RE.fullmatch(compact_model)
        if (
            match_d
            and _BG_SHORT_NUMERIC_RE.fullmatch(compact_artikel)
            and len(compact_artikel) < 5
        ):
            artikel = match_d.group(1)
            suffix = match_d.group(2).upper()
            model_head = match_d.group(3)
            modell = _append_unique_suffix(f"{model_head}{compact_artikel}", suffix)
            derived_from = "momax_bg_suffix_relocation"
            rule_applied = True

    # Rule E: explicit slash tokens -> choose strict article token and rebuild model.
    if not rule_applied:
        slash_rebuild = _build_momax_bg_codes_from_slash_tokens(artikel, modell)
        if slash_rebuild:
            artikel, modell = slash_rebuild
            derived_from = "momax_bg_strict_code_parser"
            rule_applied = True

    if not derived_from:
        return False

    new_artikel = _normalize_momax_bg_artikelnummer(artikel)
    new_modell = _normalize_momax_bg_modellnummer(modell)
    changed = False

    if new_artikel != old_artikel:
        artikel_entry["value"] = new_artikel
        _mark_momax_bg_strict_derived(artikel_entry, derived_from)
        changed = True
    if new_modell != old_modell:
        modell_entry["value"] = new_modell
        _mark_momax_bg_strict_derived(modell_entry, derived_from)
        changed = True

    return changed


def apply_momax_bg_strict_item_code_corrections(data: dict[str, Any]) -> int:
    """
    Apply deterministic MOMAX BG strict article/model correction rules.

    Returns the number of item lines that changed.
    """
    if not isinstance(data, dict):
        return 0
    items = data.get("items")
    if not isinstance(items, list) or not items:
        return 0

    corrected_lines = 0
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        if not item.get("line_no"):
            item["line_no"] = index
        if _apply_momax_bg_strict_item_code_correction(item):
            corrected_lines += 1
    return corrected_lines


def _normalize_momax_bg_item_codes(item: dict[str, Any]) -> None:
    artikel_entry = _ensure_field(item, "artikelnummer")
    modell_entry = _ensure_field(item, "modellnummer")

    artikel_value = _normalize_momax_bg_artikelnummer(artikel_entry.get("value"))
    modell_value = _clean_text(modell_entry.get("value"))
    if artikel_value != _clean_text(artikel_entry.get("value")):
        artikel_entry["value"] = artikel_value
        _mark_momax_bg_code_derived(artikel_entry)
    split_result: tuple[str, str] | None = _split_momax_bg_code(artikel_value)

    # Only split from modellnummer when artikelnummer is missing (or duplicated).
    if (not split_result) and (not artikel_value or artikel_value == modell_value):
        split_result = _split_momax_bg_code(modell_value)

    if split_result:
        new_artikel, new_modell = split_result
        new_modell = _normalize_momax_bg_modellnummer(new_modell)

        if new_artikel != artikel_value:
            artikel_entry["value"] = new_artikel
            _mark_momax_bg_code_derived(artikel_entry)
        if new_modell != modell_value:
            modell_entry["value"] = new_modell
            _mark_momax_bg_code_derived(modell_entry)
        return

    compact_model = _normalize_momax_bg_modellnummer(modell_value)
    if compact_model != modell_value:
        modell_entry["value"] = compact_model


def _ensure_field(obj: dict[str, Any], field: str) -> dict[str, Any]:
    entry = obj.get(field)
    if not isinstance(entry, dict):
        entry = {"value": entry if entry is not None else "", "source": "derived", "confidence": 0.0}
        obj[field] = entry
    entry.setdefault("value", "")
    entry.setdefault("source", "derived")
    entry.setdefault("confidence", 0.0)
    return entry


def _normalize_header(header: dict[str, Any], dayfirst: bool, warnings: list[str]) -> None:
    for field in HEADER_FIELDS:
        entry = _ensure_field(header, field)
        if entry.get("source") not in ALLOWED_SOURCES:
            entry["source"] = "derived"

        if field in ("human_review_needed", "reply_needed", "post_case"):
             val = entry.get("value")
             if isinstance(val, bool):
                 entry["value"] = val
             elif str(val).lower() == "true":
                 entry["value"] = True
             else:
                 entry["value"] = False
        else:
            entry["value"] = _clean_text(entry.get("value"))

        if not entry.get("value") and field not in ("human_review_needed", "reply_needed", "post_case"):
            entry["confidence"] = 0.0


def _normalize_items(
    items: list[dict[str, Any]],
    dayfirst: bool,
    warnings: list[str],
    is_momax_bg: bool = False,
) -> None:
    for idx, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            item = {}
        if not item.get("line_no"):
            item["line_no"] = idx

        for field in ITEM_FIELDS:
            entry = _ensure_field(item, field)
            if entry.get("source") not in ALLOWED_SOURCES:
                entry["source"] = "derived"

            if field == "menge":
                normalized, ok = _normalize_quantity(entry.get("value"))
                entry["value"] = normalized
                if not ok:
                    warnings.append(f"Failed to normalize quantity for item {idx}.")
            else:
                entry["value"] = _clean_text(entry.get("value"))

        if is_momax_bg:
            _normalize_momax_bg_item_codes(item)

        for field in ITEM_FIELDS:
            entry = _ensure_field(item, field)
            if not entry.get("value"):
                entry["confidence"] = 0.0

        items[idx - 1] = item


def _propagate_furncloud_id(items: list[dict[str, Any]], warnings: list[str]) -> None:
    values: list[str] = []
    for item in items:
        entry = item.get("furncloud_id", {})
        value = _clean_text(entry.get("value") if isinstance(entry, dict) else entry)
        if value and value not in values:
            values.append(value)

    if not values:
        return

    if len(values) > 1:
        warnings.append("Multiple furncloud_id values found; using the first for all items.")

    chosen = values[0]
    for item in items:
        entry = _ensure_field(item, "furncloud_id")
        current = _clean_text(entry.get("value"))
        entry["value"] = chosen
        if current == chosen and entry.get("source") in ALLOWED_SOURCES and entry.get("source") != "derived":
            continue
        entry["source"] = "derived"
        entry["confidence"] = 1.0


def apply_program_furncloud_to_items(data: dict[str, Any], warnings: list[str] | None = None) -> None:
    """
    If program.furncloud_id is present, fill missing items[*].furncloud_id from it.

    This keeps the dashboard (item-level furncloud_id) consistent with the XML export
    (program-level furncloud_id rendered into Program/Remarks).
    """
    if not data or not isinstance(data, dict):
        return

    program = data.get("program")
    if not isinstance(program, dict):
        return

    program_fc = _clean_text(program.get("furncloud_id"))
    if not program_fc:
        return

    items = data.get("items")
    if not isinstance(items, list) or not items:
        return

    mismatch = False
    for item in items:
        if not isinstance(item, dict):
            continue
        entry = _ensure_field(item, "furncloud_id")
        current = _clean_text(entry.get("value"))
        if not current:
            entry["value"] = program_fc
            entry["source"] = "derived"
            entry["confidence"] = 1.0
            continue
        if current != program_fc:
            mismatch = True

    if mismatch and isinstance(warnings, list):
        warnings.append("program.furncloud_id differs from one or more item furncloud_id values.")


def _apply_wunschtermin_rule(header: dict[str, Any]) -> None:
    wunsch = header.get("wunschtermin", {})
    if _clean_text(wunsch.get("value")):
        return
    liefer = header.get("liefertermin", {})
    if not _clean_text(liefer.get("value")):
        return
    header["wunschtermin"] = {
        "value": liefer.get("value"),
        "source": "derived",
        "confidence": 1.0,
        "derived_from": "liefertermin",
    }


def _is_missing(entry: dict[str, Any]) -> bool:
    value = entry.get("value")
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _enrich_from_excel(
    header: dict[str, Any],
    warnings: list[str],
    email_body: str = "",
    sender: str = "",
    is_momax_bg: bool = False,
) -> None:
    """Try to find missing customer fields in the Excel database."""
    delivery_address = header.get("lieferanschrift", {}).get("value")
    store_address = header.get("store_address", {}).get("value")

    # ILN-BASED ADDRESS MAPPING (CRITICAL - Takes precedence over raw email text)
    # This ensures consistent, normalized addresses from the ILN Excel mapping
    # and ensures PLZ from the ILN list is used for Primex filtering.

    # 1. Map ILN-Anl (Delivery Location) -> lieferanschrift
    iln_anl_val = header.get("iln_anl", {}).get("value")
    if (not is_momax_bg) and iln_anl_val:
        addr_info = lookup.find_address_by_iln(iln_anl_val)
        if addr_info:
            header["lieferanschrift"] = {
                "value": addr_info["formatted_address"],
                "source": "derived",
                "confidence": 1.0,
                "derived_from": "iln_excel_lookup"
            }
            delivery_address = header["lieferanschrift"]["value"]
        else:
            warnings.append(f"ILN-Anl {iln_anl_val} not found in Excel mapping")
        iln_entry = header.get("iln", {})
        iln_current = iln_entry.get("value") if isinstance(iln_entry, dict) else iln_entry
        if not iln_current or str(iln_current).strip() != str(iln_anl_val).strip():
            header["iln"] = {
                "value": iln_anl_val,
                "source": "derived",
                "confidence": 1.0,
                "derived_from": "iln_anl_copy",
            }

    # 2. Map ILN-Fil (Store/Branch) -> store_address and get company + filiale hint for Kundennummer disambiguation
    iln_company: Optional[str] = None
    iln_filiale_hint: Optional[str] = None
    iln_fil_val = header.get("iln_fil", {}).get("value")
    if (not is_momax_bg) and iln_fil_val:
        addr_info = lookup.find_address_by_iln(iln_fil_val)
        if addr_info:
            header["store_address"] = {
                "value": addr_info["formatted_address"],
                "source": "derived",
                "confidence": 1.0,
                "derived_from": "iln_excel_lookup"
            }
            store_address = header["store_address"]["value"]
            iln_company = addr_info.get("company") or None
            iln_filiale_hint = addr_info.get("filiale_hint") or None
        else:
            warnings.append(f"ILN-Fil {iln_fil_val} not found in Excel mapping")

    # Find ILN from ILN Excel (using delivery address if available) only if missing
    iln_entry = header.get("iln")
    iln_current = (
        iln_entry.get("value") if isinstance(iln_entry, dict) else (str(iln_entry).strip() if iln_entry else "")
    )
    if (not is_momax_bg) and delivery_address and not iln_current:
        iln_val = lookup.find_iln_by_address(delivery_address)
        if iln_val:
            header["iln"] = {
                "value": iln_val,
                "source": "derived",
                "confidence": 1.0,
                "derived_from": "iln_excel_lookup"
            }

    # KDNR-from-email: if email extracted a Kundennummer that looks like Primex (numeric, 4-8 digits, not 13-digit ILN), resolve it first
    kdnr_from_email: Optional[str] = None
    kdnr_entry = header.get("kundennummer", {})
    if isinstance(kdnr_entry, dict):
        kdnr_val = (kdnr_entry.get("value") or "")
        kdnr_val = str(kdnr_val).strip() if kdnr_val is not None else ""
        kdnr_src = (kdnr_entry.get("source") or "").lower()
        if kdnr_val and kdnr_src in ("email", "pdf", "image"):
            digits_only = re.sub(r"\D", "", kdnr_val)
            if len(digits_only) >= 4 and len(digits_only) <= 8 and len(digits_only) != 13:
                kdnr_from_email = digits_only.lstrip("0") or digits_only
    kdnr_match = None
    if (not is_momax_bg) and kdnr_from_email:
        kdnr_match = lookup.find_customer_by_address("", kundennummer=kdnr_from_email)
        if kdnr_match:
            header["kundennummer"] = {
                "value": kdnr_match["kundennummer"],
                "source": "derived",
                "confidence": 1.0,
                "derived_from": "excel_lookup_by_kundennummer",
            }
            header["adressnummer"] = {
                "value": kdnr_match["adressnummer"],
                "source": "derived",
                "confidence": 1.0,
                "derived_from": "excel_lookup_by_kundennummer",
            }
            header["tour"] = {
                "value": kdnr_match["tour"],
                "source": "derived",
                "confidence": 1.0,
                "derived_from": "excel_lookup_by_kundennummer",
            }
            warnings.append("Kundennummer from email KDNR verified in Primex; please confirm.")

    # Logic: Prefer STORE ADDRESS for finding the Customer/Kundennummer (skip if we already resolved via KDNR)
    # The store is the billing entity. Delivery address is where it goes.
    # momax_bg must use store_address from extraction only (no ILN-derived address source).
    address_to_search = store_address if is_momax_bg else (store_address if store_address else delivery_address)

    # Check for JOOP
    is_joop = "JOOP" in email_body.upper() if email_body else False
    store_name_val = header.get("store_name", {}).get("value", "")

    if not kdnr_match and is_momax_bg and address_to_search:
        momax_match = lookup.find_momax_bg_customer_by_address(
            address_to_search,
            store_name=store_name_val,
            warnings=warnings,
        )
        if momax_match:
            header["kundennummer"] = {
                "value": momax_match["kundennummer"],
                "source": "derived",
                "confidence": 1.0,
                "derived_from": "excel_lookup_momax_bg_address",
            }
            header["adressnummer"] = {
                "value": momax_match["adressnummer"],
                "source": "derived",
                "confidence": 1.0,
                "derived_from": "excel_lookup_momax_bg_address",
            }
            header["tour"] = {
                "value": momax_match["tour"],
                "source": "derived",
                "confidence": 1.0,
                "derived_from": "excel_lookup_momax_bg_address",
            }
            kdnr_match = momax_match
        else:
            warnings.append(
                "MOMAX BG address match failed in Kunden_Bulgarien.xlsx."
            )
    if is_momax_bg and not kdnr_match:
        if not address_to_search:
            warnings.append("MOMAX BG store_address missing; Kundennummer lookup failed.")
        header["kundennummer"] = {
            "value": "",
            "source": "derived",
            "confidence": 0.0,
            "derived_from": "excel_lookup_failed"
        }
        header["adressnummer"] = {
            "value": "",
            "source": "derived",
            "confidence": 0.0,
            "derived_from": "excel_lookup_failed"
        }
        header["tour"] = {
            "value": "",
            "source": "derived",
            "confidence": 0.0,
            "derived_from": "excel_lookup_failed"
        }

    if (not is_momax_bg) and (not kdnr_match) and address_to_search:
        # Perform Lookup with new params
        hint_text = "\n".join([p for p in [sender, email_body] if p]).strip()
        match = lookup.find_customer_by_address(
            address_to_search,
            kom_name=store_name_val,
            is_joop=is_joop,
            client_hint=hint_text,
            iln_company=iln_company,
            iln_filiale_hint=iln_filiale_hint,
            warnings=warnings,
        )

        if match:
            # Update fields
            # Always overwrite KndNr if we found a strict address match, as extraction often grabs ILN/Phone
            header["kundennummer"] = {
                "value": match["kundennummer"],
                "source": "derived",
                "confidence": 1.0,
                "derived_from": "excel_lookup"
            }

            # Specifically for adressnummer/tour
            header["adressnummer"] = {
                "value": match["adressnummer"],
                "source": "derived",
                "confidence": 1.0,
                "derived_from": "excel_lookup"
            }
            header["tour"] = {
                "value": match["tour"],
                "source": "derived",
                "confidence": 1.0,
                "derived_from": "excel_lookup"
            }
        else:
            # Address match failed: try ILN fallback (derive Kundennummer from ILN and verify in Primex)
            iln_for_fallback = iln_fil_val or iln_anl_val or header.get("iln", {}).get("value")
            iln_kdnr = lookup.find_kundennummer_by_iln(iln_for_fallback) if iln_for_fallback else None
            if iln_kdnr:
                warnings.append(
                    "Kundennummer from ILN fallback (address match failed); please verify."
                )
                header["kundennummer"] = {
                    "value": iln_kdnr,
                    "source": "derived",
                    "confidence": 0.8,
                    "derived_from": "iln_fallback"
                }
                # Fill tour/adressnummer from Primex by Kundennummer
                kdnr_match = lookup.find_customer_by_address("", kundennummer=iln_kdnr)
                if kdnr_match:
                    header["adressnummer"] = {
                        "value": kdnr_match["adressnummer"],
                        "source": "derived",
                        "confidence": 0.8,
                        "derived_from": "iln_fallback"
                    }
                    header["tour"] = {
                        "value": kdnr_match["tour"],
                        "source": "derived",
                        "confidence": 0.8,
                        "derived_from": "iln_fallback"
                    }
                else:
                    header["adressnummer"] = {"value": "", "source": "derived", "confidence": 0.0, "derived_from": "excel_lookup_failed"}
                    header["tour"] = {"value": "", "source": "derived", "confidence": 0.0, "derived_from": "excel_lookup_failed"}
            else:
                header["kundennummer"] = {
                    "value": "",
                    "source": "derived",
                    "confidence": 0.0,
                    "derived_from": "excel_lookup_failed"
                }
                header["adressnummer"] = {
                    "value": "",
                    "source": "derived",
                    "confidence": 0.0,
                    "derived_from": "excel_lookup_failed"
                }
                header["tour"] = {
                    "value": "",
                    "source": "derived",
                    "confidence": 0.0,
                    "derived_from": "excel_lookup_failed"
                }

    # Tour validation against Lieferlogik: warn if tour not found in delivery schedule
    tour_val = header.get("tour", {}).get("value")
    if tour_val and str(tour_val).strip():
        import delivery_logic as _dl
        if not _dl.is_tour_valid(str(tour_val).strip()):
            warnings.append(f"Tour number '{tour_val}' not found in Lieferlogik; please verify in Primex Kunden Excel.")

    # Calculate Delivery Week (using delivery_logic)
    bestelldatum_val = header.get("bestelldatum", {}).get("value")
    wunschtermin_val = header.get("wunschtermin", {}).get("value")
    store_name_val = header.get("store_name", {}).get("value", "")

    if bestelldatum_val and tour_val:
        import delivery_logic
        dw = delivery_logic.calculate_delivery_week(
            bestelldatum_val, tour_val, wunschtermin_val,
            client_name=store_name_val
        )
        if dw:
            header["delivery_week"] = {
                "value": dw,
                "source": "derived",
                "confidence": 1.0,
                "derived_from": "delivery_logic"
            }


def normalize_output(
    data: dict[str, Any],
    message_id: str,
    received_at: str,
    dayfirst: bool,
    warnings: list[str],
    email_body: str = "",
    sender: str = "",
    is_momax_bg: bool = False,
    branch_id: str = "",
) -> dict[str, Any]:
    data = data or {}
    
    # FIRST: Remap any English/alternative field names to standard German names
    # This ensures data isn't lost if the LLM uses non-standard field names
    data = _remap_response(data)
    
    had_structure = bool(data.get("header")) or bool(data.get("items"))
    data["message_id"] = message_id
    data["received_at"] = received_at

    header = data.get("header")
    if not isinstance(header, dict):
        header = {}
        data["header"] = header

    # Backend: kom_name email vs PDF conflict warning (LLM may set kom_name_pdf when PDF differs)
    _kom_name_val = header.get("kom_name")
    kom_email = ((_kom_name_val.get("value", "") or "") if isinstance(_kom_name_val, dict) else str(_kom_name_val or "")).strip()
    _pdf_entry = header.get("kom_name_pdf")
    kom_pdf = ""
    if isinstance(_pdf_entry, dict):
        kom_pdf = str(_pdf_entry.get("value", "") or "").strip()
    elif isinstance(_pdf_entry, str):
        kom_pdf = _pdf_entry.strip()
    if kom_pdf and kom_email and kom_pdf != kom_email.strip():
        warnings.append("kom_name in PDF differed from email body; using value from email body.")
    if "kom_name_pdf" in header:
        del header["kom_name_pdf"]

    _normalize_header(header, dayfirst, warnings)
    reply_needed_entry = header.get("reply_needed", {})
    reply_needed_flag = False
    if isinstance(reply_needed_entry, dict):
        reply_needed_flag = reply_needed_entry.get("value") is True
    if reply_needed_flag and email_body:
        for case in _extract_reply_cases(email_body):
            _append_unique_warning(warnings, f"Reply needed: {case}")
    _apply_wunschtermin_rule(header)
    _enrich_from_excel(
        header,
        warnings,
        email_body=email_body,
        sender=sender,
        is_momax_bg=is_momax_bg,
    )
    for field in ("lieferanschrift", "store_address"):
        entry = header.get(field)
        if isinstance(entry, dict):
            value = entry.get("value", "")
            if field == "lieferanschrift":
                if (branch_id or "").strip() == "porta":
                    formatted = _strip_company_from_lieferanschrift_for_porta(value)
                else:
                    formatted = _format_lieferanschrift_lines(value)
            else:
                formatted = _format_german_address_lines(value)
            if formatted != value:
                entry["value"] = formatted

    # When agent used ILN fallback or AI-assisted match, require human review (header-only edit)
    kdnr_entry = header.get("kundennummer", {})
    if isinstance(kdnr_entry, dict):
        derived = (kdnr_entry.get("derived_from") or "").strip()
        if derived in ("iln_fallback", "ai_assisted_match"):
            _ensure_field(header, "human_review_needed")
            header["human_review_needed"]["value"] = True

    items = data.get("items")
    if not isinstance(items, list):
        items = []
    data["items"] = items
    _normalize_items(items, dayfirst, warnings, is_momax_bg=is_momax_bg)
    if is_momax_bg:
        apply_momax_bg_strict_item_code_corrections(data)
    _propagate_furncloud_id(items, warnings)
    apply_program_furncloud_to_items(data, warnings)

    existing_warnings = data.get("warnings", [])
    if not isinstance(existing_warnings, list):
        existing_warnings = [str(existing_warnings)]
    existing_errors = data.get("errors", [])
    if not isinstance(existing_errors, list):
        existing_errors = [str(existing_errors)]

    data["warnings"] = list(dict.fromkeys(warnings + existing_warnings))
    data["errors"] = existing_errors

    missing_header = [field for field in HEADER_FIELDS if _is_missing(header.get(field, {}))]
    if is_momax_bg:
        missing_header = [field for field in missing_header if field != "kom_name"]
    missing_header_no_ticket = [field for field in missing_header if field != "ticket_number"]
    missing_critical_fields = _missing_critical_fields(missing_header)
    if missing_critical_fields:
        _set_reply_needed_from_derived(header)
        _append_unique_warning(
            data["warnings"],
            _missing_critical_reply_warning(missing_critical_fields),
        )
    missing_items = []
    if not items:
        missing_items.append((0, "items"))
    else:
        for idx, item in enumerate(items, start=1):
            for field in ITEM_FIELDS:
                if _is_missing(item.get(field, {})):
                    missing_items.append((idx, field))
    missing_critical_item_fields = _missing_critical_item_fields(missing_items)
    if missing_critical_item_fields:
        _set_reply_needed_from_derived(header)
        _append_unique_warning(
            data["warnings"],
            _missing_critical_item_reply_warning(missing_critical_item_fields),
        )

    # Status: furncloud_id alone is non-blocking (OK with warning)
    critical_missing_items = [(i, f) for (i, f) in missing_items if f != "furncloud_id"]
    if not had_structure and not items:
        data["status"] = "failed"
    elif missing_header or critical_missing_items or not items:
        data["status"] = "partial"
    else:
        data["status"] = "ok"

    if missing_header_no_ticket:
        data["warnings"].append(f"Missing header fields: {', '.join(missing_header_no_ticket)}")
    if "ticket_number" in missing_header:
        data["warnings"].append(TICKET_MISSING_WARNING)
    if missing_items:
        if missing_items == [(0, "items")]:
            data["warnings"].append("No items extracted.")
        elif all(f == "furncloud_id" for (_, f) in missing_items):
            # Only furncloud_id missing: single message (no duplicate with "Missing item fields: ...")
            data["warnings"].append("furncloud_id is missing for one or more items.")
        else:
            # Concrete message listing what is missing (e.g. artikelnummer (line 2); furncloud_id (line 1))
            parts = [f"{f} (line {i})" for (i, f) in sorted(missing_items)]
            data["warnings"].append(f"Missing item fields: {'; '.join(parts)}")

    return data


def refresh_missing_warnings(data: dict[str, Any]) -> None:
    """
    Recompute missing_header/missing_items from current data and update status and warnings.
    Call after pipeline steps that fill header/items (e.g. AI match, Excel tour, delivery_week)
    so the UI warnings match the final state.
    """
    if not data:
        return
    header = data.get("header")
    items = data.get("items")
    if not isinstance(header, dict):
        header = {}
    if not isinstance(items, list):
        items = []

    # Keep UI/status consistent with XML export: if program.furncloud_id exists, treat it as the
    # global furncloud ID and fill missing item-level values before recomputing missing fields.
    data["items"] = items
    apply_program_furncloud_to_items(data, None)

    kom_name_entry = header.get("kom_name", {})
    is_momax_bg = (
        isinstance(kom_name_entry, dict)
        and kom_name_entry.get("derived_from") == "momax_bg_policy"
    )

    missing_header = [f for f in HEADER_FIELDS if _is_missing(header.get(f, {}))]
    if is_momax_bg:
        missing_header = [field for field in missing_header if field != "kom_name"]
    missing_header_no_ticket = [field for field in missing_header if field != "ticket_number"]
    missing_critical_fields = _missing_critical_fields(missing_header)
    if missing_critical_fields:
        _set_reply_needed_from_derived(header)
    missing_items: list[tuple[int, str]] = []
    if not items:
        missing_items.append((0, "items"))
    else:
        for idx, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue
            for field in ITEM_FIELDS:
                if _is_missing(item.get(field, {})):
                    missing_items.append((idx, field))
    missing_critical_item_fields = _missing_critical_item_fields(missing_items)
    if missing_critical_item_fields:
        _set_reply_needed_from_derived(header)

    critical_missing_items = [(i, f) for (i, f) in missing_items if f != "furncloud_id"]
    if missing_header or critical_missing_items or not items:
        data["status"] = "partial"
    else:
        data["status"] = "ok"

    warnings = data.get("warnings")
    if not isinstance(warnings, list):
        warnings = list(warnings) if warnings else []
    else:
        warnings = list(warnings)

    def drop_startswith(w: str, prefix: str) -> bool:
        return isinstance(w, str) and w.startswith(prefix)

    warnings = [w for w in warnings if not drop_startswith(w, "Missing header fields:")]
    warnings = [w for w in warnings if w != "No items extracted." and w != "Missing item fields detected."]
    warnings = [w for w in warnings if not (isinstance(w, str) and w.startswith("Missing item fields:"))]
    warnings = [w for w in warnings if w != "furncloud_id is missing for one or more items."]
    warnings = [w for w in warnings if w != TICKET_MISSING_WARNING]
    warnings = [
        w
        for w in warnings
        if not (isinstance(w, str) and w.startswith(f"Reply needed: {MISSING_CRITICAL_REPLY_PREFIX}"))
    ]
    warnings = [
        w
        for w in warnings
        if not (isinstance(w, str) and w.startswith(f"Reply needed: {MISSING_CRITICAL_ITEM_REPLY_PREFIX}"))
    ]

    if missing_header_no_ticket:
        warnings.append(f"Missing header fields: {', '.join(missing_header_no_ticket)}")
    if missing_critical_fields:
        _append_unique_warning(
            warnings,
            _missing_critical_reply_warning(missing_critical_fields),
        )
    if missing_critical_item_fields:
        _append_unique_warning(
            warnings,
            _missing_critical_item_reply_warning(missing_critical_item_fields),
        )
    if "ticket_number" in missing_header:
        warnings.append(TICKET_MISSING_WARNING)
    if missing_items:
        if missing_items == [(0, "items")]:
            warnings.append("No items extracted.")
        elif all(f == "furncloud_id" for (_, f) in missing_items):
            warnings.append("furncloud_id is missing for one or more items.")
        else:
            parts = [f"{f} (line {i})" for (i, f) in sorted(missing_items)]
            warnings.append(f"Missing item fields: {'; '.join(parts)}")

    data["warnings"] = warnings
