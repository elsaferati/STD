import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock
from pipeline import process_message, ProcessedResult
from normalize import normalize_output
from config import Config
from email_ingest import IngestedEmail
import app as dashboard_app


def test_reply_needed_preservation():
    # Mock configuration
    config = Config.from_env()
    config.output_dir = Path("./test_output_reply_needed")
    config.output_dir.mkdir(exist_ok=True)

    # Mock Extractor
    extractor = MagicMock()
    
    # Mock LLM Response with reply_needed = True
    mock_response = {
        "header": {
            "kundennummer": {"value": "123456", "source": "pdf", "confidence": 0.9},
            "human_review_needed": {"value": False, "source": "pdf", "confidence": 1.0},
            "reply_needed": {"value": True, "source": "pdf", "confidence": 1.0}
        },
        "items": [],
        "warnings": [],
        "errors": []
    }
    
    # Mock extraction method
    extractor.extract.return_value = json.dumps(mock_response)

    # Create dummy message
    message = IngestedEmail(
        message_id="test_reply_needed",
        received_at="2025-01-01T12:00:00",
        subject="Test Reply Needed",
        sender="test@example.com",
        body_text="STATT X BITTE Y",
        attachments=[]
    )

    # Run processing
    result = process_message(message, config, extractor)
    
    # Check if normalized data has the flag
    print("Normalized Data Reply Needed:", result.data["header"].get("reply_needed"))
    
    # Verify the value is strictly True or boolean-like
    flag = result.data["header"].get("reply_needed", {}).get("value")
    if flag is True:
        print("SUCCESS: Reply needed flag preserved as True.")
    else:
        print(f"FAILURE: Reply needed flag is {flag}")

    # Write to disk effectively simulating the app
    output_path = config.output_dir / "test_reply_needed.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result.data, f, indent=2)

    print(f"Written to {output_path}")


def test_reply_needed_from_missing_critical_fields() -> None:
    warnings: list[str] = []
    data = {
        "header": {
            "kundennummer": {"value": "123456", "source": "email", "confidence": 1.0},
            "reply_needed": {"value": False, "source": "email", "confidence": 1.0},
        },
        "items": [
            {
                "artikelnummer": {"value": "A-1", "source": "email", "confidence": 1.0},
                "modellnummer": {"value": "M-1", "source": "email", "confidence": 1.0},
                "menge": {"value": 1, "source": "email", "confidence": 1.0},
                "furncloud_id": {"value": "FC-1", "source": "email", "confidence": 1.0},
            }
        ],
        "warnings": [],
        "errors": [],
    }
    normalized = normalize_output(
        data=data,
        message_id="test_missing_critical",
        received_at="2026-02-12T12:00:00+00:00",
        dayfirst=True,
        warnings=warnings,
        email_body="",
        sender="test@example.com",
    )
    reply_needed = normalized["header"].get("reply_needed", {}).get("value")
    warning_list = normalized.get("warnings") if isinstance(normalized.get("warnings"), list) else []
    expected_reply_warning = "Reply needed: Missing critical header fields: kom_nr"

    assert reply_needed is True, f"Expected reply_needed=True, got {reply_needed}"
    assert expected_reply_warning in warning_list, "Missing critical-fields reply warning not found"
    assert any(
        isinstance(w, str) and w.startswith("Missing header fields:")
        for w in warning_list
    ), "Missing header fields warning should still be present"
    print("SUCCESS: Missing critical header fields now force reply_needed and warning output.")


def test_reply_needed_from_missing_kundennummer() -> None:
    warnings: list[str] = []
    data = {
        "header": {
            "kom_nr": {"value": "KOM-99", "source": "email", "confidence": 1.0},
            "reply_needed": {"value": False, "source": "email", "confidence": 1.0},
        },
        "items": [
            {
                "artikelnummer": {"value": "A-1", "source": "email", "confidence": 1.0},
                "modellnummer": {"value": "M-1", "source": "email", "confidence": 1.0},
                "menge": {"value": 1, "source": "email", "confidence": 1.0},
                "furncloud_id": {"value": "FC-1", "source": "email", "confidence": 1.0},
            }
        ],
        "warnings": [],
        "errors": [],
    }
    normalized = normalize_output(
        data=data,
        message_id="test_missing_kundennummer",
        received_at="2026-02-12T12:00:00+00:00",
        dayfirst=True,
        warnings=warnings,
        email_body="",
        sender="test@example.com",
    )
    warning_list = normalized.get("warnings") if isinstance(normalized.get("warnings"), list) else []
    assert normalized["header"].get("reply_needed", {}).get("value") is True
    assert "Reply needed: Missing critical header fields: kundennummer" in warning_list
    print("SUCCESS: Missing kundennummer also triggers reply_needed.")


