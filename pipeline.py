from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import base64
import mimetypes
import re
import tempfile
from typing import Any
from PIL import Image

from config import Config
from email_ingest import Attachment, IngestedEmail
import extraction_branches
import extraction_router
from item_code_verification import apply_item_code_verification
from normalize import (
    apply_momax_bg_strict_item_code_corrections,
    normalize_output,
    refresh_missing_warnings,
)
from openai_extract import ImageInput, OpenAIExtractor, parse_json_response
from poppler_utils import pdf_to_images, resolve_pdftoppm
import reply_email

import ai_customer_match
import delivery_logic
import lookup
import momax_bg
import zb_lookup

SUPPORTED_IMAGE_MIME = {"image/png", "image/jpeg", "image/jpg", "image/webp"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}
_TICKET_SUBJECT_RE = re.compile(r"ticket\s*number\b[^0-9]*(\d+)", re.IGNORECASE)
_BESTEHEND_AUS_JE_RE = re.compile(r"bestehend\s+aus\s+je\s*:", re.IGNORECASE)
_PORTA_PARENT_ARTIKEL_NR_RE = re.compile(r"\b\d{6,8}\s*/\s*\d{2}\b")
_PORTA_COMPONENT_PAIR_RE = re.compile(r"\b([A-Z0-9]{3,14})\s+(\d{4,6}[A-Z]?)\b")
_PORTA_OJ_ACCESSORY_PAIR_RE = re.compile(r"\b([O0]J\d{2})\s*(?:-| )\s*(\d{4,6}[A-Z]?)\b")
_PORTA_QTY_STK_RE = re.compile(r"\b(\d+(?:[.,]\d+)?)\s*STK\b")
_PORTA_QTY_ONLY_LINE_RE = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*$")
_PORTA_STK_ONLY_LINE_RE = re.compile(r"^\s*STK\.?\s*$", re.IGNORECASE)
_PORTA_PARENT_ROW_RE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*STK\b.*\b\d{6,8}\s*/\s*\d{2}\b"
)
_PORTA_COMPONENT_BLOCK_END_RE = re.compile(
    r"\b(?:ANLIEFERUNG|RECHNUNGSADRESSE|VERKAUFSHAUS|SERVICE-CENTER|"
    r"BESUCHEN\s+SIE\s+UNS|FRAGEN\s+AN|MENGE|ARTIKEL-NR|"
    r"AMTSGERICHT|GESCH[AÄ]FTSF[ÜU]HRER|GESCHAEFTSFUEHRER|"
    r"UST-ID|UST\s*ID|ST\.-?NR|IBAN|BIC|COMMERZBANK|COBADEFF|"
    r"HRA\s+\d{3,8}|HRB\s+\d{3,8}|H\s*R\s*[AB8]\s+\d{3,8})\b"
)
_PORTA_LEGAL_LINE_RE = re.compile(
    r"\b(?:AMTSGERICHT|GESCH[AÄ]FTSF[ÜU]HRER|GESCHAEFTSFUEHRER|"
    r"UST-ID|USt-IdNr|ST\.-?NR|IBAN|BIC|COMMERZBANK|COBADEFF|"
    r"HRA\s+\d{3,8}|HRB\s+\d{3,8}|H\s*R\s*[AB8]\s+\d{3,8})\b",
    re.IGNORECASE,
)
_PORTA_INVALID_COMPONENT_MODELS = {"HRB", "HRA"}
_PORTA_KOM_NAME_LABEL_RE = re.compile(
    r"\b(?:kommissionsname|kommissions-?name|commissionname)\b",
    re.IGNORECASE,
)
_PORTA_KOM_LINE_RE = re.compile(
    r"\b(?:kommission|komm)\b", re.IGNORECASE
)
_PORTA_KOM_NUMBER_RE = re.compile(r"\d{4,}(?:/\d+)?")
_PORTA_KOM_NAME_REJECT_RE = re.compile(
    r"\b(?:bestelldatum|datum|kundennr|kunden-?nr|debitor|konto|iln|gln|"
    r"liefertermin|wunschtermin|lieferadresse|lieferanschrift|"
    r"verk[aä]ufer|verkaeufer|verkausfhaus|service-center|"
    r"anlieferung|rechnungsadresse)\b",
    re.IGNORECASE,
)
_PORTA_STORE_NAME_LEGAL_TOKEN_RE = re.compile(
    r"\b(?:gmbh|mbh|co\.?\s*&?\s*kg|kg|ag|handels(?:gesellschaft)?)\b",
    re.IGNORECASE,
)
_PORTA_STORE_NAME_REJECT_RE = re.compile(
    r"\b(?:anlieferung|rechnungsadresse|lieferanschrift|service-?center|"
    r"telefon|fax|mail|e-?mail|www\.|http|besuchen\s+sie\s+uns|"
    r"amtsgericht|geschaeftsfuehrer|geschäftsführer|ust-?id|iban|bic)\b",
    re.IGNORECASE,
)
_PORTA_STORE_NAME_PREFIX_RE = re.compile(
    r"^\s*(?:verkaufshaus|filiale)\s*[:\-]?\s*",
    re.IGNORECASE,
)


def _clean_porta_kom_name(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    if text.isdigit():
        return ""
    if _PORTA_KOM_NAME_REJECT_RE.search(text):
        return ""
    return text


def _extract_porta_kom_name_from_pdf_texts(
    page_text_by_image_name: dict[str, str],
) -> str:
    ordered_pages = _ordered_verification_page_texts(page_text_by_image_name)
    if not ordered_pages:
        return ""

    for _image_name, page_text in ordered_pages.items():
        lines = [
            str(line).strip()
            for line in str(page_text or "").splitlines()
            if str(line).strip()
        ]
        index = 0
        while index < len(lines):
            line = lines[index]
            if _PORTA_KOM_NAME_LABEL_RE.search(line):
                parts = re.split(r"[:\-]", line, maxsplit=1)
                candidate = parts[1] if len(parts) > 1 else ""
                candidate = _clean_porta_kom_name(candidate)
                if candidate:
                    return candidate
            if _PORTA_KOM_LINE_RE.search(line):
                after = line
                parts = re.split(r"[:\-]", line, maxsplit=1)
                if len(parts) > 1:
                    after = parts[1]
                number_match = _PORTA_KOM_NUMBER_RE.search(after)
                if number_match:
                    candidate = after[number_match.end():].strip(" :,-")
                    candidate = _clean_porta_kom_name(candidate)
                    if candidate:
                        return candidate
                if number_match and index + 1 < len(lines):
                    next_line = _clean_porta_kom_name(lines[index + 1])
                    if next_line:
                        return next_line
            index += 1
    return ""


def _clean_porta_store_name(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" :,-")
    if not text:
        return ""
    text = _PORTA_STORE_NAME_PREFIX_RE.sub("", text).strip(" :,-")
    if not text:
        return ""
    lower = text.lower()
    if "porta" not in lower:
        return ""
    if _PORTA_STORE_NAME_REJECT_RE.search(text):
        return ""
    if re.search(r"\b\d{5}\b", text):
        # Store name must not include address lines.
        return ""
    if re.search(r"\b(?:str\.?|strasse|straße|allee|weg|platz|gasse)\b", text, re.IGNORECASE):
        return ""
    return text


def _extract_porta_store_name_from_pdf_texts(
    page_text_by_image_name: dict[str, str],
) -> str:
    ordered_pages = _ordered_verification_page_texts(page_text_by_image_name)
    if not ordered_pages:
        return ""

    best = ""
    best_score = -1

    for _image_name, page_text in ordered_pages.items():
        lines = [
            str(line).strip()
            for line in str(page_text or "").splitlines()
            if str(line).strip()
        ]
        for index, line in enumerate(lines):
            candidate = _clean_porta_store_name(line)
            if not candidate:
                continue

            score = 0
            if _PORTA_STORE_NAME_LEGAL_TOKEN_RE.search(candidate):
                score += 4
            if "porta moebel" in candidate.lower() or "porta mÃ¶bel" in candidate.lower():
                score += 1
            if index > 0 and re.search(r"\bverkaufshaus\b", lines[index - 1], re.IGNORECASE):
                score += 2
            if re.search(r"\bverkaufshaus\b", line, re.IGNORECASE):
                score += 2

            if score > best_score or (score == best_score and len(candidate) > len(best)):
                best = candidate
                best_score = score

    return best


@dataclass
class ProcessedResult:
    data: dict[str, Any]
    output_name: str


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value or "")
    return cleaned.strip("_") or "message"


