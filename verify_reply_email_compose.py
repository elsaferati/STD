from __future__ import annotations

from email.message import EmailMessage

from email_ingest import IngestedEmail
from reply_email import compose_reply_needed_email


def _base_message() -> IngestedEmail:
    return IngestedEmail(
        message_id="test_reply_needed_message_id",
        received_at="2026-02-12T12:00:00+00:00",
        subject="Test subject",
        sender="sender@example.com",
        body_text="STATT TYP ABC BITTE TYP DEF",
        attachments=[],
    )


def _base_normalized(message: IngestedEmail) -> dict:
    return {
        "message_id": message.message_id,
        "received_at": message.received_at,
        "header": {
            "reply_needed": {"value": True, "source": "email", "confidence": 1.0},
            "ticket_number": {"value": "1000001", "source": "email", "confidence": 1.0},
            "kundennummer": {"value": "123456", "source": "email", "confidence": 1.0},
            "kom_nr": {"value": "KOM-1", "source": "email", "confidence": 1.0},
            "kom_name": {"value": "NAME", "source": "email", "confidence": 1.0},
            "liefertermin": {"value": "KW08/2026", "source": "email", "confidence": 1.0},
            "wunschtermin": {"value": "", "source": "derived", "confidence": 0.0},
            "iln": {"value": "9007019012285", "source": "email", "confidence": 1.0},
        },
        "warnings": [],
        "errors": [],
        "items": [],
    }


def _compose(normalized: dict) -> EmailMessage:
    return compose_reply_needed_email(
        message=_base_message(),
        normalized=normalized,
        to_addr="00primex.eu@gmail.com",
        body_template="Please send the order with furnplan or make the order with 2 positions.",
    )


def _assert_substitution_only() -> None:
    normalized = _base_normalized(_base_message())
    normalized["warnings"] = ["Reply needed: STATT TYP ABC BITTE TYP DEF"]
    msg = _compose(normalized)
    assert msg["Subject"] == "Reply needed - swap detected - 1000001"
    body = msg.get_content()
    assert "Please send the order with furnplan or make the order with 2 positions." in body
    assert "Detected a substitution request (STATT ... BITTE ...)." in body
    assert "Reply case: STATT TYP ABC BITTE TYP DEF" in body


def _assert_missing_critical_only() -> None:
    normalized = _base_normalized(_base_message())
    normalized["warnings"] = ["Reply needed: Missing critical header fields: kom_nr, liefertermin"]
    msg = _compose(normalized)
    assert msg["Subject"] == "Reply needed - missing critical fields - 1000001"
    body = msg.get_content()
    assert "Please send the order with furnplan or make the order with 2 positions." not in body
    assert "Automatic order processing could not continue because mandatory fields are missing." in body
    assert "Missing mandatory fields" in body
    assert "Missing critical header fields: kom_nr, liefertermin" in body
    assert "corrected order via furnplan" in body


def _assert_combined_equal() -> None:
    normalized = _base_normalized(_base_message())
    normalized["warnings"] = [
        "Reply needed: STATT TYP ABC BITTE TYP DEF",
        "Reply needed: Missing critical header fields: kom_nr",
    ]
    msg = _compose(normalized)
    assert msg["Subject"] == "Reply needed - multiple issues - 1000001"
    body = msg.get_content()
    assert "Please send the order with furnplan or make the order with 2 positions." not in body
    assert "Detected two reply-needed conditions:" in body
    assert "Substitution details" in body
    assert "1. STATT TYP ABC BITTE TYP DEF" in body
    assert "Missing mandatory fields" in body
    assert "Missing critical header fields: kom_nr" in body


def _assert_missing_critical_item_only() -> None:
    normalized = _base_normalized(_base_message())
    normalized["warnings"] = ["Reply needed: Missing critical item fields: artikelnummer (line 1), modellnummer (line 2)"]
    msg = _compose(normalized)
    assert msg["Subject"] == "Reply needed - missing critical fields - 1000001"
    body = msg.get_content()
    assert "Please send the order with furnplan or make the order with 2 positions." not in body
    assert "Missing mandatory fields" in body
    assert "Missing critical item fields: artikelnummer (line 1), modellnummer (line 2)" in body


def main() -> int:
    _assert_substitution_only()
    _assert_missing_critical_only()
    _assert_combined_equal()
    _assert_missing_critical_item_only()
    print("OK: reply email compose supports substitution, missing-critical, and combined cases.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