def test_reply_needed_from_missing_critical_item_fields() -> None:
    warnings: list[str] = []
    data = {
        "header": {
            "kom_nr": {"value": "KOM-99", "source": "email", "confidence": 1.0},
            "kundennummer": {"value": "123456", "source": "email", "confidence": 1.0},
            "reply_needed": {"value": False, "source": "email", "confidence": 1.0},
        },
        "items": [
            {
                "artikelnummer": {"value": "", "source": "email", "confidence": 0.0},
                "modellnummer": {"value": "M-1", "source": "email", "confidence": 1.0},
                "menge": {"value": 1, "source": "email", "confidence": 1.0},
                "furncloud_id": {"value": "FC-1", "source": "email", "confidence": 1.0},
            },
            {
                "artikelnummer": {"value": "A-2", "source": "email", "confidence": 1.0},
                "modellnummer": {"value": "", "source": "email", "confidence": 0.0},
                "menge": {"value": 1, "source": "email", "confidence": 1.0},
                "furncloud_id": {"value": "FC-1", "source": "email", "confidence": 1.0},
            },
        ],
        "warnings": [],
        "errors": [],
    }
    normalized = normalize_output(
        data=data,
        message_id="test_missing_item_critical",
        received_at="2026-02-12T12:00:00+00:00",
        dayfirst=True,
        warnings=warnings,
        email_body="",
        sender="test@example.com",
    )
    warning_list = normalized.get("warnings") if isinstance(normalized.get("warnings"), list) else []
    assert normalized["header"].get("reply_needed", {}).get("value") is True
    assert "Reply needed: Missing critical item fields: artikelnummer (line 1), modellnummer (line 2)" in warning_list
    print("SUCCESS: Missing artikelnummer/modellnummer now triggers reply_needed.")


def test_post_case_preservation() -> None:
    warnings: list[str] = []
    data = {
        "header": {
            "kom_nr": {"value": "KOM-99", "source": "email", "confidence": 1.0},
            "kundennummer": {"value": "123456", "source": "email", "confidence": 1.0},
            "post_case": {"value": True, "source": "email", "confidence": 1.0},
            "reply_needed": {"value": False, "source": "email", "confidence": 1.0},
        },
        "items": [
            {
                "artikelnummer": {"value": "A-1", "source": "email", "confidence": 1.0},
                "modellnummer": {"value": "M-1", "source": "email", "confidence": 1.0},
                "menge": {"value": 1, "source": "email", "confidence": 1.0},
                "furncloud_id": {"value": "FC-1", "source": "email", "confidence": 1.0},
            }
        ],
        "warnings": [],
        "errors": [],
    }
    normalized = normalize_output(
        data=data,
        message_id="test_post_case_preservation",
        received_at="2026-02-12T12:00:00+00:00",
        dayfirst=True,
        warnings=warnings,
        email_body="WENN MOEGLICH BITTE KUNDE DIREKT PER POST ZUKOMMEN",
        sender="test@example.com",
    )
    assert normalized["header"].get("post_case", {}).get("value") is True
    print("SUCCESS: post_case=True preserved after normalization.")


def test_post_case_default_false_when_missing() -> None:
    warnings: list[str] = []
    data = {
        "header": {
            "kom_nr": {"value": "KOM-99", "source": "email", "confidence": 1.0},
            "kundennummer": {"value": "123456", "source": "email", "confidence": 1.0},
            "reply_needed": {"value": False, "source": "email", "confidence": 1.0},
        },
        "items": [
            {
                "artikelnummer": {"value": "A-1", "source": "email", "confidence": 1.0},
                "modellnummer": {"value": "M-1", "source": "email", "confidence": 1.0},
                "menge": {"value": 1, "source": "email", "confidence": 1.0},
                "furncloud_id": {"value": "FC-1", "source": "email", "confidence": 1.0},
            }
        ],
        "warnings": [],
        "errors": [],
    }
    normalized = normalize_output(
        data=data,
        message_id="test_post_case_default",
        received_at="2026-02-12T12:00:00+00:00",
        dayfirst=True,
        warnings=warnings,
        email_body="",
        sender="test@example.com",
    )
    assert normalized["header"].get("post_case", {}).get("value") is False
    print("SUCCESS: missing post_case defaults to False.")


def test_dashboard_list_orders_post_case_mapping() -> None:
    sample = {
        "message_id": "test_post_case_order",
        "received_at": "2026-02-12T12:00:00+00:00",
        "status": "ok",
        "header": {
            "post_case": {"value": True, "source": "email", "confidence": 1.0},
            "reply_needed": {"value": False, "source": "derived", "confidence": 1.0},
            "human_review_needed": {"value": False, "source": "derived", "confidence": 1.0},
        },
        "items": [],
        "warnings": [],
        "errors": [],
    }
    with tempfile.TemporaryDirectory() as tmp_dir:
        temp_path = Path(tmp_dir)
        (temp_path / "test_post_case_order.json").write_text(
            json.dumps(sample, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        orders = dashboard_app._list_orders(temp_path)
    assert len(orders) == 1
    assert orders[0].get("post_case") is True
    print("SUCCESS: dashboard _list_orders maps post_case correctly.")


if __name__ == "__main__":
    test_reply_needed_preservation()
    test_reply_needed_from_missing_critical_fields()
    test_reply_needed_from_missing_kundennummer()
    test_reply_needed_from_missing_critical_item_fields()
    test_post_case_preservation()
    test_post_case_default_false_when_missing()
    test_dashboard_list_orders_post_case_mapping()