def _is_pdf(attachment: Attachment) -> bool:
    ct = (attachment.content_type or "").lower()
    # Some clients include parameters (e.g. "application/pdf; name=...") so use startswith.
    if ct.startswith("application/pdf") or ct == "application/x-pdf":
        return True
    if attachment.filename and attachment.filename.lower().endswith(".pdf"):
        return True
    return False


def _is_image(attachment: Attachment) -> bool:
    if attachment.content_type.startswith("image/"):
        return True
    if attachment.filename and Path(attachment.filename).suffix.lower() in IMAGE_EXTENSIONS:
        return True
    return False


def _is_multipage_tif(filename: str | None, content_type: str | None) -> bool:
    """Check if the file is a TIF/TIFF that might be multipage."""
    if filename:
        suffix = Path(filename).suffix.lower()
        if suffix in {".tif", ".tiff"}:
            return True
    if content_type and content_type.lower() in {"image/tiff", "image/tif"}:
        return True
    return False


def _extract_tif_pages(
    data: bytes, warnings: list[str], name: str
) -> list[tuple[bytes, str]]:
    """Extract all pages from a multipage TIF file, converting each to PNG."""
    pages: list[tuple[bytes, str]] = []
    try:
        image = Image.open(BytesIO(data))
        page_num = 0
        while True:
            try:
                image.seek(page_num)
                rgb_image = image.convert("RGB")
                out = BytesIO()
                rgb_image.save(out, format="PNG")
                pages.append((out.getvalue(), "image/png"))
                page_num += 1
            except EOFError:
                break
        if pages:
            print(f"Extracted {len(pages)} page(s) from TIF: {name}")
    except Exception as exc:
        warnings.append(f"Failed to extract pages from TIF {name}: {exc}")
    return pages


def _coerce_image_bytes(
    data: bytes, content_type: str | None, warnings: list[str], name: str
) -> tuple[bytes, str]:
    mime = (content_type or "").lower()
    if not mime and name:
        mime = mimetypes.guess_type(name)[0] or ""

    if mime in SUPPORTED_IMAGE_MIME:
        return data, mime

    try:
        image = Image.open(BytesIO(data))
        image = image.convert("RGB")
        out = BytesIO()
        image.save(out, format="PNG")
        return out.getvalue(), "image/png"
    except Exception:
        warnings.append(f"Failed to convert image {name} to PNG; sending as-is.")
        if not mime:
            mime = "image/png"
        return data, mime


def _to_data_url(data: bytes, mime: str) -> str:
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _extract_page_number_from_image_name(image_name: str) -> int | None:
    stem = Path(image_name).stem
    match = re.search(r"-(\d+)$", stem)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _is_invalid_porta_component_model(model: str) -> bool:
    token = re.sub(r"[^A-Z0-9]", "", str(model or "").upper())
    if not token:
        return True
    normalized = token.replace("8", "B")
    if normalized in _PORTA_INVALID_COMPONENT_MODELS:
        return True
    # OCR variants of legal register tokens should never become item models.
    return normalized.startswith("HRB") or normalized.startswith("HRA")


def _extract_pdf_page_texts(
    pdf_bytes: bytes,
    max_pages: int,
    max_chars_per_page: int,
    warnings: list[str],
    filename: str,
) -> dict[int, str]:
    if max_chars_per_page == 0:
        return {}

    try:
        import fitz
    except Exception as exc:
        warnings.append(f"PDF text extraction failed for {filename}: {exc}")
        return {}

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        warnings.append(f"PDF text extraction failed for {filename}: {exc}")
        return {}

    page_texts: dict[int, str] = {}
    has_non_empty_text = False
    try:
        total_pages = doc.page_count
        limit = total_pages if max_pages <= 0 else min(total_pages, max_pages)
        for page_index in range(limit):
            text = doc[page_index].get_text() or ""
            if max_chars_per_page > 0 and len(text) > max_chars_per_page:
                warnings.append(
                    f"PDF text truncated for {filename} page {page_index + 1} to {max_chars_per_page} chars"
                )
                text = text[:max_chars_per_page]
            if text.strip():
                has_non_empty_text = True
            page_texts[page_index + 1] = text
    except Exception as exc:
        warnings.append(f"PDF text extraction failed for {filename}: {exc}")
        return {}
    finally:
        doc.close()

    if page_texts and not has_non_empty_text:
        warnings.append(f"No digital PDF text extracted for {filename}; using images only.")

    return page_texts


def _prepare_images(
    attachments: list[Attachment], config: Config, warnings: list[str]
) -> tuple[list[ImageInput], dict[str, str]]:
    images: list[ImageInput] = []
    pdf_text_by_image_name: dict[str, str] = {}
    pdfs = [att for att in attachments if _is_pdf(att)]

    pdftoppm_path = ""
    if pdfs:
        try:
            pdftoppm_path = resolve_pdftoppm(config.poppler_path)
        except Exception as exc:
            warnings.append(str(exc))
            pdfs = []

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        for att in pdfs:
            pdf_name = _safe_name(att.filename) + ".pdf"
            pdf_path = temp_path / pdf_name
            pdf_path.write_bytes(att.data)
            page_texts = _extract_pdf_page_texts(
                att.data,
                config.max_pdf_pages,
                config.max_pdf_text_chars_per_page,
                warnings,
                att.filename or "attachment.pdf",
            )
            try:
                image_paths = pdf_to_images(
                    pdf_path,
                    temp_path,
                    pdftoppm_path,
                    config.max_pdf_pages,
                    config.pdf_dpi,
                )
            except Exception as exc:
                warnings.append(f"PDF conversion failed for {att.filename}: {exc}")
                continue
            for image_path in image_paths:
                data = image_path.read_bytes()
                data_url = _to_data_url(data, "image/png")
                images.append(
                    ImageInput(name=image_path.name, source="pdf", data_url=data_url)
                )
                page_number = _extract_page_number_from_image_name(image_path.name)
                if page_number is None:
                    continue
                page_text = page_texts.get(page_number, "")
                if page_text.strip():
                    pdf_text_by_image_name[image_path.name] = page_text

        for att in attachments:
            if not _is_image(att):
                continue
            
            # Handle multipage TIF files
            if _is_multipage_tif(att.filename, att.content_type):
                tif_pages = _extract_tif_pages(att.data, warnings, att.filename or "tif")
                for idx, (page_data, page_mime) in enumerate(tif_pages):
                    page_name = f"{att.filename or 'tif'}_page_{idx + 1}"
                    data_url = _to_data_url(page_data, page_mime)
                    images.append(ImageInput(name=page_name, source="image", data_url=data_url))
            else:
                data, mime = _coerce_image_bytes(att.data, att.content_type, warnings, att.filename)
                data_url = _to_data_url(data, mime or "image/png")
                images.append(ImageInput(name=att.filename or "image", source="image", data_url=data_url))

    if config.max_images > 0 and len(images) > config.max_images:
        warnings.append(
            f"Image count truncated from {len(images)} to {config.max_images}."
        )
        images = images[: config.max_images]
        kept_names = {image.name for image in images}
        pdf_text_by_image_name = {
            name: text
            for name, text in pdf_text_by_image_name.items()
            if name in kept_names
        }

    return images, pdf_text_by_image_name


