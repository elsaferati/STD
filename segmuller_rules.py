from __future__ import annotations

import re
from typing import Callable

from email_ingest import Attachment


_SEGMULLER_ORDER_PDF_FILENAME_RE = re.compile(r"bestell(?:ung)?", re.IGNORECASE)
_SEGMULLER_LAYOUT_PDF_FILENAME_RE = re.compile(
    r"(?:furnplan|skizze|aufstellung)",
    re.IGNORECASE,
)


def has_supporting_layout_pdf(
    attachments: list[Attachment],
    *,
    is_pdf: Callable[[Attachment], bool],
) -> bool:
    pdfs = [att for att in attachments if is_pdf(att)]
    if len(pdfs) < 2:
        return False

    kinds: list[str] = []
    for att in pdfs:
        filename = str(att.filename or "").strip()
        if _SEGMULLER_LAYOUT_PDF_FILENAME_RE.search(filename):
            kinds.append("layout")
            continue
        if _SEGMULLER_ORDER_PDF_FILENAME_RE.search(filename):
            kinds.append("order")
            continue
        kinds.append("supporting")

    return any(kind != "order" for kind in kinds)
