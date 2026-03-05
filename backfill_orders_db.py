from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

from dotenv import load_dotenv

from config import Config
from db import init_db
import order_store


def _load_json(path: Path) -> dict:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"Skipping {path.name}: {exc}")
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _flag_true(entry) -> bool:
    if isinstance(entry, dict):
        entry = entry.get("value")
    if entry is True:
        return True
    return str(entry).strip().lower() == "true"


def run_backfill() -> int:
    load_dotenv()
    config = Config.from_env()
    init_db()

    output_dir = config.output_dir
    files = sorted(output_dir.glob("*.json"), key=lambda item: item.name)
    if not files:
        print(f"No JSON files found in {output_dir}")
        return 0

    file_status = Counter()
    file_reply = 0
    file_human = 0
    file_post = 0
    imported = 0

    for path in files:
        payload = _load_json(path)
        if not payload:
            continue
        try:
            persisted = order_store.upsert_order_payload(
                payload,
                external_message_id=str(payload.get("message_id") or path.stem),
                change_type="ingested",
            )
            order_store.register_order_files(
                order_id=persisted["order_id"],
                revision_id=persisted.get("revision_id"),
                file_type="json",
                storage_paths=[str(path)],
            )
            imported += 1
        except Exception as exc:  # noqa: BLE001
            print(f"Failed to import {path.name}: {exc}")
            continue

        status = order_store.derive_status(payload)
        file_status[status] += 1
        header = payload.get("header") if isinstance(payload.get("header"), dict) else {}
        if _flag_true(header.get("reply_needed")):
            file_reply += 1
        if _flag_true(header.get("human_review_needed")):
            file_human += 1
        if _flag_true(header.get("post_case")):
            file_post += 1

    db_orders = order_store.list_order_summaries()
    db_status = Counter(order_store.normalize_status(row.get("status")) for row in db_orders)
    db_reply = sum(1 for row in db_orders if row.get("reply_needed"))
    db_human = sum(1 for row in db_orders if row.get("human_review_needed"))
    db_post = sum(1 for row in db_orders if row.get("post_case"))

    parity = {
        "files_total": imported,
        "db_total": len(db_orders),
        "files_status_counts": dict(file_status),
        "db_status_counts": dict(db_status),
        "files_reply_needed": file_reply,
        "db_reply_needed": db_reply,
        "files_human_review_needed": file_human,
        "db_human_review_needed": db_human,
        "files_post_case": file_post,
        "db_post_case": db_post,
    }

    report_path = output_dir / "backfill_parity_report.json"
    report_path.write_text(json.dumps(parity, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(parity, ensure_ascii=False, indent=2))
    print(f"Parity report written to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_backfill())
