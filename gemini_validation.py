from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import traceback
from typing import Any

from config import Config
from email_ingest import Attachment, IngestedEmail
from xml_exporter import XmlDocument

try:
    from google import genai
    from google.genai import types
except Exception:  # noqa: BLE001
    genai = None
    types = None


VALIDATION_STATUS_NOT_RUN = "not_run"
VALIDATION_STATUS_PASSED = "passed"
VALIDATION_STATUS_FLAGGED = "flagged"
VALIDATION_STATUS_STALE = "stale"
VALIDATION_STATUS_SKIPPED = "skipped"
VALIDATION_STATUS_ERROR = "error"
VALIDATION_STATUS_RESOLVED = "resolved"
VALIDATION_PROVIDER_GEMINI = "gemini"
VALIDATION_REVIEW_STATUSES = frozenset({VALIDATION_STATUS_FLAGGED, VALIDATION_STATUS_STALE})
VALIDATION_ACTIVE_STATUSES = frozenset(
    {
        VALIDATION_STATUS_PASSED,
        VALIDATION_STATUS_FLAGGED,
        VALIDATION_STATUS_STALE,
        VALIDATION_STATUS_SKIPPED,
        VALIDATION_STATUS_ERROR,
        VALIDATION_STATUS_RESOLVED,
    }
)
VALID_VALIDATION_STATUSES = frozenset(
    {
        VALIDATION_STATUS_NOT_RUN,
        VALIDATION_STATUS_PASSED,
        VALIDATION_STATUS_FLAGGED,
        VALIDATION_STATUS_STALE,
        VALIDATION_STATUS_SKIPPED,
        VALIDATION_STATUS_ERROR,
        VALIDATION_STATUS_RESOLVED,
    }
)

_VALIDATION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "validation_status": {
            "type": "string",
            "enum": [
                VALIDATION_STATUS_PASSED,
                VALIDATION_STATUS_FLAGGED,
                VALIDATION_STATUS_SKIPPED,
                VALIDATION_STATUS_ERROR,
            ],
        },
        "summary": {"type": "string"},
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "enum": ["info", "warning", "error"]},
                    "scope": {"type": "string"},
                    "field_path": {"type": "string"},
                    "source_evidence": {"type": "string"},
                    "expected_value": {"type": "string"},
                    "xml_value": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": [
                    "severity",
                    "scope",
                    "field_path",
                    "source_evidence",
                    "expected_value",
                    "xml_value",
                    "reason",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["validation_status", "summary", "issues"],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = (
    "You validate generated order XML against explicit source evidence. "
    "Compare only what is directly supported by the email body, attached PDFs, and supplied XML. "
    "Never infer missing values, never guess, and never mark a mismatch unless the evidence is explicit. "
    "If there is not enough evidence, return validation_status='skipped'. "
    "If you find any likely mismatch between source evidence and the XML payload, return validation_status='flagged'. "
    "If everything material in the XML matches the evidence, return validation_status='passed'. "
    "Return strict JSON matching the provided schema."
)


def normalize_validation_status(value: Any) -> str:
    status = str(value or VALIDATION_STATUS_NOT_RUN).strip().lower()
    if status not in VALID_VALIDATION_STATUSES:
        return VALIDATION_STATUS_NOT_RUN
    return status


def normalize_validation_result(
    payload: dict[str, Any] | None,
    *,
    provider: str,
    model: str,
    checked_at: str | None = None,
) -> dict[str, Any]:
    result = payload if isinstance(payload, dict) else {}
    issues_raw = result.get("issues")
    issues = issues_raw if isinstance(issues_raw, list) else []
    checked_text = str(checked_at or datetime.now(timezone.utc).isoformat())
    normalized_issues: list[dict[str, str]] = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        normalized_issues.append(
            {
                "severity": str(issue.get("severity") or "warning").strip().lower() or "warning",
                "scope": str(issue.get("scope") or "general").strip() or "general",
                "field_path": str(issue.get("field_path") or "").strip(),
                "source_evidence": str(issue.get("source_evidence") or "").strip(),
                "expected_value": str(issue.get("expected_value") or "").strip(),
                "xml_value": str(issue.get("xml_value") or "").strip(),
                "reason": str(issue.get("reason") or "").strip(),
            }
        )
    status = normalize_validation_status(result.get("validation_status"))
    if status == VALIDATION_STATUS_NOT_RUN:
        status = VALIDATION_STATUS_ERROR if result else VALIDATION_STATUS_NOT_RUN
    summary = str(result.get("summary") or "").strip()
    if not summary:
        if status == VALIDATION_STATUS_PASSED:
            summary = "Gemini validation passed."
        elif status == VALIDATION_STATUS_SKIPPED:
            summary = "Gemini validation skipped due to insufficient source evidence."
        elif status == VALIDATION_STATUS_FLAGGED:
            summary = "Gemini validation found likely mismatches."
        elif status == VALIDATION_STATUS_ERROR:
            summary = "Gemini validation failed."
    return {
        "validation_status": status,
        "validation_summary": summary,
        "validation_issues": normalized_issues,
        "validation_provider": provider,
        "validation_model": model,
        "validation_checked_at": checked_text,
        "validation_stale_reason": str(result.get("stale_reason") or "").strip(),
        "validation_raw_result": result,
    }


