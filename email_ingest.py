from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email import message_from_bytes
from email.header import decode_header
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
import imaplib
import poplib
import re


@dataclass
class Attachment:
    filename: str
    content_type: str
    data: bytes


@dataclass
class IngestedEmail:
    message_id: str
    subject: str
    sender: str
    received_at: str
    body_text: str
    attachments: list[Attachment]


class _HTMLStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data:
            self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts)


def _decode_header_value(value: str | None) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return "".join(decoded)


def _html_to_text(html: str) -> str:
    stripper = _HTMLStripper()
    stripper.feed(html)
    text = stripper.get_text()
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_date(date_value: str | None) -> str:
    if not date_value:
        return ""
    try:
        dt = parsedate_to_datetime(date_value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except Exception:
        return ""


_INTERNALDATE_RE = re.compile(r'INTERNALDATE "([^"]+)"')


def _parse_internaldate(fetch_meta: bytes | None) -> str | None:
    if not fetch_meta:
        return None
    text = fetch_meta.decode("utf-8", errors="ignore")
    match = _INTERNALDATE_RE.search(text)
    if not match:
        return None
    raw = match.group(1)
    try:
        dt = datetime.strptime(raw, "%d-%b-%Y %H:%M:%S %z")
    except ValueError:
        try:
            dt = parsedate_to_datetime(raw)
        except Exception:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _is_after(received_at: str, only_after: datetime) -> bool:
    dt = _parse_iso_datetime(received_at)
    if dt is None:
        return True
    return dt > only_after


def _extract_fetch_parts(msg_data: list) -> tuple[bytes | None, bytes | None]:
    for part in msg_data:
        if isinstance(part, tuple) and len(part) >= 2:
            return part[0], part[1]
    return None, None


def _extract_message_fields(raw_message: bytes, fallback_id: str) -> IngestedEmail:
    msg = message_from_bytes(raw_message)

    subject = _decode_header_value(msg.get("Subject"))
    sender = _decode_header_value(msg.get("From"))
    message_id = _decode_header_value(msg.get("Message-ID")) or fallback_id

    received_at = _parse_date(msg.get("Date"))
    if not received_at:
        received_at = datetime.now(timezone.utc).isoformat()

    text_parts: list[str] = []
    html_parts: list[str] = []
    attachments: list[Attachment] = []

    for part in msg.walk():
        if part.is_multipart():
            continue
        content_type = part.get_content_type().lower()
        content_disposition = (part.get("Content-Disposition") or "").lower()
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""

        if filename or "attachment" in content_disposition:
            attachments.append(
                Attachment(
                    filename=filename or "attachment",
                    content_type=content_type,
                    data=payload,
                )
            )
            continue

        if content_type == "text/plain":
            charset = part.get_content_charset() or "utf-8"
            text_parts.append(payload.decode(charset, errors="replace"))
            continue

        if content_type == "text/html":
            charset = part.get_content_charset() or "utf-8"
            html_parts.append(payload.decode(charset, errors="replace"))
            continue

        if content_type.startswith("image/"):
            attachments.append(
                Attachment(
                    filename=filename or "inline-image",
                    content_type=content_type,
                    data=payload,
                )
            )

    body_text = ""
    if text_parts:
        body_text = "\n".join(text_parts).strip()
    elif html_parts:
        body_text = _html_to_text("\n".join(html_parts))

    return IngestedEmail(
        message_id=message_id,
        subject=subject,
        sender=sender,
        received_at=received_at,
        body_text=body_text,
        attachments=attachments,
    )


class EmailClient:
    def __init__(
        self,
        protocol: str,
        host: str,
        port: int,
        user: str,
        password: str,
        use_ssl: bool,
        folder: str,
        search_criteria: str,
        limit: int,
        mark_seen: bool,
        only_after: datetime | None,
    ) -> None:
        self.protocol = protocol
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.use_ssl = use_ssl
        self.folder = folder
        self.search_criteria = search_criteria
        self.limit = limit
        self.mark_seen = mark_seen
        self.only_after = only_after

    def fetch(self) -> list[IngestedEmail]:
        if self.protocol == "imap":
            return self._fetch_imap()
        if self.protocol == "pop3":
            return self._fetch_pop3()
        raise ValueError("Unsupported email protocol. Use imap or pop3 for inbox access.")

    def _fetch_imap(self) -> list[IngestedEmail]:
        if self.use_ssl:
            client = imaplib.IMAP4_SSL(self.host, self.port)
        else:
            client = imaplib.IMAP4(self.host, self.port)

        client.login(self.user, self.password)
        client.select(self.folder)

        criteria = self.search_criteria.strip()
        criteria_parts = criteria.split() if criteria else ["ALL"]
        if self.only_after:
            since_date = self.only_after.strftime("%d-%b-%Y")
            criteria_parts.extend(["SINCE", since_date])

        status, data = client.search(None, *criteria_parts)
        if status != "OK" or not data or not data[0]:
            client.logout()
            return []

        ids = data[0].split()
        if self.limit > 0:
            ids = ids[-self.limit :]

        messages: list[IngestedEmail] = []
        for msg_id in ids:
            status, msg_data = client.fetch(msg_id, "(RFC822 INTERNALDATE)")
            if status != "OK" or not msg_data:
                continue
            fetch_meta, raw = _extract_fetch_parts(msg_data)
            if not raw:
                continue
            email_obj = _extract_message_fields(raw, fallback_id=msg_id.decode("ascii", errors="ignore"))
            internal_date = _parse_internaldate(fetch_meta)
            if internal_date:
                email_obj.received_at = internal_date
            if self.only_after and not _is_after(email_obj.received_at, self.only_after):
                continue
            messages.append(email_obj)
            if self.mark_seen:
                client.store(msg_id, "+FLAGS", "\\Seen")

        client.logout()
        return messages

    def _fetch_pop3(self) -> list[IngestedEmail]:
        if self.use_ssl:
            client = poplib.POP3_SSL(self.host, self.port)
        else:
            client = poplib.POP3(self.host, self.port)

        client.user(self.user)
        client.pass_(self.password)

        resp, items, _ = client.list()
        if not items:
            client.quit()
            return []

        ids = items
        if self.limit > 0:
            ids = ids[-self.limit :]

        messages: list[IngestedEmail] = []
        for item in ids:
            msg_num = item.decode("ascii", errors="ignore").split()[0]
            resp, lines, _ = client.retr(msg_num)
            raw = b"\n".join(lines)
            email_obj = _extract_message_fields(raw, fallback_id=msg_num)
            if self.only_after and not _is_after(email_obj.received_at, self.only_after):
                continue
            messages.append(email_obj)
            if self.mark_seen:
                client.dele(msg_num)

        client.quit()
        return messages
