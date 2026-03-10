from __future__ import annotations

import sys
import tempfile
import types
from pathlib import Path

from config import Config
from email_ingest import Attachment, IngestedEmail
from gemini_validation import (
    GeminiValidator,
    VALIDATION_PROVIDER_GEMINI,
    VALIDATION_STATUS_FLAGGED,
    VALIDATION_STATUS_PASSED,
    VALIDATION_STATUS_SKIPPED,
    VALIDATION_STATUS_STALE,
    _pdf_attachments,
    build_stale_validation_result,
    normalize_validation_result,
)
import xml_exporter

try:
    import order_store
except ModuleNotFoundError as exc:
    if exc.name != "psycopg":
        raise
    psycopg_stub = types.ModuleType("psycopg")
    rows_stub = types.ModuleType("psycopg.rows")

    class _PsycopgError(Exception):
        pass

    psycopg_stub.InterfaceError = _PsycopgError
    psycopg_stub.OperationalError = _PsycopgError
    psycopg_stub.Connection = object
    psycopg_stub.connect = lambda *args, **kwargs: (_ for _ in ()).throw(  # type: ignore[assignment]
        RuntimeError("Database access is not available in this verification script.")
    )
    rows_stub.dict_row = object()
    psycopg_stub.rows = rows_stub
    sys.modules["psycopg"] = psycopg_stub
    sys.modules["psycopg.rows"] = rows_stub
    import order_store


def _sample_payload() -> dict:
    return {
        "extraction_branch": "xxxlutz_default",
        "header": {
            "ticket_number": {"value": "88801711", "source": "pdf", "confidence": 1.0},
            "kundennummer": {"value": "123456", "source": "pdf", "confidence": 1.0},
            "kom_nr": {"value": "20-634616-12", "source": "pdf", "confidence": 1.0},
            "kom_name": {"value": "Muster Kunde", "source": "pdf", "confidence": 1.0},
            "delivery_week": {"value": "2026 Week - 05", "source": "email", "confidence": 1.0},
            "store_name": {"value": "Store 1", "source": "email", "confidence": 1.0},
            "store_address": {"value": "Store Street 1 12345 Berlin Germany", "source": "email", "confidence": 1.0},
            "lieferanschrift": {"value": "Delivery Street 2 54321 Bonn Germany", "source": "email", "confidence": 1.0},
            "seller": {"value": "Seller A", "source": "email", "confidence": 1.0},
        },
        "items": [
            {
                "line_no": {"value": 1, "source": "pdf", "confidence": 1.0},
                "artikelnummer": {"value": "ART-1", "source": "pdf", "confidence": 1.0},
                "modellnummer": {"value": "MOD-1", "source": "pdf", "confidence": 1.0},
                "menge": {"value": "2", "source": "pdf", "confidence": 1.0},
                "furncloud_id": {"value": "FC-1", "source": "pdf", "confidence": 1.0},
            }
        ],
        "warnings": [],
        "errors": [],
    }


def test_normalize_validation_result_defaults() -> None:
    normalized = normalize_validation_result(
        {
            "validation_status": "flagged",
            "summary": "",
            "issues": [
                {
                    "severity": "ERROR",
                    "scope": "header",
                    "field_path": "header.kom_nr",
                    "source_evidence": "20-634616-12",
                    "expected_value": "20-634616-12",
                    "xml_value": "20-634616-13",
                    "reason": "KOM mismatch",
                }
            ],
        },
        provider=VALIDATION_PROVIDER_GEMINI,
        model="gemini-2.5-flash",
        checked_at="2026-03-10T10:00:00+00:00",
    )

    assert normalized["validation_status"] == VALIDATION_STATUS_FLAGGED
    assert normalized["validation_summary"] == "Gemini validation found likely mismatches."
    assert normalized["validation_provider"] == VALIDATION_PROVIDER_GEMINI
    assert normalized["validation_model"] == "gemini-2.5-flash"
    assert normalized["validation_checked_at"] == "2026-03-10T10:00:00+00:00"
    assert normalized["validation_issues"] == [
        {
            "severity": "error",
            "scope": "header",
            "field_path": "header.kom_nr",
            "source_evidence": "20-634616-12",
            "expected_value": "20-634616-12",
            "xml_value": "20-634616-13",
            "reason": "KOM mismatch",
        }
    ]
    print("SUCCESS: normalize_validation_result normalizes flagged output and issue fields.")


