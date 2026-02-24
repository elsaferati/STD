from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

import fitz  # PyMuPDF

from config import Config
from email_ingest import Attachment, IngestedEmail
from extraction_branches import BRANCHES, DEFAULT_BRANCH_ID
from openai_extract import OpenAIExtractor, parse_json_response

_PORTA_TOKEN_RE = re.compile(r"\bporta\b", re.IGNORECASE)
_PORTA_DOMAIN_RE = re.compile(r"(?:@|\b)porta\.de\b", re.IGNORECASE)
_PORTA_ORDER_RE = re.compile(r"bestellung\s*/\s*order", re.IGNORECASE)
_BRAUN_TOKEN_RE = re.compile(r"\bbraun\b", re.IGNORECASE)
_BRAUN_MOEBEL_RE = re.compile(r"m(?:oe|o|\u00f6)bel", re.IGNORECASE)
_BRAUN_MOEBELCENTER_RE = re.compile(
    r"m(?:oe|o|\u00f6)bel\s*[- ]?\s*center",
    re.IGNORECASE,
)
_PORTA_KUNDENKOMMISSION_RE = re.compile(
    r"k\s*u\s*n\s*d\s*e\s*n\s*k\s*o\s*m\s*m\s*i\s*s\s*s\s*i\s*o\s*n",
    re.IGNORECASE,
)
_PORTA_SUPPLIER_RE = re.compile(r"lieferantennummer", re.IGNORECASE)
_PORTA_HOUSE_RE = re.compile(r"gln\s*haus|f[uü]r\s*haus", re.IGNORECASE)
_MOMAX_BG_RECIPIENT_RE = re.compile(
    r"recipient\s*:\s*moe?max\s*(?:bulgaria|aiko)\b",
    re.IGNORECASE,
)
_MOMAX_BG_AIKO_RE = re.compile(r"\baiko\b", re.IGNORECASE)
_XXXLUTZ_DEFAULT_MAIL_HINT_RE = re.compile(
    r"mail\s*:\s*office-lutz@lutz\.at\b",
    re.IGNORECASE,
)


@dataclass
class RouteDecision:
    selected_branch_id: str
    classifier_branch_id: str
    confidence: float
    reason: str
    forced_by_detector: bool
    used_fallback: bool


def _is_pdf_attachment(attachment: Attachment) -> bool:
    content_type = (attachment.content_type or "").lower()
    if content_type.startswith("application/pdf") or content_type == "application/x-pdf":
        return True
    return bool(attachment.filename and attachment.filename.lower().endswith(".pdf"))


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _pdf_first_page_text(pdf_bytes: bytes) -> str:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        if doc.page_count <= 0:
            return ""
        page = doc.load_page(0)
        return page.get_text() or ""
    finally:
        doc.close()


def _pdf_any_page_matches(pdf_bytes: bytes, pattern: re.Pattern[str]) -> bool:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        if doc.page_count <= 0:
            return False
        for page_index in range(doc.page_count):
            page = doc.load_page(page_index)
            page_text = _normalize_whitespace(page.get_text() or "")
            if pattern.search(page_text):
                return True
        return False
    finally:
        doc.close()


def _truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars]


def _evaluate_hard_detectors(attachments: list[Attachment]) -> dict[str, bool]:
    results: dict[str, bool] = {}
    for branch_id, branch in BRANCHES.items():
        detector = branch.hard_detector
        if detector is None:
            continue
        try:
            results[branch_id] = bool(detector(attachments))
        except Exception:
            results[branch_id] = False
    return results


def _forced_branch_id(detector_results: dict[str, bool]) -> str | None:
    for branch_id in BRANCHES.keys():
        if detector_results.get(branch_id):
            return branch_id
    return None


def _has_porta_hint(text: str) -> bool:
    normalized = _normalize_whitespace(text or "")
    if not normalized:
        return False

    if _PORTA_TOKEN_RE.search(normalized) or _PORTA_DOMAIN_RE.search(normalized):
        return True

    return _has_porta_layout_markers(normalized)


def _has_braun_hint(text: str) -> bool:
    normalized = _normalize_whitespace(text or "")
    if not normalized:
        return False
    has_braun = bool(_BRAUN_TOKEN_RE.search(normalized))
    has_moebel_context = bool(
        _BRAUN_MOEBEL_RE.search(normalized) or _BRAUN_MOEBELCENTER_RE.search(normalized)
    )
    return has_braun and has_moebel_context


def _has_porta_layout_markers(text: str) -> bool:
    normalized = _normalize_whitespace(text or "")
    if not normalized:
        return False
    has_order_header = bool(_PORTA_ORDER_RE.search(normalized))
    has_commission_header = bool(_PORTA_KUNDENKOMMISSION_RE.search(normalized))
    has_supplier_or_house = bool(
        _PORTA_SUPPLIER_RE.search(normalized) or _PORTA_HOUSE_RE.search(normalized)
    )
    return has_order_header and has_commission_header and has_supplier_or_house