def _extract_ticket_number(subject: str) -> str:
    if not subject:
        return ""
    match = _TICKET_SUBJECT_RE.search(subject)
    if not match:
        return ""
    digits = str(match.group(1) or "").strip()
    if len(digits) == 7 and digits.isdigit() and int(digits) >= 1000000:
        return digits
    return ""


def _entry_value(entry: Any) -> Any:
    if isinstance(entry, dict):
        return entry.get("value")
    return entry


def _ensure_item_field(item: dict[str, Any], field: str) -> dict[str, Any]:
    entry = item.get(field)
    if not isinstance(entry, dict):
        entry = {"value": entry if entry is not None else "", "source": "derived", "confidence": 0.0}
        item[field] = entry
    entry.setdefault("value", "")
    entry.setdefault("source", "derived")
    entry.setdefault("confidence", 0.0)
    return entry


def _extract_porta_qty_marker(
    lines: list[str],
    index: int,
) -> tuple[int | float, int] | None:
    line = str(lines[index] or "").strip()
    if not line:
        return None

    inline_match = _PORTA_QTY_STK_RE.search(line.upper())
    if inline_match:
        return _parse_qty_token(inline_match.group(1)), 1

    qty_only_match = _PORTA_QTY_ONLY_LINE_RE.match(line)
    if (
        qty_only_match
        and index + 1 < len(lines)
        and _PORTA_STK_ONLY_LINE_RE.match(str(lines[index + 1] or "").strip())
    ):
        return _parse_qty_token(qty_only_match.group(1)), 2

    return None


def _extract_porta_quantity_candidates(
    page_text_by_image_name: dict[str, str],
) -> dict[tuple[str, str], set[int | float]]:
    ordered_pages = _ordered_verification_page_texts(page_text_by_image_name)
    if not ordered_pages:
        return {}

    qty_map: dict[tuple[str, str], set[int | float]] = {}
    for _image_name, page_text in ordered_pages.items():
        lines = [
            str(line).strip()
            for line in str(page_text or "").splitlines()
            if str(line).strip()
        ]
        index = 0
        while index < len(lines):
            line = lines[index]
            qty_marker = _extract_porta_qty_marker(lines, index)
            if not qty_marker:
                index += 1
                continue
            qty, consumed = qty_marker
            pairs: list[tuple[str, str]] = []
            candidate_indexes = [index, index - 1, index + consumed, index + consumed + 1]
            for candidate_index in candidate_indexes:
                if candidate_index < 0 or candidate_index >= len(lines):
                    continue
                candidate_upper = lines[candidate_index].upper()
                pairs = _PORTA_COMPONENT_PAIR_RE.findall(candidate_upper)
                if pairs:
                    break
            for model, article in pairs:
                if not any(ch.isalpha() for ch in model):
                    continue
                if _is_invalid_porta_component_model(model):
                    continue
                key = (model, article)
                qty_map.setdefault(key, set()).add(qty)
            index += consumed
    return qty_map


def _apply_porta_quantity_corrections(
    normalized: dict[str, Any],
    page_text_by_image_name: dict[str, str],
) -> None:
    items = normalized.get("items")
    if not isinstance(items, list) or not items:
        return
    qty_map = _extract_porta_quantity_candidates(page_text_by_image_name)
    if not qty_map:
        return
    warnings = normalized.get("warnings")
    if not isinstance(warnings, list):
        warnings = []
        normalized["warnings"] = warnings

    for item in items:
        if not isinstance(item, dict):
            continue
        model = str(_entry_value(item.get("modellnummer")) or "").strip().upper()
        article = str(_entry_value(item.get("artikelnummer")) or "").strip().upper()
        if not model or not article:
            continue
        key = (model, article)
        qty_set = qty_map.get(key)
        if not qty_set or len(qty_set) != 1:
            continue
        qty = next(iter(qty_set))
        entry = _ensure_item_field(item, "menge")
        current = _parse_qty_token(entry.get("value"))
        if _qty_key(current) == _qty_key(qty):
            continue
        entry["value"] = qty
        entry["source"] = "derived"
        entry["confidence"] = 0.95
        entry["derived_from"] = "porta_pdf_quantity"
        line_no = item.get("line_no", "")
        warnings.append(
            f"Porta quantity corrected from PDF text for item line {line_no}: {current} -> {qty}."
        )


def _trim_porta_component_excess_items(
    normalized: dict[str, Any],
    page_text_by_image_name: dict[str, str],
) -> None:
    items = normalized.get("items")
    if not isinstance(items, list) or not items:
        return
    expected_occurrences = _extract_porta_component_occurrences_from_page_texts(
        page_text_by_image_name
    )
    if not expected_occurrences:
        return

    expected_counts: Counter[tuple[str, str, str]] = Counter()
    for occurrence in expected_occurrences:
        key = (
            str(occurrence.get("modellnummer") or "").strip().upper(),
            str(occurrence.get("artikelnummer") or "").strip().upper(),
            _qty_key(occurrence.get("menge")),
        )
        if not key[0] or not key[1]:
            continue
        expected_counts[key] += 1

    if not expected_counts:
        return

    items_by_key: dict[tuple[str, str, str], list[tuple[int, dict[str, Any]]]] = {}
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        model = str(_entry_value(item.get("modellnummer")) or "").strip().upper()
        article = str(_entry_value(item.get("artikelnummer")) or "").strip().upper()
        if not model or not article:
            continue
        qty = _qty_key(_entry_value(item.get("menge")))
        key = (model, article, qty)
        items_by_key.setdefault(key, []).append((idx, item))

    to_remove: set[int] = set()
    for key, group in items_by_key.items():
        expected = expected_counts.get(key, 0)
        if expected <= 0:
            continue
        if len(group) <= expected:
            continue
        # Prefer keeping non-derived items; remove derived reconciliation entries first.
        def _priority(entry: dict[str, Any]) -> tuple[int, int]:
            derived_from = ""
            model_entry = entry.get("modellnummer", {})
            if isinstance(model_entry, dict):
                derived_from = str(model_entry.get("derived_from") or "")
            # Lower is better (kept)
            is_reconciliation = 1 if "porta_component_occurrence_reconciliation" in derived_from else 0
            is_derived = 1 if (isinstance(model_entry, dict) and model_entry.get("source") == "derived") else 0
            return (is_reconciliation, is_derived)

        sorted_group = sorted(group, key=lambda pair: _priority(pair[1]))
        # Keep first expected, remove the rest
        for idx, _item in sorted_group[expected:]:
            to_remove.add(idx)

    if not to_remove:
        return

    warnings = normalized.get("warnings")
    if not isinstance(warnings, list):
        warnings = []
        normalized["warnings"] = warnings

    trimmed = [item for i, item in enumerate(items) if i not in to_remove]
    removed_count = len(items) - len(trimmed)
    if removed_count > 0:
        normalized["items"] = trimmed
        for line_no, item in enumerate(trimmed, start=1):
            if isinstance(item, dict):
                item["line_no"] = line_no
        warnings.append(
            f"Porta: removed {removed_count} duplicate component item(s) based on PDF text."
        )


