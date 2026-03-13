from __future__ import annotations

from email.message import EmailMessage
from pathlib import Path
import re
import smtplib
from typing import Any

from config import Config
from email_ingest import IngestedEmail
from email_templates import load_reply_templates


_REPLY_WARNING_PREFIX = "Reply needed:"
_MISSING_CRITICAL_REPLY_PREFIX = "Missing critical header fields:"
_MISSING_CRITICAL_ITEM_REPLY_PREFIX = "Missing critical item fields:"
_MISSING_ITEM_FIELDS_PREFIX = "Missing item fields:"
_DEFAULT_TEMPLATE_FILE = Path("email_templates/reply_templates.json")

_FIELD_LABELS = {
    "lieferanschrift": "Lieferanschrift",
    "store_address": "Anschrift bestellendes Haus",
    "modellnummer": "Modellnummer",
    "artikelnummer": "Artikelnummer",
    "menge": "Menge",
}
_FIELD_ORDER = ["lieferanschrift", "store_address", "modellnummer", "artikelnummer", "menge"]


def _header_value(header: dict[str, Any], key: str) -> str:
    entry = header.get(key, {})
    if isinstance(entry, dict):
        return str(entry.get("value", "") or "").strip()
    return str(entry or "").strip()


def _is_missing(value: Any) -> bool:
    if isinstance(value, dict):
        value = value.get("value")
    return str(value or "").strip() == ""


def _reply_cases_from_warnings(warnings: list[Any]) -> list[str]:
    if not isinstance(warnings, list):
        return []
    cases: list[str] = []
    seen: set[str] = set()
    for warning in warnings:
        if isinstance(warning, str) and warning.startswith(_REPLY_WARNING_PREFIX):
            case = warning[len(_REPLY_WARNING_PREFIX) :].strip()
            if not case:
                continue
            key = case.lower()
            if key in seen:
                continue
            seen.add(key)
            cases.append(case)
    return cases


def _parse_field_names_from_warning(warnings: list[str], prefix: str) -> list[str]:
    parsed: list[str] = []
    for warning in warnings:
        if not isinstance(warning, str):
            continue
        if not warning.startswith(prefix):
            continue
        tail = warning[len(prefix) :].strip()
        if not tail:
            continue
        for chunk in tail.split(";"):
            chunk = chunk.strip()
            if not chunk:
                continue
            token = re.split(r"\s*\(line.*", chunk, maxsplit=1)[0].strip().lower()
            if token in {"modellnummer", "artikelnummer", "menge"}:
                parsed.append(token)
    return parsed


def detect_missing_fields(normalized: dict[str, Any], warnings: list[Any]) -> list[str]:
    header = normalized.get("header") if isinstance(normalized.get("header"), dict) else {}
    items = normalized.get("items") if isinstance(normalized.get("items"), list) else []
    extraction_branch = str(normalized.get("extraction_branch") or "").strip()
    missing: list[str] = []

    if _is_missing(header.get("lieferanschrift")):
        missing.append("lieferanschrift")
    if _is_missing(header.get("store_address")) and extraction_branch != "braun":
        missing.append("store_address")

    if not items:
        if "modellnummer" not in missing:
            missing.append("modellnummer")
        if "artikelnummer" not in missing:
            missing.append("artikelnummer")
        if "menge" not in missing:
            missing.append("menge")
    else:
        for item in items:
            if not isinstance(item, dict):
                continue
            if _is_missing(item.get("modellnummer")) and "modellnummer" not in missing:
                missing.append("modellnummer")
            if _is_missing(item.get("artikelnummer")) and "artikelnummer" not in missing:
                missing.append("artikelnummer")
            if _is_missing(item.get("menge")) and "menge" not in missing:
                missing.append("menge")

    warning_texts = [str(w) for w in warnings if isinstance(w, str)]
    for field in _parse_field_names_from_warning(warning_texts, _MISSING_ITEM_FIELDS_PREFIX):
        if field not in missing:
            missing.append(field)
    for field in _parse_field_names_from_warning(
        warning_texts, f"{_REPLY_WARNING_PREFIX} {_MISSING_CRITICAL_ITEM_REPLY_PREFIX}"
    ):
        if field not in missing:
            missing.append(field)

    field_set = set(missing)
    return [field for field in _FIELD_ORDER if field in field_set]


