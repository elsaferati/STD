from __future__ import annotations

import re
import unicodedata
from typing import Any

import fitz  # PyMuPDF

import openai_extract
from email_ingest import Attachment, IngestedEmail
from openai_extract import ImageInput, OpenAIExtractor
from prompts_momax_bg import build_user_instructions_momax_bg


def _is_pdf_attachment(attachment: Attachment) -> bool:
    ct = (attachment.content_type or "").lower()
    if ct.startswith("application/pdf") or ct == "application/x-pdf":
        return True
    if attachment.filename and attachment.filename.lower().endswith(".pdf"):
        return True
    return False


def _first_page_text(pdf_bytes: bytes) -> str:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        if doc.page_count <= 0:
            return ""
        page = doc.load_page(0)
        return page.get_text() or ""
    finally:
        doc.close()


_BG_KOM_WITH_DATE_RE = re.compile(
    r"(?<!\d)(\d{3,12})/(\d{2}\.\d{2}\.\d{2})(?=[^0-9]|$)"
)


def _extract_momax_bg_order_candidates(attachments: list[Attachment]) -> list[tuple[str, str]]:
    pdfs = [a for a in attachments if _is_pdf_attachment(a)]
    if not pdfs:
        return []
    combined = "\n".join(_first_page_text(p.data) for p in pdfs).strip()
    if not combined:
        return []
    return [(m.group(1), m.group(2)) for m in _BG_KOM_WITH_DATE_RE.finditer(combined)]


def extract_momax_bg_kom_nr(attachments: list[Attachment]) -> str:
    """
    Extract kom_nr for Momax BG and return only the numeric order id.

    Matches values like:
      - "VARNA - 88801711/12.12.25" -> "88801711"
      - "No 1711/12.12.25" -> "1711"
    """
    try:
        matches = _extract_momax_bg_order_candidates(attachments)
        if not matches:
            return ""
        kom_values = [kom.strip() for kom, _date in matches if kom.strip()]
        if not kom_values:
            return ""
        kom_values.sort(key=lambda s: (len(s), s), reverse=True)
        return kom_values[0]
    except Exception:
        return ""


def extract_momax_bg_order_date(attachments: list[Attachment]) -> str:
    """
    Extract BG order date suffix (dd.mm.yy) from "<digits>/<dd.mm.yy>" patterns.
    """
    try:
        matches = _extract_momax_bg_order_candidates(attachments)
        if not matches:
            return ""
        matches.sort(key=lambda pair: (len(pair[0]), pair[0], pair[1]), reverse=True)
        return matches[0][1].strip()
    except Exception:
        return ""


def is_momax_bg_two_pdf_case(attachments: list[Attachment]) -> bool:
    """
    Detect the rare Momax BG case where one order arrives as exactly two PDFs.

    Fail-closed: any error or mismatch => False.
    """
    try:
        pdfs = [a for a in attachments if _is_pdf_attachment(a)]
        if not pdfs:
            return False

        combined_raw = "\n".join(_first_page_text(p.data) for p in pdfs).strip()
        if not combined_raw:
            return False

        combined = combined_raw.lower()
        combined = unicodedata.normalize("NFKD", combined)
        combined = "".join(ch for ch in combined if not unicodedata.combining(ch))

        # Handle MOEMAX/MOMAX variants after NFKD normalization.
        has_bg = re.search(r"\bmoe?max\s+bulgaria\b", combined) is not None
        has_order = re.search(r"\bmoe?max\s*-\s*order\b", combined) is not None
        has_term = re.search(r"\bterm\s+(?:for|of)\s+delivery\b", combined) is not None
        has_kom = bool(extract_momax_bg_kom_nr(attachments))

        return bool(has_bg and has_order and has_term and has_kom)
    except Exception:
        return False


def extract_momax_bg(
    extractor: OpenAIExtractor,
    message: IngestedEmail,
    images: list[ImageInput],
    source_priority: list[str],
    email_text: str,
) -> str:
    """
    Run extraction for Momax BG special-case orders.

    Uses a BG-specific user-instructions prompt, but keeps the same SYSTEM_PROMPT and
    response handling.
    """
    user_instructions = build_user_instructions_momax_bg(source_priority)
    content: list[dict[str, Any]] = [
        {"type": "input_text", "text": user_instructions},
        {
            "type": "input_text",
            "text": (
                f"Message-ID: {message.message_id}\n"
                f"Received-At: {message.received_at}\n\n"
                f"Subject: {message.subject}\n"
                f"Sender: {message.sender}\n\n"
                f"Email body (raw text):\n{email_text or ''}"
            ),
        },
    ]

    for idx, image in enumerate(images, start=1):
        content.append(
            {
                "type": "input_text",
                "text": f"Image {idx} source: {image.source}; name: {image.name}",
            }
        )
        content.append({"type": "input_image", "image_url": image.data_url})

    response = extractor._create_response(content)
    return openai_extract._response_to_text(response)
