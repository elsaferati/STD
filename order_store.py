from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any
import uuid

from db import fetch_all, fetch_one, get_connection
from extraction_branches import BRANCHES

STATUS_OK = "ok"
STATUS_REPLY = "reply"
STATUS_HUMAN = "human_in_the_loop"
STATUS_POST = "post"
STATUS_FAILED = "failed"
STATUS_PARTIAL = "partial"
STATUS_UNKNOWN = "unknown"
STATUS_WAITING_REPLY = "waiting_for_reply"
STATUS_CLIENT_REPLIED = "client_replied"
STATUS_UPDATED_AFTER_REPLY = "updated_after_reply"

VALID_STATUSES = {
    STATUS_OK,
    STATUS_REPLY,
    STATUS_HUMAN,
    STATUS_POST,
    STATUS_FAILED,
    STATUS_PARTIAL,
    STATUS_UNKNOWN,
    STATUS_WAITING_REPLY,
    STATUS_CLIENT_REPLIED,
    STATUS_UPDATED_AFTER_REPLY,
}
REVIEWABLE_STATUSES = {STATUS_REPLY, STATUS_HUMAN, STATUS_POST}
TASK_DONE_STATES = {"resolved", "cancelled"}
UNKNOWN_EXTRACTION_BRANCH = "unknown"
KNOWN_EXTRACTION_BRANCHES = frozenset(BRANCHES.keys())
ALLOWED_EXTRACTION_BRANCHES = KNOWN_EXTRACTION_BRANCHES | {UNKNOWN_EXTRACTION_BRANCH}
_KNOWN_BRANCHES_SQL = ", ".join(f"'{branch}'" for branch in sorted(ALLOWED_EXTRACTION_BRANCHES))
_STATUS_SQL = """
CASE
    WHEN LOWER(BTRIM(COALESCE(o.status, ''))) = 'partial' THEN 'reply'
    WHEN LOWER(BTRIM(COALESCE(o.status, ''))) = 'unknown' THEN 'ok'
    WHEN LOWER(BTRIM(COALESCE(o.status, ''))) IN (
        'ok', 'reply', 'human_in_the_loop', 'post', 'failed',
        'waiting_for_reply', 'client_replied', 'updated_after_reply'
    )
        THEN LOWER(BTRIM(COALESCE(o.status, '')))
    ELSE 'ok'
END
"""
_EXTRACTION_BRANCH_SQL = f"""
CASE
    WHEN LOWER(BTRIM(COALESCE(o.extraction_branch, ''))) IN ({_KNOWN_BRANCHES_SQL})
        THEN LOWER(BTRIM(COALESCE(o.extraction_branch, '')))
    ELSE '{UNKNOWN_EXTRACTION_BRANCH}'
END
"""
_EFFECTIVE_RECEIVED_SQL = "COALESCE(o.received_at, o.updated_at)"


