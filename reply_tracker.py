"""reply_tracker.py — Handles incoming client reply emails for the reply-to-order workflow.

Detects client reply emails by subject pattern, extracts the KOM number,
matches to an order with waiting_for_client_reply=True, extracts missing
fields via OpenAI, merges them into the order payload, regenerates XMLs,
and updates the order status.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any

from config import Config
from email_ingest import IngestedEmail
from gemini_validation import GeminiValidator, build_validation_error_result
from openai_extract import OpenAIExtractor
import order_store
import xml_exporter
from reply_email import detect_missing_fields, send_email_via_smtp

_REPLY_WINDOW_DAYS = 14


_KOM_FROM_SUBJECT_RE = re.compile(
    r'(?:Re:\s*)?Ruckfrage\s+zu\s+Ihrer\s+Bestellung\s+(.+?)\s+-\s+',
    re.IGNORECASE,
)

# Matches new emails like "Bestellung 20-634616-12." or "Bestellung 20-634616-12"
_BESTELLUNG_KOM_RE = re.compile(
    r'Bestellung\s+([\w][\w\-\.]*\d)',
    re.IGNORECASE,
)

# Matches a bare KOM/order number anywhere in the subject, e.g. "20-634616-12" or "AW: 20-634616-12"
_BARE_KOM_RE = re.compile(
    r'\b(\d{2,3}-\d{4,}-\d{1,})\b',
    re.IGNORECASE,
)

# Matches "Ihre Bestellung" or "IhreBestellung" followed by a KOM number
_IHRE_BESTELLUNG_KOM_RE = re.compile(
    r'Ihre\s+Bestellung\s+([\w][\w\-\.]*\d)',
    re.IGNORECASE,
)

# Matches Porta-style "KV:2881634" or "KV 2881634" prefix (Kommissionsvorgang)
_KV_KOM_RE = re.compile(
    r'\bKV[:\s]+(\d+)',
    re.IGNORECASE,
)

_REPLY_EXTRACT_SYSTEM_PROMPT = (
    "You are an order data extraction assistant. "
    "Extract only the specified fields from the client's reply email. "
    "Return a JSON object. Header fields (lieferanschrift, store_address, etc.) go at the top level. "
    "For item-level fields (modellnummer, artikelnummer, menge), return an 'items' array. "
    "IMPORTANT: each item element MUST include BOTH 'artikelnummer' AND 'modellnummer' as reference keys "
    "whenever either value is mentioned in the email, even if that field is not in the requested fields list. "
    "This is required so items can be matched to the order. "
    "If a field cannot be found at all, omit it. Example: "
    '{\"lieferanschrift\": \"Musterstr. 1\", \"items\": [{\"artikelnummer\": \"30156\", \"modellnummer\": \"CJOO\"}]}'
)


def is_client_reply(message: IngestedEmail) -> bool:
    """Return True if this email looks like a client reply to a Ruckfrage email."""
    return bool(_KOM_FROM_SUBJECT_RE.search(message.subject or ""))


def _extract_kom_number_from_subject(subject: str) -> str:
    match = _KOM_FROM_SUBJECT_RE.search(subject or "")
    if match:
        return match.group(1).strip()
    return ""


def extract_kom_from_bestellung_subject(subject: str) -> str:
    """Extract KOM number from a subject line.

    Tries multiple patterns in priority order:
    1. 'Bestellung {KOM}'
    2. 'Ihre Bestellung {KOM}'
    3. Bare KOM number like '20-634616-12' anywhere in subject
    """
    s = subject or ""
    for pattern in (_BESTELLUNG_KOM_RE, _IHRE_BESTELLUNG_KOM_RE, _KV_KOM_RE, _BARE_KOM_RE):
        match = pattern.search(s)
        if match:
            return match.group(1).strip().rstrip(".")
    return ""


def _is_missing(value: Any) -> bool:
    if isinstance(value, dict):
        value = value.get("value")
    return str(value or "").strip() == ""


def _extract_missing_fields_via_openai(
    extractor: OpenAIExtractor,
    reply_body: str,
    missing_fields: list[str],
    message_id: str,
) -> dict[str, Any]:
    """Call OpenAI to extract only the missing fields from the reply body.

    Returns a dict which may contain top-level header fields and an optional
    'items' list with per-item data keyed by artikelnummer.
    """
    header_fields = [f for f in missing_fields if f not in ("modellnummer", "artikelnummer", "menge")]
    item_fields = [f for f in missing_fields if f in ("modellnummer", "artikelnummer", "menge")]

    parts = []
    if header_fields:
        parts.append(f"Header fields: {', '.join(header_fields)}")
    if item_fields:
        parts.append(
            f"Item-level fields: {', '.join(item_fields)} — "
            "return these as an 'items' array where each element has 'artikelnummer' "
            "and the provided item-level fields"
        )
    field_description = "; ".join(parts) if parts else ", ".join(missing_fields)

    user_instructions = (
        f"Extract the following fields from the client reply email below.\n"
        f"{field_description}.\n"
        "Values should be plain strings.\n\n"
        f"Client reply:\n{reply_body}"
    )
    try:
        raw = extractor.extract_with_prompts(
            message_id=message_id,
            received_at="",
            email_text=reply_body,
            images=[],
            source_priority=[],
            subject="",
            sender="",
            system_prompt=_REPLY_EXTRACT_SYSTEM_PROMPT,
            user_instructions=user_instructions,
        )
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
            text = re.sub(r"\n?```$", "", text)
        return json.loads(text)
    except Exception as exc:
        print(f"[reply_tracker] OpenAI extraction failed for {message_id}: {exc}")
        return {}


_STALE_WARNING_PREFIXES = (
    "Missing critical header fields:",
    "Missing critical item fields:",
    "Missing item fields:",
    "Reply needed: Missing critical header fields:",
    "Reply needed: Missing critical item fields:",
    "Reply needed:",
)


def _prepare_xml_documents_and_validation(
    *,
    config: Config,
    validator: GeminiValidator | None,
    message: IngestedEmail,
    payload: dict[str, Any],
    output_name: str,
) -> tuple[list[xml_exporter.XmlDocument], dict[str, Any] | None]:
    xml_documents: list[xml_exporter.XmlDocument] = []
    validation_result: dict[str, Any] | None = None
    try:
        xml_documents = xml_exporter.render_xml_documents(payload, output_name, config, config.output_dir)
        if validator is not None:
            validation_result = validator.validate_order(
                message=message,
                branch_id=str(payload.get("extraction_branch") or "").strip(),
                normalized=payload,
                xml_documents=xml_documents,
            )
    except Exception as exc:
        print(f"[reply_tracker] Failed to prepare XML documents for validation: {exc}")
        if validator is not None:
            validation_result = build_validation_error_result(
                f"Gemini validation skipped because XML rendering failed: {exc}",
                model=config.gemini_model,
            )
    return xml_documents, validation_result


def _strip_stale_field_warnings(payload: dict[str, Any]) -> None:
    """Remove field-related warning entries that may be stale after a reply merge.

    Only strips warnings about specific missing-field conditions — leaves all
    other warnings (routing, ticket, etc.) intact.
    """
    warnings = payload.get("warnings")
    if not isinstance(warnings, list):
        return
    payload["warnings"] = [
        w for w in warnings
        if not (isinstance(w, str) and any(w.startswith(p) for p in _STALE_WARNING_PREFIXES))
    ]


def _merge_reply_fields(
    payload: dict[str, Any],
    extracted_fields: dict[str, Any],
) -> dict[str, Any]:
    """Merge extracted reply fields into payload — only fills missing slots, never overwrites.

    extracted_fields may contain top-level header fields and an optional 'items' list
    with per-item data keyed by artikelnummer.
    """
    header = payload.get("header")
    if not isinstance(header, dict):
        header = {}
        payload["header"] = header

    items = payload.get("items")
    if not isinstance(items, list):
        items = []
        payload["items"] = items

    _ITEM_LEVEL_FIELDS = {"modellnummer", "artikelnummer", "menge"}

    # Merge header-level fields
    for field_name, value in extracted_fields.items():
        if field_name == "items":
            continue
        if not value or not str(value).strip():
            continue
        if field_name in _ITEM_LEVEL_FIELDS:
            continue
        value_str = str(value).strip()
        if field_name in ("lieferanschrift", "store_address"):
            if _is_missing(header.get(field_name)):
                header[field_name] = {"value": value_str, "source": "reply_email", "confidence": 0.9}
        elif _is_missing(header.get(field_name)):
            header[field_name] = {"value": value_str, "source": "reply_email", "confidence": 0.9}

    # Merge item-level fields from structured 'items' list
    # Matching strategy (in priority order):
    #   1. By artikelnummer (both sides must be non-empty and equal)
    #   2. By modellnummer fallback (handles the case where artikelnummer IS the missing field)
    extracted_items = extracted_fields.get("items")
    if isinstance(extracted_items, list):
        for ext_item in extracted_items:
            if not isinstance(ext_item, dict):
                continue
            ext_art = str(ext_item.get("artikelnummer") or "").strip()
            ext_mod = str(ext_item.get("modellnummer") or "").strip()

            matched_item = None

            # Strategy 1: match by artikelnummer
            if ext_art:
                for ex_item in items:
                    if not isinstance(ex_item, dict):
                        continue
                    ex_art = str(
                        (ex_item.get("artikelnummer", {}).get("value")
                         if isinstance(ex_item.get("artikelnummer"), dict)
                         else ex_item.get("artikelnummer")) or ""
                    ).strip()
                    if ex_art and ex_art == ext_art:
                        matched_item = ex_item
                        break

            # Strategy 2: match by modellnummer (fallback when artikelnummer is the missing field)
            if matched_item is None and ext_mod:
                for ex_item in items:
                    if not isinstance(ex_item, dict):
                        continue
                    ex_mod = str(
                        (ex_item.get("modellnummer", {}).get("value")
                         if isinstance(ex_item.get("modellnummer"), dict)
                         else ex_item.get("modellnummer")) or ""
                    ).strip()
                    if ex_mod and ex_mod == ext_mod:
                        matched_item = ex_item
                        break

            if matched_item is not None:
                for field_name in ("modellnummer", "artikelnummer", "menge"):
                    ext_val = str(ext_item.get(field_name) or "").strip()
                    if ext_val and _is_missing(matched_item.get(field_name)):
                        matched_item[field_name] = {"value": ext_val, "source": "reply_email", "confidence": 0.9}

    # Strip stale field-missing warnings before checking remaining fields
    _strip_stale_field_warnings(payload)

    # Clear reply_needed if all fields are now filled (check actual values only, not stale warnings)
    remaining = detect_missing_fields(payload, [])
    if not remaining:
        reply_entry = header.get("reply_needed")
        if isinstance(reply_entry, dict):
            reply_entry["value"] = False
            reply_entry["source"] = "reply_email"
            reply_entry["confidence"] = 1.0
        else:
            header["reply_needed"] = {"value": False, "source": "reply_email", "confidence": 1.0}

    return payload


_HEADER_FIELDS = (
    "lieferanschrift", "store_address", "kom_nr", "ticket_number",
    "kundennummer", "adressnummer", "tour", "liefertermin", "wunschtermin",
    "bestelldatum", "store_name", "iln",
)


def _get_value(entry: Any) -> str:
    if isinstance(entry, dict):
        return str(entry.get("value") or "").strip()
    return str(entry or "").strip()


def _merge_new_extraction(
    existing_payload: dict[str, Any],
    new_payload: dict[str, Any],
) -> dict[str, Any]:
    """Merge header and item fields from new_payload into existing_payload.

    Only fills slots that are currently empty — never overwrites non-empty values.
    """
    existing_header = existing_payload.get("header")
    if not isinstance(existing_header, dict):
        existing_header = {}
        existing_payload["header"] = existing_header

    new_header = new_payload.get("header") or {}

    # Merge header fields
    for field in _HEADER_FIELDS:
        if _is_missing(existing_header.get(field)) and not _is_missing(new_header.get(field)):
            raw = new_header[field]
            existing_header[field] = (
                raw if isinstance(raw, dict)
                else {"value": str(raw).strip(), "source": "followup_email", "confidence": 0.9}
            )

    # Merge item fields by position (line_no → artikelnummer → index)
    existing_items = existing_payload.get("items")
    if not isinstance(existing_items, list):
        existing_items = []
        existing_payload["items"] = existing_items

    new_items = new_payload.get("items") or []

    def _get_item_field(item: dict, field: str) -> str:
        raw = item.get(field)
        if isinstance(raw, dict):
            return str(raw.get("value") or "").strip()
        return str(raw or "").strip()

    def _find_new_item(ex_item: dict) -> dict | None:
        ex_line = _get_item_field(ex_item, "line_no")
        ex_art = _get_item_field(ex_item, "artikelnummer")
        for ni in new_items:
            if not isinstance(ni, dict):
                continue
            ni_line = _get_item_field(ni, "line_no")
            ni_art = _get_item_field(ni, "artikelnummer")
            if ex_line and ni_line and ex_line == ni_line:
                return ni
            if ex_art and ni_art and ex_art == ni_art:
                return ni
        return None

    # Snapshot BEFORE the merge loop mutates existing_items in-place.
    # Guard: only append extra items when at least one existing item had both fields empty.
    _had_placeholders = any(
        _is_missing(ex.get("artikelnummer")) and _is_missing(ex.get("modellnummer"))
        for ex in existing_items
        if isinstance(ex, dict)
    )

    item_fields = ("modellnummer", "artikelnummer", "menge", "beschreibung", "farbe", "furncloud_id")
    for idx, ex_item in enumerate(existing_items):
        if not isinstance(ex_item, dict):
            continue
        new_item = _find_new_item(ex_item) or (new_items[idx] if idx < len(new_items) else None)
        if not new_item or not isinstance(new_item, dict):
            continue
        for field in item_fields:
            if _is_missing(ex_item.get(field)) and not _is_missing(new_item.get(field)):
                raw = new_item[field]
                ex_item[field] = (
                    raw if isinstance(raw, dict)
                    else {"value": str(raw).strip(), "source": "followup_email", "confidence": 0.9}
                )

    # Append extra Furnplan items (uses pre-loop snapshot so placeholder check is accurate).
    if _had_placeholders and len(new_items) > len(existing_items):
        for new_item in new_items[len(existing_items):]:
            if isinstance(new_item, dict):
                existing_items.append(new_item)

    # Strip stale field-missing warnings before checking remaining fields
    _strip_stale_field_warnings(existing_payload)

    # Clear reply_needed if all fields are now filled (check actual values only, not stale warnings)
    remaining = detect_missing_fields(existing_payload, [])
    if not remaining:
        reply_entry = existing_header.get("reply_needed")
        if isinstance(reply_entry, dict):
            reply_entry["value"] = False
            reply_entry["source"] = "followup_email"
            reply_entry["confidence"] = 1.0
        else:
            existing_header["reply_needed"] = {"value": False, "source": "followup_email", "confidence": 1.0}

    return existing_payload


def process_new_email_followup(
    existing_order: dict[str, Any],
    new_payload: dict[str, Any],
    message: Any,
    config: Any,
    validator: GeminiValidator | None = None,
) -> bool:
    """Handle a new (non-Re:) email whose KOM matches an existing reply-needed order.

    Merges new extraction data into the original order and skips creating a new one.
    Returns True if successfully processed.
    """
    order_id = existing_order["id"]
    original_message_id = existing_order.get("external_message_id") or ""

    print(
        f"[reply_tracker] New-email follow-up matched order_id={order_id} "
        f"(message_id={message.message_id!r})"
    )

    existing_payload = order_store.get_order_current_payload(order_id)
    if not existing_payload:
        print(f"[reply_tracker] No payload found for order_id={order_id}")
        return False

    merged = _merge_new_extraction(existing_payload, new_payload)
    output_name = f"followup_{order_id}"
    xml_documents, validation_result = _prepare_xml_documents_and_validation(
        config=config,
        validator=validator,
        message=message,
        payload=merged,
        output_name=output_name,
    )

    try:
        persisted = order_store.upsert_order_payload(
            merged,
            external_message_id=original_message_id,
            change_type="followup_update",
            validation_result=validation_result,
        )
        if validation_result and persisted.get("revision_id"):
            order_store.record_validation_run(
                order_id=order_id,
                revision_id=persisted["revision_id"],
                validation_result=validation_result,
            )
    except Exception as exc:
        print(f"[reply_tracker] Failed to upsert followup payload for order {order_id}: {exc}")
        return False

    try:
        order_store.mark_client_replied(order_id, message.message_id or "")
    except Exception as exc:
        print(f"[reply_tracker] Failed to mark_client_replied for order {order_id}: {exc}")
        return False

    try:
        xml_paths = (
            xml_exporter.write_xml_documents(xml_documents)
            if xml_documents
            else xml_exporter.export_xmls(merged, output_name, config, config.output_dir)
        )
        for xp in xml_paths:
            print(f"[reply_tracker] Regenerated XML: {xp}")
        try:
            order_store.record_xml_activity_event(
                order_id_snapshot=order_id,
                event_type=order_store.XML_ACTIVITY_EVENT_REGENERATED_BOTH,
                file_count=2,
                source="reply_tracker_followup",
                metadata={"files": [str(path) for path in xml_paths]},
            )
        except Exception as ledger_exc:
            print(f"[reply_tracker] Failed to record XML activity ledger for order {order_id}: {ledger_exc}")
    except Exception as exc:
        print(f"[reply_tracker] XML regeneration failed for order {order_id}: {exc}")

    # Check if fields are still missing after the merge (actual values only, not stale warnings)
    remaining_missing = detect_missing_fields(merged, [])
    if remaining_missing:
        # Fields still missing — keep order open for another follow-up
        print(
            f"[reply_tracker] Order {order_id} still has missing fields after follow-up: {remaining_missing}. "
            "Re-opening waiting state."
        )
        try:
            order_store.reopen_waiting_for_reply(order_id, remaining_missing)
        except Exception as exc:
            print(f"[reply_tracker] Failed to reopen_waiting_for_reply for order {order_id}: {exc}")
    else:
        # All fields filled — mark as fully updated
        try:
            order_store.mark_order_updated_after_reply(order_id)
        except Exception as exc:
            print(f"[reply_tracker] Failed to mark_order_updated_after_reply for order {order_id}: {exc}")

    print(f"[reply_tracker] Successfully processed follow-up for order {order_id}.")
    return True


def process_client_reply(
    message: IngestedEmail,
    config: Config,
    extractor: OpenAIExtractor,
    validator: GeminiValidator | None = None,
) -> bool:
    """Process a client reply email.

    Returns True if successfully matched and processed, False otherwise.
    """
    kom_number = _extract_kom_number_from_subject(message.subject or "")
    if not kom_number:
        print(f"[reply_tracker] Could not extract KOM number from subject: {message.subject!r}")
        return False

    order = order_store.find_order_awaiting_reply_by_kom(kom_number)
    if not order:
        print(f"[reply_tracker] No order awaiting reply found for KOM: {kom_number!r}")
        return False

    order_id = order["id"]
    original_message_id = order.get("external_message_id") or ""
    missing_fields: list[str] = list(order.get("missing_fields_snapshot") or [])

    print(f"[reply_tracker] Matched reply for KOM={kom_number!r} → order_id={order_id}, missing={missing_fields}")

    payload = order_store.get_order_current_payload(order_id)
    if not payload:
        print(f"[reply_tracker] No payload found for order_id={order_id}")
        return False

    reply_body = message.body_text or ""

    if missing_fields:
        extracted = _extract_missing_fields_via_openai(
            extractor, reply_body, missing_fields, message.message_id or ""
        )
        print(f"[reply_tracker] Extracted fields for order {order_id}: {extracted}")
        payload = _merge_reply_fields(payload, extracted)
    else:
        print(f"[reply_tracker] No missing_fields_snapshot for order {order_id}; skipping extraction.")

    output_name = f"reply_{order_id}"
    xml_documents, validation_result = _prepare_xml_documents_and_validation(
        config=config,
        validator=validator,
        message=message,
        payload=payload,
        output_name=output_name,
    )

    # Persist the updated payload — must use the ORIGINAL message_id so the dedupe_key
    # matches the existing order row rather than creating a new one.
    try:
        persisted = order_store.upsert_order_payload(
            payload,
            external_message_id=original_message_id,
            change_type="reply_update",
            validation_result=validation_result,
        )
        if validation_result and persisted.get("revision_id"):
            order_store.record_validation_run(
                order_id=order_id,
                revision_id=persisted["revision_id"],
                validation_result=validation_result,
            )
    except Exception as exc:
        print(f"[reply_tracker] Failed to upsert updated payload for order {order_id}: {exc}")
        return False

    # Mark client replied in DB
    try:
        order_store.mark_client_replied(order_id, message.message_id or "")
    except Exception as exc:
        print(f"[reply_tracker] Failed to mark_client_replied for order {order_id}: {exc}")
        return False

    # Regenerate XMLs
    try:
        xml_paths = (
            xml_exporter.write_xml_documents(xml_documents)
            if xml_documents
            else xml_exporter.export_xmls(payload, output_name, config, config.output_dir)
        )
        for xp in xml_paths:
            print(f"[reply_tracker] Regenerated XML: {xp}")
        try:
            order_store.record_xml_activity_event(
                order_id_snapshot=order_id,
                event_type=order_store.XML_ACTIVITY_EVENT_REGENERATED_BOTH,
                file_count=2,
                source="reply_tracker_reply",
                metadata={"files": [str(path) for path in xml_paths]},
            )
        except Exception as ledger_exc:
            print(f"[reply_tracker] Failed to record XML activity ledger for order {order_id}: {ledger_exc}")
    except Exception as exc:
        print(f"[reply_tracker] XML regeneration failed for order {order_id}: {exc}")

    # Check if fields are still missing after the merge (actual values only, not stale warnings)
    remaining_missing = detect_missing_fields(payload, [])
    if remaining_missing:
        # Fields still missing — keep order open for another follow-up
        print(
            f"[reply_tracker] Order {order_id} still has missing fields after reply: {remaining_missing}. "
            "Re-opening waiting state."
        )
        try:
            order_store.reopen_waiting_for_reply(order_id, remaining_missing)
        except Exception as exc:
            print(f"[reply_tracker] Failed to reopen_waiting_for_reply for order {order_id}: {exc}")
    else:
        # All fields filled — mark as fully updated
        try:
            order_store.mark_order_updated_after_reply(order_id)
        except Exception as exc:
            print(f"[reply_tracker] Failed to mark_order_updated_after_reply for order {order_id}: {exc}")

    print(f"[reply_tracker] Successfully processed reply for order {order_id}.")
    return True


def _count_working_days(start: datetime, end: datetime) -> int:
    """Count Mon–Fri days between start and end (exclusive of end date)."""
    start_date = start.date()
    end_date = end.date()
    if end_date <= start_date:
        return 0
    count = 0
    current = start_date
    while current < end_date:
        if current.weekday() < 5:  # 0=Mon … 4=Fri
            count += 1
        current += timedelta(days=1)
    return count


def _working_day_cutoff(now: datetime, working_days: int) -> datetime:
    """Return the datetime that is exactly working_days Mon–Fri days before now.
    Any reply_email_sent_at older than this has waited the full period."""
    target_date = now.date()
    days_counted = 0
    while days_counted < working_days:
        target_date -= timedelta(days=1)
        if target_date.weekday() < 5:
            days_counted += 1
    return datetime(target_date.year, target_date.month, target_date.day, tzinfo=timezone.utc)


def escalate_stale_waiting_orders(config: Config) -> int:
    """Escalate orders waiting more than config.stale_reply_working_days working days.

    For each stale order:
      1. Sets status='human_in_the_loop', waiting_for_client_reply=FALSE
      2. Sends notification email to config.reply_email_to
      3. Logs the action

    Returns the number of orders escalated.
    """
    now = datetime.now(timezone.utc)
    cutoff = _working_day_cutoff(now, config.stale_reply_working_days)
    stale_orders = order_store.get_stale_waiting_orders(cutoff)

    if not stale_orders:
        return 0

    escalated = 0
    for order in stale_orders:
        order_id = order["id"]
        kom_nr = order.get("kom_nr") or order_id
        sent_at = order.get("reply_email_sent_at")

        try:
            order_store.mark_order_escalated(order_id)
        except Exception as exc:
            print(f"[reply_tracker] escalate: DB update failed for order {order_id}: {exc}")
            continue

        try:
            msg = EmailMessage()
            msg["To"] = config.reply_email_to
            msg["Subject"] = (
                f"Escalation: Order {kom_nr} — no Furnplan reply in "
                f"{config.stale_reply_working_days} working days"
            )
            msg.set_content(
                f"Order {kom_nr} has not received a Furnplan reply in "
                f"{config.stale_reply_working_days} working days and has been escalated "
                f"to human review.\n\n"
                f"Reply email was sent at: {sent_at}\n"
                f"Order ID: {order_id}\n"
            )
            send_email_via_smtp(config, msg)
        except Exception as exc:
            print(f"[reply_tracker] escalate: notification email failed for {order_id}: {exc}")

        print(
            f"[reply_tracker] Escalated order {order_id} (KOM={kom_nr}) "
            f"after {config.stale_reply_working_days} working days without reply."
        )
        escalated += 1

    return escalated
