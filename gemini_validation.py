from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
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
    "Compare only what is directly supported by the email body, attached PDFs, supplied XML, "
    "and any supplied business_logic_context. "
    "Never infer missing values, never guess, and never mark a mismatch unless the evidence is explicit. "
    "Treat business_logic_context as authoritative system evidence from the same internal pipeline that generated the order. "
    "When a field is marked as derived or a rule note is supplied there, validate the XML against the final resolved value "
    "in business_logic_context instead of raw earlier values from the email or PDF. "
    "In particular, delivery week and customer number may intentionally differ from raw email text because they are resolved "
    "by internal delivery and customer lookup rules. Do not flag those as mismatches when the XML matches business_logic_context. "
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


def _entry_text(entry: Any) -> str:
    value = _entry_plain(entry)
    return "" if value is None else str(value).strip()


def _entry_source(entry: Any) -> str:
    if isinstance(entry, dict):
        return str(entry.get("source") or "").strip()
    return ""


def _entry_derived_from(entry: Any) -> str:
    if isinstance(entry, dict):
        return str(entry.get("derived_from") or "").strip()
    return ""


def _xml_delivery_week_value(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = re.match(r"(\d{4})\s*Week\s*-\s*(\d{1,2})\b", text, re.IGNORECASE)
    if match:
        year, week = int(match.group(1)), int(match.group(2))
        if 1 <= week <= 53:
            return f"{year}{week:02d}WO"
    match = re.search(r"(?:KW|Woche)\s*(\d{1,2})\s*[/.-]?\s*(\d{4})", text, re.IGNORECASE)
    if match:
        week, year = int(match.group(1)), int(match.group(2))
        if 1 <= week <= 53:
            return f"{year}{week:02d}WO"
    return ""


def _kundennummer_rule_note(derived_from: str) -> str:
    normalized = str(derived_from or "").strip().lower()
    if normalized == "excel_lookup":
        return "Customer number was resolved from the Primex customer Excel by address matching."
    if normalized == "excel_lookup_by_kundennummer":
        return "Raw KDNR from the source was verified against the Primex customer Excel and then expanded to final customer, address, and tour values."
    if normalized == "excel_lookup_momax_bg_address":
        return "Customer number was resolved from the MOMAX BG customer Excel by store address matching."
    if normalized == "segmuller_kom_nr_prefix":
        return "Customer number was derived from the Segmuller kom_nr prefix and then verified against the Primex customer Excel."
    if normalized == "iln_fallback":
        return "Address matching failed, so customer number was derived from ILN fallback and then used to fill related fields."
    return "Customer number was resolved by internal customer lookup logic. Validate XML against the final resolved value."


def _delivery_week_rule_note(derived_from: str) -> str:
    normalized = str(derived_from or "").strip().lower()
    if normalized == "delivery_logic":
        return "Delivery week was computed by internal delivery_logic using order date, tour schedule, and requested delivery window."
    return "Delivery week was resolved by internal business logic. Validate XML against the final resolved value."


def _build_business_logic_context(branch_id: str, normalized: dict[str, Any]) -> dict[str, Any]:
    header = normalized.get("header")
    warnings = normalized.get("warnings")
    if not isinstance(header, dict):
        header = {}

    context: dict[str, Any] = {
        "branch_id": str(branch_id or "").strip(),
        "authoritative_xml_rules": [],
        "resolved_fields": {},
        "warnings": [str(item) for item in warnings[:10]] if isinstance(warnings, list) else [],
    }

    kundennummer_entry = header.get("kundennummer")
    kundennummer_value = _entry_text(kundennummer_entry)
    kundennummer_source = _entry_source(kundennummer_entry)
    kundennummer_derived_from = _entry_derived_from(kundennummer_entry)
    if kundennummer_value:
        context["resolved_fields"]["kundennummer"] = {
            "value": kundennummer_value,
            "source": kundennummer_source,
            "derived_from": kundennummer_derived_from,
            "related_fields": {
                "adressnummer": _entry_text(header.get("adressnummer")),
                "tour": _entry_text(header.get("tour")),
                "store_name": _entry_text(header.get("store_name")),
                "store_address": _entry_text(header.get("store_address")),
                "lieferanschrift": _entry_text(header.get("lieferanschrift")),
                "iln": _entry_text(header.get("iln")),
            },
            "rule_note": _kundennummer_rule_note(kundennummer_derived_from),
        }
        if kundennummer_source.lower() == "derived" or kundennummer_derived_from:
            context["authoritative_xml_rules"].append(
                {
                    "xml_field": "OrderInformations.DealerNumberAtManufacturer",
                    "resolved_from": "normalized.header.kundennummer",
                    "expected_value": kundennummer_value,
                    "rule_note": _kundennummer_rule_note(kundennummer_derived_from),
                }
            )

    delivery_week_entry = header.get("delivery_week")
    delivery_week_value = _entry_text(delivery_week_entry)
    delivery_week_source = _entry_source(delivery_week_entry)
    delivery_week_derived_from = _entry_derived_from(delivery_week_entry)
    if delivery_week_value:
        delivery_week_xml = _xml_delivery_week_value(delivery_week_value)
        requested_week_input = _entry_text(header.get("wunschtermin")) or _entry_text(header.get("liefertermin"))
        context["resolved_fields"]["delivery_week"] = {
            "value": delivery_week_value,
            "xml_value": delivery_week_xml,
            "source": delivery_week_source,
            "derived_from": delivery_week_derived_from,
            "inputs": {
                "bestelldatum": _entry_text(header.get("bestelldatum")),
                "tour": _entry_text(header.get("tour")),
                "requested_week_input": requested_week_input,
                "store_name": _entry_text(header.get("store_name")),
            },
            "rule_note": _delivery_week_rule_note(delivery_week_derived_from),
        }
        if delivery_week_source.lower() == "derived" or delivery_week_derived_from:
            context["authoritative_xml_rules"].append(
                {
                    "xml_field": "OrderInformations.DateOfDelivery",
                    "resolved_from": "normalized.header.delivery_week",
                    "expected_value": delivery_week_xml or delivery_week_value,
                    "rule_note": _delivery_week_rule_note(delivery_week_derived_from),
                }
            )

    return context


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
            "business_logic_context": _build_business_logic_context(branch_id, normalized),
            "xml_documents": [
                {"name": document.name, "filename": document.filename, "content": document.content}
                for document in xml_documents
            ],
            "validation_task": (
                "Compare the source evidence against the XML documents. "
                "Check ticket/order identifiers, customer/store data, delivery dates or delivery week, "
                "line items, quantities, and obvious article/model mismatches. "
                "When business_logic_context supplies an authoritative resolved field for the XML, use that final resolved value. "
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
