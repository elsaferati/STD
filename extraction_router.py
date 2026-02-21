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
        "4. If uncertain, return branch_id=\"unknown\" with low confidence."
    )


def _build_router_user_text(
    message: IngestedEmail,
    config: Config,
    detector_results: dict[str, bool],
) -> str:
    body_preview = _truncate(message.body_text or "", config.router_max_body_chars)
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
    detector_results = _evaluate_hard_detectors(message.attachments)
    forced_branch_id = _forced_branch_id(detector_results)

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