def _has_momax_bg_recipient_hint(text: str) -> bool:
    normalized = _normalize_whitespace(text or "")
    if not normalized:
        return False
    return bool(_MOMAX_BG_RECIPIENT_RE.search(normalized))


def _has_xxxlutz_default_mail_hint_in_body(text: str) -> bool:
    normalized = _normalize_whitespace(text or "")
    if not normalized:
        return False
    return bool(_XXXLUTZ_DEFAULT_MAIL_HINT_RE.search(normalized))


def _is_momax_bg_hard_match(message: IngestedEmail) -> bool:
    sender_subject_text = _normalize_whitespace(
        "\n".join([message.sender or "", message.subject or ""])
    )
    if _MOMAX_BG_AIKO_RE.search(sender_subject_text):
        return True

    email_hint_text = _normalize_whitespace(
        "\n".join([message.sender or "", message.subject or "", message.body_text or ""])
    )
    if _has_momax_bg_recipient_hint(email_hint_text):
        return True

    for attachment in message.attachments:
        if not _is_pdf_attachment(attachment):
            continue
        try:
            if _pdf_any_page_matches(attachment.data, _MOMAX_BG_RECIPIENT_RE):
                return True
        except Exception:
            continue
    return False


def _is_porta_hard_match(message: IngestedEmail, config: Config) -> bool:
    sender_text = _normalize_whitespace(message.sender or "")
    sender_domain_match = bool(_PORTA_DOMAIN_RE.search(sender_text))
    pdf_attachments = [a for a in message.attachments if _is_pdf_attachment(a)]
    if not pdf_attachments:
        return False
    if sender_domain_match:
        return True

    for attachment in pdf_attachments:
        try:
            preview_text = _pdf_first_page_text(attachment.data)
        except Exception:
            continue
        preview_text = _truncate(
            _normalize_whitespace(preview_text),
            config.router_max_pdf_preview_chars,
        )
        if _has_porta_layout_markers(preview_text):
            return True
    return False


def _is_braun_hard_match(message: IngestedEmail, config: Config) -> bool:
    pdf_attachments = [a for a in message.attachments if _is_pdf_attachment(a)]
    if not pdf_attachments:
        return False

    email_preview = _normalize_whitespace(
        "\n".join(
            [
                message.sender or "",
                message.subject or "",
                _truncate(message.body_text or "", config.router_max_body_chars),
            ]
        )
    )
    if _has_braun_hint(email_preview):
        return True

    for attachment in pdf_attachments:
        try:
            preview_text = _pdf_first_page_text(attachment.data)
        except Exception:
            continue
        preview_text = _truncate(
            _normalize_whitespace(preview_text),
            config.router_max_pdf_preview_chars,
        )
        if _has_braun_hint(preview_text):
            return True
    return False


def _build_router_system_prompt() -> str:
    branch_lines = [
        f"- {branch.id}: {branch.description}" for branch in BRANCHES.values()
    ]
    branch_text = "\n".join(branch_lines)
    return (
        "You are a routing classifier for email extraction branches. "
        "Choose exactly one branch_id from the allowed list.\n\n"
        "Allowed branch IDs:\n"
        f"{branch_text}\n"
        "- unknown: use this when no branch is a reliable match.\n\n"
        "Return strict JSON only with this schema:\n"
        '{"branch_id":"<allowed id or unknown>","confidence":0.0,"reason":"short reason"}\n\n'
        "Rules:\n"
        "1. branch_id must be one of the listed IDs or unknown.\n"
        "2. confidence must be a float from 0.0 to 1.0.\n"
        "3. If momax_bg_detector is true in the input, return branch_id=\"momax_bg\" and confidence=1.0.\n"
        "4. If porta_hint is true, prefer branch_id=\"porta\" with high confidence unless a forced detector applies.\n"
        "5. If braun_hint is true, prefer branch_id=\"braun\" with high confidence unless a forced detector applies.\n"
        "6. If uncertain, return branch_id=\"unknown\" with low confidence."
    )


