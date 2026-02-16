import argparse

import pandas as pd

import lookup


def _normalize(s: str) -> str:
    if not isinstance(s, str):
        return ""
    s = s.strip().lower()
    s = s.replace("Ã¤", "ae").replace("Ã¶", "oe").replace("Ã¼", "ue").replace("ÃŸ", "ss")
    s = (
        s.replace("straÃŸe", "str")
        .replace("strasse", "str")
        .replace("strase", "str")
        .replace("strabe", "str")
        .replace("str.", "str")
    )
    return s.replace(" ", "").replace("-", "")


def main() -> int:
    ap = argparse.ArgumentParser(description="Show which customer row lookup.find_customer_by_address would pick.")
    ap.add_argument("--address", required=True, help="Full address string (can include newlines).")
    ap.add_argument("--client-hint", default="", help="Optional hint string (e.g. sender email/domain).")
    ap.add_argument("--is-joop", action="store_true", help="Prefer JOOP entries when multiple candidates exist.")
    ap.add_argument("--limit", type=int, default=10, help="How many matching candidates to print.")
    args = ap.parse_args()

    df = lookup.load_data()
    if df is None:
        print("Could not load Excel data.")
        return 2

    address_str = args.address.strip()
    addr_clean = _normalize(address_str)

    # Extract PLZ similarly to lookup.find_customer_by_address
    import re

    plz = None
    plz_match = re.search(r"[A-Z]-\s*(\d{4,5})\b", address_str, re.IGNORECASE)
    if plz_match:
        plz = plz_match.group(1)
    else:
        all_matches = re.findall(r"\b(\d{4,5})\b", address_str)
        if all_matches:
            plz = max(all_matches, key=lambda x: (len(x) == 5, len(x)))

    subset = df[df["Adressnummer"].astype(str).str.replace(".0", "", regex=False).str.strip() == "0"]
    subset = lookup._filter_by_verband(subset)
    if subset is None:
        print("Missing/invalid Verband column; strict filter returns None.")
        return 2

    if plz:
        subset = subset[subset["Postleitzahl"].astype(str).str.replace(".0", "", regex=False).str.strip() == plz]

    candidates = []
    for _, row in subset.iterrows():
        strasse_db = str(row.get("Strasse", ""))
        ort_db = str(row.get("Ort", ""))
        if len(strasse_db) < 3 or len(ort_db) < 3:
            continue
        if _normalize(strasse_db) in addr_clean and _normalize(ort_db) in addr_clean:
            candidates.append(row)

    cand_df = pd.DataFrame(candidates) if candidates else pd.DataFrame()

    cols = [c for c in ["Kundennummer", "Kundenbetrieb", "Name1", "Name2", "Strasse", "Ort", "Postleitzahl", "Adressnummer", "Tour", "Verband"] if c in cand_df.columns]
    print(f"PLZ extracted: {plz!r}")
    print(f"Strict address candidates: {len(cand_df)}")
    if not cand_df.empty:
        print("\nTop candidates (Excel order):")
        print(cand_df[cols].head(args.limit).to_string(index=True))

    picked = lookup.find_customer_by_address(address_str, is_joop=args.is_joop, client_hint=args.client_hint)
    print("\nlookup.find_customer_by_address result:")
    print(picked)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