class OrderStoreError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _jsonb(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _entry_value(entry: Any) -> Any:
    if isinstance(entry, dict):
        return entry.get("value")
    return entry


def _entry_text(entry: Any) -> str:
    value = _entry_value(entry)
    return "" if value is None else str(value).strip()


def _entry_bool(entry: Any) -> bool:
    value = _entry_value(entry)
    if value is True:
        return True
    return str(value).strip().lower() == "true"


def _normalize_extraction_branch(value: Any) -> str:
    branch_id = str(value or "").strip().lower()
    if branch_id in ALLOWED_EXTRACTION_BRANCHES:
        return branch_id
    return UNKNOWN_EXTRACTION_BRANCH


def _normalize_branch_set(branches: set[str] | None) -> list[str] | None:
    if branches is None:
        return None
    normalized = sorted({_normalize_extraction_branch(branch) for branch in branches})
    return normalized


def _scope_where_fragments(
    *,
    assigned_user_id: str | None,
    allowed_client_branches: set[str] | None,
) -> tuple[list[str], list[Any]]:
    scope_clauses: list[str] = []
    scope_params: list[Any] = []

    if assigned_user_id:
        scope_clauses.append(
            """
            EXISTS (
                SELECT 1
                FROM order_review_tasks t_scope
                WHERE t_scope.order_id = o.id
                  AND t_scope.state NOT IN ('resolved', 'cancelled')
                  AND t_scope.assigned_user_id = %s
            )
            """
        )
        scope_params.append(assigned_user_id)

    normalized_allowed = _normalize_branch_set(allowed_client_branches)
    if normalized_allowed is not None:
        if not normalized_allowed:
            scope_clauses.append("1 = 0")
        else:
            scope_clauses.append(f"{_EXTRACTION_BRANCH_SQL} = ANY(%s)")
            scope_params.append(normalized_allowed)

    return scope_clauses, scope_params


def normalize_status(value: Any) -> str:
    status = str(value or STATUS_OK).strip().lower()
    if status == STATUS_PARTIAL:
        return STATUS_REPLY
    if status == STATUS_UNKNOWN:
        return STATUS_OK
    if status not in VALID_STATUSES:
        return STATUS_OK
    return status


def derive_status(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        return STATUS_FAILED
    header = payload.get("header")
    items = payload.get("items")
    if not isinstance(header, dict) or not isinstance(items, list):
        return STATUS_FAILED
    if _entry_bool(header.get("reply_needed")):
        return STATUS_REPLY
    if _entry_bool(header.get("human_review_needed")):
        return STATUS_HUMAN
    if _entry_bool(header.get("post_case")):
        return STATUS_POST
    legacy = normalize_status(payload.get("status"))
    if legacy in {STATUS_REPLY, STATUS_HUMAN, STATUS_POST}:
        return legacy
    return STATUS_OK


def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = dict(payload or {})
    if not isinstance(normalized.get("header"), dict):
        normalized["header"] = {}
    if not isinstance(normalized.get("items"), list):
        normalized["items"] = []
    if not isinstance(normalized.get("warnings"), list):
        normalized["warnings"] = [] if normalized.get("warnings") in (None, "") else [str(normalized["warnings"])]
    if not isinstance(normalized.get("errors"), list):
        normalized["errors"] = [] if normalized.get("errors") in (None, "") else [str(normalized["errors"])]
    normalized["warnings"] = [str(item) for item in normalized.get("warnings", [])]
    normalized["errors"] = [str(item) for item in normalized.get("errors", [])]
    normalized["extraction_branch"] = _normalize_extraction_branch(normalized.get("extraction_branch"))
    normalized["status"] = derive_status(normalized)
    return normalized


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _to_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value or "")


def _dedupe_key(message_id: str) -> str:
    token = str(message_id or "").strip().lower()
    if token.startswith("<") and token.endswith(">"):
        token = token[1:-1]
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _projection(payload: dict[str, Any], parse_error: str | None) -> dict[str, Any]:
    header = payload.get("header", {})
    warnings = payload.get("warnings", [])
    errors = payload.get("errors", [])
    items = payload.get("items", [])
    return {
        "received_at": _parse_iso(payload.get("received_at")),
        "status": derive_status(payload),
        "reply_needed": _entry_bool(header.get("reply_needed")),
        "human_review_needed": _entry_bool(header.get("human_review_needed")),
        "post_case": _entry_bool(header.get("post_case")),
        "ticket_number": _entry_text(header.get("ticket_number")),
        "kundennummer": _entry_text(header.get("kundennummer")),
        "kom_nr": _entry_text(header.get("kom_nr")),
        "kom_name": _entry_text(header.get("kom_name")),
        "liefertermin": _entry_text(header.get("liefertermin")),
        "wunschtermin": _entry_text(header.get("wunschtermin")),
        "delivery_week": _entry_text(header.get("delivery_week")),
        "store_name": _entry_text(header.get("store_name")),
        "store_address": _entry_text(header.get("store_address")),
        "iln": _entry_text(header.get("iln")),
        "mail_to": _entry_text(header.get("mail_to")),
        "extraction_branch": _normalize_extraction_branch(payload.get("extraction_branch")),
        "item_count": len(items),
        "warnings_count": len(warnings),
        "errors_count": len(errors),
        "parse_error": str(parse_error or "").strip() or None,
    }


def _ensure_task(conn, *, order_id: str, status: str, actor_user_id: str | None) -> None:
    now = _now()
    with conn.cursor() as cursor:
        if status not in REVIEWABLE_STATUSES:
            cursor.execute(
                """
                UPDATE order_review_tasks
                SET state = 'resolved',
                    resolved_at = COALESCE(resolved_at, %s),
                    resolution_outcome = COALESCE(resolution_outcome, 'auto_ok'),
                    resolution_note = COALESCE(resolution_note, 'Auto-resolved after status transition'),
                    claim_expires_at = NULL,
                    updated_at = %s
                WHERE order_id = %s
                  AND state NOT IN ('resolved', 'cancelled')
                """,
                (now, now, order_id),
            )
            return

        cursor.execute(
            """
            SELECT id, assigned_user_id, claim_expires_at
            FROM order_review_tasks
            WHERE order_id = %s
              AND state NOT IN ('resolved', 'cancelled')
            ORDER BY created_at DESC
            LIMIT 1
            FOR UPDATE
            """,
            (order_id,),
        )
        current = cursor.fetchone()
        if current:
            cursor.execute(
                """
                UPDATE order_review_tasks
                SET task_type = %s,
                    state = CASE
                        WHEN claim_expires_at IS NOT NULL AND claim_expires_at <= %s THEN 'queued'
                        WHEN assigned_user_id IS NULL THEN 'queued'
                        ELSE state
                    END,
                    assigned_user_id = CASE
                        WHEN claim_expires_at IS NOT NULL AND claim_expires_at <= %s THEN NULL
                        ELSE assigned_user_id
                    END,
                    claimed_at = CASE
                        WHEN claim_expires_at IS NOT NULL AND claim_expires_at <= %s THEN NULL
                        ELSE claimed_at
                    END,
                    claim_expires_at = CASE
                        WHEN claim_expires_at IS NOT NULL AND claim_expires_at <= %s THEN NULL
                        ELSE claim_expires_at
                    END,
                    due_at = COALESCE(due_at, %s),
                    updated_at = %s
                WHERE id = %s
                """,
                (status, now, now, now, now, now + timedelta(hours=24), now, current["id"]),
            )
            return

        cursor.execute(
            """
            INSERT INTO order_review_tasks (
                id, order_id, task_type, state, priority, due_at, created_at, updated_at
            )
            VALUES (%s, %s, %s, 'queued', 5, %s, %s, %s)
            """,
            (str(uuid.uuid4()), order_id, status, now + timedelta(hours=24), now, now),
        )
        cursor.execute(
            """
            INSERT INTO order_events (order_id, revision_id, event_type, actor_type, actor_user_id, event_data, created_at)
            VALUES (%s, NULL, 'review_task_created', %s, %s, %s::jsonb, %s)
            """,
            (order_id, "user" if actor_user_id else "system", actor_user_id, _jsonb({"task_type": status}), now),
        )


def _replace_messages(conn, *, order_id: str, revision_id: str, warnings: list[str], errors: list[str]) -> None:
    now = _now()
    with conn.cursor() as cursor:
        cursor.execute("UPDATE order_messages SET is_active = FALSE WHERE order_id = %s AND is_active = TRUE", (order_id,))
        for message in warnings:
            cursor.execute(
                """
                INSERT INTO order_messages (id, order_id, revision_id, level, message, is_active, created_at)
                VALUES (%s, %s, %s, 'warning', %s, TRUE, %s)
                """,
                (str(uuid.uuid4()), order_id, revision_id, str(message), now),
            )
        for message in errors:
            cursor.execute(
                """
                INSERT INTO order_messages (id, order_id, revision_id, level, message, is_active, created_at)
                VALUES (%s, %s, %s, 'error', %s, TRUE, %s)
                """,
                (str(uuid.uuid4()), order_id, revision_id, str(message), now),
            )


def _replace_items(conn, *, order_id: str, items: list[Any]) -> None:
    now = _now()
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM order_items_current WHERE order_id = %s", (order_id,))
        for idx, raw in enumerate(items, start=1):
            if not isinstance(raw, dict):
                continue
            line_no = raw.get("line_no")
            try:
                line_no = int(line_no)
            except (TypeError, ValueError):
                line_no = idx
            menge_raw = _entry_value(raw.get("menge"))
            menge_value = None
            if menge_raw not in (None, ""):
                try:
                    menge_value = float(str(menge_raw).replace(",", "."))
                except ValueError:
                    menge_value = None
            field_meta = {
                key: raw.get(key)
                for key in ("artikelnummer", "modellnummer", "menge", "furncloud_id")
                if isinstance(raw.get(key), dict)
            }
            cursor.execute(
                """
                INSERT INTO order_items_current (
                    id, order_id, line_no, artikelnummer, modellnummer, menge, furncloud_id, field_meta, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                """,
                (
                    str(uuid.uuid4()),
                    order_id,
                    line_no,
                    _entry_text(raw.get("artikelnummer")),
                    _entry_text(raw.get("modellnummer")),
                    menge_value,
                    _entry_text(raw.get("furncloud_id")),
                    _jsonb(field_meta),
                    now,
                ),
            )


def _upsert_revision(
    conn,
    *,
    payload: dict[str, Any],
    external_message_id: str,
    change_type: str,
    changed_by_user_id: str | None,
    parse_error: str | None,
    diff_json: dict[str, Any] | None,
) -> dict[str, Any]:
    now = _now()
    projection = _projection(payload, parse_error)
    dedupe_key = _dedupe_key(external_message_id)
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, current_revision_no
            FROM orders
            WHERE dedupe_key = %s
            FOR UPDATE
            """,
            (dedupe_key,),
        )
        existing = cursor.fetchone()
        if existing:
            order_id = str(existing["id"])
            revision_no = int(existing.get("current_revision_no") or 0) + 1
        else:
            order_id = str(uuid.uuid4())
            revision_no = 1
            cursor.execute(
                """
                INSERT INTO orders (id, external_message_id, dedupe_key, current_revision_no, created_at, updated_at)
                VALUES (%s, %s, %s, 0, %s, %s)
                """,
                (order_id, external_message_id, dedupe_key, now, now),
            )

        revision_id = str(uuid.uuid4())
        cursor.execute(
            """
            INSERT INTO order_revisions (
                id, order_id, revision_no, change_type, changed_by_user_id, payload_json, diff_json, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)
            """,
            (
                revision_id,
                order_id,
                revision_no,
                change_type,
                changed_by_user_id,
                _jsonb(payload),
                _jsonb(diff_json),
                now,
            ),
        )
        cursor.execute(
            """
            UPDATE orders
            SET external_message_id = %s,
                received_at = %s,
                status = %s,
                reply_needed = %s,
                human_review_needed = %s,
                post_case = %s,
                ticket_number = %s,
                kundennummer = %s,
                kom_nr = %s,
                kom_name = %s,
                liefertermin = %s,
                wunschtermin = %s,
                delivery_week = %s,
                store_name = %s,
                store_address = %s,
                iln = %s,
                mail_to = %s,
                extraction_branch = %s,
                item_count = %s,
                warnings_count = %s,
                errors_count = %s,
                parse_error = %s,
                current_revision_id = %s,
                current_revision_no = %s,
                updated_at = %s
            WHERE id = %s
              AND deleted_at IS NULL
            """,
            (
                external_message_id,
                projection["received_at"],
                projection["status"],
                projection["reply_needed"],
                projection["human_review_needed"],
                projection["post_case"],
                projection["ticket_number"],
                projection["kundennummer"],
                projection["kom_nr"],
                projection["kom_name"],
                projection["liefertermin"],
                projection["wunschtermin"],
                projection["delivery_week"],
                projection["store_name"],
                projection["store_address"],
                projection["iln"],
                projection["mail_to"],
                projection["extraction_branch"],
                projection["item_count"],
                projection["warnings_count"],
                projection["errors_count"],
                projection["parse_error"],
                revision_id,
                revision_no,
                now,
                order_id,
            ),
        )
        cursor.execute(
            """
            INSERT INTO order_events (order_id, revision_id, event_type, actor_type, actor_user_id, event_data, created_at)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
            """,
            (
                order_id,
                revision_id,
                f"order_{change_type}",
                "user" if changed_by_user_id else "system",
                changed_by_user_id,
                _jsonb({"status": projection["status"]}),
                now,
            ),
        )
    _replace_messages(
        conn,
        order_id=order_id,
        revision_id=revision_id,
        warnings=payload.get("warnings", []),
        errors=payload.get("errors", []),
    )
    _replace_items(conn, order_id=order_id, items=payload.get("items", []))
    _ensure_task(conn, order_id=order_id, status=projection["status"], actor_user_id=changed_by_user_id)
    return {
        "order_id": order_id,
        "revision_id": revision_id,
        "revision_no": revision_no,
        "status": projection["status"],
    }


def upsert_order_payload(
    payload: dict[str, Any],
    *,
    external_message_id: str | None = None,
    change_type: str = "ingested",
    changed_by_user_id: str | None = None,
    parse_error: str | None = None,
    diff_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = _normalize_payload(payload)
    message_id = str(external_message_id or normalized.get("message_id") or uuid.uuid4())
    with get_connection() as conn:
        result = _upsert_revision(
            conn,
            payload=normalized,
            external_message_id=message_id,
            change_type=change_type,
            changed_by_user_id=changed_by_user_id,
            parse_error=parse_error,
            diff_json=diff_json,
        )
        conn.commit()
    return result


def mark_reply_email_sent(order_id: str, missing_fields: list[str]) -> None:
    now = _now()
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE orders
                SET reply_email_sent_at = %s,
                    waiting_for_client_reply = TRUE,
                    missing_fields_snapshot = %s,
                    status = %s,
                    updated_at = %s
                WHERE id = %s
                """,
                (now, missing_fields, STATUS_WAITING_REPLY, now, order_id),
            )
        conn.commit()


