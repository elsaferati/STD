from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from config import Config
from normalize import (
    apply_momax_bg_strict_item_code_corrections,
    refresh_missing_warnings,
)
import xml_exporter


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _stable_dump(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _is_momax_bg_record(data: dict[str, Any]) -> bool:
    header = data.get("header")
    if isinstance(header, dict):
        kom_name = header.get("kom_name")
        if isinstance(kom_name, dict) and str(kom_name.get("derived_from") or "") == "momax_bg_policy":
            return True

    warnings = data.get("warnings")
    if isinstance(warnings, list):
        for warning in warnings:
            text = str(warning or "").lower()
            if "selected=momax_bg" in text:
                return True
    return False


def _match_only_id(path: Path, data: dict[str, Any], only_ids: set[str]) -> bool:
    if not only_ids:
        return True
    header = data.get("header")
    ticket_number = ""
    kom_nr = ""
    if isinstance(header, dict):
        ticket = header.get("ticket_number")
        kom = header.get("kom_nr")
        if isinstance(ticket, dict):
            ticket_number = str(ticket.get("value") or "").strip()
        else:
            ticket_number = str(ticket or "").strip()
        if isinstance(kom, dict):
            kom_nr = str(kom.get("value") or "").strip()
        else:
            kom_nr = str(kom or "").strip()

    candidates = {path.stem, ticket_number, kom_nr}
    return any(candidate in only_ids for candidate in candidates if candidate)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill MOMAX BG strict artikelnummer/modellnummer corrections and regenerate XML."
    )
    parser.add_argument("dir", type=Path, help="Directory containing JSON files (e.g. output)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show changes without writing JSON/XML files.",
    )
    parser.add_argument(
        "--only-id",
        action="append",
        default=[],
        help="Only process matching order id (file stem, ticket_number, or kom_nr). Repeatable.",
    )
    args = parser.parse_args()

    root = args.dir
    if not root.exists() or not root.is_dir():
        raise SystemExit(f"Not a directory: {root}")

    only_ids = {str(value).strip() for value in args.only_id if str(value).strip()}
    config = Config.from_env()

    scanned = filtered = skipped_non_momax = changed = updated = errors = 0
    for path in sorted(root.glob("*.json")):
        scanned += 1
        data = _load_json(path)
        if data is None:
            errors += 1
            continue

        id_match = _match_only_id(path, data, only_ids)
        if not id_match:
            filtered += 1
            continue
        is_momax_bg = _is_momax_bg_record(data)
        forced_by_only_id = bool(only_ids) and id_match and (not is_momax_bg)
        if not is_momax_bg and not forced_by_only_id:
            skipped_non_momax += 1
            continue
        if forced_by_only_id:
            print(f"[forced] {path.name}: processing due to --only-id override")

        before = _stable_dump(data)
        try:
            corrected_lines = apply_momax_bg_strict_item_code_corrections(data)
            refresh_missing_warnings(data)
        except Exception as exc:
            print(f"[error] {path.name}: correction failed: {exc}")
            errors += 1
            continue
        after = _stable_dump(data)

        if after == before:
            continue

        changed += 1
        print(f"[changed] {path.name}: corrected_lines={corrected_lines}")
        if args.dry_run:
            continue

        try:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            xml_exporter.export_xmls(data, path.stem, config, root)
            updated += 1
        except Exception as exc:
            print(f"[error] {path.name}: write/export failed: {exc}")
            errors += 1

    print(
        "scanned={scanned} filtered={filtered} skipped_non_momax={skipped_non_momax} "
        "changed={changed} updated={updated} errors={errors} dry_run={dry}".format(
            scanned=scanned,
            filtered=filtered,
            skipped_non_momax=skipped_non_momax,
            changed=changed,
            updated=updated,
            errors=errors,
            dry=args.dry_run,
        )
    )
    return 0 if errors == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
