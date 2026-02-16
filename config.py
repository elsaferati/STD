from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "y", "on")


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass
class Config:
    openai_api_key: str
    openai_model: str
    openai_temperature: float
    openai_max_output_tokens: int
    poppler_path: str
    email_protocol: str
    email_host: str
    email_port: int
    email_user: str
    email_password: str
    email_ssl: bool
    email_folder: str
    email_search: str
    email_limit: int
    email_mark_seen: bool
    email_only_after_start: bool
    email_poll_seconds: int
    output_dir: Path

    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_ssl: bool

    reply_email_to: str
    reply_email_body: str

    source_priority: list[str]
    max_email_chars: int
    max_pdf_pages: int
    pdf_dpi: int
    max_images: int
    date_dayfirst: bool

    @classmethod
    def from_env(cls) -> "Config":
        priority_raw = os.getenv("SOURCE_PRIORITY", "pdf,email,image")
        priority = [p.strip() for p in priority_raw.split(",") if p.strip()]

        return cls(
            openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5.2-chat-latest").strip(),
            openai_temperature=_get_float("OPENAI_TEMPERATURE", 0.0),
            openai_max_output_tokens=_get_int("OPENAI_MAX_OUTPUT_TOKENS", 2000),
            poppler_path=os.getenv("POPPLER_PATH", "").strip(),
            email_protocol=os.getenv("EMAIL_PROTOCOL", "imap").strip().lower(),
            email_host=os.getenv("EMAIL_HOST", "").strip(),
            email_port=_get_int("EMAIL_PORT", 993),
            email_user=os.getenv("EMAIL_USER", "").strip(),
            email_password=os.getenv("EMAIL_PASSWORD", "").strip(),
            email_ssl=_get_bool("EMAIL_SSL", True),
            email_folder=os.getenv("EMAIL_FOLDER", "INBOX").strip(),
            email_search=os.getenv("EMAIL_SEARCH", "UNSEEN").strip(),
            email_limit=_get_int("EMAIL_LIMIT", 50),
            email_mark_seen=_get_bool("EMAIL_MARK_SEEN", False),
            email_only_after_start=_get_bool("EMAIL_ONLY_AFTER_START", True),
            email_poll_seconds=_get_int("EMAIL_POLL_SECONDS", 30),
            output_dir=Path(os.getenv("OUTPUT_DIR", "output").strip()),

            smtp_host=os.getenv("SMTP_HOST", "").strip(),
            smtp_port=_get_int("SMTP_PORT", 587),
            smtp_user=os.getenv("SMTP_USER", "").strip(),
            smtp_password=os.getenv("SMTP_PASSWORD", "").strip(),
            smtp_ssl=_get_bool("SMTP_SSL", True),

            reply_email_to=os.getenv("REPLY_EMAIL_TO", "00primex.eu@gmail.com").strip(),
            reply_email_body=os.getenv(
                "REPLY_EMAIL_BODY",
                "Please send the order with furnplan or make the order with 2 positions.",
            ).strip(),

            source_priority=priority,
            max_email_chars=_get_int("MAX_EMAIL_CHARS", 20000),
            max_pdf_pages=_get_int("MAX_PDF_PAGES", 10),
            pdf_dpi=_get_int("PDF_DPI", 300),
            max_images=_get_int("MAX_IMAGES", 20),
            date_dayfirst=_get_bool("DATE_DAYFIRST", True),
        )
