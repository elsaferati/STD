from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from normalize import refresh_missing_warnings


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _stable_dump(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill items[*].furncloud_id from program.furncloud_id and refresh warnings/status."
    )
    parser.add_argument("dir", type=Path, help="Directory containing JSON files (e.g. output)")
    args = parser.parse_args()

    root = args.dir
    if not root.exists() or not root.is_dir():
        raise SystemExit(f"Not a directory: {root}")

    scanned = updated = skipped = errors = 0
    for path in sorted(root.glob("*.json")):
        scanned += 1
        data = _load_json(path)
        if data is None:
            errors += 1
            continue

        before = _stable_dump(data)
        try:
            refresh_missing_warnings(data)
        except Exception:
            errors += 1
            continue
        after = _stable_dump(data)

        if after == before:
            skipped += 1
            continue

        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        updated += 1

    print(f"scanned={scanned} updated={updated} skipped={skipped} errors={errors}")
    return 0 if errors == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())