def _build_router_user_text(
    message: IngestedEmail,
    config: Config,
    detector_results: dict[str, bool],
) -> str:
    body_preview = _truncate(message.body_text or "", config.router_max_body_chars)
    joined_email_text = "\n".join([message.sender or "", message.subject or "", body_preview])
    attachment_info: list[dict[str, Any]] = []
    pdf_previews: list[dict[str, str]] = []

    for attachment in message.attachments:
        attachment_info.append(
            {
                "filename": attachment.filename,
                "content_type": attachment.content_type,
                "size_bytes": len(attachment.data) if attachment.data is not None else 0,
            }
        )
        if _is_pdf_attachment(attachment):
            try:
                preview_text = _pdf_first_page_text(attachment.data)
            except Exception as exc:
                preview_text = f"[pdf preview unavailable: {exc}]"
            preview_text = _truncate(
                _normalize_whitespace(preview_text),
                config.router_max_pdf_preview_chars,
            )
            pdf_previews.append(
                {
                    "filename": attachment.filename,
                    "first_page_text": preview_text,
                }
            )

    payload = {
        "message_id": message.message_id,
        "received_at": message.received_at,
        "subject": message.subject,
        "sender": message.sender,
        "email_body_preview": body_preview,
        "attachments": attachment_info,
        "pdf_first_page_previews": pdf_previews,
        "porta_hint": bool(
            _has_porta_hint(joined_email_text)
            or any(
                _has_porta_hint(preview.get("first_page_text", ""))
                for preview in pdf_previews
            )
        ),
        "braun_hint": bool(
            _has_braun_hint(joined_email_text)
            or any(
                _has_braun_hint(preview.get("first_page_text", ""))
                for preview in pdf_previews
            )
        ),
        "momax_bg_detector": bool(detector_results.get("momax_bg", False)),
        "hard_detectors": detector_results,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _parse_classifier_response(response_text: str) -> tuple[str, float, str]:
    parsed = parse_json_response(response_text)
    branch_id_raw = parsed.get("branch_id")
    confidence_raw = parsed.get("confidence")
    reason_raw = parsed.get("reason")

    if not isinstance(branch_id_raw, str):
        raise ValueError("Router response missing string branch_id")
    branch_id = branch_id_raw.strip()

    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        raise ValueError("Router response confidence is not a float")

    if confidence < 0.0 or confidence > 1.0:
        raise ValueError("Router response confidence out of range")

    reason = str(reason_raw or "").strip() or "no_reason"

    if branch_id != "unknown" and branch_id not in BRANCHES:
        return "unknown", confidence, f"unknown_branch:{branch_id}"

    return branch_id, confidence, reason


def route_message(
    message: IngestedEmail,
    config: Config,
    extractor: OpenAIExtractor,
) -> RouteDecision:
    if _has_xxxlutz_default_mail_hint_in_body(message.body_text or ""):
        return RouteDecision(
            selected_branch_id=DEFAULT_BRANCH_ID,
            classifier_branch_id=DEFAULT_BRANCH_ID,
            confidence=1.0,
            reason="xxxlutz_default_mail_hint",
            forced_by_detector=True,
            used_fallback=False,
        )

    detector_results = _evaluate_hard_detectors(message.attachments)
    if not detector_results.get("momax_bg") and _is_momax_bg_hard_match(message):
        detector_results["momax_bg"] = True
    forced_branch_id = _forced_branch_id(detector_results)
    if not forced_branch_id and _is_braun_hard_match(message, config):
        forced_branch_id = "braun"
        detector_results["braun"] = True
    if not forced_branch_id and _is_porta_hard_match(message, config):
        forced_branch_id = "porta"
        detector_results["porta"] = True

    if not config.router_enabled:
        return RouteDecision(
            selected_branch_id=forced_branch_id or DEFAULT_BRANCH_ID,
            classifier_branch_id="unknown",
            confidence=1.0 if forced_branch_id else 0.0,
            reason="router_disabled",
            forced_by_detector=bool(forced_branch_id),
            used_fallback=True,
        )

    classifier_branch_id = "unknown"
    confidence = 0.0
    reason = "classifier_error"

    try:
        router_system_prompt = _build_router_system_prompt()
        routing_user_text = _build_router_user_text(message, config, detector_results)
        response_text = extractor.complete_text(router_system_prompt, routing_user_text)
        classifier_branch_id, confidence, reason = _parse_classifier_response(response_text)
    except Exception as exc:
        reason = f"classifier_error: {exc}"

    if forced_branch_id:
        return RouteDecision(
            selected_branch_id=forced_branch_id,
            classifier_branch_id=classifier_branch_id,
            confidence=confidence,
            reason=reason,
            forced_by_detector=True,
            used_fallback=False,
        )

    if classifier_branch_id in BRANCHES and confidence >= config.router_min_confidence:
        return RouteDecision(
            selected_branch_id=classifier_branch_id,
            classifier_branch_id=classifier_branch_id,
            confidence=confidence,
            reason=reason,
            forced_by_detector=False,
            used_fallback=False,
        )

    fallback_reason = reason
    if classifier_branch_id == "unknown":
        fallback_reason = "unknown"
    elif classifier_branch_id in BRANCHES and confidence < config.router_min_confidence:
        fallback_reason = "low confidence"

    return RouteDecision(
        selected_branch_id=DEFAULT_BRANCH_ID,
        classifier_branch_id=classifier_branch_id,
        confidence=confidence,
        reason=fallback_reason,
        forced_by_detector=False,
        used_fallback=True,
    )


def format_routing_warning(route: RouteDecision) -> str:
    forced = "true" if route.forced_by_detector else "false"
    fallback = "true" if route.used_fallback else "false"
    base = (
        f"Routing: selected={route.selected_branch_id} confidence={route.confidence:.2f} "
        f"forced={forced} fallback={fallback}"
    )
    if route.used_fallback and route.reason:
        return f"{base} ({route.reason})"
    return base