def _format_affected_items(items: list[Any], missing_field: str) -> str:
    """Bullet list of items missing a field, each referenced by the other identifier."""
    _REF = {
        "artikelnummer": ("modellnummer", "Modellnummer"),
        "modellnummer": ("artikelnummer", "Artikelnummer"),
    }
    ref_key, ref_label = _REF.get(missing_field, (None, None))
    bullets: list[str] = []
    for idx, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        if not _is_missing(item.get(missing_field)):
            continue
        if ref_key:
            entry = item.get(ref_key, {})
            ref_val = str((entry.get("value") if isinstance(entry, dict) else entry) or "").strip()
        else:
            ref_val = ""
        bullets.append(f"- {ref_label}: {ref_val}" if ref_val else f"- Position {idx}")
    return "\n".join(bullets) if bullets else "- (keine Zuordnung verfügbar)"


def _format_missing_field_list(missing_fields: list[str], reply_cases: list[str]) -> str:
    bullets = [f"- {_FIELD_LABELS[field]}" for field in missing_fields if field in _FIELD_LABELS]
    if not bullets and reply_cases:
        bullets = [f"- {case}" for case in reply_cases]
    if not bullets:
        bullets = ["- Lieferanschrift", "- Anschrift bestellendes Haus", "- Modellnummer", "- Artikelnummer", "- Menge"]
    return "\n".join(bullets)


def select_template_id(missing_fields: list[str], reply_cases: list[str]) -> str:
    if len(missing_fields) == 1:
        if missing_fields[0] == "lieferanschrift":
            return "missing_lieferanschrift"
        if missing_fields[0] == "store_address":
            return "missing_bestellendes_haus"
        if missing_fields[0] == "modellnummer":
            return "missing_modellnummer"
        if missing_fields[0] == "artikelnummer":
            return "missing_artikelnummer"
        if missing_fields[0] == "menge":
            return "missing_menge"

    if len(missing_fields) > 1:
        return "missing_multiple_pflichtfelder"

    if reply_cases:
        # Per plan: non-field clarification/substitution cases route to generic missing-data template.
        return "missing_multiple_pflichtfelder"

    return "missing_multiple_pflichtfelder"


def render_template(template_text: str, placeholders: dict[str, str]) -> str:
    output = str(template_text or "")
    for key, value in placeholders.items():
        output = output.replace(f"{{{{{key}}}}}", str(value or ""))
    return output


def _compose_legacy_reply_needed_email(
    message: IngestedEmail,
    normalized: dict[str, Any],
    to_addr: str,
    body_template: str,
) -> EmailMessage:
    if not (to_addr or "").strip():
        raise ValueError("Reply email recipient is empty")
    header = normalized.get("header") if isinstance(normalized.get("header"), dict) else {}
    warnings = normalized.get("warnings") if isinstance(normalized.get("warnings"), list) else []

    ticket_number = _header_value(header, "ticket_number")
    kom_nr = _header_value(header, "kom_nr")
    message_id = message.message_id or normalized.get("message_id") or ""
    subject_hint = ticket_number or kom_nr or message_id or "unknown"

    reply_cases = _reply_cases_from_warnings(warnings)
    if not reply_cases:
        reply_cases = ["Automatic clarification requested by workflow."]

    body_lines: list[str] = []
    template_text = (body_template or "").strip()
    if template_text:
        body_lines.append(template_text)
        body_lines.append("")
    body_lines.append("What happened")
    body_lines.append("Detected reply-needed conditions:")
    for idx, case in enumerate(reply_cases, start=1):
        body_lines.append(f"{idx}. {case}")
    body_lines.append("")
    body_lines.append("Context")
    body_lines.append(f"Message-ID: {message_id}")
    body_lines.append(f"Received-At: {message.received_at or normalized.get('received_at') or ''}")
    body_lines.append(f"From: {message.sender or ''}")
    body_lines.append(f"Subject: {message.subject or ''}")

    msg = EmailMessage()
    msg["To"] = to_addr
    msg["Subject"] = f"Reply needed - {subject_hint}"
    msg.set_content("\n".join(body_lines).rstrip() + "\n")
    return msg


