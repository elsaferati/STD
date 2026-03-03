from __future__ import annotations

from pathlib import Path

from email_ingest import IngestedEmail
from reply_email import compose_reply_needed_email


TEMPLATE_FILE = Path("email_templates/reply_templates.json")


def _base_message() -> IngestedEmail:
    return IngestedEmail(
        message_id="test_reply_needed_message_id",
        received_at="2026-02-12T12:00:00+00:00",
        subject="Test subject",
        sender="sender@example.com",
        body_text="Body",
        attachments=[],
    )


def _entry(value: str, source: str = "email", confidence: float = 1.0) -> dict:
    return {"value": value, "source": source, "confidence": confidence}


def _item(artikel: str, modell: str, menge: str = "1") -> dict:
    return {
        "artikelnummer": _entry(artikel),
        "modellnummer": _entry(modell),
        "menge": _entry(menge),
        "furncloud_id": _entry("", source="derived", confidence=0.0),
    }


def _base_normalized(message: IngestedEmail) -> dict:
    return {
        "message_id": message.message_id,
        "received_at": message.received_at,
        "header": {
            "reply_needed": _entry("true", source="derived"),
            "ticket_number": _entry("1000001"),
            "kundennummer": _entry("123456"),
            "kom_nr": _entry("KOM-1"),
            "kom_name": _entry("NAME"),
            "liefertermin": _entry("KW08/2026"),
            "wunschtermin": _entry(""),
            "iln": _entry("9007019012285"),
            "lieferanschrift": _entry("Musterstrasse 1, 12345 Musterstadt"),
            "store_address": _entry("Storestrasse 1, 12345 Storestadt"),
        },
        "warnings": [],
        "errors": [],
        "items": [_item("ART-1", "MOD-1", "1")],
    }


def _compose(normalized: dict, template_file: Path | None = None):
    return compose_reply_needed_email(
        message=_base_message(),
        normalized=normalized,
        to_addr="00primex.eu@gmail.com",
        body_template="Legacy fallback body.",
        template_file=template_file or TEMPLATE_FILE,
    )


def _assert_template_1_missing_lieferanschrift() -> None:
    normalized = _base_normalized(_base_message())
    normalized["header"]["lieferanschrift"]["value"] = ""
    msg = _compose(normalized)
    body = msg.get_content()
    assert msg["Subject"] == "Ruckfrage zu Ihrer Bestellung KOM-1 - Lieferanschrift fehlt"
    assert "benotigen wir noch die Lieferanschrift" in body
    assert "{{kommisionsnummer}}" not in body


def _assert_template_2_missing_store_address() -> None:
    normalized = _base_normalized(_base_message())
    normalized["header"]["store_address"]["value"] = ""
    msg = _compose(normalized)
    body = msg.get_content()
    assert msg["Subject"] == "Ruckfrage zu Ihrer Bestellung KOM-1 - Anschrift bestellendes Haus fehlt"
    assert "Anschrift des bestellenden Hauses" in body


def _assert_template_3_missing_modellnummer() -> None:
    normalized = _base_normalized(_base_message())
    normalized["items"] = [_item("ART-1", "", "1")]
    msg = _compose(normalized)
    body = msg.get_content()
    assert msg["Subject"] == "Ruckfrage zu Ihrer Bestellung KOM-1 - Modellnummer fehlt"
    assert "benotigen wir noch die Modellnummer" in body


def _assert_template_4_missing_artikelnummer() -> None:
    normalized = _base_normalized(_base_message())
    normalized["items"] = [_item("", "MOD-1", "1")]
    msg = _compose(normalized)
    body = msg.get_content()
    assert msg["Subject"] == "Ruckfrage zu Ihrer Bestellung KOM-1 - Artikelnummer fehlt"
    assert "benotigen wir noch die Artikelnummer" in body


def _assert_template_5_missing_menge() -> None:
    normalized = _base_normalized(_base_message())
    normalized["items"] = [_item("ART-1", "MOD-1", "")]
    msg = _compose(normalized)
    body = msg.get_content()
    assert msg["Subject"] == "Ruckfrage zu Ihrer Bestellung KOM-1 - Menge fehlt"
    assert "benotigen wir noch die Menge" in body


def _assert_template_6_multiple_missing_fields() -> None:
    normalized = _base_normalized(_base_message())
    normalized["header"]["lieferanschrift"]["value"] = ""
    normalized["items"] = [_item("", "", "")]
    msg = _compose(normalized)
    body = msg.get_content()
    assert msg["Subject"] == "Ruckfrage zu Ihrer Bestellung KOM-1 - Angaben fehlen"
    assert "- Lieferanschrift" in body
    assert "- Modellnummer" in body
    assert "- Artikelnummer" in body
    assert "- Menge" in body


def _assert_template_6_for_substitution_without_field_mapping() -> None:
    normalized = _base_normalized(_base_message())
    normalized["warnings"] = ["Reply needed: STATT TYP ABC BITTE TYP DEF"]
    msg = _compose(normalized)
    body = msg.get_content()
    assert msg["Subject"] == "Ruckfrage zu Ihrer Bestellung KOM-1 - Angaben fehlen"
    assert "STATT TYP ABC BITTE TYP DEF" in body


def _assert_placeholder_fallback_ticket_then_message_id() -> None:
    normalized_ticket = _base_normalized(_base_message())
    normalized_ticket["header"]["kom_nr"]["value"] = ""
    normalized_ticket["header"]["lieferanschrift"]["value"] = ""
    msg_ticket = _compose(normalized_ticket)
    assert "1000001" in str(msg_ticket["Subject"])

    normalized_message = _base_normalized(_base_message())
    normalized_message["header"]["kom_nr"]["value"] = ""
    normalized_message["header"]["ticket_number"]["value"] = ""
    normalized_message["header"]["lieferanschrift"]["value"] = ""
    msg_message = _compose(normalized_message)
    assert "test_reply_needed_message_id" in str(msg_message["Subject"])


def _assert_dormant_template_7_8_not_auto_selected() -> None:
    normalized = _base_normalized(_base_message())
    normalized["warnings"] = [
        "Reply needed: clarification required for order parsing"
    ]
    msg = _compose(normalized)
    assert "Furnplan fehlt" not in str(msg["Subject"])
    assert "Unterlage unleserlich" not in str(msg["Subject"])
    assert str(msg["Subject"]).endswith("Angaben fehlen")


def _assert_malformed_template_file_falls_back_to_legacy() -> None:
    malformed = Path("tmp_malformed_reply_templates.json")
    malformed.write_text("{}", encoding="utf-8")
    try:
        normalized = _base_normalized(_base_message())
        normalized["warnings"] = ["Reply needed: STATT X BITTE Y"]
        msg = _compose(normalized, template_file=malformed)
        body = msg.get_content()
        assert str(msg["Subject"]).startswith("Reply needed -")
        assert "Legacy fallback body." in body
    finally:
        malformed.unlink(missing_ok=True)


def main() -> int:
    _assert_template_1_missing_lieferanschrift()
    _assert_template_2_missing_store_address()
    _assert_template_3_missing_modellnummer()
    _assert_template_4_missing_artikelnummer()
    _assert_template_5_missing_menge()
    _assert_template_6_multiple_missing_fields()
    _assert_template_6_for_substitution_without_field_mapping()
    _assert_placeholder_fallback_ticket_then_message_id()
    _assert_dormant_template_7_8_not_auto_selected()
    _assert_malformed_template_file_falls_back_to_legacy()
    print("OK: reply email templates route and render correctly with fallback support.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
