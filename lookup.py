import pandas as pd
import re
import os
from typing import Optional, Dict, Any, List, Set
from difflib import SequenceMatcher

try:
    from rapidfuzz import fuzz
except ImportError:
    fuzz = None  # Fuzzy fallback disabled if rapidfuzz not installed

# Cache for the Excel data to avoid reloading on every request
_excel_cache: Optional[pd.DataFrame] = None
EXCEL_PATH = "Primex_Kunden_mit_Verband.xlsb"
VERBAND_FILTER = (27750, 29000, 30000)

_iln_cache: Optional[pd.DataFrame] = None
ILN_EXCEL_PATH = "ALL ILN LISTE_20.01.2026_LH.xlsx"
MOMAX_BG_ALLOWED_KUNDENNUMMERN = {"68935", "68936", "68937", "68938", "68939", "68941"}

# ---------------------------------------------------------------------------
# Column mapping and normalization (single place for both Excels)
# ---------------------------------------------------------------------------
# Primex (EXCEL_PATH): Kundennummer, Kundenbetrieb, Name1, Name2, Name3, Strasse, Ort,
#   Postleitzahl, Adressnummer, Tour, Verband.
#   Matching: Strasse, Ort, Postleitzahl. Tie-break: Name1, Name2. Filter: Verband, Adressnummer.
# ILN Excel (ILN_EXCEL_PATH): ILN, Straße (or "Strasse"), PLZ, Ort, Gesellschaft, Filialträger,
#   Filiale/Lager. Address: Straße, PLZ, Ort. Company/tie-break: Gesellschaft, Filialträger, Filiale/Lager.
# Normalizers: Street -> _normalize_address_token (ß→ss, Straße/str.→str, collapse spaces/hyphens).
#   City -> _city_tokens + _city_matches (token set, order-independent; stopwords: neu, am, bei).
#   PLZ -> _plz_digits_only. Company -> token set for tie-breaking (existing logic in find_customer_by_address).


def _fix_mojibake(s: str) -> str:
    """Fix common encoding/mojibake so addresses from ILN Excel and Primex match (e.g. Haßfurt)."""
    if not isinstance(s, str):
        return ""
    # Latin-1/CP1252 mojibake when UTF-8 is misinterpreted
    s = s.replace("\u00c3\u00df", "ss").replace("ÃŸ", "ss").replace("Ã¼", "ue")
    s = s.replace("Ã¤", "ae").replace("Ã¶", "oe").replace("Ã„", "ae").replace("Ã–", "oe").replace("Ãœ", "ue")
    # Unicode replacement character (e.g. from Excel): treat as ß for city names like Hafurt -> Hassfurt
    if "\ufffd" in s:
        s = s.replace("\ufffd", "ss")
    return s


def _normalize_address_token(s: str) -> str:
    """Single shared normalizer for street/address tokens. Lowercase, umlauts to ae/oe/ue, ß to ss,
    collapse street words (straße/strasse/str.) to 'str', remove spaces and hyphens."""
    if not isinstance(s, str):
        return ""
    s = _fix_mojibake(s)
    s = s.lower()
    s = s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    s = s.replace("straße", "str").replace("strasse", "str").replace("strase", "str").replace("strabe", "str").replace("str.", "str")
    return s.replace(" ", "").replace("-", "").replace("/", "")


def _normalize_city(s: str) -> str:
    """Normalize city for comparison: 'Zell am See' and 'Zell/See' -> same form; 'Wien (12)' -> wien12."""
    if not isinstance(s, str):
        return ""
    s = _fix_mojibake(s)
    s = s.lower().strip()
    s = s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    # " am " -> "" and "/" -> "" so "Zell am See" and "Zell/See" both become "zellsee"
    s = s.replace(" am ", " ").replace("/", " ")
    # Remove parentheses but keep digits: "Wien (12)" -> "wien 12" then collapse
    s = re.sub(r"\s*\(\s*(\d+)\s*\)\s*", r" \1 ", s)
    return s.replace(" ", "").replace("-", "")


# Stopwords to drop when comparing city tokens (order-independent match, e.g. Innsbruck/Neu Rum vs Rum/Innsbruck)
_CITY_STOPWORDS = {"neu", "am", "bei", "der", "die", "das"}