def test_build_stale_validation_result() -> None:
    stale = build_stale_validation_result(VALIDATION_STATUS_PASSED, reason="manual_xml_export")
    assert stale is not None
    assert stale["validation_status"] == VALIDATION_STATUS_STALE
    assert stale["validation_stale_reason"] == "manual_xml_export"
    assert build_stale_validation_result("not_run", reason="manual_save") is None
    print("SUCCESS: stale validation state is created only for prior active Gemini results.")


def test_pdf_attachment_filtering() -> None:
    attachments = [
        Attachment(filename="order.pdf", content_type="application/pdf", data=b"pdf-1"),
        Attachment(filename="image.png", content_type="image/png", data=b"img"),
        Attachment(filename="spec.PDF", content_type="application/octet-stream", data=b"pdf-2"),
    ]
    filtered = _pdf_attachments(attachments, 1)
    assert len(filtered) == 1
    assert filtered[0].filename == "order.pdf"
    print("SUCCESS: PDF attachment filtering respects MIME type, filename, and max attachment limit.")


def test_validator_skips_when_evidence_is_insufficient() -> None:
    validator = object.__new__(GeminiValidator)
    validator.model = "gemini-2.5-flash"
    validator.max_email_chars = 12000
    validator.max_attachments = 4

    result = validator.validate_order(
        message=IngestedEmail(
            message_id="msg-1",
            subject="Short mail",
            sender="test@example.com",
            received_at="2026-03-10T10:00:00+00:00",
            body_text="Too short",
            attachments=[],
        ),
        branch_id="xxxlutz_default",
        normalized=_sample_payload(),
        xml_documents=[],
    )

    assert result["validation_status"] == VALIDATION_STATUS_SKIPPED
    assert "not enough email or PDF evidence" in result["validation_summary"]
    print("SUCCESS: validator returns skipped without calling Gemini when evidence is insufficient.")


def test_order_store_validation_helpers() -> None:
    normalized = order_store._normalize_validation_result_payload(
        {
            "validation_status": "flagged",
            "validation_summary": "Mismatch found",
            "validation_checked_at": "2026-03-10T11:00:00+00:00",
            "validation_provider": VALIDATION_PROVIDER_GEMINI,
            "validation_model": "gemini-2.5-flash",
            "validation_stale_reason": "",
            "validation_issues": [{"field_path": "header.kom_nr", "reason": "Mismatch"}],
            "validation_raw_result": {"validation_status": "flagged"},
        }
    )
    assert normalized["validation_status"] == VALIDATION_STATUS_FLAGGED
    assert normalized["validation_provider"] == VALIDATION_PROVIDER_GEMINI
    assert normalized["validation_model"] == "gemini-2.5-flash"
    assert normalized["validation_issues"] == [
        {
            "severity": "warning",
            "scope": "general",
            "field_path": "header.kom_nr",
            "source_evidence": "",
            "expected_value": "",
            "xml_value": "",
            "reason": "Mismatch",
        }
    ]
    assert order_store.validation_status_needs_review("flagged") is True
    assert order_store.validation_status_needs_review("stale") is True
    assert order_store.validation_status_needs_review("passed") is False
    print("SUCCESS: order_store validation helpers normalize issues and review queue states.")


def test_xml_render_write_parity() -> None:
    config = Config.from_env()
    payload = _sample_payload()
    with tempfile.TemporaryDirectory() as tmp_dir:
        output_dir = Path(tmp_dir)
        documents = xml_exporter.render_xml_documents(payload, "ignored", config, output_dir)
        assert len(documents) == 2
        paths = xml_exporter.write_xml_documents(documents)
        assert [path.name for path in paths] == [document.filename for document in documents]
        for document, path in zip(documents, paths, strict=True):
            assert path.read_text(encoding="utf-8") == document.content
    print("SUCCESS: XML documents are rendered in memory and written without altering content.")


if __name__ == "__main__":
    test_normalize_validation_result_defaults()
    test_build_stale_validation_result()
    test_pdf_attachment_filtering()
    test_validator_skips_when_evidence_is_insufficient()
    test_order_store_validation_helpers()
    test_xml_render_write_parity()
    print("All Gemini validation verification checks passed.")