def find_reply_needed_order_by_kom(kom_number: str) -> dict[str, Any] | None:
    """Find an order that is awaiting or recently received a client reply, by KOM/ticket number.

    Looks back up to 14 days to also catch orders where the first reply was already
    processed (client_replied / updated_after_reply) so that follow-up emails can still
    be merged into the original order instead of creating a new one.
    """
    row = fetch_one(
        """
        SELECT id, status, missing_fields_snapshot, external_message_id
        FROM orders
        WHERE (
            waiting_for_client_reply = TRUE
            OR reply_needed = TRUE
            OR status IN ('waiting_for_reply', 'client_replied', 'updated_after_reply')
        )
          AND (kom_nr = %s OR ticket_number = %s)
          AND deleted_at IS NULL
          AND updated_at >= NOW() - INTERVAL '1 days'
        ORDER BY received_at DESC
        LIMIT 1
        """,
        (kom_number, kom_number),
    )
    return dict(row) if row else None


def find_order_awaiting_reply_by_kom(kom_number: str) -> dict[str, Any] | None:
    """Find an order awaiting or recently received a client reply, by KOM/ticket number.

    Like find_reply_needed_order_by_kom but used specifically for the Re: email path.
    Also covers recently-processed orders within 14 days so repeated replies work.
    """
    row = fetch_one(
        """
        SELECT id, status, missing_fields_snapshot, external_message_id
        FROM orders
        WHERE (
            waiting_for_client_reply = TRUE
            OR status IN ('waiting_for_reply', 'client_replied', 'updated_after_reply')
        )
          AND (kom_nr = %s OR ticket_number = %s)
          AND deleted_at IS NULL
          AND updated_at >= NOW() - INTERVAL '1 days'
        ORDER BY received_at DESC
        LIMIT 1
        """,
        (kom_number, kom_number),
    )
    return dict(row) if row else None


def reopen_waiting_for_reply(order_id: str, missing_fields: list[str]) -> None:
    """Re-mark an order as waiting for client reply after a partial follow-up.

    Called when a follow-up email was processed but some fields are still missing.
    Updates the missing_fields_snapshot without touching reply_email_sent_at.
    """
    now = _now()
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE orders
                SET waiting_for_client_reply = TRUE,
                    missing_fields_snapshot = %s,
                    status = %s,
                    updated_at = %s
                WHERE id = %s
                """,
                (missing_fields, STATUS_WAITING_REPLY, now, order_id),
            )
        conn.commit()


def get_order_current_payload(order_id: str) -> dict[str, Any] | None:
    row = fetch_one(
        """
        SELECT r.payload_json
        FROM order_revisions r
        WHERE r.order_id = %s
        ORDER BY r.revision_no DESC
        LIMIT 1
        """,
        (order_id,),
    )
    if not row:
        return None
    payload = row.get("payload_json")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = {}
    return payload if isinstance(payload, dict) else {}


def mark_client_replied(order_id: str, reply_message_id: str) -> None:
    now = _now()
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE orders
                SET waiting_for_client_reply = FALSE,
                    client_replied_at = %s,
                    client_reply_message_id = %s,
                    status = %s,
                    updated_at = %s
                WHERE id = %s
                """,
                (now, reply_message_id, STATUS_CLIENT_REPLIED, now, order_id),
            )
        conn.commit()


