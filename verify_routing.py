import json
from pathlib import Path
from unittest.mock import MagicMock

import pipeline
from config import Config
from email_ingest import IngestedEmail


def _base_extraction_response() -> str:
    return json.dumps(
        {
            "header": {
                "kundennummer": {"value": "123456", "source": "email", "confidence": 1.0},
                "kom_nr": {"value": "KOM-1", "source": "email", "confidence": 1.0},
                "human_review_needed": {"value": False, "source": "derived", "confidence": 1.0},
                "reply_needed": {"value": False, "source": "derived", "confidence": 1.0},
                "post_case": {"value": False, "source": "derived", "confidence": 1.0},
            },
            "items": [
                {
                    "line_no": 1,
                    "artikelnummer": {"value": "1001", "source": "email", "confidence": 1.0},
                    "modellnummer": {"value": "MODEL1", "source": "email", "confidence": 1.0},
                    "menge": {"value": 1, "source": "email", "confidence": 1.0},
                    "furncloud_id": {"value": "", "source": "derived", "confidence": 0.0},
                }
            ],
            "warnings": [],
            "errors": [],
            "status": "ok",
        }
    )


def _message() -> IngestedEmail:
    return IngestedEmail(
        message_id="routing_test",
        received_at="2026-02-20T10:00:00+00:00",
        subject="Routing test",
        sender="test@example.com",
        body_text="Body",
        attachments=[],
    )


def _config() -> Config:
    config = Config.from_env()
    config.output_dir = Path("./tmp_routing_verify")
    config.output_dir.mkdir(exist_ok=True)
    return config


def test_routing_high_confidence_branch() -> None:
    extractor = MagicMock()
    extractor.complete_text.return_value = json.dumps(
        {"branch_id": "xxxlutz_default", "confidence": 0.99, "reason": "matched"}
    )
    extractor.extract_with_prompts.return_value = _base_extraction_response()

    result = pipeline.process_message(_message(), _config(), extractor)
    warnings = result.data.get("warnings") or []
    review_flag = result.data.get("header", {}).get("human_review_needed", {}).get("value")

    assert any("Routing: selected=xxxlutz_default" in str(w) and "fallback=false" in str(w) for w in warnings)
    assert review_flag is False
    print("SUCCESS: high-confidence known branch routes without fallback.")


def test_routing_unknown_forces_human_review() -> None:
    extractor = MagicMock()
    extractor.complete_text.return_value = json.dumps(
        {"branch_id": "unknown", "confidence": 0.3, "reason": "unsure"}
    )
    extractor.extract_with_prompts.return_value = _base_extraction_response()

    result = pipeline.process_message(_message(), _config(), extractor)
    warnings = result.data.get("warnings") or []
    human_review = result.data.get("header", {}).get("human_review_needed", {})

    assert any("fallback=true" in str(w) for w in warnings)
    assert "Routing fallback: forced human_review_needed=true" in warnings
    assert human_review.get("value") is True
    assert human_review.get("derived_from") == "routing_fallback"
    print("SUCCESS: unknown routing falls back and forces human review.")


def test_routing_malformed_json_forces_human_review() -> None:
    extractor = MagicMock()
    extractor.complete_text.return_value = "not-json"
    extractor.extract_with_prompts.return_value = _base_extraction_response()

    result = pipeline.process_message(_message(), _config(), extractor)
    warnings = result.data.get("warnings") or []
    human_review = result.data.get("header", {}).get("human_review_needed", {})

    assert any("fallback=true" in str(w) for w in warnings)
    assert "Routing fallback: forced human_review_needed=true" in warnings
    assert human_review.get("value") is True
    assert human_review.get("derived_from") == "routing_fallback"
    print("SUCCESS: malformed routing response falls back and forces human review.")


if __name__ == "__main__":
    test_routing_high_confidence_branch()
    test_routing_unknown_forces_human_review()
    test_routing_malformed_json_forces_human_review()
