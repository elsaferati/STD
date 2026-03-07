"""reply_tracker.py — Handles incoming client reply emails for the reply-to-order workflow.

Detects client reply emails by subject pattern, extracts the KOM number,
matches to an order with waiting_for_client_reply=True, extracts missing
fields via OpenAI, merges them into the order payload, regenerates XMLs,
and updates the order status.
"""

from __future__ import annotations

import json
import re
from typing import Any

from config import Config
from email_ingest import IngestedEmail
from openai_extract import OpenAIExtractor
import order_store
import xml_exporter
from reply_email import detect_missing_fields


_KOM_FROM_SUBJECT_RE = re.compile(
    r'(?:Re:\s*)?Ruckfrage\s+zu\s+Ihrer\s+Bestellung\s+(.+?)\s+-\s+',
    re.IGNORECASE,
)

_REPLY_EXTRACT_SYSTEM_PROMPT = (
    "You are an order data extraction assistant. "
    "Extract only the specified fields from the client's reply email. "
    "Return a JSON object with only the requested field keys and their string values. "
    "If a field cannot be found, omit it from the response."
)


def is_client_reply(message: IngestedEmail) -> bool:
    """Return True if this email looks like a client reply to a Ruckfrage email."""
    return bool(_KOM_FROM_SUBJECT_RE.search(message.subject or ""))


def _extract_kom_number_from_subject(subject: str) -> str:
    match = _KOM_FROM_SUBJECT_RE.search(subject or "")
    if match:
        return match.group(1).strip()
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
) -> dict[str, str]:
    """Call OpenAI to extract only the missing fields from the reply body."""
    field_list = ", ".join(missing_fields)
    user_instructions = (
        f"Extract the following fields from the client reply email below: {field_list}.\n"
        "Return a JSON object with only these keys. "
        "Values should be plain strings (e.g. an address as one string, a model number as a string).\n\n"
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
        # Try to parse the JSON from the response
        # Strip markdown code fences if present
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
            text = re.sub(r"\n?```$", "", text)
        return json.loads(text)
    except Exception as exc:
        print(f"[reply_tracker] OpenAI extraction failed for {message_id}: {exc}")
        return {}


def _merge_reply_fields(
    payload: dict[str, Any],
    extracted_fields: dict[str, str],
) -> dict[str, Any]:
    """Merge extracted reply fields into payload — only fills missing slots, never overwrites."""
    header = payload.get("header")
    if not isinstance(header, dict):
        header = {}
        payload["header"] = header

    items = payload.get("items")
    if not isinstance(items, list):
        items = []
        payload["items"] = items

    for field_name, value in extracted_fields.items():
        if not value or not str(value).strip():
            continue
        value = str(value).strip()
        if field_name in ("lieferanschrift", "store_address"):
            if _is_missing(header.get(field_name)):
                header[field_name] = {"value": value, "source": "reply_email", "confidence": 0.9}
        elif field_name in ("modellnummer", "artikelnummer", "menge"):
            for item in items:
                if isinstance(item, dict) and _is_missing(item.get(field_name)):
                    item[field_name] = {"value": value, "source": "reply_email", "confidence": 0.9}

    # Clear reply_needed if all fields are now filled
    remaining = detect_missing_fields(payload, payload.get("warnings") or [])
    if not remaining:
        reply_entry = header.get("reply_needed")
        if isinstance(reply_entry, dict):
            reply_entry["value"] = False
            reply_entry["source"] = "reply_email"
            reply_entry["confidence"] = 1.0
        else:
            header["reply_needed"] = {"value": False, "source": "reply_email", "confidence": 1.0}

    return payload


def process_client_reply(
    message: IngestedEmail,
    config: Config,
    extractor: OpenAIExtractor,
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

    # Persist the updated payload — must use the ORIGINAL message_id so the dedupe_key
    # matches the existing order row rather than creating a new one.
    try:
        order_store.upsert_order_payload(
            payload,
            external_message_id=original_message_id,
            change_type="reply_update",
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
        output_name = f"reply_{order_id}"
        xml_paths = xml_exporter.export_xmls(payload, output_name, config, config.output_dir)
        for xp in xml_paths:
            print(f"[reply_tracker] Regenerated XML: {xp}")
    except Exception as exc:
        print(f"[reply_tracker] XML regeneration failed for order {order_id}: {exc}")

    # Mark updated after reply
    try:
        order_store.mark_order_updated_after_reply(order_id)
    except Exception as exc:
        print(f"[reply_tracker] Failed to mark_order_updated_after_reply for order {order_id}: {exc}")

    print(f"[reply_tracker] Successfully processed reply for order {order_id}.")
    return True
