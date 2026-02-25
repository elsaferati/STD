from __future__ import annotations

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

SUPPORTED_IMAGE_MIME = {"image/png", "image/jpeg", "image/jpg", "image/webp"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}
_TICKET_SUBJECT_RE = re.compile(r"ticket\s*number\b[^0-9]*(\d+)", re.IGNORECASE)


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
