from __future__ import annotations

from email.message import EmailMessage
import smtplib
from typing import Any

from config import Config
from email_ingest import IngestedEmail


_REPLY_WARNING_PREFIX = "Reply needed:"
_MISSING_CRITICAL_REPLY_PREFIX = "Missing critical header fields:"
_MISSING_CRITICAL_ITEM_REPLY_PREFIX = "Missing critical item fields:"


def _header_value(header: dict[str, Any], key: str) -> str:
    entry = header.get(key, {})
    if isinstance(entry, dict):
        return str(entry.get("value", "") or "").strip()
    return str(entry or "").strip()


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


def _parse_missing_critical_case(reply_case: str) -> str:
    if not isinstance(reply_case, str):
        return ""
    stripped = reply_case.strip()
    if stripped[: len(_MISSING_CRITICAL_REPLY_PREFIX)].lower() == _MISSING_CRITICAL_REPLY_PREFIX.lower():
        tail = stripped[len(_MISSING_CRITICAL_REPLY_PREFIX) :].strip()
        return f"{_MISSING_CRITICAL_REPLY_PREFIX} {tail}".strip()
    if stripped[: len(_MISSING_CRITICAL_ITEM_REPLY_PREFIX)].lower() == _MISSING_CRITICAL_ITEM_REPLY_PREFIX.lower():
        tail = stripped[len(_MISSING_CRITICAL_ITEM_REPLY_PREFIX) :].strip()
        return f"{_MISSING_CRITICAL_ITEM_REPLY_PREFIX} {tail}".strip()
    return ""


def _classify_reply_cases(reply_cases: list[str]) -> tuple[list[str], list[str]]:
    substitution_cases: list[str] = []
    missing_cases: list[str] = []
    seen_missing: set[str] = set()

    for case in reply_cases:
        parsed_missing = _parse_missing_critical_case(case)
        if parsed_missing:
            key = parsed_missing.lower()
            if key in seen_missing:
                continue
            seen_missing.add(key)
            missing_cases.append(parsed_missing)
            continue
        substitution_cases.append(case)

    return substitution_cases, missing_cases


def compose_reply_needed_email(
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
    substitution_cases, missing_critical_fields = _classify_reply_cases(reply_cases)
    has_substitution = bool(substitution_cases)
    has_missing_critical = bool(missing_critical_fields)

    body_lines: list[str] = []
    if not has_missing_critical:
        template_text = (body_template or "").strip()
        if template_text:
            body_lines.append(template_text)
            body_lines.append("")
    body_lines.append("What happened")
    if has_substitution and has_missing_critical:
        body_lines.append("Detected two reply-needed conditions:")
        body_lines.append("1) Substitution request (STATT ... BITTE ...).")
        body_lines.append("2) Missing mandatory header fields for automatic processing.")
        body_lines.append("")
        body_lines.append("Substitution details")
        for idx, case in enumerate(substitution_cases, start=1):
            body_lines.append(f"{idx}. {case}")
        body_lines.append("")
        body_lines.append("Missing mandatory fields")
        for idx, case in enumerate(missing_critical_fields, start=1):
            body_lines.append(f"{idx}. {case}")
        body_lines.append(
            "Please resend the order with these fields filled in, or send a corrected order via furnplan."
        )
    elif has_missing_critical:
        body_lines.append("Automatic order processing could not continue because mandatory fields are missing.")
        body_lines.append("")
        body_lines.append("Missing mandatory fields")
        for idx, case in enumerate(missing_critical_fields, start=1):
            body_lines.append(f"{idx}. {case}")
        body_lines.append(
            "Please resend the order with these fields filled in, or send a corrected order via furnplan."
        )
    else:
        body_lines.append("Detected a substitution request (STATT ... BITTE ...).")
        for case in substitution_cases:
            body_lines.append(f"Reply case: {case}")
    body_lines.append("")
    body_lines.append("Context")
    body_lines.append(f"Message-ID: {message_id}")
    body_lines.append(f"Received-At: {message.received_at or normalized.get('received_at') or ''}")
    body_lines.append(f"From: {message.sender or ''}")
    body_lines.append(f"Subject: {message.subject or ''}")
    body_lines.append("")
    body_lines.append("Extracted fields")
    body_lines.append(f"ticket_number: {ticket_number}")
    body_lines.append(f"kundennummer: {_header_value(header, 'kundennummer')}")
    body_lines.append(f"kom_nr: {kom_nr}")
    body_lines.append(f"kom_name: {_header_value(header, 'kom_name')}")
    body_lines.append(f"liefertermin: {_header_value(header, 'liefertermin')}")
    body_lines.append(f"wunschtermin: {_header_value(header, 'wunschtermin')}")
    body_lines.append(f"iln: {_header_value(header, 'iln')}")

    msg = EmailMessage()
    msg["To"] = to_addr
    if has_substitution and has_missing_critical:
        msg["Subject"] = f"Reply needed - multiple issues - {subject_hint}"
    elif has_missing_critical:
        msg["Subject"] = f"Reply needed - missing critical fields - {subject_hint}"
    else:
        msg["Subject"] = f"Reply needed - swap detected - {subject_hint}"
    msg.set_content("\n".join(body_lines).rstrip() + "\n")
    return msg


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
