from __future__ import annotations

from datetime import datetime, timezone
import time

from dotenv import load_dotenv

from config import Config
from db import init_db
from email_ingest import EmailClient
from openai_extract import OpenAIExtractor
import order_store
from pipeline import process_message
from reply_tracker import (
    is_client_reply,
    process_client_reply,
    process_new_email_followup,
    extract_kom_from_bestellung_subject,
)
import xml_exporter


def _validate_config(config: Config) -> list[str]:
    missing = []
    if not config.openai_api_key:
        missing.append("OPENAI_API_KEY")
    if not config.email_host:
        missing.append("EMAIL_HOST")
    if not config.email_user:
        missing.append("EMAIL_USER")
    if not config.email_password:
        missing.append("EMAIL_PASSWORD")
    if config.email_protocol not in ("imap", "pop3"):
        missing.append("EMAIL_PROTOCOL (imap|pop3)")
    return missing


def main() -> int:
    load_dotenv()
    config = Config.from_env()
    try:
        init_db()
    except Exception as exc:
        print(f"DB init failed: {exc}")
        return 1

    missing = _validate_config(config)
    if missing:
        print("Missing or invalid configuration values:")
        for name in missing:
            print(f" - {name}")
        return 1

    start_time = datetime.now(timezone.utc)
    only_after = start_time if config.email_only_after_start else None

    email_client = EmailClient(
        protocol=config.email_protocol,
        host=config.email_host,
        port=config.email_port,
        user=config.email_user,
        password=config.email_password,
        use_ssl=config.email_ssl,
        folder=config.email_folder,
        search_criteria=config.email_search,
        limit=config.email_limit,
        mark_seen=config.email_mark_seen,
        only_after=only_after,
    )

    extractor = OpenAIExtractor(
        api_key=config.openai_api_key,
        model=config.openai_model,
        temperature=config.openai_temperature,
        reasoning_effort=config.openai_reasoning_effort,
        max_output_tokens=config.openai_max_output_tokens,
    )

    config.output_dir.mkdir(parents=True, exist_ok=True)

    poll_seconds = max(0, config.email_poll_seconds)
    seen_message_ids: set[str] = set()

    while True:
        messages = email_client.fetch()
        if not messages:
            if poll_seconds <= 0:
                print("No messages found.")
                return 0
            print(f"No new messages. Sleeping {poll_seconds}s.")
            time.sleep(poll_seconds)
            continue

        new_messages = [m for m in messages if m.message_id not in seen_message_ids]
        if not new_messages:
            if poll_seconds <= 0:
                print("No new messages.")
                return 0
            print(f"No new messages. Sleeping {poll_seconds}s.")
            time.sleep(poll_seconds)
            continue

        for message in new_messages:
            if is_client_reply(message):
                handled = process_client_reply(message, config, extractor)
                if handled:
                    seen_message_ids.add(message.message_id)
                    continue

            # Check if subject looks like "Bestellung {KOM}" — a new client reply email
            _bestellung_kom = extract_kom_from_bestellung_subject(message.subject or "")
            if _bestellung_kom:
                _existing_bestellung = order_store.find_reply_needed_order_by_kom(_bestellung_kom)
                if _existing_bestellung:
                    # Process as a reply using full extraction for the body content
                    result = process_message(message, config, extractor)
                    _handled = process_new_email_followup(_existing_bestellung, result.data, message, config)
                    if _handled:
                        seen_message_ids.add(message.message_id)
                        continue

            result = process_message(message, config, extractor)

            # Check if this new email is a follow-up for an existing reply-needed order
            _header = result.data.get("header") or {}
            _kom_entry = _header.get("kom_nr") or _header.get("ticket_number")
            _kom_nr = str((_kom_entry.get("value") if isinstance(_kom_entry, dict) else _kom_entry) or "").strip()
            # Also try extracting KOM from subject directly as a fallback
            if not _kom_nr:
                _kom_nr = _bestellung_kom
            if _kom_nr:
                _existing = order_store.find_reply_needed_order_by_kom(_kom_nr)
                if _existing:
                    _handled = process_new_email_followup(_existing, result.data, message, config)
                    if _handled:
                        seen_message_ids.add(message.message_id)
                        continue

            try:
                persisted = order_store.upsert_order_payload(
                    result.data,
                    external_message_id=message.message_id,
                    change_type="ingested",
                )
                print(
                    "DB upsert complete: "
                    f"order_id={persisted['order_id']} revision_no={persisted.get('revision_no')}"
                )
                if result.reply_email_sent:
                    try:
                        order_store.mark_reply_email_sent(
                            persisted["order_id"], result.missing_fields_snapshot
                        )
                        print(f"Marked order {persisted['order_id']} as waiting_for_reply.")
                    except Exception as mark_exc:
                        print(f"Failed to mark reply email sent for {persisted['order_id']}: {mark_exc}")
            except Exception as exc:
                print(f"DB upsert failed for {message.message_id}: {exc}")
                return 1

            # Generate XML outputs
            xml_paths: list[str] = []
            try:
                generated_xml_paths = xml_exporter.export_xmls(result.data, result.output_name, config, config.output_dir)
                xml_paths = [str(path) for path in generated_xml_paths]
                for xp in generated_xml_paths:
                    print(f"Generated XML: {xp}")
            except Exception as exc:
                print(f"Failed to generate XMLs for {result.output_name}: {exc}")

            if xml_paths:
                try:
                    order_store.register_order_files(
                        order_id=persisted["order_id"],
                        revision_id=persisted.get("revision_id"),
                        file_type="xml",
                        storage_paths=xml_paths,
                    )
                except Exception as exc:
                    print(f"DB xml registration failed for {message.message_id}: {exc}")
                    return 1

            seen_message_ids.add(message.message_id)

        if poll_seconds <= 0:
            return 0
        time.sleep(poll_seconds)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
