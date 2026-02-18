
from __future__ import annotations

import csv
from datetime import date, datetime, timedelta
import hmac
import io
import json
import os
from pathlib import Path
import re
from threading import Lock
import time
from typing import Any
from urllib.parse import quote

from dotenv import load_dotenv
from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from openpyxl import Workbook
from werkzeug.exceptions import HTTPException

from config import Config
from normalize import refresh_missing_warnings
import xml_exporter

load_dotenv()
config = Config.from_env()
OUTPUT_DIR = config.output_dir

app = Flask(__name__)

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
REPLY_EMAIL_TO = (os.getenv("REPLY_EMAIL_TO") or "").strip() or "00primex.eu@gmail.com"
REPLY_EMAIL_BODY = (
    (os.getenv("REPLY_EMAIL_BODY") or "").strip()
    or "Please send the order with furnplan or make the order with 2 positions."
)

DASHBOARD_TOKEN = (os.getenv("DASHBOARD_TOKEN") or "").strip()
_RAW_ALLOWED_ORIGINS = os.getenv("DASHBOARD_ALLOWED_ORIGINS", "")
DASHBOARD_ALLOWED_ORIGINS = {
    origin.strip() for origin in _RAW_ALLOWED_ORIGINS.split(",") if origin.strip()
}
ALLOW_ANY_ORIGIN = "*" in DASHBOARD_ALLOWED_ORIGINS
API_INDEX_CACHE_TTL_SECONDS = max(
    0.5,
    float((os.getenv("API_INDEX_CACHE_TTL_SECONDS") or "3").strip()),
)

EDITABLE_HEADER_FIELDS = [
    "ticket_number",
    "kundennummer",
    "adressnummer",
    "tour",
    "kom_nr",
    "kom_name",
    "liefertermin",
    "wunschtermin",
    "bestelldatum",
    "lieferanschrift",
    "store_name",
    "store_address",
    "seller",
    "delivery_week",
    "iln",
]
EDITABLE_ITEM_FIELDS = ["artikelnummer", "modellnummer", "menge", "furncloud_id"]

VALID_STATUSES = {"ok", "partial", "failed", "unknown"}
ALLOWED_SORTS = {"received_at_desc", "received_at_asc"}
ALLOWED_DOWNLOAD_EXTENSIONS = {".xml", ".json"}

_ORDER_INDEX_CACHE: dict[str, Any] = {
    "checked_at": 0.0,
    "signature": None,
    "orders": [],
}
_ORDER_INDEX_LOCK = Lock()


def _safe_id(value: str) -> str | None:
    if not value or not _SAFE_ID_RE.match(value):
        return None
    return value


def _read_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data, None
        return {"value": data}, None
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def _entry_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {
            "value": value.get("value", ""),
            "source": value.get("source", ""),
            "confidence": value.get("confidence", ""),
            "derived_from": value.get("derived_from", ""),
        }
    return {"value": value or "", "source": "", "confidence": "", "derived_from": ""}


def _header_value(header: dict[str, Any], key: str) -> str:
    entry = header.get(key, {})
    if isinstance(entry, dict):
        return str(entry.get("value", "") or "")
    return str(entry or "")


def _is_truthy_flag(value: Any) -> bool:
    if isinstance(value, dict):
        value = value.get("value")
    if value is True:
        return True
    return str(value).lower() == "true"


def _reply_mailto(message_id: str, order_id: str, reply_case: str = "") -> str:
    subject = f"Reply needed for order {message_id or order_id}"
    reply_case_section = f"Reply case: {reply_case}\n\n" if reply_case else ""
    body = (
        f"{REPLY_EMAIL_BODY}\n\n"
        f"{reply_case_section}"
        f"Order ID: {order_id}\n"
        f"Message ID: {message_id or order_id}"
    )
    return (
        f"mailto:{REPLY_EMAIL_TO}"
        f"?subject={quote(subject)}"
        f"&body={quote(body)}"
    )


def _reply_case_from_warnings(warnings: list[str]) -> str:
    if not isinstance(warnings, list):
        return ""
    prefix = "Reply needed:"
    for warning in warnings:
        if isinstance(warning, str) and warning.startswith(prefix):
            return warning[len(prefix):].strip()
    return ""


def _manual_entry(value: str) -> dict[str, Any]:
    return {
        "value": value,
        "source": "manual",
        "confidence": 1.0 if value else 0.0,
        "derived_from": "manual_edit",
    }


def _set_manual_entry(target: dict[str, Any], field: str, value: str) -> None:
    entry = target.get(field)
    if not isinstance(entry, dict):
        target[field] = _manual_entry(value)
        return
    entry["value"] = value
    entry["source"] = "manual"
    entry["confidence"] = 1.0 if value else 0.0
    entry["derived_from"] = "manual_edit"


def _clean_form_value(value: str | None) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_status(value: Any) -> str:
    status = str(value or "unknown").strip().lower()
    if status not in VALID_STATUSES:
        return "unknown"
    return status


