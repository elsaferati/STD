from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import time
import json
import sys

from dotenv import load_dotenv

from config import Config
from email_ingest import EmailClient
from openai_extract import OpenAIExtractor
from pipeline import process_message
import xml_exporter


def _resolve_output_path(output_dir: Path, base_name: str) -> Path:
    candidate = output_dir / f"{base_name}.json"
    if not candidate.exists():
        return candidate
    for idx in range(1, 1000):
        candidate = output_dir / f"{base_name}_{idx}.json"
        if not candidate.exists():
            return candidate
    return output_dir / f"{base_name}_overflow.json"


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
            result = process_message(message, config, extractor)
            output_path = _resolve_output_path(config.output_dir, result.output_name)
            with output_path.open("w", encoding="utf-8") as handle:
                json.dump(result.data, handle, ensure_ascii=False, indent=2)
            print(f"Saved: {output_path}")

            # Generate XML outputs
            try:
                xml_paths = xml_exporter.export_xmls(result.data, result.output_name, config, config.output_dir)
                for xp in xml_paths:
                    print(f"Generated XML: {xp}")
            except Exception as exc:
                print(f"Failed to generate XMLs for {result.output_name}: {exc}")

            seen_message_ids.add(message.message_id)

        if poll_seconds <= 0:
            return 0
        time.sleep(poll_seconds)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
