from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Callable

from email_ingest import Attachment


_SEGMULLER_ORDER_PDF_FILENAME_RE = re.compile(r"bestell(?:ung)?", re.IGNORECASE)
_SEGMULLER_LAYOUT_PDF_FILENAME_RE = re.compile(
    r"(?:furnplan|skizze|aufstellung)",
    re.IGNORECASE,
)
_SEGMULLER_ORDER_PAGE_RE = re.compile(
    r"\bB\s*E\s*S\s*T\s*E\s*L\s*L\s*U\s*N\s*G\b|\bPos\s+Upo\s+Seg-?Nr\b",
    re.IGNORECASE,
)
_SEGMULLER_ORDER_SEG_NR_RE = re.compile(r"^\s*\d{1,3}\s+\d{3}\s+(\d{5,8})\b", re.MULTILINE)
_SEGMULLER_VENDOR_SECTION_RE = re.compile(
    r"^\s*([^\W\d_][\wÄÖÜäöüß.&/\-]*)\s+.+?\(\s*Seg(?:m)?\.?\s*Nr\.?\s*\.?\s*(\d{5,8})\s*\)",
    re.IGNORECASE | re.MULTILINE,
)
_SEGMULLER_REVIEW_ONLY_REASONS = {
    "segmuller_missing_furnplan_pdf",
    "segmuller_no_staud_section",
}


@dataclass(frozen=True)
class SegmullerVendorSectionSummary:
    ordered_seg_numbers: tuple[str, ...]
    vendor_sections_found: bool
    staud_section_found: bool
    matched_staud_section_found: bool
    non_staud_vendors: tuple[str, ...]


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


def is_review_only_reason(reason: str) -> bool:
    return str(reason or "").strip() in _SEGMULLER_REVIEW_ONLY_REASONS


def extract_order_seg_numbers(page_text_by_image_name: dict[str, str]) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()
    for _image_name, page_text in sorted(page_text_by_image_name.items()):
        text = str(page_text or "")
        if not _SEGMULLER_ORDER_PAGE_RE.search(text):
            continue
        for match in _SEGMULLER_ORDER_SEG_NR_RE.finditer(text):
            seg_nr = str(match.group(1) or "").strip()
            if not seg_nr or seg_nr in seen:
                continue
            seen.add(seg_nr)
            ordered.append(seg_nr)
    return tuple(ordered)


def summarize_vendor_sections(
    page_text_by_image_name: dict[str, str],
) -> SegmullerVendorSectionSummary:
    ordered_seg_numbers = extract_order_seg_numbers(page_text_by_image_name)
    ordered_seg_set = set(ordered_seg_numbers)
    vendor_sections_found = False
    staud_section_found = False
    matched_staud_section_found = False
    non_staud_vendors: list[str] = []
    seen_non_staud: set[str] = set()

    for _image_name, page_text in sorted(page_text_by_image_name.items()):
        text = str(page_text or "")
        if not text.strip() or _SEGMULLER_ORDER_PAGE_RE.search(text):
            continue
        for match in _SEGMULLER_VENDOR_SECTION_RE.finditer(text):
            vendor_sections_found = True
            vendor_raw = str(match.group(1) or "").strip()
            seg_nr = str(match.group(2) or "").strip()
            normalized_vendor = _normalize_vendor_token(vendor_raw)
            if normalized_vendor == "staud":
                staud_section_found = True
                if not ordered_seg_set or seg_nr in ordered_seg_set:
                    matched_staud_section_found = True
                continue
            display_vendor = _clean_vendor_display_name(vendor_raw)
            if display_vendor and display_vendor not in seen_non_staud:
                seen_non_staud.add(display_vendor)
                non_staud_vendors.append(display_vendor)

    return SegmullerVendorSectionSummary(
        ordered_seg_numbers=ordered_seg_numbers,
        vendor_sections_found=vendor_sections_found,
        staud_section_found=staud_section_found,
        matched_staud_section_found=matched_staud_section_found,
        non_staud_vendors=tuple(non_staud_vendors),
    )


def _normalize_vendor_token(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^A-Za-z]+", "", text).lower()
    return text


def _clean_vendor_display_name(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:1].upper() + text[1:] if text else ""