def _parse_received_at(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone()


def _effective_received_at(order: dict[str, Any]) -> datetime:
    parsed = _parse_received_at(order.get("received_at"))
    if parsed:
        return parsed

    mtime = order.get("mtime")
    if isinstance(mtime, datetime):
        return mtime.astimezone()

    return datetime.fromtimestamp(0).astimezone()

def _list_orders(output_dir: Path) -> list[dict[str, Any]]:
    if not output_dir.exists():
        return []
    files = sorted(
        output_dir.glob("*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    orders: list[dict[str, Any]] = []
    for path in files:
        data, error = _read_json(path)
        data = data or {}
        header = data.get("header") if isinstance(data.get("header"), dict) else {}
        warnings = data.get("warnings", [])
        errors = data.get("errors", [])
        if not isinstance(warnings, list):
            warnings = [str(warnings)]
        warnings = [str(item) for item in warnings]
        if not isinstance(errors, list):
            errors = [str(errors)]
        errors = [str(item) for item in errors]

        human_review_needed = _is_truthy_flag(header.get("human_review_needed"))
        reply_needed = _is_truthy_flag(header.get("reply_needed"))
        post_case = _is_truthy_flag(header.get("post_case"))
        reply_case = _reply_case_from_warnings(warnings)
        orders.append(
            {
                "id": path.stem,
                "file_name": path.name,
                "message_id": data.get("message_id") or path.stem,
                "received_at": data.get("received_at") or "",
                "status": _normalize_status(data.get("status")),
                "item_count": len(data.get("items", []))
                if isinstance(data.get("items"), list)
                else 0,
                "warnings_count": len(warnings),
                "errors_count": len(errors),
                "warnings": warnings,
                "errors": errors,
                "ticket_number": _header_value(header, "ticket_number"),
                "kundennummer": _header_value(header, "kundennummer"),
                "kom_nr": _header_value(header, "kom_nr"),
                "kom_name": _header_value(header, "kom_name"),
                "liefertermin": _header_value(header, "liefertermin"),
                "wunschtermin": _header_value(header, "wunschtermin"),
                "delivery_week": _header_value(header, "delivery_week"),
                "store_name": _header_value(header, "store_name"),
                "store_address": _header_value(header, "store_address"),
                "iln": _header_value(header, "iln"),
                "human_review_needed": human_review_needed,
                "reply_needed": reply_needed,
                "post_case": post_case,
                "reply_mailto": _reply_mailto(
                    data.get("message_id") or path.stem,
                    path.stem,
                    reply_case,
                )
                if reply_needed
                else "",
                "parse_error": error,
                "mtime": datetime.fromtimestamp(path.stat().st_mtime).astimezone(),
            }
        )

    return orders


def _status_counts(orders: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"ok": 0, "partial": 0, "failed": 0, "unknown": 0}
    for order in orders:
        status = _normalize_status(order.get("status"))
        counts[status] += 1
    counts["total"] = len(orders)
    return counts


def _rate(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round((count / total) * 100, 2)


def _status_breakdown(orders: list[dict[str, Any]]) -> dict[str, Any]:
    counts = _status_counts(orders)
    total = counts["total"]
    return {
        "total": total,
        "ok": counts["ok"],
        "partial": counts["partial"],
        "failed": counts["failed"],
        "unknown": counts["unknown"],
        "ok_rate": _rate(counts["ok"], total),
        "partial_rate": _rate(counts["partial"], total),
        "failed_rate": _rate(counts["failed"], total),
        "unknown_rate": _rate(counts["unknown"], total),
    }


def _build_output_signature(output_dir: Path) -> tuple[tuple[str, int, int], ...]:
    if not output_dir.exists():
        return ()
    signature: list[tuple[str, int, int]] = []
    for path in sorted(output_dir.glob("*.json"), key=lambda item: item.name):
        stat = path.stat()
        signature.append((path.name, stat.st_mtime_ns, stat.st_size))
    return tuple(signature)


def _invalidate_order_index_cache() -> None:
    with _ORDER_INDEX_LOCK:
        _ORDER_INDEX_CACHE["checked_at"] = 0.0
        _ORDER_INDEX_CACHE["signature"] = None


def _get_order_index() -> list[dict[str, Any]]:
    now = time.time()
    with _ORDER_INDEX_LOCK:
        if now - float(_ORDER_INDEX_CACHE["checked_at"]) < API_INDEX_CACHE_TTL_SECONDS:
            return list(_ORDER_INDEX_CACHE["orders"])

        signature = _build_output_signature(OUTPUT_DIR)
        if signature == _ORDER_INDEX_CACHE["signature"]:
            _ORDER_INDEX_CACHE["checked_at"] = now
            return list(_ORDER_INDEX_CACHE["orders"])

        orders = _list_orders(OUTPUT_DIR)
        _ORDER_INDEX_CACHE["checked_at"] = now
        _ORDER_INDEX_CACHE["signature"] = signature
        _ORDER_INDEX_CACHE["orders"] = orders
        return list(orders)


def _serialize_order_summary(order: dict[str, Any]) -> dict[str, Any]:
    effective_received_at = _effective_received_at(order)
    mtime = order.get("mtime")
    mtime_text = mtime.isoformat() if isinstance(mtime, datetime) else ""

    return {
        "id": order.get("id", ""),
        "file_name": order.get("file_name", ""),
        "message_id": order.get("message_id", ""),
        "received_at": order.get("received_at", ""),
        "effective_received_at": effective_received_at.isoformat(),
        "status": _normalize_status(order.get("status")),
        "item_count": int(order.get("item_count") or 0),
        "warnings_count": int(order.get("warnings_count") or 0),
        "errors_count": int(order.get("errors_count") or 0),
        "ticket_number": order.get("ticket_number", ""),
        "kundennummer": order.get("kundennummer", ""),
        "kom_nr": order.get("kom_nr", ""),
        "kom_name": order.get("kom_name", ""),
        "liefertermin": order.get("liefertermin", ""),
        "wunschtermin": order.get("wunschtermin", ""),
        "delivery_week": order.get("delivery_week", ""),
        "store_name": order.get("store_name", ""),
        "store_address": order.get("store_address", ""),
        "iln": order.get("iln", ""),
        "human_review_needed": bool(order.get("human_review_needed")),
        "reply_needed": bool(order.get("reply_needed")),
        "post_case": bool(order.get("post_case")),
        "reply_mailto": order.get("reply_mailto", ""),
        "parse_error": order.get("parse_error"),
        "mtime": mtime_text,
    }

def _parse_bool_query(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized == "":
        return None
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


def _parse_date_query(value: str | None) -> date | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    return datetime.strptime(text, "%Y-%m-%d").date()


def _api_error(status_code: int, code: str, message: str):
    return jsonify({"error": {"code": code, "message": message}}), status_code


def require_auth(req) -> Any:
    if req.method == "OPTIONS":
        return None

    if not DASHBOARD_TOKEN:
        return _api_error(500, "config_error", "DASHBOARD_TOKEN is not configured")

    authorization = (req.headers.get("Authorization") or "").strip()
    if not authorization.lower().startswith("bearer "):
        return _api_error(401, "unauthorized", "Missing or invalid Authorization header")

    token = authorization[7:].strip()
    if not token or not hmac.compare_digest(token, DASHBOARD_TOKEN):
        return _api_error(401, "unauthorized", "Invalid dashboard token")
    return None


def _is_origin_allowed(origin: str | None) -> bool:
    if not origin:
        return False
    if ALLOW_ANY_ORIGIN:
        return True
    return origin in DASHBOARD_ALLOWED_ORIGINS


def _append_vary(existing: str | None, value: str) -> str:
    if not existing:
        return value
    parts = [part.strip() for part in existing.split(",") if part.strip()]
    if value in parts:
        return ", ".join(parts)
    parts.append(value)
    return ", ".join(parts)


def _filter_orders(
    orders: list[dict[str, Any]],
    *,
    q: str,
    date_from: date | None,
    date_to: date | None,
    statuses: set[str] | None,
    reply_needed: bool | None,
    human_review_needed: bool | None,
    post_case: bool | None,
) -> list[dict[str, Any]]:
    query = q.strip().lower()
    result: list[dict[str, Any]] = []

    for order in orders:
        effective_dt = _effective_received_at(order)
        effective_date = effective_dt.date()

        if date_from and effective_date < date_from:
            continue
        if date_to and effective_date > date_to:
            continue

        status = _normalize_status(order.get("status"))
        if statuses and status not in statuses:
            continue

        if reply_needed is not None and bool(order.get("reply_needed")) != reply_needed:
            continue
        if human_review_needed is not None and bool(order.get("human_review_needed")) != human_review_needed:
            continue
        if post_case is not None and bool(order.get("post_case")) != post_case:
            continue

        if query:
            searchable = " ".join(
                [
                    str(order.get("ticket_number") or ""),
                    str(order.get("kom_nr") or ""),
                    str(order.get("kom_name") or ""),
                    str(order.get("message_id") or ""),
                    str(order.get("file_name") or ""),
                ]
            ).lower()
            if query not in searchable:
                continue

        cloned = dict(order)
        cloned["_effective_dt"] = effective_dt
        result.append(cloned)

    return result


def _sort_orders(orders: list[dict[str, Any]], sort_key: str) -> list[dict[str, Any]]:
    reverse = sort_key != "received_at_asc"
    return sorted(
        orders,
        key=lambda order: order.get("_effective_dt") or _effective_received_at(order),
        reverse=reverse,
    )


def _tab_counts(orders: list[dict[str, Any]]) -> dict[str, int]:
    today = datetime.now().astimezone().date()
    return {
        "all": len(orders),
        "today": sum(1 for order in orders if _effective_received_at(order).date() == today),
        "needs_reply": sum(1 for order in orders if bool(order.get("reply_needed"))),
        "manual_review": sum(1 for order in orders if bool(order.get("human_review_needed"))),
    }


def _parse_orders_query(allow_default_pagination: bool = True):
    q = (request.args.get("q") or "").strip()

    raw_status = (request.args.get("status") or "").strip()
    statuses: set[str] | None = None
    if raw_status:
        parsed_statuses = {item.strip().lower() for item in raw_status.split(",") if item.strip()}
        unknown = [status for status in parsed_statuses if status not in VALID_STATUSES]
        if unknown:
            return None, _api_error(400, "invalid_status", f"Invalid status values: {', '.join(sorted(unknown))}")
        statuses = parsed_statuses

    try:
        date_from = _parse_date_query(request.args.get("from"))
    except ValueError:
        return None, _api_error(400, "invalid_date", "Invalid 'from' date format. Use YYYY-MM-DD.")

    try:
        date_to = _parse_date_query(request.args.get("to"))
    except ValueError:
        return None, _api_error(400, "invalid_date", "Invalid 'to' date format. Use YYYY-MM-DD.")

    if date_from and date_to and date_from > date_to:
        return None, _api_error(400, "invalid_date_range", "'from' cannot be after 'to'.")

    raw_reply_needed = request.args.get("reply_needed")
    reply_needed = _parse_bool_query(raw_reply_needed)
    if raw_reply_needed not in (None, "") and reply_needed is None:
        return None, _api_error(400, "invalid_flag", "Invalid reply_needed flag. Use true or false.")

    raw_human_review = request.args.get("human_review_needed")
    human_review_needed = _parse_bool_query(raw_human_review)
    if raw_human_review not in (None, "") and human_review_needed is None:
        return None, _api_error(400, "invalid_flag", "Invalid human_review_needed flag. Use true or false.")

    raw_post_case = request.args.get("post_case")
    post_case = _parse_bool_query(raw_post_case)
    if raw_post_case not in (None, "") and post_case is None:
        return None, _api_error(400, "invalid_flag", "Invalid post_case flag. Use true or false.")

    sort_key = (request.args.get("sort") or "received_at_desc").strip().lower()
    if sort_key not in ALLOWED_SORTS:
        return None, _api_error(
            400,
            "invalid_sort",
            f"Unsupported sort '{sort_key}'. Allowed: {', '.join(sorted(ALLOWED_SORTS))}.",
        )

    page = 1
    page_size = 25
    should_paginate = allow_default_pagination
    if not allow_default_pagination and "page" not in request.args and "page_size" not in request.args:
        should_paginate = False

    if "page" in request.args:
        try:
            page = max(1, int((request.args.get("page") or "1").strip()))
        except ValueError:
            return None, _api_error(400, "invalid_pagination", "Invalid page value.")

    if "page_size" in request.args:
        try:
            page_size = int((request.args.get("page_size") or "25").strip())
        except ValueError:
            return None, _api_error(400, "invalid_pagination", "Invalid page_size value.")
        if page_size < 1 or page_size > 500:
            return None, _api_error(400, "invalid_pagination", "page_size must be between 1 and 500.")
    elif should_paginate:
        page_size = 25

    query = {
        "q": q,
        "date_from": date_from,
        "date_to": date_to,
        "statuses": statuses,
        "reply_needed": reply_needed,
        "human_review_needed": human_review_needed,
        "post_case": post_case,
        "sort_key": sort_key,
        "page": page,
        "page_size": page_size,
        "paginate": should_paginate,
    }
    return query, None


def _query_orders(allow_default_pagination: bool = True) -> tuple[dict[str, Any] | None, Any]:
    parsed, parse_error = _parse_orders_query(allow_default_pagination=allow_default_pagination)
    if parse_error is not None:
        return None, parse_error

    orders = _get_order_index()
    filtered = _filter_orders(
        orders,
        q=parsed["q"],
        date_from=parsed["date_from"],
        date_to=parsed["date_to"],
        statuses=parsed["statuses"],
        reply_needed=parsed["reply_needed"],
        human_review_needed=parsed["human_review_needed"],
        post_case=parsed["post_case"],
    )
    sorted_orders = _sort_orders(filtered, parsed["sort_key"])

    counts = _tab_counts(filtered)
    status_counts = _status_counts(filtered)
    total = len(sorted_orders)

    if parsed["paginate"]:
        page = parsed["page"]
        page_size = parsed["page_size"]
        total_pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, total_pages)
        start = (page - 1) * page_size
        end = start + page_size
        rows = sorted_orders[start:end]
    else:
        page = 1
        page_size = total if total > 0 else 1
        total_pages = 1
        rows = sorted_orders

    return (
        {
            "orders": rows,
            "orders_serialized": [_serialize_order_summary(order) for order in rows],
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": total_pages,
            },
            "counts": {
                "all": counts["all"],
                "today": counts["today"],
                "needs_reply": counts["needs_reply"],
                "manual_review": counts["manual_review"],
                "status": status_counts,
            },
        },
        None,
    )

def _header_val(header: dict[str, Any], key: str) -> str:
    entry = header.get(key)
    if isinstance(entry, dict):
        return str(entry.get("value", "") or "").strip()
    return str(entry or "").strip()


def _sanitize_xml_base(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", (value or "").strip())
    return cleaned.strip("_") or ""


def _resolve_xml_files(order_id: str, header: dict[str, Any]) -> list[dict[str, str]]:
    effective_base = (
        _sanitize_xml_base(_header_val(header, "ticket_number"))
        or _sanitize_xml_base(_header_val(header, "kom_nr"))
        or _sanitize_xml_base(_header_val(header, "kom_name"))
        or "unknown"
    )
    order_info_xml = f"OrderInfo_{effective_base}.xml"
    article_info_xml = f"OrderArticleInfo_{effective_base}.xml"
    if not (OUTPUT_DIR / order_info_xml).exists():
        order_info_xml = f"OrderInfo_{order_id}.xml"
    if not (OUTPUT_DIR / article_info_xml).exists():
        article_info_xml = f"OrderArticleInfo_{order_id}.xml"

    xml_files: list[dict[str, str]] = []
    if (OUTPUT_DIR / order_info_xml).exists():
        xml_files.append({"name": "Order Info XML", "filename": order_info_xml})
    if (OUTPUT_DIR / article_info_xml).exists():
        xml_files.append({"name": "Article Info XML", "filename": article_info_xml})
    return xml_files


def _delete_order_files(order_id: str, header: dict[str, Any]) -> None:
    (OUTPUT_DIR / f"{order_id}.json").unlink(missing_ok=True)

    file_candidates = {
        f"OrderInfo_{order_id}.xml",
        f"OrderArticleInfo_{order_id}.xml",
    }

    effective_base = (
        _sanitize_xml_base(_header_val(header, "ticket_number"))
        or _sanitize_xml_base(_header_val(header, "kom_nr"))
        or _sanitize_xml_base(_header_val(header, "kom_name"))
    )
    if effective_base:
        file_candidates.add(f"OrderInfo_{effective_base}.xml")
        file_candidates.add(f"OrderArticleInfo_{effective_base}.xml")

    for filename in file_candidates:
        (OUTPUT_DIR / filename).unlink(missing_ok=True)


def _load_order(order_id: str) -> tuple[dict[str, Any] | None, Any]:
    safe_id = _safe_id(order_id)
    if not safe_id:
        return None, _api_error(404, "not_found", "Order not found")

    path = OUTPUT_DIR / f"{safe_id}.json"
    if not path.exists():
        return None, _api_error(404, "not_found", "Order not found")

    data, parse_error = _read_json(path)
    data = data or {}
    if not isinstance(data, dict):
        data = {}

    header = data.get("header") if isinstance(data.get("header"), dict) else {}
    items = data.get("items") if isinstance(data.get("items"), list) else []
    warnings = data.get("warnings", [])
    errors = data.get("errors", [])
    if not isinstance(warnings, list):
        warnings = [str(warnings)]
    warnings = [str(item) for item in warnings]
    if not isinstance(errors, list):
        errors = [str(errors)]
    errors = [str(item) for item in errors]

    human_review_needed = _is_truthy_flag(header.get("human_review_needed"))
    reply_needed = _is_truthy_flag(header.get("reply_needed"))
    post_case = _is_truthy_flag(header.get("post_case"))
    reply_case = _reply_case_from_warnings(warnings)

    payload = {
        "safe_id": safe_id,
        "path": path,
        "data": data,
        "parse_error": parse_error,
        "header": header,
        "items": items,
        "warnings": warnings,
        "errors": errors,
        "human_review_needed": human_review_needed,
        "reply_needed": reply_needed,
        "post_case": post_case,
        "reply_mailto": _reply_mailto(
            str(data.get("message_id") or safe_id),
            safe_id,
            reply_case,
        )
        if reply_needed
        else "",
    }
    return payload, None


def _order_api_payload(order: dict[str, Any]) -> dict[str, Any]:
    data = order["data"]
    response = dict(data)
    response["order_id"] = order["safe_id"]
    response["header"] = order["header"]
    response["items"] = order["items"]
    response["warnings"] = order["warnings"]
    response["errors"] = order["errors"]
    response["parse_error"] = order["parse_error"]
    response["xml_files"] = _resolve_xml_files(order["safe_id"], order["header"])
    response["is_editable"] = bool(order["human_review_needed"] and not order["parse_error"])
    response["reply_mailto"] = order["reply_mailto"]
    response["reply_needed"] = order["reply_needed"]
    response["post_case"] = order["post_case"]
    response["editable_header_fields"] = EDITABLE_HEADER_FIELDS
    response["editable_item_fields"] = EDITABLE_ITEM_FIELDS
    return response


def _export_entry_value(entry: Any) -> Any:
    value = entry.get("value", "") if isinstance(entry, dict) else entry
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _ensure_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if value in (None, ""):
        return []
    return [str(value)]


def _load_order_export_data(order: dict[str, Any]) -> dict[str, Any]:
    order_id = str(order.get("id") or "")
    fallback_file_name = f"{order_id}.json" if order_id else ""
    file_name = str(order.get("file_name") or fallback_file_name)

    data: dict[str, Any] = {}
    parse_error = ""
    if file_name:
        parsed_data, parse_error = _read_json(OUTPUT_DIR / file_name)
        if isinstance(parsed_data, dict):
            data = parsed_data
    else:
        parse_error = "Missing file_name"

    header = data.get("header") if isinstance(data.get("header"), dict) else {}
    items = data.get("items") if isinstance(data.get("items"), list) else []
    warnings = _ensure_string_list(data.get("warnings", order.get("warnings", [])))
    errors = _ensure_string_list(data.get("errors", order.get("errors", [])))

    return {
        "order_id": order_id,
        "file_name": file_name,
        "message_id": str(data.get("message_id") or order.get("message_id") or order_id),
        "received_at": str(data.get("received_at") or order.get("received_at") or ""),
        "status": _normalize_status(data.get("status") or order.get("status")),
        "item_count": len(items),
        "warnings_count": len(warnings),
        "errors_count": len(errors),
        "reply_needed": _is_truthy_flag(header.get("reply_needed")) if header else bool(order.get("reply_needed")),
        "human_review_needed": _is_truthy_flag(header.get("human_review_needed"))
        if header
        else bool(order.get("human_review_needed")),
        "post_case": _is_truthy_flag(header.get("post_case")) if header else bool(order.get("post_case")),
        "warnings": warnings,
        "errors": errors,
        "parse_error": parse_error or "",
        "header": header,
        "items": items,
    }


def _as_orders_xlsx_bytes(orders: list[dict[str, Any]]) -> bytes:
    parsed_orders = [_load_order_export_data(order) for order in orders]

    fixed_header_columns = [
        "order_id",
        "file_name",
        "message_id",
        "received_at",
        "status",
        "item_count",
        "warnings_count",
        "errors_count",
        "reply_needed",
        "human_review_needed",
        "post_case",
        "warnings",
        "errors",
        "parse_error",
    ]
    excluded_header_keys = {"reply_needed", "human_review_needed", "post_case"}
    seen_header_keys: set[str] = set()
    for parsed_order in parsed_orders:
        seen_header_keys.update(parsed_order["header"].keys())

    header_value_columns = [
        field for field in EDITABLE_HEADER_FIELDS if field not in excluded_header_keys
    ] + sorted(
        key
        for key in seen_header_keys
        if key not in excluded_header_keys and key not in EDITABLE_HEADER_FIELDS
    )
    header_columns = fixed_header_columns + header_value_columns

    fixed_item_columns = ["order_id", "ticket_number", "kom_nr", "kom_name", "line_no"]
    seen_item_keys: set[str] = set()
    for parsed_order in parsed_orders:
        for item in parsed_order["items"]:
            if isinstance(item, dict):
                seen_item_keys.update(item.keys())

    item_value_columns = list(EDITABLE_ITEM_FIELDS) + sorted(
        key for key in seen_item_keys if key != "line_no" and key not in EDITABLE_ITEM_FIELDS
    )
    item_columns = fixed_item_columns + item_value_columns

    workbook = Workbook()
    header_sheet = workbook.active
    header_sheet.title = "Header"
    items_sheet = workbook.create_sheet("Items")

    header_sheet.append(header_columns)
    items_sheet.append(item_columns)

    for parsed_order in parsed_orders:
        header = parsed_order["header"]
        header_row = {
            "order_id": parsed_order["order_id"],
            "file_name": parsed_order["file_name"],
            "message_id": parsed_order["message_id"],
            "received_at": parsed_order["received_at"],
            "status": parsed_order["status"],
            "item_count": parsed_order["item_count"],
            "warnings_count": parsed_order["warnings_count"],
            "errors_count": parsed_order["errors_count"],
            "reply_needed": parsed_order["reply_needed"],
            "human_review_needed": parsed_order["human_review_needed"],
            "post_case": parsed_order["post_case"],
            "warnings": " | ".join(parsed_order["warnings"]),
            "errors": " | ".join(parsed_order["errors"]),
            "parse_error": parsed_order["parse_error"],
        }
        for field in header_value_columns:
            header_row[field] = _export_entry_value(header.get(field, ""))
        header_sheet.append([header_row.get(column, "") for column in header_columns])

        ticket_number = _export_entry_value(header.get("ticket_number", ""))
        kom_nr = _export_entry_value(header.get("kom_nr", ""))
        kom_name = _export_entry_value(header.get("kom_name", ""))
        for index, item in enumerate(parsed_order["items"], start=1):
            if not isinstance(item, dict):
                continue
            line_no = item.get("line_no")
            if line_no in (None, ""):
                line_no = index

            item_row = {
                "order_id": parsed_order["order_id"],
                "ticket_number": ticket_number,
                "kom_nr": kom_nr,
                "kom_name": kom_name,
                "line_no": line_no,
            }
            for field in item_value_columns:
                item_row[field] = _export_entry_value(item.get(field, ""))
            items_sheet.append([item_row.get(column, "") for column in item_columns])

    header_sheet.freeze_panes = "A2"
    items_sheet.freeze_panes = "A2"

    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def _as_csv_text(orders: list[dict[str, Any]]) -> str:
    fieldnames = [
        "received_at",
        "status",
        "ticket_number",
        "kom_nr",
        "kom_name",
        "message_id",
        "kundennummer",
        "store_name",
        "store_address",
        "delivery_week",
        "liefertermin",
        "wunschtermin",
        "item_count",
        "warnings_count",
        "errors_count",
        "reply_needed",
        "human_review_needed",
        "post_case",
        "warnings",
        "errors",
        "file_name",
        "order_id",
    ]

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for order in orders:
        writer.writerow(
            {
                "received_at": order.get("received_at", ""),
                "status": _normalize_status(order.get("status")),
                "ticket_number": order.get("ticket_number", ""),
                "kom_nr": order.get("kom_nr", ""),
                "kom_name": order.get("kom_name", ""),
                "message_id": order.get("message_id", ""),
                "kundennummer": order.get("kundennummer", ""),
                "store_name": order.get("store_name", ""),
                "store_address": order.get("store_address", ""),
                "delivery_week": order.get("delivery_week", ""),
                "liefertermin": order.get("liefertermin", ""),
                "wunschtermin": order.get("wunschtermin", ""),
                "item_count": order.get("item_count", 0),
                "warnings_count": order.get("warnings_count", 0),
                "errors_count": order.get("errors_count", 0),
                "reply_needed": bool(order.get("reply_needed")),
                "human_review_needed": bool(order.get("human_review_needed")),
                "post_case": bool(order.get("post_case")),
                "warnings": " | ".join([str(item) for item in order.get("warnings", [])]),
                "errors": " | ".join([str(item) for item in order.get("errors", [])]),
                "file_name": order.get("file_name", ""),
                "order_id": order.get("id", ""),
            }
        )
    return output.getvalue()

@app.before_request
def _api_auth_guard():
    if not request.path.startswith("/api/"):
        return None
    return require_auth(request)


@app.after_request
def _api_cors_headers(response: Response):
    if not request.path.startswith("/api/"):
        return response

    origin = request.headers.get("Origin")
    if _is_origin_allowed(origin):
        response.headers["Access-Control-Allow-Origin"] = "*" if ALLOW_ANY_ORIGIN else str(origin)
        if not ALLOW_ANY_ORIGIN:
            response.headers["Vary"] = _append_vary(response.headers.get("Vary"), "Origin")

    response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, DELETE, OPTIONS"
    response.headers["Access-Control-Max-Age"] = "86400"
    return response


@app.errorhandler(HTTPException)
def _http_error_handler(error: HTTPException):
    if not request.path.startswith("/api/"):
        return error
    code_map = {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        405: "method_not_allowed",
    }
    status_code = error.code or 500
    code = code_map.get(status_code, "http_error")
    return _api_error(status_code, code, error.description or error.name)


@app.errorhandler(500)
def _internal_error_handler(error):
    if not request.path.startswith("/api/"):
        return error
    return _api_error(500, "internal_error", "Unexpected server error")


@app.route("/api", methods=["OPTIONS"])
@app.route("/api/<path:any_path>", methods=["OPTIONS"])
def api_options(any_path: str | None = None):  # noqa: ARG001
    return ("", 204)


@app.route("/api/auth/check")
def api_auth_check():
    return ("", 204)


@app.route("/api/overview")
def api_overview():
    orders = _get_order_index()
    now = datetime.now().astimezone()
    today = now.date()
    last_24h_start = now - timedelta(hours=24)

    today_orders: list[dict[str, Any]] = []
    last_24h_orders: list[dict[str, Any]] = []

    queue_counts = {
        "reply_needed": 0,
        "human_review_needed": 0,
        "post_case": 0,
    }

    day_buckets: dict[date, dict[str, Any]] = {}
    seven_days: list[date] = [today - timedelta(days=offset) for offset in range(6, -1, -1)]
    for bucket_day in seven_days:
        day_buckets[bucket_day] = {
            "date": bucket_day.isoformat(),
            "label": bucket_day.strftime("%a"),
            "ok": 0,
            "partial": 0,
            "failed": 0,
            "unknown": 0,
            "total": 0,
        }

    current_hour = now.replace(minute=0, second=0, microsecond=0)
    hourly_keys: list[datetime] = [current_hour - timedelta(hours=offset) for offset in range(23, -1, -1)]
    hourly_counts: dict[datetime, int] = {key: 0 for key in hourly_keys}

    for order in orders:
        status = _normalize_status(order.get("status"))
        effective_dt = _effective_received_at(order)

        if bool(order.get("reply_needed")):
            queue_counts["reply_needed"] += 1
        if bool(order.get("human_review_needed")):
            queue_counts["human_review_needed"] += 1
        if bool(order.get("post_case")):
            queue_counts["post_case"] += 1

        if effective_dt.date() == today:
            today_orders.append(order)
        if effective_dt >= last_24h_start:
            last_24h_orders.append(order)

        bucket = day_buckets.get(effective_dt.date())
        if bucket is not None:
            bucket[status] += 1
            bucket["total"] += 1

        hour_bucket = effective_dt.replace(minute=0, second=0, microsecond=0)
        if hour_bucket in hourly_counts:
            hourly_counts[hour_bucket] += 1

    latest_orders = sorted(orders, key=_effective_received_at, reverse=True)[:20]
    processed_by_hour = [
        {
            "hour": bucket.isoformat(),
            "label": bucket.strftime("%H:%M"),
            "processed": hourly_counts[bucket],
        }
        for bucket in hourly_keys
    ]

    return jsonify(
        {
            "generated_at": now.isoformat(),
            "today": _status_breakdown(today_orders),
            "last_24h": _status_breakdown(last_24h_orders),
            "queue_counts": queue_counts,
            "status_by_day": [day_buckets[bucket_day] for bucket_day in seven_days],
            "processed_by_hour": processed_by_hour,
            "latest_orders": [_serialize_order_summary(order) for order in latest_orders],
        }
    )


@app.route("/api/orders")
def api_orders():
    result, error = _query_orders(allow_default_pagination=True)
    if error is not None:
        return error

    return jsonify(
        {
            "orders": result["orders_serialized"],
            "pagination": result["pagination"],
            "counts": result["counts"],
        }
    )


@app.route("/api/orders.csv")
def api_orders_csv():
    result, error = _query_orders(allow_default_pagination=False)
    if error is not None:
        return error

    csv_text = _as_csv_text(result["orders"])
    response = Response(csv_text, mimetype="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=orders.csv"
    return response


@app.route("/api/orders.xlsx")
def api_orders_xlsx():
    result, error = _query_orders(allow_default_pagination=False)
    if error is not None:
        return error

    xlsx_bytes = _as_orders_xlsx_bytes(result["orders"])
    response = Response(
        xlsx_bytes,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response.headers["Content-Disposition"] = "attachment; filename=orders.xlsx"
    return response

@app.route("/api/orders/<order_id>", methods=["GET", "PATCH", "DELETE"])
def api_order_detail(order_id: str):
    order, load_error = _load_order(order_id)
    if load_error is not None:
        return load_error

    if request.method == "GET":
        return jsonify(_order_api_payload(order))

    if request.method == "DELETE":
        delete_errors: list[str] = []
        try:
            order["path"].unlink()
        except FileNotFoundError:
            pass
        except Exception as exc:  # noqa: BLE001
            delete_errors.append(f"json:{exc}")

        for xml_file in _resolve_xml_files(order["safe_id"], order["header"]):
            try:
                (OUTPUT_DIR / xml_file["filename"]).unlink()
            except FileNotFoundError:
                continue
            except Exception as exc:  # noqa: BLE001
                delete_errors.append(f"{xml_file['filename']}:{exc}")

        _invalidate_order_index_cache()
        if delete_errors:
            return _api_error(500, "delete_failed", "Failed to delete order files")
        return jsonify({"deleted": True, "order_id": order["safe_id"]})

    if request.method == "DELETE":
        _delete_order_files(order["safe_id"], order["header"])
        _invalidate_order_index_cache()
        return ("", 204)

    if not (order["human_review_needed"] and not order["parse_error"]):
        return _api_error(403, "forbidden", "Order is not editable")

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _api_error(400, "invalid_body", "PATCH body must be a JSON object")

    header_updates = body.get("header", {})
    item_updates = body.get("items", {})
    if not isinstance(header_updates, dict):
        return _api_error(400, "invalid_body", "'header' must be an object")
    if not isinstance(item_updates, dict):
        return _api_error(400, "invalid_body", "'items' must be an object keyed by item index")

    for field, value in header_updates.items():
        if field not in EDITABLE_HEADER_FIELDS:
            return _api_error(400, "invalid_field", f"Header field '{field}' is not editable")
        _set_manual_entry(order["header"], field, _clean_form_value(str(value) if value is not None else ""))

    for raw_index, fields in item_updates.items():
        if not isinstance(fields, dict):
            return _api_error(400, "invalid_body", f"Item patch for index '{raw_index}' must be an object")
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            return _api_error(400, "invalid_body", f"Invalid item index '{raw_index}'")
        if index < 0 or index >= len(order["items"]):
            return _api_error(400, "invalid_body", f"Item index '{raw_index}' is out of range")
        item = order["items"][index]
        if not isinstance(item, dict):
            return _api_error(400, "invalid_body", f"Item '{raw_index}' is not editable")

        for field, value in fields.items():
            if field not in EDITABLE_ITEM_FIELDS:
                return _api_error(400, "invalid_field", f"Item field '{field}' is not editable")
            _set_manual_entry(item, field, _clean_form_value(str(value) if value is not None else ""))

    order["data"]["header"] = order["header"]
    order["data"]["items"] = order["items"]
    refresh_missing_warnings(order["data"])
    order["path"].write_text(json.dumps(order["data"], ensure_ascii=False, indent=2), encoding="utf-8")

    xml_regenerated = False
    try:
        xml_exporter.export_xmls(order["data"], order["safe_id"], config, OUTPUT_DIR)
        xml_regenerated = True
    except Exception:  # noqa: BLE001
        xml_regenerated = False

    _invalidate_order_index_cache()
    updated_order, updated_error = _load_order(order["safe_id"])
    if updated_error is not None:
        return updated_error

    payload = _order_api_payload(updated_order)
    payload["xml_regenerated"] = xml_regenerated
    return jsonify(payload)


@app.route("/api/orders/<order_id>/export-xml", methods=["POST"])
def api_export_order_xml(order_id: str):
    order, load_error = _load_order(order_id)
    if load_error is not None:
        return load_error
    if order["parse_error"]:
        return _api_error(400, "invalid_order", "Order JSON could not be parsed")

    try:
        xml_exporter.export_xmls(order["data"], order["safe_id"], config, OUTPUT_DIR)
    except Exception:  # noqa: BLE001
        return _api_error(500, "xml_export_failed", "Failed to regenerate XML files")

    files = _resolve_xml_files(order["safe_id"], order["header"])
    return jsonify({"xml_files": files})


@app.route("/api/files/<filename>")
def api_download_file(filename: str):
    safe_filename = _safe_id(filename)
    if not safe_filename:
        return _api_error(404, "not_found", "File not found")

    extension = Path(safe_filename).suffix.lower()
    if extension not in ALLOWED_DOWNLOAD_EXTENSIONS:
        return _api_error(403, "forbidden", "File type is not allowed")

    full_path = OUTPUT_DIR / safe_filename
    if not full_path.exists() or not full_path.is_file():
        return _api_error(404, "not_found", "File not found")

    return send_from_directory(OUTPUT_DIR, safe_filename, as_attachment=True)

@app.route("/")
def index() -> str:
    orders = _list_orders(OUTPUT_DIR)

    date_scope = (request.args.get("date_scope") or "").lower().strip()
    if date_scope not in {"today", "all"}:
        date_scope = "today"

    for order in orders:
        parsed = _parse_received_at(order.get("received_at"))
        order["_received_at_sort"] = parsed

    orders_sorted = sorted(
        orders,
        key=lambda order: (
            order.get("_received_at_sort") is not None,
            order.get("_received_at_sort"),
        ),
        reverse=True,
    )

    if date_scope == "today":
        today = datetime.now().astimezone().date()
        scoped_orders = [
            order
            for order in orders_sorted
            if isinstance(order.get("_received_at_sort"), datetime)
            and order["_received_at_sort"].date() == today
        ]
    else:
        scoped_orders = orders_sorted

    counts = _status_counts(scoped_orders)

    status_filter = (request.args.get("status") or "").lower().strip()
    if status_filter and status_filter != "all":
        filtered_orders = [order for order in scoped_orders if order.get("status") == status_filter]
    else:
        status_filter = "all"
        filtered_orders = scoped_orders

    total_rows = len(filtered_orders)
    for idx, order in enumerate(filtered_orders, start=1):
        order["display_index"] = total_rows - idx + 1

    return render_template(
        "index.html",
        orders=filtered_orders,
        counts=counts,
        status_filter=status_filter,
        date_scope=date_scope,
        body_class="dashboard",
    )


@app.route("/download/<filename>")
def download_file(filename: str):
    safe_filename = _safe_id(filename)
    if not safe_filename:
        abort(404)
    return send_from_directory(OUTPUT_DIR, safe_filename, as_attachment=True)


@app.route("/order/<order_id>/export-xml", methods=["POST"])
def export_order_xml(order_id: str):
    safe_id = _safe_id(order_id)
    if not safe_id:
        abort(404)
    path = OUTPUT_DIR / f"{safe_id}.json"
    if not path.exists():
        abort(404)
    data, error = _read_json(path)
    if error or not data or not isinstance(data, dict):
        abort(404)
    try:
        xml_exporter.export_xmls(data, safe_id, config, OUTPUT_DIR)
    except Exception:  # noqa: BLE001
        abort(500)
    _invalidate_order_index_cache()
    return redirect(url_for("order_detail", order_id=safe_id, exported="1"))


@app.route("/order/<order_id>/delete", methods=["POST"])
def delete_order(order_id: str):
    safe_id = _safe_id(order_id)
    if not safe_id:
        abort(404)

    path = OUTPUT_DIR / f"{safe_id}.json"
    if not path.exists():
        abort(404)

    data, _ = _read_json(path)
    header = data.get("header") if isinstance(data, dict) and isinstance(data.get("header"), dict) else {}
    _delete_order_files(safe_id, header)
    _invalidate_order_index_cache()

    date_scope = (request.args.get("date_scope") or "").lower().strip()
    status_filter = (request.args.get("status") or "").lower().strip()
    return redirect(url_for("index", date_scope=date_scope or "today", status=status_filter or "all"))


@app.route("/order/<order_id>", methods=["GET", "POST"])
def order_detail(order_id: str) -> str:
    safe_id = _safe_id(order_id)
    if not safe_id:
        abort(404)

    path = OUTPUT_DIR / f"{safe_id}.json"
    if not path.exists():
        abort(404)

    data, error = _read_json(path)
    data = data or {}
    header = data.get("header") if isinstance(data.get("header"), dict) else {}
    items = data.get("items") if isinstance(data.get("items"), list) else []
    human_review_needed = _is_truthy_flag(header.get("human_review_needed"))
    reply_needed = _is_truthy_flag(header.get("reply_needed"))
    post_case = _is_truthy_flag(header.get("post_case"))

    if request.method == "POST":
        if error or not human_review_needed:
            abort(403)

        for field in EDITABLE_HEADER_FIELDS:
            form_key = f"header_{field}"
            if form_key in request.form:
                _set_manual_entry(header, field, _clean_form_value(request.form.get(form_key)))

        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            for field in EDITABLE_ITEM_FIELDS:
                form_key = f"item_{idx}_{field}"
                if form_key in request.form:
                    _set_manual_entry(item, field, _clean_form_value(request.form.get(form_key)))

        data["header"] = header
        data["items"] = items
        refresh_missing_warnings(data)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        xml_regenerated = False
        try:
            xml_exporter.export_xmls(data, safe_id, config, OUTPUT_DIR)
            xml_regenerated = True
        except Exception:  # noqa: BLE001
            xml_regenerated = False

        _invalidate_order_index_cache()
        return redirect(
            url_for("order_detail", order_id=safe_id, saved="1", xml_regenerated="1" if xml_regenerated else "0")
        )

    header_rows = [
        {"field": "ticket_number", **_entry_dict(header.get("ticket_number"))},
        {"field": "kundennummer", **_entry_dict(header.get("kundennummer"))},
        {"field": "adressnummer", **_entry_dict(header.get("adressnummer"))},
        {"field": "tour", **_entry_dict(header.get("tour"))},
        {"field": "kom_nr", **_entry_dict(header.get("kom_nr"))},
        {"field": "kom_name", **_entry_dict(header.get("kom_name"))},
        {"field": "liefertermin", **_entry_dict(header.get("liefertermin"))},
        {"field": "wunschtermin", **_entry_dict(header.get("wunschtermin"))},
        {"field": "bestelldatum", **_entry_dict(header.get("bestelldatum"))},
        {"field": "lieferanschrift", **_entry_dict(header.get("lieferanschrift"))},
        {"field": "store_name", **_entry_dict(header.get("store_name"))},
        {"field": "store_address", **_entry_dict(header.get("store_address"))},
        {"field": "seller", **_entry_dict(header.get("seller"))},
        {"field": "delivery_week", **_entry_dict(header.get("delivery_week"))},
        {"field": "iln", **_entry_dict(header.get("iln"))},
        {"field": "human_review_needed", **_entry_dict(header.get("human_review_needed"))},
        {"field": "reply_needed", **_entry_dict(header.get("reply_needed"))},
        {"field": "post_case", **_entry_dict(header.get("post_case"))},
    ]

    item_rows = []
    for item in items:
        if not isinstance(item, dict):
            continue
        item_rows.append(
            {
                "line_no": item.get("line_no", ""),
                "artikelnummer": _entry_dict(item.get("artikelnummer")),
                "modellnummer": _entry_dict(item.get("modellnummer")),
                "menge": _entry_dict(item.get("menge")),
                "furncloud_id": _entry_dict(item.get("furncloud_id")),
            }
        )

    warnings = data.get("warnings", [])
    errors = data.get("errors", [])
    if not isinstance(warnings, list):
        warnings = [str(warnings)]
    warnings = [str(item) for item in warnings]
    if not isinstance(errors, list):
        errors = [str(errors)]
    errors = [str(item) for item in errors]

    reply_case = _reply_case_from_warnings(warnings)
    raw_json = json.dumps(data, ensure_ascii=False, indent=2)
    xml_files = _resolve_xml_files(safe_id, header)

    saved = (request.args.get("saved") or "") == "1"
    exported = (request.args.get("exported") or "") == "1"
    xml_regenerated = (request.args.get("xml_regenerated") or "") == "1"
    return render_template(
        "detail.html",
        order_id=safe_id,
        message_id=data.get("message_id") or safe_id,
        received_at=data.get("received_at") or "",
        status=_normalize_status(data.get("status")),
        header_rows=header_rows,
        item_rows=item_rows,
        warnings=warnings,
        errors=errors,
        raw_json=raw_json,
        parse_error=error,
        xml_files=xml_files,
        ab_files=[],
        is_editable=human_review_needed and not error,
        reply_needed=reply_needed,
        post_case=post_case,
        reply_mailto=_reply_mailto(data.get("message_id") or safe_id, safe_id, reply_case) if reply_needed else "",
        editable_header_fields=EDITABLE_HEADER_FIELDS,
        editable_item_fields=EDITABLE_ITEM_FIELDS,
        saved=saved,
        exported=exported,
        xml_regenerated=xml_regenerated,
    )


if __name__ == "__main__":
    host = os.getenv("DASHBOARD_HOST", "127.0.0.1")
    port = int(os.getenv("DASHBOARD_PORT", "5000"))
    app.run(host=host, port=port, debug=False)