def build_stale_validation_result(existing_status: Any, *, reason: str) -> dict[str, Any] | None:
    current = normalize_validation_status(existing_status)
    if current not in {
        VALIDATION_STATUS_PASSED,
        VALIDATION_STATUS_FLAGGED,
        VALIDATION_STATUS_RESOLVED,
        VALIDATION_STATUS_SKIPPED,
    }:
        return None
    return {
        "validation_status": VALIDATION_STATUS_STALE,
        "validation_summary": "Gemini validation is stale after a manual change.",
        "validation_issues": [],
        "validation_provider": VALIDATION_PROVIDER_GEMINI,
        "validation_model": "",
        "validation_checked_at": datetime.now(timezone.utc).isoformat(),
        "validation_stale_reason": str(reason or "").strip() or "manual_change",
        "validation_raw_result": {},
    }


def build_validation_error_result(summary: str, *, model: str) -> dict[str, Any]:
    return normalize_validation_result(
        {
            "validation_status": VALIDATION_STATUS_ERROR,
            "summary": str(summary or "").strip() or "Gemini validation failed.",
            "issues": [],
        },
        provider=VALIDATION_PROVIDER_GEMINI,
        model=model,
    )


def _compact_order_snapshot(normalized: dict[str, Any]) -> dict[str, Any]:
    header = normalized.get("header")
    items = normalized.get("items")
    compact_header: dict[str, Any] = {}
    if isinstance(header, dict):
        for key, entry in header.items():
            if isinstance(entry, dict):
                compact_header[key] = entry.get("value", "")
            else:
                compact_header[key] = entry
    compact_items: list[dict[str, Any]] = []
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            compact_items.append(
                {
                    "line_no": item.get("line_no"),
                    "artikelnummer": _entry_plain(item.get("artikelnummer")),
                    "modellnummer": _entry_plain(item.get("modellnummer")),
                    "menge": _entry_plain(item.get("menge")),
                    "furncloud_id": _entry_plain(item.get("furncloud_id")),
                }
            )
    return {"header": compact_header, "items": compact_items}


def _entry_plain(entry: Any) -> Any:
    if isinstance(entry, dict):
        return entry.get("value", "")
    return entry


def _pdf_attachments(attachments: list[Attachment], max_attachments: int) -> list[Attachment]:
    pdfs: list[Attachment] = []
    for attachment in attachments:
        content_type = str(attachment.content_type or "").lower()
        filename = str(attachment.filename or "").lower()
        if content_type.startswith("application/pdf") or filename.endswith(".pdf"):
            pdfs.append(attachment)
    return pdfs[: max(0, max_attachments)]


def _attachment_mime_type(attachment: Attachment) -> str:
    content_type = str(attachment.content_type or "").strip().lower()
    filename = str(attachment.filename or "").strip().lower()
    if content_type.startswith("application/pdf") or filename.endswith(".pdf"):
        return "application/pdf"
    return content_type or "application/octet-stream"