def mark_order_updated_after_reply(order_id: str) -> None:
    now = _now()
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE orders
                SET status = %s,
                    updated_at = %s
                WHERE id = %s
                """,
                (STATUS_UPDATED_AFTER_REPLY, now, order_id),
            )
        conn.commit()


def list_order_summaries() -> list[dict[str, Any]]:
    rows = fetch_all(
        """
        SELECT o.id,
               o.external_message_id,
               o.received_at,
               o.status,
               o.item_count,
               o.warnings_count,
               o.errors_count,
               o.ticket_number,
               o.kundennummer,
               o.kom_nr,
               o.kom_name,
               o.liefertermin,
               o.wunschtermin,
               o.delivery_week,
               o.store_name,
               o.store_address,
               o.iln,
               o.mail_to,
               o.extraction_branch,
               o.reply_needed,
               o.human_review_needed,
               o.post_case,
               o.parse_error,
               o.updated_at AS mtime
        FROM orders o
        WHERE o.deleted_at IS NULL
        ORDER BY COALESCE(o.received_at, o.updated_at) DESC
        """
    )
    return [_summary_row_to_order(row, status_field="status", branch_field="extraction_branch") for row in rows]


def _summary_row_to_order(
    row: dict[str, Any],
    *,
    status_field: str = "status",
    branch_field: str = "extraction_branch",
) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "file_name": str(row["id"]),
        "message_id": row.get("external_message_id") or str(row["id"]),
        "received_at": _to_iso(row.get("received_at")),
        "status": normalize_status(row.get(status_field)),
        "item_count": int(row.get("item_count") or 0),
        "warnings_count": int(row.get("warnings_count") or 0),
        "errors_count": int(row.get("errors_count") or 0),
        "warnings": [],
        "errors": [],
        "ticket_number": row.get("ticket_number") or "",
        "kundennummer": row.get("kundennummer") or "",
        "kom_nr": row.get("kom_nr") or "",
        "kom_name": row.get("kom_name") or "",
        "liefertermin": row.get("liefertermin") or "",
        "wunschtermin": row.get("wunschtermin") or "",
        "delivery_week": row.get("delivery_week") or "",
        "store_name": row.get("store_name") or "",
        "store_address": row.get("store_address") or "",
        "iln": row.get("iln") or "",
        "mail_to": row.get("mail_to") or "",
        "extraction_branch": _normalize_extraction_branch(row.get(branch_field)),
        "human_review_needed": bool(row.get("human_review_needed")),
        "reply_needed": bool(row.get("reply_needed")),
        "post_case": bool(row.get("post_case")),
        "reply_mailto": "",
        "parse_error": row.get("parse_error"),
        "mtime": row.get("mtime"),
    }


def _build_orders_where_clause(
    *,
    q: str,
    received_from: datetime | None,
    received_to: datetime | None,
    statuses: set[str] | None,
    reply_needed: bool | None,
    human_review_needed: bool | None,
    post_case: bool | None,
    client_branches: set[str] | None,
    assigned_user_id: str | None,
    allowed_client_branches: set[str] | None,
) -> tuple[str, list[Any]]:
    clauses = ["o.deleted_at IS NULL"]
    params: list[Any] = []

    query = str(q or "").strip()
    if query:
        like = f"%{query}%"
        clauses.append(
            """
            (
                o.ticket_number ILIKE %s
                OR o.kom_nr ILIKE %s
                OR o.kom_name ILIKE %s
                OR o.external_message_id ILIKE %s
                OR CAST(o.id AS TEXT) ILIKE %s
            )
            """
        )
        params.extend([like, like, like, like, like])

    if received_from is not None:
        clauses.append(f"{_EFFECTIVE_RECEIVED_SQL} >= %s")
        params.append(received_from)

    if received_to is not None:
        clauses.append(f"{_EFFECTIVE_RECEIVED_SQL} < %s")
        params.append(received_to)

    if statuses:
        normalized_statuses = sorted({normalize_status(status) for status in statuses})
        clauses.append(f"{_STATUS_SQL} = ANY(%s)")
        params.append(normalized_statuses)

    if reply_needed is not None:
        clauses.append("o.reply_needed = %s")
        params.append(bool(reply_needed))

    if human_review_needed is not None:
        clauses.append("o.human_review_needed = %s")
        params.append(bool(human_review_needed))

    if post_case is not None:
        clauses.append("o.post_case = %s")
        params.append(bool(post_case))

    normalized_branches = _normalize_branch_set(client_branches)
    if normalized_branches:
        clauses.append(f"{_EXTRACTION_BRANCH_SQL} = ANY(%s)")
        params.append(normalized_branches)

    scope_clauses, scope_params = _scope_where_fragments(
        assigned_user_id=assigned_user_id,
        allowed_client_branches=allowed_client_branches,
    )
    clauses.extend(scope_clauses)
    params.extend(scope_params)

    return " AND ".join(clauses), params


def query_order_summaries(
    *,
    q: str,
    received_from: datetime | None,
    received_to: datetime | None,
    statuses: set[str] | None,
    reply_needed: bool | None,
    human_review_needed: bool | None,
    post_case: bool | None,
    client_branches: set[str] | None,
    assigned_user_id: str | None,
    allowed_client_branches: set[str] | None,
    sort_key: str,
    page: int,
    page_size: int,
    paginate: bool,
    today_start: datetime,
    today_end: datetime,
    counts_override: dict[str, int] | None = None,
) -> dict[str, Any]:
    where_sql, where_params = _build_orders_where_clause(
        q=q,
        received_from=received_from,
        received_to=received_to,
        statuses=statuses,
        reply_needed=reply_needed,
        human_review_needed=human_review_needed,
        post_case=post_case,
        client_branches=client_branches,
        assigned_user_id=assigned_user_id,
        allowed_client_branches=allowed_client_branches,
    )
    order_direction = "ASC" if sort_key == "received_at_asc" else "DESC"

    counts_payload: dict[str, int]
    if counts_override is not None:
        counts_payload = {
            "total": int(counts_override.get("total") or 0),
            "today": int(counts_override.get("today") or 0),
            "needs_reply": int(counts_override.get("needs_reply") or 0),
            "manual_review": int(counts_override.get("manual_review") or 0),
            "status_ok": int(counts_override.get("status_ok") or 0),
            "status_reply": int(counts_override.get("status_reply") or 0),
            "status_human_in_the_loop": int(counts_override.get("status_human_in_the_loop") or 0),
            "status_post": int(counts_override.get("status_post") or 0),
            "status_failed": int(counts_override.get("status_failed") or 0),
        }
    else:
        counts_row = fetch_one(
            f"""
            SELECT COUNT(*)::bigint AS total,
                   SUM(CASE WHEN {_EFFECTIVE_RECEIVED_SQL} >= %s AND {_EFFECTIVE_RECEIVED_SQL} < %s THEN 1 ELSE 0 END)::bigint AS today,
                   SUM(CASE WHEN {_STATUS_SQL} = 'reply' THEN 1 ELSE 0 END)::bigint AS needs_reply,
                   SUM(CASE WHEN {_STATUS_SQL} = 'human_in_the_loop' THEN 1 ELSE 0 END)::bigint AS manual_review,
                   SUM(CASE WHEN {_STATUS_SQL} = 'ok' THEN 1 ELSE 0 END)::bigint AS status_ok,
                   SUM(CASE WHEN {_STATUS_SQL} = 'reply' THEN 1 ELSE 0 END)::bigint AS status_reply,
                   SUM(CASE WHEN {_STATUS_SQL} = 'human_in_the_loop' THEN 1 ELSE 0 END)::bigint AS status_human_in_the_loop,
                   SUM(CASE WHEN {_STATUS_SQL} = 'post' THEN 1 ELSE 0 END)::bigint AS status_post,
                   SUM(CASE WHEN {_STATUS_SQL} = 'failed' THEN 1 ELSE 0 END)::bigint AS status_failed
            FROM orders o
            WHERE {where_sql}
            """,
            [today_start, today_end, *where_params],
        ) or {}
        counts_payload = {
            "total": int(counts_row.get("total") or 0),
            "today": int(counts_row.get("today") or 0),
            "needs_reply": int(counts_row.get("needs_reply") or 0),
            "manual_review": int(counts_row.get("manual_review") or 0),
            "status_ok": int(counts_row.get("status_ok") or 0),
            "status_reply": int(counts_row.get("status_reply") or 0),
            "status_human_in_the_loop": int(counts_row.get("status_human_in_the_loop") or 0),
            "status_post": int(counts_row.get("status_post") or 0),
            "status_failed": int(counts_row.get("status_failed") or 0),
        }

    total = counts_payload["total"]
    if paginate:
        effective_page_size = max(1, page_size)
        total_pages = max(1, (total + effective_page_size - 1) // effective_page_size)
        effective_page = min(max(1, page), total_pages)
    else:
        effective_page_size = total if total > 0 else 1
        total_pages = 1
        effective_page = 1

    rows_query = f"""
        SELECT o.id,
               o.external_message_id,
               o.received_at,
               {_STATUS_SQL} AS normalized_status,
               o.item_count,
               o.warnings_count,
               o.errors_count,
               o.ticket_number,
               o.kundennummer,
               o.kom_nr,
               o.kom_name,
               o.liefertermin,
               o.wunschtermin,
               o.delivery_week,
               o.store_name,
               o.store_address,
               o.iln,
               o.mail_to,
               {_EXTRACTION_BRANCH_SQL} AS normalized_extraction_branch,
               o.reply_needed,
               o.human_review_needed,
               o.post_case,
               o.parse_error,
               o.updated_at AS mtime
        FROM orders o
        WHERE {where_sql}
        ORDER BY {_EFFECTIVE_RECEIVED_SQL} {order_direction}, o.id {order_direction}
    """
    row_params: list[Any] = list(where_params)
    if paginate:
        offset = (effective_page - 1) * effective_page_size
        rows_query += " LIMIT %s OFFSET %s"
        row_params.extend([effective_page_size, offset])
    rows = fetch_all(rows_query, row_params)

    orders = [
        _summary_row_to_order(row, status_field="normalized_status", branch_field="normalized_extraction_branch")
        for row in rows
    ]

    return {
        "orders": orders,
        "pagination": {
            "page": effective_page,
            "page_size": effective_page_size,
            "total": total,
            "total_pages": total_pages,
        },
        "counts": {
            "all": total,
            "today": counts_payload["today"],
            "needs_reply": counts_payload["needs_reply"],
            "manual_review": counts_payload["manual_review"],
            "status": {
                "ok": counts_payload["status_ok"],
                "reply": counts_payload["status_reply"],
                "human_in_the_loop": counts_payload["status_human_in_the_loop"],
                "post": counts_payload["status_post"],
                "failed": counts_payload["status_failed"],
                "total": total,
            },
        },
        "count_snapshot": counts_payload,
    }


def list_client_branch_counts(
    *,
    assigned_user_id: str | None = None,
    allowed_client_branches: set[str] | None = None,
) -> dict[str, int]:
    scope_clauses, scope_params = _scope_where_fragments(
        assigned_user_id=assigned_user_id,
        allowed_client_branches=allowed_client_branches,
    )
    where_sql = " AND ".join(["o.deleted_at IS NULL", *scope_clauses])
    rows = fetch_all(
        f"""
        SELECT {_EXTRACTION_BRANCH_SQL} AS branch_id,
               COUNT(*)::bigint AS total
        FROM orders o
        WHERE {where_sql}
        GROUP BY {_EXTRACTION_BRANCH_SQL}
        """,
        scope_params,
    )
    counts = {branch: 0 for branch in sorted(ALLOWED_EXTRACTION_BRANCHES)}
    for row in rows:
        branch_id = _normalize_extraction_branch(row.get("branch_id"))
        counts[branch_id] = int(row.get("total") or 0)
    return counts


def query_overview_snapshot(
    *,
    now: datetime,
    today_start: datetime,
    today_end: datetime,
    seven_day_start: datetime,
    last_24h_start: datetime,
    current_hour: datetime,
    hourly_start: datetime,
    assigned_user_id: str | None = None,
    allowed_client_branches: set[str] | None = None,
) -> dict[str, Any]:
    scope_clauses, scope_params = _scope_where_fragments(
        assigned_user_id=assigned_user_id,
        allowed_client_branches=allowed_client_branches,
    )
    where_sql = " AND ".join(["o.deleted_at IS NULL", *scope_clauses])
    join_scope_sql = ""
    if scope_clauses:
        join_scope_sql = " AND " + " AND ".join(scope_clauses)

    summary = fetch_one(
        f"""
        SELECT
            SUM(CASE WHEN {_EFFECTIVE_RECEIVED_SQL} >= %s AND {_EFFECTIVE_RECEIVED_SQL} < %s THEN 1 ELSE 0 END)::bigint AS today_total,
            SUM(CASE WHEN {_EFFECTIVE_RECEIVED_SQL} >= %s AND {_EFFECTIVE_RECEIVED_SQL} < %s AND {_STATUS_SQL} = 'ok' THEN 1 ELSE 0 END)::bigint AS today_ok,
            SUM(CASE WHEN {_EFFECTIVE_RECEIVED_SQL} >= %s AND {_EFFECTIVE_RECEIVED_SQL} < %s AND {_STATUS_SQL} = 'reply' THEN 1 ELSE 0 END)::bigint AS today_reply,
            SUM(CASE WHEN {_EFFECTIVE_RECEIVED_SQL} >= %s AND {_EFFECTIVE_RECEIVED_SQL} < %s AND {_STATUS_SQL} = 'human_in_the_loop' THEN 1 ELSE 0 END)::bigint AS today_human,
            SUM(CASE WHEN {_EFFECTIVE_RECEIVED_SQL} >= %s AND {_EFFECTIVE_RECEIVED_SQL} < %s AND {_STATUS_SQL} = 'post' THEN 1 ELSE 0 END)::bigint AS today_post,
            SUM(CASE WHEN {_EFFECTIVE_RECEIVED_SQL} >= %s AND {_EFFECTIVE_RECEIVED_SQL} < %s AND {_STATUS_SQL} = 'failed' THEN 1 ELSE 0 END)::bigint AS today_failed,
            SUM(CASE WHEN {_EFFECTIVE_RECEIVED_SQL} >= %s AND {_EFFECTIVE_RECEIVED_SQL} < %s THEN 1 ELSE 0 END)::bigint AS last24_total,
            SUM(CASE WHEN {_EFFECTIVE_RECEIVED_SQL} >= %s AND {_EFFECTIVE_RECEIVED_SQL} < %s AND {_STATUS_SQL} = 'ok' THEN 1 ELSE 0 END)::bigint AS last24_ok,
            SUM(CASE WHEN {_EFFECTIVE_RECEIVED_SQL} >= %s AND {_EFFECTIVE_RECEIVED_SQL} < %s AND {_STATUS_SQL} = 'reply' THEN 1 ELSE 0 END)::bigint AS last24_reply,
            SUM(CASE WHEN {_EFFECTIVE_RECEIVED_SQL} >= %s AND {_EFFECTIVE_RECEIVED_SQL} < %s AND {_STATUS_SQL} = 'human_in_the_loop' THEN 1 ELSE 0 END)::bigint AS last24_human,
            SUM(CASE WHEN {_EFFECTIVE_RECEIVED_SQL} >= %s AND {_EFFECTIVE_RECEIVED_SQL} < %s AND {_STATUS_SQL} = 'post' THEN 1 ELSE 0 END)::bigint AS last24_post,
            SUM(CASE WHEN {_EFFECTIVE_RECEIVED_SQL} >= %s AND {_EFFECTIVE_RECEIVED_SQL} < %s AND {_STATUS_SQL} = 'failed' THEN 1 ELSE 0 END)::bigint AS last24_failed,
            SUM(CASE WHEN {_STATUS_SQL} = 'reply' THEN 1 ELSE 0 END)::bigint AS queue_reply,
            SUM(CASE WHEN {_STATUS_SQL} = 'human_in_the_loop' THEN 1 ELSE 0 END)::bigint AS queue_human,
            SUM(CASE WHEN {_STATUS_SQL} = 'post' THEN 1 ELSE 0 END)::bigint AS queue_post
        FROM orders o
        WHERE {where_sql}
        """,
        [
            today_start,
            today_end,
            today_start,
            today_end,
            today_start,
            today_end,
            today_start,
            today_end,
            today_start,
            today_end,
            today_start,
            today_end,
            last_24h_start,
            now,
            last_24h_start,
            now,
            last_24h_start,
            now,
            last_24h_start,
            now,
            last_24h_start,
            now,
            last_24h_start,
            now,
            *scope_params,
        ],
    ) or {}

    day_rows = fetch_all(
        f"""
        WITH day_buckets AS (
            SELECT generate_series(%s::timestamptz, %s::timestamptz, interval '1 day') AS bucket_start
        )
        SELECT b.bucket_start,
               SUM(CASE WHEN o.id IS NOT NULL AND {_STATUS_SQL} = 'ok' THEN 1 ELSE 0 END)::bigint AS ok,
               SUM(CASE WHEN o.id IS NOT NULL AND {_STATUS_SQL} = 'reply' THEN 1 ELSE 0 END)::bigint AS reply,
               SUM(CASE WHEN o.id IS NOT NULL AND {_STATUS_SQL} = 'human_in_the_loop' THEN 1 ELSE 0 END)::bigint AS human_in_the_loop,
               SUM(CASE WHEN o.id IS NOT NULL AND {_STATUS_SQL} = 'post' THEN 1 ELSE 0 END)::bigint AS post,
               SUM(CASE WHEN o.id IS NOT NULL AND {_STATUS_SQL} = 'failed' THEN 1 ELSE 0 END)::bigint AS failed,
               COUNT(o.id)::bigint AS total
        FROM day_buckets b
        LEFT JOIN orders o
          ON o.deleted_at IS NULL
         AND {_EFFECTIVE_RECEIVED_SQL} >= b.bucket_start
         AND {_EFFECTIVE_RECEIVED_SQL} < b.bucket_start + interval '1 day'
         {join_scope_sql}
        GROUP BY b.bucket_start
        ORDER BY b.bucket_start
        """,
        [seven_day_start, today_start, *scope_params],
    )

    hour_rows = fetch_all(
        f"""
        WITH hour_buckets AS (
            SELECT generate_series(%s::timestamptz, %s::timestamptz, interval '1 hour') AS bucket_start
        )
        SELECT b.bucket_start,
               COUNT(o.id)::bigint AS processed
        FROM hour_buckets b
        LEFT JOIN orders o
          ON o.deleted_at IS NULL
         AND {_EFFECTIVE_RECEIVED_SQL} >= b.bucket_start
         AND {_EFFECTIVE_RECEIVED_SQL} < b.bucket_start + interval '1 hour'
         {join_scope_sql}
        GROUP BY b.bucket_start
        ORDER BY b.bucket_start
        """,
        [hourly_start, current_hour, *scope_params],
    )

    return {
        "summary": {
            "today_total": int(summary.get("today_total") or 0),
            "today_ok": int(summary.get("today_ok") or 0),
            "today_reply": int(summary.get("today_reply") or 0),
            "today_human": int(summary.get("today_human") or 0),
            "today_post": int(summary.get("today_post") or 0),
            "today_failed": int(summary.get("today_failed") or 0),
            "last24_total": int(summary.get("last24_total") or 0),
            "last24_ok": int(summary.get("last24_ok") or 0),
            "last24_reply": int(summary.get("last24_reply") or 0),
            "last24_human": int(summary.get("last24_human") or 0),
            "last24_post": int(summary.get("last24_post") or 0),
            "last24_failed": int(summary.get("last24_failed") or 0),
            "queue_reply": int(summary.get("queue_reply") or 0),
            "queue_human": int(summary.get("queue_human") or 0),
            "queue_post": int(summary.get("queue_post") or 0),
        },
        "status_by_day": [
            {
                "bucket_start": row.get("bucket_start"),
                "ok": int(row.get("ok") or 0),
                "reply": int(row.get("reply") or 0),
                "human_in_the_loop": int(row.get("human_in_the_loop") or 0),
                "post": int(row.get("post") or 0),
                "failed": int(row.get("failed") or 0),
                "total": int(row.get("total") or 0),
            }
            for row in day_rows
        ],
        "processed_by_hour": [
            {
                "bucket_start": row.get("bucket_start"),
                "processed": int(row.get("processed") or 0),
            }
            for row in hour_rows
        ],
    }


def get_order_detail(
    order_id: str,
    *,
    assigned_user_id: str | None = None,
    allowed_client_branches: set[str] | None = None,
) -> dict[str, Any] | None:
    where_parts = [
        "o.id = %s",
        "o.deleted_at IS NULL",
    ]
    params: list[Any] = [order_id]
    scope_clauses, scope_params = _scope_where_fragments(
        assigned_user_id=assigned_user_id,
        allowed_client_branches=allowed_client_branches,
    )
    where_parts.extend(scope_clauses)
    params.extend(scope_params)
    where_sql = " AND ".join(where_parts)

    row = fetch_one(
        f"""
        SELECT o.*,
               r.payload_json,
               t.id AS review_task_id,
               t.state AS review_state,
               t.assigned_user_id,
               t.claim_expires_at,
               t.due_at AS sla_due_at,
               u.username AS assigned_username,
               e.last_event_at
        FROM orders o
        LEFT JOIN order_revisions r ON r.id = o.current_revision_id
        LEFT JOIN LATERAL (
            SELECT t1.*
            FROM order_review_tasks t1
            WHERE t1.order_id = o.id
              AND t1.state NOT IN ('resolved', 'cancelled')
            ORDER BY t1.created_at DESC
            LIMIT 1
        ) t ON TRUE
        LEFT JOIN users u ON u.id = t.assigned_user_id
        LEFT JOIN LATERAL (
            SELECT MAX(created_at) AS last_event_at
            FROM order_events e1
            WHERE e1.order_id = o.id
        ) e ON TRUE
        WHERE {where_sql}
        """,
        params,
    )
    if not row:
        return None

    payload = row.get("payload_json")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload = _normalize_payload(payload)

    warnings = payload.get("warnings", [])
    errors = payload.get("errors", [])
    return {
        "safe_id": str(row["id"]),
        "data": payload,
        "parse_error": row.get("parse_error"),
        "header": payload.get("header") if isinstance(payload.get("header"), dict) else {},
        "items": payload.get("items") if isinstance(payload.get("items"), list) else [],
        "warnings": [str(item) for item in warnings] if isinstance(warnings, list) else [],
        "errors": [str(item) for item in errors] if isinstance(errors, list) else [],
        "status": normalize_status(row.get("status")),
        "human_review_needed": bool(row.get("human_review_needed")),
        "reply_needed": bool(row.get("reply_needed")),
        "post_case": bool(row.get("post_case")),
        "message_id": row.get("external_message_id") or str(row["id"]),
        "received_at": _to_iso(row.get("received_at")),
        "review_task_id": str(row["review_task_id"]) if row.get("review_task_id") else None,
        "review_state": row.get("review_state"),
        "assigned_user_id": str(row["assigned_user_id"]) if row.get("assigned_user_id") else None,
        "assigned_user": row.get("assigned_username"),
        "claim_expires_at": _to_iso(row.get("claim_expires_at")) if row.get("claim_expires_at") else None,
        "sla_due_at": _to_iso(row.get("sla_due_at")) if row.get("sla_due_at") else None,
        "last_event_at": _to_iso(row.get("last_event_at")) if row.get("last_event_at") else None,
    }


def get_order_payload_map(order_ids: list[str]) -> dict[str, dict[str, Any]]:
    cleaned_ids = [str(order_id).strip() for order_id in order_ids if str(order_id).strip()]
    if not cleaned_ids:
        return {}
    unique_ids = list(dict.fromkeys(cleaned_ids))
    rows = fetch_all(
        """
        SELECT o.id,
               o.parse_error,
               r.payload_json
        FROM orders o
        LEFT JOIN order_revisions r ON r.id = o.current_revision_id
        WHERE o.deleted_at IS NULL
          AND o.id = ANY(%s)
        """,
        (unique_ids,),
    )
    payload_map: dict[str, dict[str, Any]] = {}
    for row in rows:
        payload = row.get("payload_json")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = {}
        if not isinstance(payload, dict):
            payload = {}
        payload_map[str(row["id"])] = {
            "data": _normalize_payload(payload),
            "parse_error": row.get("parse_error"),
        }
    return payload_map


def is_order_editable_for_detail(
    *,
    order: dict[str, Any] | None,
    user_id: str,
    is_admin: bool,
) -> tuple[bool, str]:
    _ = user_id, is_admin
    if not order:
        return False, "Order not found"
    if order.get("parse_error"):
        return False, "Order payload could not be parsed"
    return True, ""


def is_order_editable_for_user(*, order_id: str, user_id: str, is_admin: bool) -> tuple[bool, str]:
    order = get_order_detail(order_id)
    return is_order_editable_for_detail(order=order, user_id=user_id, is_admin=is_admin)


def save_manual_revision(
    *,
    order_id: str,
    payload: dict[str, Any],
    actor_user_id: str,
    diff_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    existing = get_order_detail(order_id)
    if not existing:
        raise OrderStoreError(404, "not_found", "Order not found")
    payload_with_branch = dict(payload or {})
    if "extraction_branch" not in payload_with_branch:
        existing_data = existing.get("data")
        existing_branch = ""
        if isinstance(existing_data, dict):
            existing_branch = str(existing_data.get("extraction_branch") or "")
        payload_with_branch["extraction_branch"] = _normalize_extraction_branch(existing_branch)
    with get_connection() as conn:
        result = _upsert_revision(
            conn,
            payload=_normalize_payload(payload_with_branch),
            external_message_id=str(existing.get("message_id") or order_id),
            change_type="manual_edit",
            changed_by_user_id=actor_user_id,
            parse_error=None,
            diff_json=diff_json,
        )
        conn.commit()
    return result


def soft_delete_order(*, order_id: str, actor_user_id: str | None) -> bool:
    detail = get_order_detail(order_id)
    if not detail:
        return False
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM orders WHERE id = %s", (order_id,))
        conn.commit()
    return True


def record_order_event(
    *,
    order_id: str,
    event_type: str,
    actor_user_id: str | None = None,
    actor_type: str | None = None,
    revision_id: str | None = None,
    event_data: dict[str, Any] | None = None,
) -> None:
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO order_events (order_id, revision_id, event_type, actor_type, actor_user_id, event_data, created_at)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
                """,
                (
                    order_id,
                    revision_id,
                    event_type,
                    actor_type or ("user" if actor_user_id else "system"),
                    actor_user_id,
                    _jsonb(event_data),
                    _now(),
                ),
            )
        conn.commit()