def _city_tokens(s: str) -> set:
    """Split city string into significant tokens (lowercase, umlauts normalized); drop stopwords."""
    if not isinstance(s, str) or not s.strip():
        return set()
    s = _fix_mojibake(s)
    s = s.lower().strip()
    s = s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    parts = re.split(r"[\s/,]+", s)
    # Remove parentheses content kept as token for Wien (12)
    tokens = []
    for p in parts:
        p = re.sub(r"^\(|\)$", "", p).strip()
        if p and len(p) >= 2 and p not in _CITY_STOPWORDS:
            tokens.append(p)
    return set(tokens)


def _plz_digits_only(plz_val: str) -> str:
    """Return digits-only part of PLZ (strip A-, D-, etc.)."""
    if not plz_val:
        return ""
    s = str(plz_val).strip().replace(".0", "")
    m = re.search(r"[A-Z]+-\s*(\d{4,5})\b", s, re.IGNORECASE)
    if m:
        return m.group(1)
    return re.sub(r"\D", "", s) or s


def _city_matches(ort_db_val: str, addr: str) -> bool:
    """Token-based city match so e.g. Innsbruck/Neu Rum and Rum/Innsbruck match the same address."""
    tokens = _city_tokens(ort_db_val)
    if not tokens or len(ort_db_val) < 3:
        return False
    if all(t in addr for t in tokens):
        return True
    ort_norm = _normalize_city(ort_db_val)
    if ort_norm and ort_norm in addr:
        return True
    if "wien" in (ort_norm or ""):
        district = re.search(r"\d+", ort_norm)
        if district:
            return "wien" in addr and district.group(0) in addr
    return False


def load_data():
    global _excel_cache
    if _excel_cache is None:
        if os.path.exists(EXCEL_PATH):
            try:
                _excel_cache = pd.read_excel(EXCEL_PATH, engine="pyxlsb")
                # Pre-process: ensure PLZ is clean string
                if "Postleitzahl" in _excel_cache.columns:
                    _excel_cache["Postleitzahl"] = _excel_cache["Postleitzahl"].astype(str).str.replace(".0", "", regex=False).str.strip()
                # Fill NaNs
                _excel_cache = _excel_cache.fillna("")
                print(f"Loaded {len(_excel_cache)} customer records from Excel.")
            except Exception as e:
                print(f"Error loading Excel data: {e}")
        else:
                print(f"Excel file not found at {EXCEL_PATH}")
    return _excel_cache