def _apply_porta_oj_accessory_article_backfill(
    normalized: dict[str, Any],
    page_text_by_image_name: dict[str, str],
) -> None:
    items = normalized.get("items")
    if not isinstance(items, list) or not items:
        return

    ordered_pages = _ordered_verification_page_texts(page_text_by_image_name)
    if not ordered_pages:
        return

    expected_counts: Counter[tuple[str, str]] = Counter()
    for _image_name, page_text in ordered_pages.items():
        text_upper = str(page_text or "").upper()
        for model, article in _PORTA_OJ_ACCESSORY_PAIR_RE.findall(text_upper):
            expected_counts[(model, article)] += 1
    if not expected_counts:
        return

    existing_counts: Counter[tuple[str, str]] = Counter()
    for item in items:
        if not isinstance(item, dict):
            continue
        model = str(_entry_value(item.get("modellnummer")) or "").strip().upper()
        article = str(_entry_value(item.get("artikelnummer")) or "").strip().upper()
        if not model or not article:
            continue
        existing_counts[(model, article)] += 1

    remaining_by_model: dict[str, Counter[str]] = {}
    for (model, article), expected in expected_counts.items():
        remaining = expected - existing_counts.get((model, article), 0)
        if remaining <= 0:
            continue
        remaining_by_model.setdefault(model, Counter())[article] = remaining
    if not remaining_by_model:
        return

    warnings = _ensure_warning_list(normalized)
    corrections = 0
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        model = str(_entry_value(item.get("modellnummer")) or "").strip().upper()
        article = str(_entry_value(item.get("artikelnummer")) or "").strip().upper()
        if not model or not model.startswith(("OJ", "0J")) or article:
            continue
        model_remaining = remaining_by_model.get(model)
        if not model_remaining:
            continue
        candidates = [art for art, count in model_remaining.items() if count > 0]
        if len(candidates) != 1:
            continue

        chosen_article = candidates[0]
        article_entry = _ensure_item_field(item, "artikelnummer")
        article_entry["value"] = chosen_article
        article_entry["source"] = "derived"
        article_entry["confidence"] = 1.0
        article_entry["derived_from"] = "porta_oj_accessory_backfill"

        model_remaining[chosen_article] -= 1
        if model_remaining[chosen_article] <= 0:
            del model_remaining[chosen_article]

        line_no = item.get("line_no", index)
        warnings.append(
            f"Porta: filled missing artikelnummer for item line {line_no} "
            f"from PDF accessory pair {model} {chosen_article}."
        )
        corrections += 1

    if corrections > 0:
        header = normalized.get("header")
        if not isinstance(header, dict):
            header = {}
            normalized["header"] = header
        review_entry = header.get("human_review_needed")
        if not isinstance(review_entry, dict):
            review_entry = {"value": False, "source": "derived", "confidence": 1.0}
            header["human_review_needed"] = review_entry
        review_entry["value"] = True
        review_entry["source"] = "derived"
        review_entry["confidence"] = 1.0
        review_entry["derived_from"] = "porta_oj_accessory_backfill"


def _build_items_snapshot(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    snapshot: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        try:
            line_no = int(item.get("line_no", index))
        except (TypeError, ValueError):
            line_no = index
        snapshot.append(
            {
                "line_no": line_no,
                "modellnummer": _entry_value(item.get("modellnummer")) or "",
                "artikelnummer": _entry_value(item.get("artikelnummer")) or "",
                "menge": _entry_value(item.get("menge")),
            }
        )
    return snapshot


def _ordered_verification_page_texts(
    page_text_by_image_name: dict[str, str],
) -> dict[str, str]:
    ordered_pages: list[tuple[str, str, int, str]] = []
    for image_name, page_text in page_text_by_image_name.items():
        text = str(page_text or "")
        if not text.strip():
            continue
        page_number = _extract_page_number_from_image_name(image_name)
        ordered_pages.append(
            (
                image_name,
                text,
                page_number if page_number is not None else 10**9,
                image_name,
            )
        )

    ordered_pages.sort(key=lambda item: (item[2], item[3]))
    return {image_name: text for image_name, text, _, _ in ordered_pages}


def _parse_qty_token(token: str) -> int | float:
    text = str(token or "").strip().replace(" ", "")
    if not text:
        return 1
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    else:
        text = text.replace(",", "")
    try:
        number = float(text)
    except ValueError:
        return 1
    if number.is_integer():
        return int(number)
    return number


def _qty_key(value: Any) -> str:
    if value is None:
        return "1"
    if isinstance(value, (int, float)):
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)
    text = str(value).strip()
    if not text:
        return "1"
    parsed = _parse_qty_token(text)
    return str(parsed)


def _is_porta_component_block_end(line: str) -> bool:
    upper = str(line or "").upper()
    if _PORTA_PARENT_ARTIKEL_NR_RE.search(upper):
        return True
    if _PORTA_PARENT_ROW_RE.search(upper):
        return True
    if _PORTA_LEGAL_LINE_RE.search(upper):
        return True
    return bool(_PORTA_COMPONENT_BLOCK_END_RE.search(upper))