def _checksum(path: Path) -> tuple[str, int]:
    hasher = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            hasher.update(chunk)
    return hasher.hexdigest(), size


def register_order_files(*, order_id: str, revision_id: str | None, file_type: str, storage_paths: list[str]) -> None:
    now = _now()
    with get_connection() as conn:
        with conn.cursor() as cursor:
            for storage_path in storage_paths:
                if not storage_path:
                    continue
                path = Path(storage_path)
                checksum = ""
                size = 0
                if path.exists() and path.is_file():
                    try:
                        checksum, size = _checksum(path)
                    except OSError:
                        checksum, size = "", 0
                cursor.execute(
                    """
                    INSERT INTO order_files (id, order_id, revision_id, file_type, storage_path, checksum_sha256, size_bytes, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (str(uuid.uuid4()), order_id, revision_id, file_type, storage_path, checksum, size, now),
                )
        conn.commit()


def list_review_tasks(
    *,
    states: set[str] | None = None,
    assigned_user_id: str | None = None,
    include_unassigned: bool = True,
    allowed_client_branches: set[str] | None = None,
) -> list[dict[str, Any]]:
    where_parts = ["o.deleted_at IS NULL"]
    params: list[Any] = []
    if states:
        where_parts.append("t.state = ANY(%s)")
        params.append(list(states))
    else:
        where_parts.append("t.state NOT IN ('resolved', 'cancelled')")
    if assigned_user_id:
        if include_unassigned:
            where_parts.append("(t.assigned_user_id = %s OR t.assigned_user_id IS NULL)")
        else:
            where_parts.append("t.assigned_user_id = %s")
        params.append(assigned_user_id)
    normalized_branches = _normalize_branch_set(allowed_client_branches)
    if normalized_branches is not None:
        if not normalized_branches:
            where_parts.append("1 = 0")
        else:
            where_parts.append(f"{_EXTRACTION_BRANCH_SQL} = ANY(%s)")
            params.append(normalized_branches)
    where_sql = " AND ".join(where_parts)
    rows = fetch_all(
        f"""
        SELECT t.id,
               t.order_id,
               t.task_type,
               t.state,
               t.priority,
               t.assigned_user_id,
               t.claimed_at,
               t.claim_expires_at,
               t.due_at,
               t.resolved_at,
               t.resolution_outcome,
               t.resolution_note,
               t.created_at,
               t.updated_at,
               u.username AS assigned_username,
               o.status AS order_status,
               o.external_message_id,
               o.ticket_number,
               o.kom_nr,
               o.kom_name
        FROM order_review_tasks t
        JOIN orders o ON o.id = t.order_id
        LEFT JOIN users u ON u.id = t.assigned_user_id
        WHERE {where_sql}
        ORDER BY
            CASE t.state
                WHEN 'claimed' THEN 0
                WHEN 'in_progress' THEN 1
                WHEN 'queued' THEN 2
                ELSE 3
            END,
            t.priority ASC,
            COALESCE(t.due_at, t.created_at) ASC
        """,
        params,
    )
    tasks: list[dict[str, Any]] = []
    for row in rows:
        tasks.append(
            {
                "id": str(row["id"]),
                "order_id": str(row["order_id"]),
                "task_type": row.get("task_type"),
                "state": row.get("state"),
                "priority": int(row.get("priority") or 0),
                "assigned_user_id": str(row["assigned_user_id"]) if row.get("assigned_user_id") else None,
                "assigned_user": row.get("assigned_username"),
                "claimed_at": _to_iso(row.get("claimed_at")) if row.get("claimed_at") else None,
                "claim_expires_at": _to_iso(row.get("claim_expires_at")) if row.get("claim_expires_at") else None,
                "due_at": _to_iso(row.get("due_at")) if row.get("due_at") else None,
                "resolved_at": _to_iso(row.get("resolved_at")) if row.get("resolved_at") else None,
                "resolution_outcome": row.get("resolution_outcome"),
                "resolution_note": row.get("resolution_note"),
                "created_at": _to_iso(row.get("created_at")) if row.get("created_at") else None,
                "updated_at": _to_iso(row.get("updated_at")) if row.get("updated_at") else None,
                "order_status": normalize_status(row.get("order_status")),
                "message_id": row.get("external_message_id"),
                "ticket_number": row.get("ticket_number") or "",
                "kom_nr": row.get("kom_nr") or "",
                "kom_name": row.get("kom_name") or "",
            }
        )
    return tasks


def _load_task_for_update(conn, task_id: str) -> dict[str, Any] | None:
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM order_review_tasks WHERE id = %s FOR UPDATE", (task_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def _task_by_id(task_id: str) -> dict[str, Any] | None:
    items = [task for task in list_review_tasks() if task["id"] == task_id]
    return items[0] if items else None


def claim_task(*, task_id: str, user_id: str, lease_seconds: int = 300) -> dict[str, Any]:
    now = _now()
    lease_seconds = max(30, min(3600, int(lease_seconds)))
    lease_until = now + timedelta(seconds=lease_seconds)
    with get_connection() as conn:
        task = _load_task_for_update(conn, task_id)
        if not task:
            raise OrderStoreError(404, "not_found", "Review task not found")
        if task.get("state") in TASK_DONE_STATES:
            raise OrderStoreError(409, "conflict", "Review task is already resolved")
        assigned_user_id = str(task.get("assigned_user_id") or "")
        claim_expires = task.get("claim_expires_at")
        active_other_claim = (
            assigned_user_id
            and assigned_user_id != user_id
            and isinstance(claim_expires, datetime)
            and claim_expires > now
        )
        if active_other_claim:
            raise OrderStoreError(409, "conflict", "Task is currently claimed by another reviewer")

        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE order_review_tasks
                SET assigned_user_id = %s,
                    state = 'claimed',
                    claimed_at = COALESCE(claimed_at, %s),
                    claim_expires_at = %s,
                    updated_at = %s
                WHERE id = %s
                """,
                (user_id, now, lease_until, now, task_id),
            )
            cursor.execute(
                """
                INSERT INTO order_events (order_id, revision_id, event_type, actor_type, actor_user_id, event_data, created_at)
                VALUES (%s, NULL, 'review_task_claimed', 'user', %s, %s::jsonb, %s)
                """,
                (task["order_id"], user_id, _jsonb({"task_id": task_id, "claim_expires_at": lease_until.isoformat()}), now),
            )
        conn.commit()
    claimed = _task_by_id(task_id)
    if not claimed:
        raise OrderStoreError(500, "internal_error", "Claim succeeded but task reload failed")
    return claimed


