from __future__ import annotations

from datetime import datetime, timezone
import time

from dotenv import load_dotenv

from config import Config
from db import init_db
from email_ingest import EmailClient
from gemini_validation import GeminiValidator, build_validation_error_result
from openai_extract import OpenAIExtractor
import order_store
from pipeline import process_message
from reply_tracker import (
    is_client_reply,
    process_client_reply,
    process_new_email_followup,
    extract_kom_from_bestellung_subject,
    escalate_stale_waiting_orders,
)
import xml_exporter


def _validate_config(config: Config) -> list[str]:
    missing = []
    if not config.openai_api_key:
        missing.append("OPENAI_API_KEY")
    if config.gemini_validation_enabled and not config.gemini_api_key:
        missing.append("GEMINI_API_KEY")
    if not config.email_host:
        missing.append("EMAIL_HOST")
    if not config.email_user:
        missing.append("EMAIL_USER")
    if not config.email_password:
        missing.append("EMAIL_PASSWORD")
    if config.email_protocol not in ("imap", "pop3"):
        missing.append("EMAIL_PROTOCOL (imap|pop3)")
    return missing


def _prepare_xml_documents_and_validation(
    *,
    config: Config,
    validator: GeminiValidator | None,
    message,
    payload: dict[str, object],
    output_name: str,
) -> tuple[list[xml_exporter.XmlDocument], dict[str, object] | None]:
    xml_documents: list[xml_exporter.XmlDocument] = []
    validation_result: dict[str, object] | None = None
    try:
        xml_documents = xml_exporter.render_xml_documents(payload, output_name, config, config.output_dir)
        if validator is not None:
            branch_id = str(payload.get("extraction_branch") or "").strip()
            validation_result = validator.validate_order(
                message=message,
                branch_id=branch_id,
                normalized=payload,
                xml_documents=xml_documents,
            )
    except Exception as exc:
        print(f"Failed to prepare XML documents for {message.message_id}: {exc}")
        if validator is not None:
            validation_result = build_validation_error_result(
                f"Gemini validation skipped because XML rendering failed: {exc}",
                model=config.gemini_model,
            )
    return xml_documents, validation_result


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
    validator = GeminiValidator.from_config(config)

    config.output_dir.mkdir(parents=True, exist_ok=True)

    poll_seconds = max(0, config.email_poll_seconds)
    seen_message_ids: set[str] = set()
    _last_escalation_check: datetime = datetime.min.replace(tzinfo=timezone.utc)

    while True:
        _now_utc = datetime.now(timezone.utc)
        if (_now_utc - _last_escalation_check).total_seconds() >= 3600:
            try:
                n = escalate_stale_waiting_orders(config)
                if n:
                    print(f"[main] Escalated {n} stale order(s) to human_in_the_loop.")
            except Exception as exc:
                print(f"[main] escalate_stale_waiting_orders failed: {exc}")
            _last_escalation_check = _now_utc

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
                handled = process_client_reply(message, config, extractor, validator)
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
                    _handled = process_new_email_followup(
                        _existing_bestellung,
                        result.data,
                        message,
                        config,
                        validator,
                    )
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
                    _handled = process_new_email_followup(
                        _existing,
                        result.data,
                        message,
                        config,
                        validator,
                    )
                    if _handled:
                        seen_message_ids.add(message.message_id)
                        continue

            xml_documents, validation_result = _prepare_xml_documents_and_validation(
                config=config,
                validator=validator,
                message=message,
                payload=result.data,
                output_name=result.output_name,
            )

            try:
                persisted = order_store.upsert_order_payload(
                    result.data,
                    external_message_id=message.message_id,
                    change_type="ingested",
                    validation_result=validation_result,
                )
                print(
                    "DB upsert complete: "
                    f"order_id={persisted['order_id']} revision_no={persisted.get('revision_no')}"
                )
                if validation_result and persisted.get("revision_id"):
                    order_store.record_validation_run(
                        order_id=persisted["order_id"],
                        revision_id=persisted["revision_id"],
                        validation_result=validation_result,
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
                generated_xml_paths = (
                    xml_exporter.write_xml_documents(xml_documents)
                    if xml_documents
                    else xml_exporter.export_xmls(result.data, result.output_name, config, config.output_dir)
                )
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