def _filter_by_verband(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """
    Filter: only consider rows whose Verband is in VERBAND_FILTER (e.g. 27750, 29000, 30000).
    If the column is missing, we cannot enforce the requirement -> return None.
    """
    if df is None:
        return None
    if "Verband" not in df.columns:
        return None
    numeric_verband = pd.to_numeric(df["Verband"], errors="coerce")
    mask = numeric_verband.isin(VERBAND_FILTER)
    return df[mask]

def load_iln_data():
    global _iln_cache
    if _iln_cache is None:
        if os.path.exists(ILN_EXCEL_PATH):
            try:
                _iln_cache = pd.read_excel(ILN_EXCEL_PATH)
                # Fill NaNs
                _iln_cache = _iln_cache.fillna("")
                print(f"Loaded {len(_iln_cache)} ILN records from Excel.")
            except Exception as e:
                print(f"Error loading ILN Excel data: {e}")
        else:
            print(f"ILN Excel file not found at {ILN_EXCEL_PATH}")
    return _iln_cache


def _extract_plz_from_address(address_str: str) -> str:
    if not address_str:
        return ""
    plz_match = re.search(r"[A-Z]+-\s*(\d{4,5})\b", address_str, re.IGNORECASE)
    if plz_match:
        return plz_match.group(1)
    all_matches = re.findall(r"\b(\d{4,5})\b", address_str)
    if all_matches:
        return max(all_matches, key=lambda x: (len(x) == 5, len(x)))
    return ""


def _normalize_loose_alnum(text: str) -> str:
    if not isinstance(text, str):
        return ""
    text = _fix_mojibake(text).lower()
    text = text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return " ".join(re.findall(r"[a-z0-9]+", text))


def _extract_house_number_tokens(text: str) -> Set[str]:
    if not isinstance(text, str):
        return set()
    text = _fix_mojibake(text).lower()
    text = text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return set(re.findall(r"\b\d{1,4}[a-z]?\b", text))


def _street_tokens(text: str) -> List[str]:
    if not isinstance(text, str):
        return []
    s = _fix_mojibake(text).lower()
    s = s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    toks = re.findall(r"[a-z0-9]+", s)
    stop = {"blvd", "str", "strasse", "street", "ul", "ulitsa", "evropa"}
    return [t for t in toks if len(t) >= 3 and t not in stop]


def _token_coverage_score(row_tokens: List[str], input_tokens: List[str]) -> float:
    if not row_tokens or not input_tokens:
        return 0.0
    matched = 0
    for rt in row_tokens:
        best = 0.0
        for it in input_tokens:
            if rt == it:
                best = 1.0
                break
            sim = SequenceMatcher(None, rt, it).ratio()
            if sim > best:
                best = sim
        if best >= 0.84:
            matched += 1
    return matched / len(row_tokens)


def _clean_kdnr(value: Any) -> str:
    s = str(value).replace(".0", "").strip()
    return s.lstrip("0") or s


def _kdnr_sort_value(value: Any) -> int:
    cleaned = _clean_kdnr(value)
    digits = re.sub(r"\D", "", cleaned)
    if not digits:
        return 10**9
    try:
        return int(digits)
    except ValueError:
        return 10**9


def find_momax_bg_customer_by_address(
    address_str: str,
    warnings: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """
    momax_bg-only customer lookup constrained to a fixed Kundennummer allowlist.
    Match by address/street with typo-tolerant fallback.
    """
    df = load_data()
    if df is None or not address_str or not address_str.strip():
        return None
    if "Adressnummer" not in df.columns or "Kundennummer" not in df.columns:
        return None

    subset = df[
        df["Adressnummer"].astype(str).str.replace(".0", "", regex=False).str.strip() == "0"
    ]
    subset = _filter_by_verband(subset)
    if subset is None or subset.empty:
        return None

    subset = subset[
        subset["Kundennummer"]
        .astype(str)
        .str.replace(".0", "", regex=False)
        .str.strip()
        .apply(_clean_kdnr)
        .isin({_clean_kdnr(v) for v in MOMAX_BG_ALLOWED_KUNDENNUMMERN})
    ]
    if subset.empty:
        return None

    address_str = address_str.strip()
    addr_clean = _normalize_address_token(address_str)
    input_plz = _extract_plz_from_address(address_str)
    input_street_loose = _normalize_loose_alnum(address_str)
    input_house_tokens = _extract_house_number_tokens(address_str)

    candidates: List[Dict[str, Any]] = []
    for _, row in subset.iterrows():
        strasse_db = str(row.get("Strasse", ""))
        ort_db = str(row.get("Ort", ""))
        if len(strasse_db) < 3 or len(ort_db) < 3:
            continue

        strasse_clean = _normalize_address_token(strasse_db)
        ort_clean = _normalize_city(ort_db)
        city_match = bool(ort_clean and (ort_clean in addr_clean or _city_matches(ort_db, addr_clean)))
        if not city_match:
            continue

        street_matches = bool(
            strasse_clean in addr_clean
            or (strasse_clean.startswith("am") and len(strasse_clean) > 2 and strasse_clean[2:] in addr_clean)
        )

        row_street_loose = _normalize_loose_alnum(strasse_db)
        fuzzy_score = 0.0
        if fuzz is not None and input_street_loose and row_street_loose:
            fuzzy_score = float(fuzz.token_set_ratio(input_street_loose, row_street_loose))

        row_house_tokens = _extract_house_number_tokens(strasse_db)
        house_match = bool(
            row_house_tokens
            and input_house_tokens
            and not row_house_tokens.isdisjoint(input_house_tokens)
        )

        row_tokens = _street_tokens(strasse_db)
        input_tokens = _street_tokens(address_str)
        token_coverage = _token_coverage_score(row_tokens, input_tokens)

        fuzzy_accept = bool(
            not street_matches
            and fuzz is not None
            and (fuzzy_score >= 78.0 or (house_match and fuzzy_score >= 70.0))
        )
        token_accept = bool(
            not street_matches
            and token_coverage >= 0.75
            and (house_match or not row_house_tokens)
        )

        if not street_matches and not fuzzy_accept and not token_accept:
            continue

        plz_db = _plz_digits_only(str(row.get("Postleitzahl", "")).replace(".0", "").strip())
        plz_exact = bool(input_plz and plz_db == input_plz)

        rank_score = fuzzy_score if fuzz is not None else (token_coverage * 100.0)

        candidates.append(
            {
                "row": row,
                "strict": street_matches,
                "plz_exact": plz_exact,
                "house_match": house_match,
                "fuzzy_score": rank_score,
                "kdnr_sort": _kdnr_sort_value(row.get("Kundennummer", "")),
            }
        )

    if not candidates:
        return None

    candidates.sort(
        key=lambda c: (
            0 if c["strict"] else 1,
            0 if c["plz_exact"] else 1,
            0 if c["house_match"] else 1,
            -c["fuzzy_score"],
            c["kdnr_sort"],
        )
    )
    best_match = candidates[0]["row"]
    return {
        "kundennummer": str(best_match.get("Kundennummer", "")).replace(".0", "").strip(),
        "adressnummer": str(best_match.get("Adressnummer", "")).replace(".0", "").strip(),
        "tour": str(best_match.get("Tour", "")).strip(),
    }

def find_customer_by_address(
    address_str: str,
    kundennummer: Optional[str] = None,
    kom_name: Optional[str] = None,
    is_joop: bool = False,
    client_hint: str = "",
    iln_company: Optional[str] = None,
    iln_filiale_hint: Optional[str] = None,
    warnings: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    df = load_data()
    if df is None:
        return None

    def _clean_num(value: Any) -> str:
        s = str(value).replace(".0", "").strip()
        return s.lstrip("0") or s

    def _match_by_kundennummer_fallback(kdnr: str) -> Optional[Dict[str, Any]]:
        if not kdnr:
            return None

        kdnr_clean = _clean_num(kdnr)
        if "Kundennummer" not in df.columns:
            return None

        mask = (
            df["Kundennummer"]
            .astype(str)
            .str.replace(".0", "", regex=False)
            .str.strip()
            .apply(_clean_num)
            == kdnr_clean
        )
        kdn_subset = df[mask]
        kdn_subset = _filter_by_verband(kdn_subset)
        if kdn_subset is None or kdn_subset.empty:
            return None

        # Prefer main customer row (Adressnummer == 0) for Tour; fallback to any row if none.
        if "Adressnummer" in kdn_subset.columns:
            adr_zero = kdn_subset[
                kdn_subset["Adressnummer"].astype(str).str.replace(".0", "", regex=False).str.strip() == "0"
            ]
            if not adr_zero.empty:
                best = adr_zero.iloc[0]
            else:
                best = kdn_subset.iloc[0]
        else:
            best = kdn_subset.iloc[0]

        return {
            "kundennummer": str(best.get("Kundennummer", "")).replace(".0", ""),
            "adressnummer": str(best.get("Adressnummer", "")).replace(".0", ""),
            "tour": str(best.get("Tour", "")),
        }

    if not address_str or not address_str.strip():
        # Allow lookup purely by kundennummer when address is missing.
        return _match_by_kundennummer_fallback(kundennummer) if kundennummer else None

    address_str = address_str.strip()
    addr_clean = _normalize_address_token(address_str)
    if iln_company:
        addr_clean = addr_clean + _normalize_address_token(iln_company)
    
    # Step 1: Strict Address Matching (Street AND City)
    # We require 100% containment of the excel Street and City in the input address
    
    valid_candidates = []
    
    # Scan logic (vectorized or iteration). Iteration is safest for custom logic.
    # We filter first by primitive checks to speed up
    
    # Try to extract PLZ for fast filtering (optional but helps performance)
    # Extract PLZ - handle formats like "RO-300645", "D-75177", "A-4490", or just "75177"
    # Normalize country codes (e.g., "RO-300645" → "300645") and use exact matching
    plz = None
    # First try: match country code format (RO-300645, D-75177, etc.) - one or more letters
    plz_match = re.search(r"[A-Z]+-\s*(\d{4,5})\b", address_str, re.IGNORECASE)
    if plz_match:
        # Extract just the digits (normalize "RO-300645" → "300645")
        plz = plz_match.group(1)
    else:
        # Fallback: match standalone 4-5 digit numbers (but prefer longer ones)
        # This handles cases where PLZ doesn't have country prefix
        all_matches = re.findall(r"\b(\d{4,5})\b", address_str)
        if all_matches:
            # Prefer 5-digit codes (German postal codes are 5 digits)
            # If multiple matches, take the longest one that's 4-5 digits
            plz = max(all_matches, key=lambda x: (len(x) == 5, len(x)))
    
    # Filter by Adressnummer == 0 FIRST (before any matching).
    subset = df[df["Adressnummer"].astype(str).str.replace(".0", "", regex=False).str.strip() == "0"]

    subset = _filter_by_verband(subset)
    if subset is None:
        return None

    # Optional PLZ pre-filter per spec: if we have PLZ, narrow subset; if result empty, keep full subset
    if plz and "Postleitzahl" in subset.columns:
        plz_mask = subset["Postleitzahl"].astype(str).apply(
            lambda x: _plz_digits_only(str(x).replace(".0", "").strip()) == plz
        )
        subset_plz = subset[plz_mask]
        if not subset_plz.empty:
            subset = subset_plz

    candidates = []
    for _, row in subset.iterrows():
        strasse_db = str(row.get("Strasse", ""))
        ort_db = str(row.get("Ort", ""))
        
        # Skip empty
        if len(strasse_db) < 3 or len(ort_db) < 3:
            continue
            
        strasse_clean = _normalize_address_token(strasse_db)
        ort_clean = _normalize_city(ort_db)
        
        # Street containment (human-like: Str./Straße, spaces, hyphens normalized)
        # Allow match when DB has "Am X" and input has "X" (e.g. ILN gives "Wasserwerk 4", Primex has "Am Wasserwerk 4")
        street_matches = (
            strasse_clean in addr_clean
            or (strasse_clean.startswith("am") and len(strasse_clean) > 2 and strasse_clean[2:] in addr_clean)
        )
        if not street_matches:
            continue
        # City: token-based or normalized containment or Wien (12)
        if not (ort_clean in addr_clean or _city_matches(ort_db, addr_clean)):
            continue
        # Do not skip when PLZ differs; we accept match on Strasse+Ort and will prefer PLZ match later / warn
        candidates.append(row)

    if not candidates and fuzz is not None:
        # Fuzzy fallback: token_set_ratio; PLZ match +20; threshold 70 (with PLZ) or 85 (without)
        input_str = addr_clean + (" " + plz if plz else "")
        threshold = 70 if plz else 85
        for _, row in subset.iterrows():
            strasse_db = str(row.get("Strasse", ""))
            ort_db = str(row.get("Ort", ""))
            if len(strasse_db) < 3 or len(ort_db) < 3:
                continue
            plz_db = _plz_digits_only(str(row.get("Postleitzahl", "")).replace(".0", "").strip())
            row_str = _normalize_address_token(strasse_db) + " " + _normalize_city(ort_db) + (" " + plz_db if plz_db else "")
            score = fuzz.token_set_ratio(input_str, row_str)
            if plz and plz_db == plz:
                score += 20
            if score >= threshold:
                candidates.append(row)

    if not candidates:
        return _match_by_kundennummer_fallback(kundennummer) if kundennummer else None

    # Convert to DataFrame for easier filtering
    cand_df = pd.DataFrame(candidates)

    # Prefer candidates with matching PLZ when input had PLZ (keep all if none match)
    if plz and not cand_df.empty:
        plz_match_mask = cand_df["Postleitzahl"].astype(str).apply(
            lambda x: _plz_digits_only(str(x).replace(".0", "").strip()) == plz
        )
        plz_matched = cand_df[plz_match_mask]
        if not plz_matched.empty:
            cand_df = plz_matched

    # Step 2a: ILN company / Gesellschaft match (when multiple candidates and iln_company from ILN row)
    company_matched_candidates = cand_df
    if iln_company and len(cand_df) > 1:
        def _company_tokens(t: str) -> set:
            if not isinstance(t, str):
                return set()
            t = _normalize_address_token(t)
            return set(re.findall(r"[a-z0-9]+", t)) - {"gmbh", "co", "kg", "und"}

        iln_tokens = _company_tokens(iln_company)
        if iln_tokens:
            def score_company(row) -> int:
                n1 = str(row.get("Name1", ""))
                n2 = str(row.get("Name2", ""))
                cand_tokens = _company_tokens(n1) | _company_tokens(n2)
                overlap = len(iln_tokens & cand_tokens)
                if overlap > 0:
                    return overlap * 10 + sum(1 for t in iln_tokens if any(t in c for c in cand_tokens))
                return 0

            scores = cand_df.apply(score_company, axis=1)
            best = int(scores.max()) if not scores.empty else 0
            if best > 0:
                company_matched_candidates = cand_df[scores == best]

    # Step 2a-bis: ILN filiale/branch hint (e.g. "Neubert" in Filial-Lagerkürzel -> prefer Primex "Neubert GmbH")
    filiale_matched_candidates = company_matched_candidates
    if iln_filiale_hint and isinstance(iln_filiale_hint, str) and iln_filiale_hint.strip() and len(company_matched_candidates) > 1:
        def _get_tokens(t: str) -> list:
            if not isinstance(t, str):
                return []
            parts = re.split(r"[^a-z0-9äöüß]+", t.lower())
            stop = {"gmbh", "co", "kg", "und", "der", "die", "das"}
            return [p for p in parts if len(p) >= 3 and p not in stop]

        filiale_tokens = set(_get_tokens(iln_filiale_hint.strip()))
        if filiale_tokens:
            def score_filiale(row) -> int:
                n1 = str(row.get("Name1", ""))
                n2 = str(row.get("Name2", ""))
                cand_tokens = _get_tokens(n1) + _get_tokens(n2)
                matched = set()
                for t in cand_tokens:
                    if not t:
                        continue
                    if t in filiale_tokens:
                        matched.add(t)
                        continue
                    if len(t) >= 4 and any(ft.endswith(t) for ft in filiale_tokens):
                        matched.add(t)
                return sum(len(t) for t in matched)

            scores_f = company_matched_candidates.apply(score_filiale, axis=1)
            best_f = int(scores_f.max()) if not scores_f.empty else 0
            if best_f > 0:
                filiale_matched_candidates = company_matched_candidates[scores_f == best_f]

    # Step 2b: Client Hint Context (Name Match)
    # Filter candidates where Name1/Name2 matches the client_hint (e.g. "xxxlutz")
    name_matched_candidates = filiale_matched_candidates
    hint_text = " ".join([client_hint or "", kom_name or ""]).strip()
    if hint_text:
        hint_lower = hint_text.lower()
        # Score candidates by how many (and how specific) Name1/Name2 tokens appear in the hint.
        # This avoids the common failure mode where a generic token like "lutz" matches multiple rows.

        def get_tokens(text):
            if not isinstance(text, str):
                return []
            parts = re.split(r"[^a-z0-9äöüß]+", text.lower())
            stop = {"gmbh", "co", "kg", "und", "der", "die", "das"}
            return [p for p in parts if len(p) >= 3 and p not in stop]

        hint_tokens = set(get_tokens(hint_lower))

        def score_hint(row) -> int:
            tokens = get_tokens(str(row.get("Name1", ""))) + get_tokens(str(row.get("Name2", "")))
            matched = set()
            for t in tokens:
                if not t:
                    continue
                if t in hint_tokens:
                    matched.add(t)
                    continue
                # Allow a safe "suffix" match (e.g. hint token "xxxlutz" should match candidate token "lutz"),
                # but avoid short/generic tokens like "xxx".
                if len(t) >= 4 and any(ht.endswith(t) for ht in hint_tokens):
                    matched.add(t)
            # Weight by token length so "bopfingen" beats "lutz" when both match.
            return sum(len(t) for t in matched)

        scores = filiale_matched_candidates.apply(score_hint, axis=1)
        best_score = int(scores.max()) if not scores.empty else 0
        if best_score > 0:
            matches = filiale_matched_candidates[scores == best_score]
            if not matches.empty:
                name_matched_candidates = matches
        # If no matches, we keep the strict list (maybe hint was wrong or just generic email)

    # Step 3: JOOP Selection
    # If is_joop -> prefer "-Jo-"
    # If not is_joop -> prefer NOT "-Jo-"
    
    final_candidates = name_matched_candidates
    
    def has_joop(row):
        n1 = str(row.get("Name1", "")).lower()
        n2 = str(row.get("Name2", "")).lower()
        return "-jo-" in n1 or "-jo-" in n2 or n1.endswith("-jo") or n2.endswith("-jo")
        
    joop_matches = name_matched_candidates[name_matched_candidates.apply(has_joop, axis=1)]
    non_joop_matches = name_matched_candidates[~name_matched_candidates.apply(has_joop, axis=1)]
    
    if is_joop:
        if not joop_matches.empty:
            final_candidates = joop_matches
        else:
            # If we want JOOP but found none, we take what we have (best effort)
            pass
    else:
        if not non_joop_matches.empty:
            final_candidates = non_joop_matches
        else:
            # If we want standard but only found JOOP, we take what we have
            pass

    # Step 3.5: Prefer "Einrichtungshaus" in Name2 (over e.g. Hauptverwaltung) when multiple candidates remain
    if len(final_candidates) > 1:
        einrichtungshaus_mask = final_candidates["Name2"].astype(str).str.lower().str.contains("einrichtungshaus", regex=False, na=False)
        einrichtungshaus_candidates = final_candidates[einrichtungshaus_mask]
        if not einrichtungshaus_candidates.empty:
            final_candidates = einrichtungshaus_candidates

    # Step 4: Final Selection (Tie-Breaker)
    if final_candidates.empty:
        return None

    best_match = final_candidates.iloc[0]
    adr_match = str(best_match.get("Adressnummer", "")).replace(".0", "").strip()
    if adr_match != "0":
        return None

    # Warn when match is not 100% identical (e.g. PLZ differs)
    if warnings is not None and plz:
        plz_match = _plz_digits_only(str(best_match.get("Postleitzahl", "")).replace(".0", "").strip())
        if plz_match != plz:
            warnings.append(
                f"Customer match is not 100% identical: Postleitzahl differs (input: {plz}, Excel: {plz_match}). Please verify."
            )

    return {
        "kundennummer": str(best_match["Kundennummer"]).replace(".0", ""),
        "adressnummer": str(best_match["Adressnummer"]).replace(".0", ""),
        "tour": str(best_match["Tour"])
    }



def find_iln_by_address(address_str: str) -> Optional[str]:
    """Find ILN number based on address (Strasse and Ort) from the ILN Excel."""
    df = load_iln_data()
    if df is None or not address_str:
        return None

    address_str = address_str.strip()
    addr_clean = _normalize_address_token(address_str)
    
    plz = None
    plz_match = re.search(r"[A-Z]+-\s*(\d{4,5})\b", address_str, re.IGNORECASE)
    if plz_match:
        plz = plz_match.group(1)
    else:
        plz_match = re.search(r"\b(\d{4,5})\b", address_str)
        plz = plz_match.group(1) if plz_match else None

    scored_candidates = []
    for _, row in df.iterrows():
        strasse_db = str(row.get("Straße", row.get("Strasse", "")))
        ort_db = str(row.get("Ort", ""))
        plz_db = _plz_digits_only(str(row.get("PLZ", "")))
        
        strasse_clean_db = _normalize_address_token(strasse_db)
        ort_clean_db = _normalize_city(ort_db)
        
        score = 0
        if strasse_clean_db and strasse_clean_db in addr_clean:
            score += 40
        if ort_clean_db and (ort_clean_db in addr_clean or _city_matches(ort_db, addr_clean)):
            score += 30
        if plz and plz == plz_db:
            score += 20

        if score >= 60:
            scored_candidates.append((score, row))

    if not scored_candidates:
        return None

    # Sort by score descending
    scored_candidates.sort(key=lambda x: x[0], reverse=True)
    best_match = scored_candidates[0][1]

    iln_val = str(best_match.get("ILN", ""))
    # Clean up ILN (remove .0 if it's a float-looking string)
    if iln_val.endswith(".0"):
        iln_val = iln_val[:-2]
    return iln_val


def find_address_by_iln(iln_value: str) -> Optional[Dict[str, str]]:
    """
    Find address details based on ILN number from the ILN Excel.
    
    Args:
        iln_value: The ILN number to look up (e.g., '9007019012285')
    
    Returns:
        Dict with keys: 'strasse', 'plz', 'ort', 'formatted_address'
        Returns None if ILN not found or Excel not loaded.
    """
    df = load_iln_data()
    if df is None or not iln_value:
        return None
    
    # Clean the ILN value
    iln_clean = str(iln_value).strip().replace(".0", "")
    if not iln_clean:
        return None
    
    # Look for exact match in ILN column (Column B)
    try:
        # Try exact match first
        mask = df["ILN"].astype(str).str.replace(".0", "", regex=False).str.strip() == iln_clean
        matches = df[mask]
        
        if matches.empty:
            return None
        
        # Take the first match (should be unique but just in case)
        match = matches.iloc[0]
        
        # Extract address components (ILN column may be "Straße" or "Strasse")
        strasse = str(match.get("Straße", match.get("Strasse", ""))).strip()
        plz_raw = str(match.get("PLZ", "")).replace(".0", "").strip()
        plz = _plz_digits_only(plz_raw) or plz_raw
        ort = str(match.get("Ort", "")).strip()
        
        # Company/branch for Kundennummer disambiguation: concatenate all so Filiale/Lager (e.g. "Kröger") is included
        parts = []
        for col in ("Gesellschaft", "Filialträger", "Filiale/Lager"):
            val = match.get(col, "")
            if isinstance(val, str) and val.strip():
                parts.append(val.strip())
        company = " ".join(parts) if parts else ""
        
        # Branch/filiale description (e.g. "Neubert (inkl. Hausleger)...") for preferring matching Primex Name1/Name2
        filiale_hint = ""
        for col in ("Filial-Lagerkürzel", "Filial Lagerkürzel", "Filiale", "Filial-Lager"):
            if col in df.columns:
                val = match.get(col, "")
                if isinstance(val, str) and val.strip():
                    filiale_hint = val.strip()
                    break
        
        # Validate we have the essential components
        if not strasse or not ort:
            return None
        
        # Format address as: Straße\nPLZ Ort (keep original PLZ format for display if preferred)
        formatted_address = f"{strasse}\n{plz_raw} {ort}" if plz_raw else f"{strasse}\n{plz} {ort}"
        
        result: Dict[str, str] = {
            "strasse": strasse,
            "plz": plz,
            "ort": ort,
            "formatted_address": formatted_address
        }
        if company:
            result["company"] = company
        if filiale_hint:
            result["filiale_hint"] = filiale_hint
        return result
    
    except Exception as e:
        print(f"Error looking up ILN {iln_value}: {e}")
        return None


def find_kundennummer_by_iln(iln_value: str) -> Optional[str]:
    """
    Return a Kundennummer for the given ILN if it can be derived and verified in Primex.
    ILN Excel has no Kundennummer column; we derive candidate from ILN number (e.g. last 5 digits)
    and only return it if that Kundennummer exists in Primex (Verband filter).
    """
    df_primex = load_data()
    if df_primex is None or not iln_value:
        return None
    iln_clean = str(iln_value).strip().replace(".0", "")
    if not iln_clean:
        return None
    # If ILN Excel had a Kundennummer column we would use it here
    # Derive candidate from ILN number: last 5 digits (e.g. 40065920000027566 -> 27566)
    digits = re.sub(r"\D", "", iln_clean)
    if len(digits) < 4:
        return None
    candidate = digits[-5:] if len(digits) >= 5 else digits
    candidate_stripped = candidate.lstrip("0") or candidate
    if not candidate_stripped:
        return None
    if "Kundennummer" not in df_primex.columns:
        return None
    def _clean_num(value: Any) -> str:
        s = str(value).replace(".0", "").strip()
        return s.lstrip("0") or s
    mask = (
        df_primex["Kundennummer"]
        .astype(str)
        .str.replace(".0", "", regex=False)
        .str.strip()
        .apply(_clean_num)
        == _clean_num(candidate)
    )
    subset = df_primex[mask]
    subset = _filter_by_verband(subset)
    if subset is None or subset.empty:
        return None
    # Return in same format as Primex (leading zeros as in first row)
    first = subset.iloc[0]
    kdnr = str(first.get("Kundennummer", "")).replace(".0", "").strip()
    return kdnr if kdnr else None
