import json
from pathlib import Path
from unittest.mock import MagicMock
import sys
import types

try:
    import fitz  # noqa: F401
except ModuleNotFoundError:
    fitz_stub = types.ModuleType("fitz")

    def _missing_fitz(*args, **kwargs):
        raise ModuleNotFoundError("PyMuPDF (fitz) is required for PDF text helpers.")

    fitz_stub.open = _missing_fitz
    sys.modules["fitz"] = fitz_stub

import extraction_branches
import pipeline
from config import Config
from email_ingest import IngestedEmail
from openai_extract import ImageInput, OpenAIExtractor


def _config() -> Config:
    config = Config.from_env()
    config.output_dir = Path("./tmp_text_only_verification")
    config.output_dir.mkdir(exist_ok=True)
    return config


def _message() -> IngestedEmail:
    return IngestedEmail(
        message_id="text_only_verify",
        received_at="2026-02-24T10:00:00+00:00",
        subject="Verification test",
        sender="orders@example.com",
        body_text="Body",
        attachments=[],
    )


def _extraction_payload(items: list[dict]) -> str:
    return json.dumps(
        {
            "header": {
                "kundennummer": {"value": "123456", "source": "email", "confidence": 1.0},
                "kom_nr": {"value": "KOM-1", "source": "email", "confidence": 1.0},
                "reply_needed": {"value": False, "source": "derived", "confidence": 1.0},
                "human_review_needed": {"value": False, "source": "derived", "confidence": 1.0},
                "post_case": {"value": False, "source": "derived", "confidence": 1.0},
            },
            "items": items,
            "warnings": [],
            "errors": [],
            "status": "ok",
        }
    )


def test_branch_flags_xxxlutz_default() -> None:
    branch = extraction_branches.get_branch("xxxlutz_default")
    assert branch.enable_detail_extraction is False
    assert branch.enable_item_code_verification is True
    print("SUCCESS: xxxlutz_default branch flags match expected config.")


def test_verifier_called_when_text_and_items_present() -> None:
    extractor = MagicMock()
    extractor.complete_text.return_value = json.dumps(
        {"branch_id": "porta", "confidence": 1.0, "reason": "test"}
    )
    extractor.extract_with_prompts.return_value = _extraction_payload(
        [
            {
                "line_no": 1,
                "artikelnummer": {"value": "1001", "source": "pdf", "confidence": 1.0},
                "modellnummer": {"value": "MODEL1", "source": "pdf", "confidence": 1.0},
                "menge": {"value": 1, "source": "pdf", "confidence": 1.0},
            }
        ]
    )
    extractor.verify_items_from_text.return_value = json.dumps(
        {"verified_items": [], "warnings": []}
    )

    original_prepare_images = pipeline._prepare_images
    pipeline._prepare_images = lambda attachments, config, warnings: (
        [ImageInput(name="order-1.png", source="pdf", data_url="data:image/png;base64,")],
        {"order-1.png": "Artikel 1001"},
    )
    try:
        pipeline.process_message(_message(), _config(), extractor)
        extractor.verify_items_from_text.assert_called_once()
        print("SUCCESS: verifier runs when item snapshot and digital PDF text are available.")
    finally:
        pipeline._prepare_images = original_prepare_images


def test_verifier_skipped_without_digital_text() -> None:
    extractor = MagicMock()
    extractor.complete_text.return_value = json.dumps(
        {"branch_id": "porta", "confidence": 1.0, "reason": "test"}
    )
    extractor.extract_with_prompts.return_value = _extraction_payload(
        [
            {
                "line_no": 1,
                "artikelnummer": {"value": "1001", "source": "pdf", "confidence": 1.0},
                "modellnummer": {"value": "MODEL1", "source": "pdf", "confidence": 1.0},
                "menge": {"value": 1, "source": "pdf", "confidence": 1.0},
            }
        ]
    )

    original_prepare_images = pipeline._prepare_images
    pipeline._prepare_images = lambda attachments, config, warnings: (
        [ImageInput(name="order-1.png", source="pdf", data_url="data:image/png;base64,")],
        {},
    )
    try:
        result = pipeline.process_message(_message(), _config(), extractor)
        extractor.verify_items_from_text.assert_not_called()
        warnings = result.data.get("warnings") or []
        assert any("item verification skipped: no digital PDF text available." in str(w) for w in warnings)
        print("SUCCESS: verifier skips and warns when digital PDF text is missing.")
    finally:
        pipeline._prepare_images = original_prepare_images


def test_verifier_not_called_when_items_empty() -> None:
    extractor = MagicMock()
    extractor.complete_text.return_value = json.dumps(
        {"branch_id": "porta", "confidence": 1.0, "reason": "test"}
    )
    extractor.extract_with_prompts.return_value = _extraction_payload([])

    original_prepare_images = pipeline._prepare_images
    pipeline._prepare_images = lambda attachments, config, warnings: (
        [ImageInput(name="order-1.png", source="pdf", data_url="data:image/png;base64,")],
        {"order-1.png": "Artikel 1001"},
    )
    try:
        result = pipeline.process_message(_message(), _config(), extractor)
        extractor.verify_items_from_text.assert_not_called()
        warnings = result.data.get("warnings") or []
        assert not any("item verification skipped: no digital PDF text available." in str(w) for w in warnings)
        print("SUCCESS: verifier is not called when items snapshot is empty.")
    finally:
        pipeline._prepare_images = original_prepare_images


def test_verify_items_payload_is_text_only() -> None:
    extractor = OpenAIExtractor(
        api_key="test-key",
        model="gpt-5.1-chat-latest",
        max_output_tokens=200,
    )
    captured: dict[str, object] = {}

    def _fake_create(content, system_prompt):
        captured["content"] = content
        captured["system_prompt"] = system_prompt
        return {"output_text": '{"verified_items":[],"warnings":[]}'}

    extractor._create_response_with_prompt = _fake_create  # type: ignore[method-assign]
    extractor.verify_items_from_text(
        items_snapshot=[
            {"line_no": 1, "modellnummer": "MODEL1", "artikelnummer": "1001", "menge": 1}
        ],
        page_text_by_image_name={"order-2.png": "two", "order-1.png": "one"},
        verification_profile="porta",
    )

    content = captured.get("content") or []
    assert isinstance(content, list)
    assert all(part.get("type") != "input_image" for part in content if isinstance(part, dict))
    page_headers = [
        part.get("text")
        for part in content
        if isinstance(part, dict) and isinstance(part.get("text"), str) and str(part.get("text")).startswith("PDF text page ")
    ]
    assert page_headers == ["PDF text page 1: order-1.png", "PDF text page 2: order-2.png"]
    assert any(
        "Current extracted items snapshot" in str(part.get("text"))
        for part in content
        if isinstance(part, dict)
    )
    print("SUCCESS: verify_items_from_text sends text-only payload in deterministic page order.")


if __name__ == "__main__":
    test_branch_flags_xxxlutz_default()
    test_verifier_called_when_text_and_items_present()
    test_verifier_skipped_without_digital_text()
    test_verifier_not_called_when_items_empty()
    test_verify_items_payload_is_text_only()