def compose_reply_needed_email(
    message: IngestedEmail,
    normalized: dict[str, Any],
    to_addr: str,
    body_template: str,
    template_file: str | Path | None = None,
) -> EmailMessage:
    if not (to_addr or "").strip():
        raise ValueError("Reply email recipient is empty")

    header = normalized.get("header") if isinstance(normalized.get("header"), dict) else {}
    warnings = normalized.get("warnings") if isinstance(normalized.get("warnings"), list) else []
    message_id = str(message.message_id or normalized.get("message_id") or "").strip()
    kom_number = (
        _header_value(header, "kom_nr")
        or _header_value(header, "ticket_number")
        or message_id
    )
    reply_cases = _reply_cases_from_warnings(warnings)

    template_path = Path(template_file) if template_file else _DEFAULT_TEMPLATE_FILE
    try:
        store = load_reply_templates(template_path)
        templates = store.get("templates") if isinstance(store.get("templates"), dict) else {}
        missing_fields = detect_missing_fields(normalized, warnings)
        template_id = select_template_id(missing_fields, reply_cases)
        template_data = templates.get(template_id)
        if not isinstance(template_data, dict):
            raise ValueError(f"Template '{template_id}' not found in {template_path}")

        items = normalized.get("items") if isinstance(normalized.get("items"), list) else []
        placeholders = {
            "kommisionsnummer": kom_number,
            "fehlende_pflichtfelder_liste": _format_missing_field_list(missing_fields, reply_cases),
            "betroffene_positionen": _format_affected_items(
                items, missing_fields[0] if len(missing_fields) == 1 else ""
            ),
        }
        subject = render_template(str(template_data.get("subject", "")), placeholders).strip()
        body = render_template(str(template_data.get("body", "")), placeholders).strip()
        if not subject or not body:
            raise ValueError(f"Template '{template_id}' rendered empty subject/body")

        msg = EmailMessage()
        msg["To"] = to_addr
        msg["Subject"] = subject
        msg.set_content(body + "\n")
        return msg
    except Exception as exc:
        # Compatibility fallback: if templates are unavailable or invalid, keep old behavior.
        if isinstance(warnings, list):
            warnings.append(f"Reply email template fallback: {exc}")
        return _compose_legacy_reply_needed_email(
            message=message,
            normalized=normalized,
            to_addr=to_addr,
            body_template=body_template,
        )


def send_px_xml_email(order_id: str, config: Config, output_dir: "Path") -> None:
    """Send both XML files to 333primex.eu@gmail.com after triple PX control confirmation."""
    import order_store as _order_store
    import xml_exporter as _xml_exporter

    payload_map = _order_store.get_order_payload_map([order_id])
    entry = payload_map.get(order_id)
    if not entry or entry.get("parse_error"):
        raise ValueError(f"Cannot send PX XML for order {order_id}: no valid payload")

    data = entry["data"]
    documents = _xml_exporter.render_xml_documents(data, "", config, Path(str(output_dir)))

    recipient = "333primex.eu@gmail.com"
    msg = EmailMessage()
    msg["To"] = recipient
    msg["Subject"] = f"PX Order XML - {order_id}"
    msg.set_content("PX quality control completed. XML files are attached.\n")

    for doc in documents:
        msg.add_attachment(
            doc.content.encode("utf-8"),
            maintype="application",
            subtype="xml",
            filename=doc.filename,
        )

    send_email_via_smtp(config, msg)
    _order_store.mark_px_xml_sent(order_id)


def send_email_via_smtp(config: Config, email_message: EmailMessage) -> None:
    if not config.smtp_host:
        raise ValueError("SMTP_HOST is missing")
    if not config.smtp_user:
        raise ValueError("SMTP_USER is missing")
    if not config.smtp_password:
        raise ValueError("SMTP_PASSWORD is missing")

    if "From" in email_message:
        email_message.replace_header("From", config.smtp_user)
    else:
        email_message["From"] = config.smtp_user

    host = config.smtp_host
    port = int(config.smtp_port or 0) or 587

    if config.smtp_ssl and port == 465:
        with smtplib.SMTP_SSL(host, port) as server:
            server.ehlo()
            server.login(config.smtp_user, config.smtp_password)
            server.send_message(email_message)
        return

    with smtplib.SMTP(host, port) as server:
        server.ehlo()
        if config.smtp_ssl:
            server.starttls()
            server.ehlo()
        server.login(config.smtp_user, config.smtp_password)
        server.send_message(email_message)