@dataclass
class GeminiValidator:
    api_key: str
    model: str
    timeout_seconds: int = 30
    max_email_chars: int = 12000
    max_attachments: int = 4

    def __post_init__(self) -> None:
        if not self.api_key:
            raise ValueError("Gemini validator requires an API key.")
        if genai is None or types is None:
            raise RuntimeError("google-genai is not installed.")
        client_kwargs: dict[str, Any] = {"api_key": self.api_key}
        http_options = self._build_http_options(self.timeout_seconds)
        if http_options is not None:
            client_kwargs["http_options"] = http_options
        self.client = genai.Client(**client_kwargs)

    @classmethod
    def from_config(cls, config: Config) -> GeminiValidator | None:
        if not config.gemini_validation_enabled:
            return None
        if not config.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is required when GEMINI_VALIDATION_ENABLED=true.")
        return cls(
            api_key=config.gemini_api_key,
            model=config.gemini_model,
            timeout_seconds=config.gemini_validation_timeout_seconds,
            max_email_chars=config.gemini_validation_max_email_chars,
            max_attachments=config.gemini_validation_max_attachments,
        )

    def validate_order(
        self,
        *,
        message: IngestedEmail,
        branch_id: str,
        normalized: dict[str, Any],
        xml_documents: list[XmlDocument],
    ) -> dict[str, Any]:
        pdfs = _pdf_attachments(message.attachments or [], self.max_attachments)
        body_text = str(message.body_text or "")
        if self.max_email_chars > 0 and len(body_text) > self.max_email_chars:
            body_text = body_text[: self.max_email_chars]

        if not pdfs and len(body_text.strip()) < 20:
            return normalize_validation_result(
                {
                    "validation_status": VALIDATION_STATUS_SKIPPED,
                    "summary": "Gemini validation skipped because there is not enough email or PDF evidence.",
                    "issues": [],
                },
                provider=VALIDATION_PROVIDER_GEMINI,
                model=self.model,
            )

        prompt_payload = {
            "branch_id": branch_id,
            "message_id": message.message_id,
            "received_at": message.received_at,
            "subject": message.subject,
            "sender": message.sender,
            "email_text": body_text,
            "normalized_order": _compact_order_snapshot(normalized),
            "xml_documents": [
                {"name": document.name, "filename": document.filename, "content": document.content}
                for document in xml_documents
            ],
            "validation_task": (
                "Compare the source evidence against the XML documents. "
                "Check ticket/order identifiers, customer/store data, delivery dates or delivery week, "
                "line items, quantities, and obvious article/model mismatches. "
                "Only flag mismatches when the source evidence is explicit."
            ),
        }
        contents: list[Any] = [
            types.Part.from_text(text=_SYSTEM_PROMPT),
            types.Part.from_text(text=json.dumps(prompt_payload, ensure_ascii=False, indent=2)),
        ]
        for attachment in pdfs:
            mime_type = _attachment_mime_type(attachment)
            contents.append(
                types.Part.from_text(
                    text=(
                        f"Attached source PDF: {attachment.filename or 'attachment.pdf'} "
                        f"(mime={mime_type})"
                    )
                )
            )
            contents.append(
                types.Part.from_bytes(
                    data=attachment.data,
                    mime_type=mime_type,
                )
            )

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=contents,
                config={
                    "response_mime_type": "application/json",
                    "response_json_schema": _VALIDATION_JSON_SCHEMA,
                    "temperature": 0,
                },
            )
            text = getattr(response, "text", "") or ""
            parsed = json.loads(text) if text else {}
            return normalize_validation_result(
                parsed,
                provider=VALIDATION_PROVIDER_GEMINI,
                model=self.model,
            )
        except Exception as exc:  # noqa: BLE001
            print(
                "[gemini_validation] Gemini validation failed "
                f"for message_id={message.message_id!r} model={self.model}: {exc}"
            )
            traceback.print_exc()
            return normalize_validation_result(
                {
                    "validation_status": VALIDATION_STATUS_ERROR,
                    "summary": f"Gemini validation failed: {exc}",
                    "issues": [],
                },
                provider=VALIDATION_PROVIDER_GEMINI,
                model=self.model,
            )

    def _build_http_options(self, timeout_seconds: int) -> Any:
        if types is None or timeout_seconds <= 0:
            return None
        timeout_ms = int(timeout_seconds) * 1000
        http_options_cls = getattr(types, "HttpOptions", None)
        if http_options_cls is None:
            return None
        for kwargs in ({"timeout": timeout_ms}, {"timeout_ms": timeout_ms}):
            try:
                return http_options_cls(**kwargs)
            except TypeError:
                continue
        return None