def heartbeat_task(*, task_id: str, user_id: str, lease_seconds: int = 300) -> dict[str, Any]:
    now = _now()
    lease_seconds = max(30, min(3600, int(lease_seconds)))
    lease_until = now + timedelta(seconds=lease_seconds)
    with get_connection() as conn:
        task = _load_task_for_update(conn, task_id)
        if not task:
            raise OrderStoreError(404, "not_found", "Review task not found")
        if task.get("state") in TASK_DONE_STATES:
            raise OrderStoreError(409, "conflict", "Review task is already resolved")
        if str(task.get("assigned_user_id") or "") != user_id:
            raise OrderStoreError(403, "forbidden", "Task is assigned to another reviewer")
        expires_at = task.get("claim_expires_at")
        if not isinstance(expires_at, datetime) or expires_at <= now:
            raise OrderStoreError(403, "forbidden", "Task claim has expired")
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE order_review_tasks
                SET state = 'in_progress',
                    claim_expires_at = %s,
                    updated_at = %s
                WHERE id = %s
                """,
                (lease_until, now, task_id),
            )
            cursor.execute(
                """
                INSERT INTO order_events (order_id, revision_id, event_type, actor_type, actor_user_id, event_data, created_at)
                VALUES (%s, NULL, 'review_task_heartbeat', 'user', %s, %s::jsonb, %s)
                """,
                (task["order_id"], user_id, _jsonb({"task_id": task_id, "claim_expires_at": lease_until.isoformat()}), now),
            )
        conn.commit()
    heartbeat = _task_by_id(task_id)
    if not heartbeat:
        raise OrderStoreError(500, "internal_error", "Heartbeat succeeded but task reload failed")
    return heartbeat


def resolve_task(
    *,
    task_id: str,
    user_id: str,
    is_admin: bool,
    outcome: str,
    note: str,
    force: bool = False,
) -> dict[str, Any]:
    now = _now()
    outcome_text = (outcome or "resolved").strip() or "resolved"
    note_text = (note or "").strip()
    with get_connection() as conn:
        task = _load_task_for_update(conn, task_id)
        if not task:
            raise OrderStoreError(404, "not_found", "Review task not found")
        if task.get("state") in TASK_DONE_STATES:
            raise OrderStoreError(409, "conflict", "Review task is already resolved")
        if not is_admin and str(task.get("assigned_user_id") or "") != user_id:
            raise OrderStoreError(403, "forbidden", "Only the assigned reviewer can resolve this task")
        if force and not is_admin:
            raise OrderStoreError(403, "forbidden", "Force resolve requires admin role")
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE order_review_tasks
                SET state = 'resolved',
                    resolved_at = %s,
                    resolution_outcome = %s,
                    resolution_note = %s,
                    claim_expires_at = NULL,
                    updated_at = %s
                WHERE id = %s
                """,
                (now, outcome_text, note_text, now, task_id),
            )
            cursor.execute(
                """
                INSERT INTO order_events (order_id, revision_id, event_type, actor_type, actor_user_id, event_data, created_at)
                VALUES (%s, NULL, 'review_task_resolved', %s, %s, %s::jsonb, %s)
                """,
                (
                    task["order_id"],
                    "user" if user_id else "system",
                    user_id,
                    _jsonb({"task_id": task_id, "outcome": outcome_text, "force": bool(force)}),
                    now,
                ),
            )
        conn.commit()
    resolved = _task_by_id(task_id)
    if resolved:
        return resolved
    return {
        "id": task_id,
        "order_id": str(task["order_id"]),
        "state": "resolved",
        "resolution_outcome": outcome_text,
        "resolution_note": note_text,
        "resolved_at": now.isoformat(),
    }