def _normalize_porta_parent_artikel_nr(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").upper())


def _extract_porta_parent_signature(line: str) -> tuple[str, str, str] | None:
    upper = str(line or "").upper()
    if not upper or _PORTA_LEGAL_LINE_RE.search(upper):
        return None

    artikel_match = _PORTA_PARENT_ARTIKEL_NR_RE.search(upper)
    artikel_nr = (
        _normalize_porta_parent_artikel_nr(artikel_match.group(0))
        if artikel_match
        else ""
    )

    pair_model = ""
    pair_article = ""
    for model, article in _PORTA_COMPONENT_PAIR_RE.findall(upper):
        if not any(ch.isalpha() for ch in model):
            continue
        if _is_invalid_porta_component_model(model):
            continue
        pair_model = model
        pair_article = article

    # Parent signatures should be anchored to visible parent context, not arbitrary lines.
    if not artikel_nr and not ("LIEFERMODELL" in upper and pair_model and pair_article):
        return None
    if not artikel_nr and not pair_model:
        return None
    return (artikel_nr, pair_model, pair_article)


def _extract_porta_component_pair_from_group(
    group_lines: list[str],
) -> tuple[str, str] | None:
    if not group_lines:
        return None

    pairs: list[tuple[str, str]] = []
    for raw_line in group_lines:
        line = str(raw_line or "").upper()
        if _PORTA_LEGAL_LINE_RE.search(line):
            continue
        pairs.extend(_PORTA_COMPONENT_PAIR_RE.findall(line))
    if not pairs:
        return None

    model, article = pairs[-1]
    if not any(ch.isalpha() for ch in model):
        return None
    if _is_invalid_porta_component_model(model):
        return None
    return (model, article)


def _append_component_to_block(
    component_block: dict[str, Any] | None,
    group_lines: list[str],
    quantity: int | float,
    has_explicit_qty: bool,
) -> None:
    if not component_block:
        return
    if not has_explicit_qty:
        return

    pair = _extract_porta_component_pair_from_group(group_lines)
    if not pair:
        return

    components = component_block.get("components")
    if not isinstance(components, list):
        components = []
        component_block["components"] = components
    model, article = pair
    components.append(
        {
            "modellnummer": model,
            "artikelnummer": article,
            "menge": quantity,
            "explicit": True,
        }
    )


def _finalize_porta_component_block(
    blocks: list[dict[str, Any]],
    block: dict[str, Any] | None,
) -> None:
    if not isinstance(block, dict):
        return
    components = block.get("components")
    if not isinstance(components, list) or not components:
        return
    blocks.append(block)


def _extract_porta_component_blocks_from_page_texts(
    page_text_by_image_name: dict[str, str],
) -> list[dict[str, Any]]:
    ordered_pages = _ordered_verification_page_texts(page_text_by_image_name)
    if not ordered_pages:
        return []

    blocks: list[dict[str, Any]] = []
    for image_name, page_text in ordered_pages.items():
        lines = [
            str(line).strip()
            for line in str(page_text or "").splitlines()
            if str(line).strip()
        ]
        in_component_block = False
        current_group_lines: list[str] = []
        current_group_qty: int | float = 1
        current_group_has_explicit_qty = False
        current_block: dict[str, Any] | None = None
        last_parent_signature: tuple[str, str, str] | None = None
        index = 0

        while index < len(lines):
            line = lines[index]
            upper = line.upper()

            if in_component_block and _is_porta_component_block_end(line):
                _append_component_to_block(
                    component_block=current_block,
                    group_lines=current_group_lines,
                    quantity=current_group_qty,
                    has_explicit_qty=current_group_has_explicit_qty,
                )
                current_group_lines = []
                current_group_qty = 1
                current_group_has_explicit_qty = False
                _finalize_porta_component_block(blocks, current_block)
                current_block = None
                in_component_block = False
                continue

            if _BESTEHEND_AUS_JE_RE.search(line):
                if in_component_block:
                    _append_component_to_block(
                        component_block=current_block,
                        group_lines=current_group_lines,
                        quantity=current_group_qty,
                        has_explicit_qty=current_group_has_explicit_qty,
                    )
                    _finalize_porta_component_block(blocks, current_block)
                in_component_block = True
                current_group_lines = []
                current_group_qty = 1
                current_group_has_explicit_qty = False
                current_block = {
                    "page": image_name,
                    "parent_signature": last_parent_signature,
                    "components": [],
                }
                index += 1
                continue

            if in_component_block:
                qty_marker = _extract_porta_qty_marker(lines, index)
                if qty_marker:
                    qty_value, consumed = qty_marker
                    if current_group_lines and not current_group_has_explicit_qty:
                        # Layout variant where qty marker comes after the component description.
                        _append_component_to_block(
                            component_block=current_block,
                            group_lines=current_group_lines,
                            quantity=qty_value,
                            has_explicit_qty=True,
                        )
                        current_group_lines = []
                        current_group_qty = 1
                        current_group_has_explicit_qty = False
                    else:
                        # Default layout where qty marker starts a component group.
                        _append_component_to_block(
                            component_block=current_block,
                            group_lines=current_group_lines,
                            quantity=current_group_qty,
                            has_explicit_qty=current_group_has_explicit_qty,
                        )
                        current_group_lines = [line]
                        current_group_qty = qty_value
                        current_group_has_explicit_qty = True
                    index += consumed
                else:
                    current_group_lines.append(line)
                    index += 1
                continue

            parent_signature = _extract_porta_parent_signature(line)
            if parent_signature:
                last_parent_signature = parent_signature
            index += 1

        if in_component_block:
            _append_component_to_block(
                component_block=current_block,
                group_lines=current_group_lines,
                quantity=current_group_qty,
                has_explicit_qty=current_group_has_explicit_qty,
            )
            _finalize_porta_component_block(blocks, current_block)

    return blocks


def _extract_porta_component_occurrences_from_blocks(
    blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    occurrences: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        components = block.get("components")
        if not isinstance(components, list):
            continue
        for component in components:
            if not isinstance(component, dict):
                continue
            model = str(component.get("modellnummer") or "").strip().upper()
            article = str(component.get("artikelnummer") or "").strip().upper()
            if not model or not article:
                continue
            occurrences.append(
                {
                    "modellnummer": model,
                    "artikelnummer": article,
                    "menge": component.get("menge", 1),
                    "page": block.get("page", ""),
                    "parent_signature": block.get("parent_signature"),
                    "explicit": bool(component.get("explicit", False)),
                }
            )
    return occurrences


def _extract_porta_expected_occurrences_with_backfill(
    blocks: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    expected: list[dict[str, Any]] = []
    canonical_components_by_parent: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    backfilled_component_count = 0

    for block in blocks:
        if not isinstance(block, dict):
            continue

        raw_components = block.get("components")
        if not isinstance(raw_components, list):
            raw_components = []

        components: list[dict[str, Any]] = []
        for component in raw_components:
            if not isinstance(component, dict):
                continue
            model = str(component.get("modellnummer") or "").strip().upper()
            article = str(component.get("artikelnummer") or "").strip().upper()
            if not model or not article:
                continue
            components.append(
                {
                    "modellnummer": model,
                    "artikelnummer": article,
                    "menge": component.get("menge", 1),
                    "explicit": bool(component.get("explicit", False)),
                }
            )

        parent_signature = block.get("parent_signature")
        if (
            isinstance(parent_signature, tuple)
            and len(parent_signature) == 3
            and any(parent_signature)
        ):
            canonical = canonical_components_by_parent.get(parent_signature)
            if canonical and len(components) < len(canonical):
                canonical_counts: Counter[tuple[str, str, str]] = Counter()
                observed_counts: Counter[tuple[str, str, str]] = Counter()
                for canonical_component in canonical:
                    canonical_counts[
                        (
                            str(canonical_component.get("modellnummer") or "").strip().upper(),
                            str(canonical_component.get("artikelnummer") or "").strip().upper(),
                            _qty_key(canonical_component.get("menge")),
                        )
                    ] += 1
                for observed_component in components:
                    observed_counts[
                        (
                            str(observed_component.get("modellnummer") or "").strip().upper(),
                            str(observed_component.get("artikelnummer") or "").strip().upper(),
                            _qty_key(observed_component.get("menge")),
                        )
                    ] += 1

                missing_counts = canonical_counts - observed_counts
                if missing_counts:
                    for canonical_component in canonical:
                        key = (
                            str(canonical_component.get("modellnummer") or "").strip().upper(),
                            str(canonical_component.get("artikelnummer") or "").strip().upper(),
                            _qty_key(canonical_component.get("menge")),
                        )
                        if missing_counts.get(key, 0) <= 0:
                            continue
                        backfilled = dict(canonical_component)
                        backfilled["explicit"] = False
                        components.append(backfilled)
                        missing_counts[key] -= 1
                        backfilled_component_count += 1
            if parent_signature not in canonical_components_by_parent or len(components) > len(
                canonical_components_by_parent[parent_signature]
            ):
                canonical_components_by_parent[parent_signature] = [
                    dict(component) for component in components
                ]

        for component in components:
            expected.append(
                {
                    "modellnummer": component.get("modellnummer", ""),
                    "artikelnummer": component.get("artikelnummer", ""),
                    "menge": component.get("menge", 1),
                    "page": block.get("page", ""),
                    "parent_signature": parent_signature,
                    "explicit": bool(component.get("explicit", False)),
                }
            )

    return expected, backfilled_component_count


def _extract_porta_component_occurrences_from_page_texts(
    page_text_by_image_name: dict[str, str],
) -> list[dict[str, Any]]:
    blocks = _extract_porta_component_blocks_from_page_texts(page_text_by_image_name)
    return _extract_porta_component_occurrences_from_blocks(blocks)


def _count_item_occurrences(items: Any) -> dict[tuple[str, str, str], int]:
    counts: Counter[tuple[str, str, str]] = Counter()
    if not isinstance(items, list):
        return {}
    for item in items:
        if not isinstance(item, dict):
            continue
        model = str(_entry_value(item.get("modellnummer")) or "").strip().upper()
        article = str(_entry_value(item.get("artikelnummer")) or "").strip().upper()
        if not model or not article:
            continue
        qty = _qty_key(_entry_value(item.get("menge")))
        counts[(model, article, qty)] += 1
    return dict(counts)


def _count_non_derived_item_pairs(items: Any) -> dict[tuple[str, str], int]:
    counts: Counter[tuple[str, str]] = Counter()
    if not isinstance(items, list):
        return {}
    for item in items:
        if not isinstance(item, dict):
            continue
        model = str(_entry_value(item.get("modellnummer")) or "").strip().upper()
        article = str(_entry_value(item.get("artikelnummer")) or "").strip().upper()
        if not model or not article:
            continue
        model_source = "derived"
        article_source = "derived"
        model_entry = item.get("modellnummer")
        article_entry = item.get("artikelnummer")
        if isinstance(model_entry, dict):
            model_source = str(model_entry.get("source") or "derived").lower()
        if isinstance(article_entry, dict):
            article_source = str(article_entry.get("source") or "derived").lower()
        if model_source == "derived" and article_source == "derived":
            continue
        counts[(model, article)] += 1
    return dict(counts)


def _ensure_warning_list(normalized: dict[str, Any]) -> list[str]:
    warnings = normalized.get("warnings")
    if isinstance(warnings, list):
        return warnings
    if warnings is None:
        warnings = []
    else:
        warnings = [str(warnings)]
    normalized["warnings"] = warnings
    return warnings


def _set_porta_reconciliation_human_review(normalized: dict[str, Any]) -> None:
    header = normalized.get("header")
    if not isinstance(header, dict):
        header = {}
        normalized["header"] = header

    entry = header.get("human_review_needed")
    if not isinstance(entry, dict):
        entry = {"value": False, "source": "derived", "confidence": 1.0}
        header["human_review_needed"] = entry

    entry["value"] = True
    entry["source"] = "derived"
    entry["confidence"] = 1.0
    entry["derived_from"] = "porta_component_occurrence_reconciliation"


def _reconcile_porta_component_occurrences(
    normalized: dict[str, Any],
    page_text_by_image_name: dict[str, str],
) -> int:
    component_blocks = _extract_porta_component_blocks_from_page_texts(
        page_text_by_image_name
    )
    expected_occurrences, backfilled_component_count = (
        _extract_porta_expected_occurrences_with_backfill(component_blocks)
    )
    if not expected_occurrences:
        return 0

    items = normalized.get("items")
    if not isinstance(items, list):
        items = []
        normalized["items"] = items

    existing_counts = _count_item_occurrences(items)
    non_derived_pair_counts = _count_non_derived_item_pairs(items)
    explicit_expected_pair_counts: Counter[tuple[str, str]] = Counter()
    for occurrence in expected_occurrences:
        if not bool(occurrence.get("explicit", False)):
            continue
        model = str(occurrence.get("modellnummer") or "").strip().upper()
        article = str(occurrence.get("artikelnummer") or "").strip().upper()
        if not model or not article:
            continue
        explicit_expected_pair_counts[(model, article)] += 1

    seen_expected: Counter[tuple[str, str, str]] = Counter()
    missing_occurrences: list[dict[str, Any]] = []
    skipped_due_guard = 0

    for occurrence in expected_occurrences:
        key = (
            str(occurrence.get("modellnummer") or "").strip().upper(),
            str(occurrence.get("artikelnummer") or "").strip().upper(),
            _qty_key(occurrence.get("menge")),
        )
        if not key[0] or not key[1]:
            continue
        seen_expected[key] += 1
        if seen_expected[key] > existing_counts.get(key, 0):
            pair_key = (key[0], key[1])
            has_non_derived_item = non_derived_pair_counts.get(pair_key, 0) > 0
            has_second_explicit_occurrence = explicit_expected_pair_counts.get(pair_key, 0) > 1
            parent_signature = occurrence.get("parent_signature")
            has_parent_signature = (
                isinstance(parent_signature, tuple)
                and len(parent_signature) == 3
                and any(parent_signature)
            )
            is_inferred_occurrence = not bool(occurrence.get("explicit", False))
            if (
                has_non_derived_item
                and not has_second_explicit_occurrence
                and is_inferred_occurrence
                and not has_parent_signature
            ):
                skipped_due_guard += 1
                continue
            missing_occurrences.append(occurrence)

    warnings = _ensure_warning_list(normalized)
    if backfilled_component_count > 0:
        warnings.append(
            "Porta reconciliation backfilled missing component(s) in repeated "
            "'bestehend aus je:' block based on earlier matching block."
        )
    if skipped_due_guard > 0:
        warnings.append(
            "Porta reconciliation skipped "
            f"{skipped_due_guard} inferred component occurrence(s) because a non-derived "
            "item already exists for the same model/article and no second explicit "
            "'bestehend aus je:' occurrence was found."
        )

    if not missing_occurrences:
        return 0

    for occurrence in missing_occurrences:
        qty_value = occurrence.get("menge", 1)
        items.append(
            {
                "line_no": 0,
                "modellnummer": {
                    "value": str(occurrence.get("modellnummer") or "").strip().upper(),
                    "source": "derived",
                    "confidence": 1.0,
                    "derived_from": "porta_component_occurrence_reconciliation",
                },
                "artikelnummer": {
                    "value": str(occurrence.get("artikelnummer") or "").strip().upper(),
                    "source": "derived",
                    "confidence": 1.0,
                    "derived_from": "porta_component_occurrence_reconciliation",
                },
                "menge": {
                    "value": _parse_qty_token(str(qty_value)),
                    "source": "derived",
                    "confidence": 1.0,
                    "derived_from": "porta_component_occurrence_reconciliation",
                },
                "furncloud_id": {
                    "value": "",
                    "source": "derived",
                    "confidence": 0.0,
                },
            }
        )

    for line_no, item in enumerate(items, start=1):
        if isinstance(item, dict):
            item["line_no"] = line_no

    inserted_counts: Counter[tuple[str, str, str]] = Counter()
    for occurrence in missing_occurrences:
        inserted_counts[
            (
                str(occurrence.get("modellnummer") or "").strip().upper(),
                str(occurrence.get("artikelnummer") or "").strip().upper(),
                _qty_key(occurrence.get("menge")),
            )
        ] += 1

    summary_parts: list[str] = []
    for (model, article, qty), count in inserted_counts.items():
        summary_parts.append(f"{model}/{article} qty={qty} x{count}")
    if len(summary_parts) > 6:
        summary = ", ".join(summary_parts[:6]) + f", ... (+{len(summary_parts) - 6} more)"
    else:
        summary = ", ".join(summary_parts)

    warnings.append(
        "Porta component occurrence reconciliation added "
        f"{len(missing_occurrences)} item(s) from 'bestehend aus je:' blocks: {summary}."
    )
    _set_porta_reconciliation_human_review(normalized)
    return len(missing_occurrences)


def process_message(
    message: IngestedEmail, config: Config, extractor: OpenAIExtractor
) -> ProcessedResult:
    warnings: list[str] = []
    body_text = message.body_text or ""
    if config.max_email_chars > 0 and len(body_text) > config.max_email_chars:
        warnings.append(
            f"Email body truncated to {config.max_email_chars} characters."
        )
        body_text = body_text[: config.max_email_chars]

    route = extraction_router.route_message(message, config, extractor)
    branch = extraction_branches.get_branch(route.selected_branch_id)
    warnings.append(extraction_router.format_routing_warning(route))

    prepared_images = _prepare_images(message.attachments, config, warnings)
    if isinstance(prepared_images, tuple):
        images, pdf_text_by_image_name = prepared_images
    else:
        images = prepared_images
        pdf_text_by_image_name = {}
    user_instructions = branch.build_user_instructions(config.source_priority)

    max_retries = 3
    last_error: Exception | None = None
    parsed = None
    
    for attempt in range(1, max_retries + 1):
        try:
            response_text = extractor.extract_with_prompts(
                message_id=message.message_id,
                received_at=message.received_at,
                email_text=body_text,
                images=images,
                source_priority=config.source_priority,
                subject=message.subject,
                sender=message.sender,
                system_prompt=branch.system_prompt,
                user_instructions=user_instructions,
                page_text_by_image_name=pdf_text_by_image_name,
            )
            parsed = parse_json_response(response_text)
            if branch.is_momax_bg and isinstance(parsed, dict):
                header = parsed.get("header")
                if isinstance(header, dict):
                    header["kom_name"] = {
                        "value": "",
                        "source": "derived",
                        "confidence": 0.0,
                        "derived_from": "momax_bg_policy",
                    }
                    if "kom_name_pdf" in header:
                        del header["kom_name_pdf"]
            break  # Success, exit retry loop
        except Exception as exc:
            last_error = exc
            if attempt < max_retries:
                import time
                print(f"Extraction attempt {attempt} failed: {exc}. Retrying...")
                time.sleep(2)  # Wait 2 seconds before retry
            else:
                print(f"Extraction attempt {attempt} failed: {exc}. No more retries.")
    
    if parsed is None:
        data = {
            "message_id": message.message_id,
            "received_at": message.received_at,
            "header": {},
            "items": [],
            "status": "failed",
            "warnings": warnings,
            "errors": [str(last_error)],
        }
        output_name = _safe_name(message.message_id)
        return ProcessedResult(data=data, output_name=output_name)

    normalized = normalize_output(
        parsed,
        message_id=message.message_id,
        received_at=message.received_at,
        dayfirst=config.date_dayfirst,
        warnings=warnings,
        email_body=body_text,
        sender=message.sender,
        is_momax_bg=branch.is_momax_bg,
        branch_id=branch.id,
    )

    if branch.id == "porta":
        _reconcile_porta_component_occurrences(normalized, pdf_text_by_image_name)
        header = normalized.get("header")
        if not isinstance(header, dict):
            header = {}
            normalized["header"] = header
        store_from_pdf = _extract_porta_store_name_from_pdf_texts(pdf_text_by_image_name)
        if store_from_pdf:
            store_entry = header.get("store_name")
            existing_store = _entry_value(store_entry).strip()
            should_override = False
            if not existing_store:
                should_override = True
            else:
                existing_has_legal = bool(_PORTA_STORE_NAME_LEGAL_TOKEN_RE.search(existing_store))
                pdf_has_legal = bool(_PORTA_STORE_NAME_LEGAL_TOKEN_RE.search(store_from_pdf))
                if pdf_has_legal and (not existing_has_legal or len(store_from_pdf) > len(existing_store)):
                    should_override = True
            if should_override:
                prev_value = existing_store
                header["store_name"] = {
                    "value": store_from_pdf,
                    "source": "pdf",
                    "confidence": 0.98,
                    "derived_from": "porta_pdf_verkaufshaus_store_name",
                }
                normalized_warnings = normalized.get("warnings")
                if isinstance(normalized_warnings, list):
                    if prev_value and prev_value != store_from_pdf:
                        normalized_warnings.append(
                            "Porta: store_name replaced by full legal Verkaufshaus name from PDF."
                        )
                    elif not prev_value:
                        normalized_warnings.append(
                            "Porta: store_name filled from PDF Verkaufshaus legal name."
                        )
        kom_nr_entry = header.get("kom_nr", {})
        kom_nr_val = ""
        if isinstance(kom_nr_entry, dict):
            kom_nr_val = str(kom_nr_entry.get("value", "") or "").strip()
        else:
            kom_nr_val = str(kom_nr_entry or "").strip()
        if kom_nr_val:
            kom_nr_trimmed = re.sub(r"/\d+\b", "", kom_nr_val).strip()
            if kom_nr_trimmed != kom_nr_val:
                if not isinstance(kom_nr_entry, dict):
                    kom_nr_entry = {"value": kom_nr_val, "source": "derived", "confidence": 0.0}
                kom_nr_entry["value"] = kom_nr_trimmed
                kom_nr_entry["derived_from"] = "porta_kom_nr_suffix_trim"
                header["kom_nr"] = kom_nr_entry
        kom_entry = header.get("kom_name", {})
        kom_val = ""
        if isinstance(kom_entry, dict):
            kom_val = str(kom_entry.get("value", "") or "").strip()
        else:
            kom_val = str(kom_entry or "").strip()
        if not kom_val:
            kom_from_pdf = _extract_porta_kom_name_from_pdf_texts(
                pdf_text_by_image_name
            )
            if kom_from_pdf:
                header["kom_name"] = {
                    "value": kom_from_pdf,
                    "source": "pdf",
                    "confidence": 0.95,
                    "derived_from": "porta_pdf_kom_name",
                }
                normalized_warnings = normalized.get("warnings")
                if isinstance(normalized_warnings, list):
                    normalized_warnings.append(
                        "Porta: kom_name filled from PDF kommission line."
                    )
            else:
                store_entry = header.get("store_name", {})
                store_val = ""
                store_source = "derived"
                store_conf = 0.0
                if isinstance(store_entry, dict):
                    store_val = str(store_entry.get("value", "") or "").strip()
                    store_source = str(store_entry.get("source", "") or "derived")
                    try:
                        store_conf = float(store_entry.get("confidence", 0.0) or 0.0)
                    except (TypeError, ValueError):
                        store_conf = 0.0
                else:
                    store_val = str(store_entry or "").strip()
                if store_val and re.search(r"\bporta\b", store_val, re.IGNORECASE):
                    header["kom_name"] = {
                        "value": store_val,
                        "source": store_source or "derived",
                        "confidence": store_conf if store_conf > 0.0 else 0.9,
                        "derived_from": "porta_store_name_fallback",
                    }
                    normalized_warnings = normalized.get("warnings")
                    if isinstance(normalized_warnings, list):
                        normalized_warnings.append(
                            "Porta: kom_name filled from store_name fallback."
                        )

    if branch.is_momax_bg:
        wrapped_article_map = momax_bg.extract_momax_bg_wrapped_article_map(message.attachments)
        if wrapped_article_map:
            normalized_items = normalized.get("items")
            normalized_warnings = normalized.get("warnings")
            if isinstance(normalized_items, list):
                for index, item in enumerate(normalized_items, start=1):
                    if not isinstance(item, dict):
                        continue
                    artikel_entry = item.get("artikelnummer")
                    if not isinstance(artikel_entry, dict):
                        artikel_entry = {
                            "value": artikel_entry if artikel_entry is not None else "",
                            "source": "derived",
                            "confidence": 0.0,
                        }
                        item["artikelnummer"] = artikel_entry
                    current_article = str(artikel_entry.get("value", "") or "").strip()
                    corrected_article = wrapped_article_map.get(current_article, "")
                    if not corrected_article or corrected_article == current_article:
                        continue
                    artikel_entry["value"] = corrected_article
                    artikel_entry["source"] = "derived"
                    artikel_entry["confidence"] = 1.0
                    artikel_entry["derived_from"] = "momax_bg_pdf_wrapped_article_correction"
                    if isinstance(normalized_warnings, list):
                        line_no = item.get("line_no", index)
                        normalized_warnings.append(
                            f"MOMAX BG wrapped Code/Type correction: item line {line_no} "
                            f"artikelnummer '{current_article}' -> '{corrected_article}'."
                        )
        apply_momax_bg_strict_item_code_corrections(normalized)

    if branch.enable_item_code_verification and not branch.is_momax_bg:
        items_snapshot = _build_items_snapshot(normalized.get("items"))
        if items_snapshot:
            verification_page_text_by_name = _ordered_verification_page_texts(
                pdf_text_by_image_name
            )
            if not verification_page_text_by_name:
                normalized_warnings = normalized.get("warnings")
                if isinstance(normalized_warnings, list):
                    normalized_warnings.append(
                        f"{branch.label} item verification skipped: no digital PDF text available."
                    )
            else:
                verification_profile = branch.id
                try:
                    verification_text = extractor.verify_items_from_text(
                        items_snapshot=items_snapshot,
                        page_text_by_image_name=verification_page_text_by_name,
                        verification_profile=verification_profile,
                    )
                    verification_data = parse_json_response(verification_text)
                    apply_item_code_verification(
                        normalized,
                        verification_data,
                        verification_profile=verification_profile,
                    )
                except Exception as exc:
                    normalized_warnings = normalized.get("warnings")
                    if isinstance(normalized_warnings, list):
                        normalized_warnings.append(
                            f"{branch.label} item verification failed (non-critical): {exc}"
                        )

    # --- ZB Zubehör modellnummer lookup (all clients) ---
    _zb_warnings = normalized.get("warnings")
    if not isinstance(_zb_warnings, list):
        _zb_warnings = []
        normalized["warnings"] = _zb_warnings
    if zb_lookup.apply_zb_modellnummer_lookup(normalized, _zb_warnings):
        refresh_missing_warnings(normalized)

    if branch.id == "porta":
        _apply_porta_oj_accessory_article_backfill(normalized, pdf_text_by_image_name)
        _apply_porta_quantity_corrections(normalized, pdf_text_by_image_name)
        _trim_porta_component_excess_items(normalized, pdf_text_by_image_name)

    if route.used_fallback:
        header = normalized.get("header")
        if not isinstance(header, dict):
            header = {}
            normalized["header"] = header
        human_review_entry = header.get("human_review_needed")
        already_true = (
            isinstance(human_review_entry, dict)
            and human_review_entry.get("value") is True
        )
        if not already_true:
            header["human_review_needed"] = {
                "value": True,
                "source": "derived",
                "confidence": 1.0,
                "derived_from": "routing_fallback",
            }
        normalized_warnings = normalized.get("warnings")
        if isinstance(normalized_warnings, list):
            normalized_warnings.append("Routing fallback: forced human_review_needed=true")

    # BG special-case (MOMAX/MOEMAX/AIKO): keep kom_nr/date fixes only.
    # Kundennummer must come from address-based Excel logic.
    if branch.is_momax_bg:
        header = normalized.get("header") if isinstance(normalized.get("header"), dict) else {}
        kom_nr_from_pdf = momax_bg.extract_momax_bg_kom_nr(message.attachments)
        kom_entry = header.get("kom_nr", {})
        kom_val = ""
        if isinstance(kom_entry, dict):
            kom_val = str(kom_entry.get("value", "") or "").strip()
        else:
            kom_val = str(kom_entry or "").strip()

        if kom_nr_from_pdf and kom_nr_from_pdf != kom_val:
            header["kom_nr"] = {
                "value": kom_nr_from_pdf,
                "source": "pdf",
                "confidence": 1.0,
            }
            normalized["header"] = header

        # If bestelldatum is missing, derive from BG PDF order suffix "<digits>/<dd.mm.yy>".
        bd_entry = header.get("bestelldatum", {})
        bd_val = ""
        if isinstance(bd_entry, dict):
            bd_val = str(bd_entry.get("value", "") or "").strip()
        else:
            bd_val = str(bd_entry or "").strip()
        if not bd_val:
            order_date_from_pdf = momax_bg.extract_momax_bg_order_date(message.attachments)
            if order_date_from_pdf:
                header["bestelldatum"] = {
                    "value": order_date_from_pdf,
                    "source": "derived",
                    "confidence": 1.0,
                    "derived_from": "pdf_order_suffix",
                }
                normalized["header"] = header

        reply_entry = header.get("reply_needed", {})
        if isinstance(reply_entry, dict) and reply_entry.get("source") == "derived":
            reply_entry["value"] = False

    ticket_number = _extract_ticket_number(message.subject or "")
    header = normalized.get("header")
    if not isinstance(header, dict):
        header = {}
        normalized["header"] = header
    header["ticket_number"] = {
        "value": ticket_number,
        "source": "email" if ticket_number else "derived",
        "confidence": 1.0 if ticket_number else 0.0,
    }

    if (not branch.is_momax_bg) and ai_customer_match.should_try_ai_customer_match(
        normalized.get("header") or {},
        normalized.get("warnings") or [],
    ):
        ai_customer_match.try_ai_customer_match(
            normalized["header"],
            normalized["warnings"],
            extractor,
            config,
        )

    # After kundennummer is final (rules or AI): ensure tour comes from Kunden Excel, then recompute delivery_week
    header = normalized.get("header") or {}
    if isinstance(header, dict):
        def _hv(h: dict, key: str) -> str:
            e = h.get(key)
            if isinstance(e, dict):
                return str(e.get("value", "") or "").strip()
            return str(e or "").strip()

        kdnr = _hv(header, "kundennummer")
        if kdnr:
            excel_match = lookup.find_customer_by_address("", kundennummer=kdnr)
            if excel_match:
                header["tour"] = {
                    "value": excel_match["tour"],
                    "source": "derived",
                    "confidence": 1.0,
                    "derived_from": "excel_lookup_by_kundennummer",
                }
                header["adressnummer"] = {
                    "value": excel_match["adressnummer"],
                    "source": "derived",
                    "confidence": 1.0,
                    "derived_from": "excel_lookup_by_kundennummer",
                }

        bestelldatum_val = _hv(header, "bestelldatum")
        tour_val = _hv(header, "tour")
        wunschtermin_val = _hv(header, "wunschtermin")
        liefertermin_val = _hv(header, "liefertermin")
        requested_kw_str = wunschtermin_val or liefertermin_val  # delivery_logic parses KWxx/yyyy from either
        store_name_val = _hv(header, "store_name")
        if bestelldatum_val and tour_val:
            dw = delivery_logic.calculate_delivery_week(
                bestelldatum_val, tour_val, requested_kw_str,
                client_name=store_name_val or None,
            )
            if dw:
                header["delivery_week"] = {
                    "value": dw,
                    "source": "derived",
                    "confidence": 1.0,
                    "derived_from": "delivery_logic",
                }

        # Tour validity: warn if tour (e.g. from Excel by kundennummer) is not in Lieferlogik
        if tour_val and str(tour_val).strip():
            if not delivery_logic.is_tour_valid(str(tour_val).strip()):
                w = normalized.get("warnings")
                if isinstance(w, list):
                    w.append(f"Tour number '{tour_val}' not found in Lieferlogik; please verify in Primex Kunden Excel.")

    refresh_missing_warnings(normalized)

    # Auto-send reply-needed email (swap/substitution cases)
    try:
        header = normalized.get("header") if isinstance(normalized.get("header"), dict) else {}
        reply_entry = header.get("reply_needed", {})
        reply_needed = isinstance(reply_entry, dict) and reply_entry.get("value") is True
        if reply_needed:
            msg = reply_email.compose_reply_needed_email(
                message=message,
                normalized=normalized,
                to_addr=config.reply_email_to,
                body_template=config.reply_email_body,
            )
            reply_email.send_email_via_smtp(config, msg)
            w = normalized.get("warnings")
            if isinstance(w, list):
                w.append(f"Auto-reply email sent to {config.reply_email_to}.")
            print(f"Auto-reply email sent to {config.reply_email_to} for {message.message_id}.")
    except Exception as exc:
        w = normalized.get("warnings")
        if isinstance(w, list):
            w.append(f"Auto-reply email failed: {exc}")
        print(f"Auto-reply email failed for {message.message_id}: {exc}")

    output_name = _safe_name(message.message_id)

    return ProcessedResult(data=normalized, output_name=output_name)
