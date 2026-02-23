import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import extraction_router
import pipeline
from config import Config
from email_ingest import Attachment, IngestedEmail


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


def _message(
    *,
    subject: str = "Routing test",
    sender: str = "test@example.com",
    body_text: str = "Body",
) -> IngestedEmail:
    return IngestedEmail(
        message_id="routing_test",
        received_at="2026-02-20T10:00:00+00:00",
        subject=subject,
        sender=sender,
        body_text=body_text,
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


def test_routing_porta_branch_selected() -> None:
    extractor = MagicMock()
    extractor.complete_text.return_value = json.dumps(
        {"branch_id": "porta", "confidence": 0.99, "reason": "porta_hint"}
    )
    extractor.extract_with_prompts.return_value = _base_extraction_response()
    extractor.verify_items_from_pdf.return_value = json.dumps(
        {"verified_items": [], "warnings": []}
    )

    result = pipeline.process_message(
        _message(subject="PORTA Bestellung", sender="orders@porta.example"),
        _config(),
        extractor,
    )
    warnings = result.data.get("warnings") or []

    assert any(
        "Routing: selected=porta" in str(w) and "fallback=false" in str(w)
        for w in warnings
    )
    print("SUCCESS: high-confidence porta branch routes without fallback.")


def test_porta_hint_from_pdf_layout_markers() -> None:
    message = IngestedEmail(
        message_id="routing_porta_hint_pdf",
        received_at="2026-02-23T10:00:00+00:00",
        subject="Neue Bestellung",
        sender="orders@example.com",
        body_text="Siehe Anhang",
        attachments=[
            Attachment(
                filename="porta_order.pdf",
                content_type="application/pdf",
                data=b"%PDF-1.4 fake",
            )
        ],
    )
    pdf_preview_text = (
        "Bestellung/Order\n"
        "K U N D E N K O M M I S S I O N\n"
        "Fuer Haus: 706\n"
        "Lieferantennummer: 31201"
    )

    with patch("extraction_router._pdf_first_page_text", return_value=pdf_preview_text):
        payload_text = extraction_router._build_router_user_text(message, _config(), {})

    payload = json.loads(payload_text)
    assert payload.get("porta_hint") is True
    print("SUCCESS: Porta PDF layout markers trigger porta_hint=true.")


def test_routing_porta_hard_match_from_sender_domain() -> None:
    extractor = MagicMock()
    extractor.complete_text.return_value = json.dumps(
        {"branch_id": "unknown", "confidence": 0.10, "reason": "unsure"}
    )
    extractor.extract_with_prompts.return_value = _base_extraction_response()
    message = IngestedEmail(
        message_id="routing_porta_hard_sender",
        received_at="2026-02-23T10:00:00+00:00",
        subject="Wichtige Information zu Bestellung 2891146",
        sender="service@porta.de",
        body_text="Im Anhang senden wir unsere Bestellung als PDF-Datei.",
        attachments=[
            Attachment(
                filename="603800292.pdf",
                content_type="application/pdf",
                data=b"%PDF-1.4 fake",
            )
        ],
    )

    with patch("extraction_router._pdf_first_page_text", return_value=""):
        result = pipeline.process_message(message, _config(), extractor)

    warnings = result.data.get("warnings") or []
    assert any(
        "Routing: selected=porta" in str(w)
        and "forced=true" in str(w)
        and "fallback=false" in str(w)
        for w in warnings
    )
    print("SUCCESS: sender @porta.de + PDF forces porta routing.")


if __name__ == "__main__":
    test_routing_high_confidence_branch()
    test_routing_unknown_forces_human_review()
    test_routing_malformed_json_forces_human_review()
    test_routing_porta_branch_selected()
    test_porta_hint_from_pdf_layout_markers()
    test_routing_porta_hard_match_from_sender_domain()
