import json
from pathlib import Path
from unittest.mock import MagicMock

import fitz  # PyMuPDF

import lookup
import momax_bg
import pipeline
from config import Config
from email_ingest import Attachment, IngestedEmail
from normalize import normalize_output
from openai_extract import ImageInput


def _make_pdf_bytes(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def test_momax_bg_two_pdf_special_case() -> None:
    pdf_a = _make_pdf_bytes(
        "Recipient: MOMAX BULGARIA\n"
        "IDENT No: 20197304\n"
        "ORDER\n"
        "No 1711/12.12.25\n"
        "Term for delivery: 20.03.26\n"
        "Store: VARNA\n"
        "Address: Varna, Blvd. Vladislav Varnenchik 277A\n"
    )
    pdf_b = _make_pdf_bytes(
        "MOMAX - ORDER\n"
        "VARNA - 88801711/12.12.25г.\n"
        "Code/Type Quantity\n"
        "SN/SN/71/SP/91/181 1\n"
        "ZB99/76403 1\n"
    )

    message = IngestedEmail(
        message_id="test_momax_bg",
        received_at="2026-02-13T12:00:00+00:00",
        subject="MOMAX BG order",
        sender="bg@example.com",
        body_text="",
        attachments=[
            Attachment(filename="bg_a.pdf", content_type="application/pdf", data=pdf_a),
            Attachment(filename="bg_b.pdf", content_type="application/pdf", data=pdf_b),
        ],
    )

    config = Config.from_env()
    config.output_dir = Path("./tmp_momax_bg_verify")
    config.output_dir.mkdir(exist_ok=True)

    # Force at least one PDF image so the "detail extraction" block would run unless guarded.
    original_prepare_images = pipeline._prepare_images
    pipeline._prepare_images = lambda attachments, config, warnings: [
        ImageInput(name="dummy_pdf_page.png", source="pdf", data_url="data:image/png;base64,")
    ]

    try:
        extractor = MagicMock()
        extractor.extract.side_effect = RuntimeError("BG case must NOT call extractor.extract()")
        extractor.extract_article_details.side_effect = RuntimeError(
            "BG case must skip detail extraction"
        )

        mock_llm_json = {
            "message_id": "test_momax_bg",
            "received_at": "2026-02-13T12:00:00+00:00",
            "header": {
                "kundennummer": {"value": "20197304", "source": "pdf", "confidence": 0.99},
                # Simulate LLM missing kom_nr; pipeline should recover from PDF text.
                "kom_nr": {"value": "", "source": "pdf", "confidence": 0.0},
                "kom_name": {"value": "VARNA", "source": "pdf", "confidence": 0.95},
                "liefertermin": {"value": "20.03.26", "source": "pdf", "confidence": 0.95},
                "bestelldatum": {"value": "12.12.25", "source": "derived", "confidence": 0.9},
                "store_name": {"value": "MOMAX BULGARIA - VARNA", "source": "pdf", "confidence": 0.95},
                "store_address": {"value": "Varna, Blvd. Vladislav Varnenchik 277A", "source": "pdf", "confidence": 0.95},
                "lieferanschrift": {"value": "Varna, Blvd. Vladislav Varnenchik 277A", "source": "derived", "confidence": 0.9},
                "reply_needed": {"value": False, "source": "derived", "confidence": 1.0},
                "human_review_needed": {"value": False, "source": "derived", "confidence": 1.0},
                "post_case": {"value": False, "source": "derived", "confidence": 1.0},
            },
            "items": [
                {
                    "line_no": 1,
                    "artikelnummer": {"value": "181", "source": "pdf", "confidence": 0.9},
                    "modellnummer": {"value": "SN/SN/71/SP/91", "source": "pdf", "confidence": 0.9},
                    "menge": {"value": 1, "source": "pdf", "confidence": 0.9},
                    "furncloud_id": {"value": "", "source": "derived", "confidence": 0.0},
                }
            ],
            "status": "ok",
            "warnings": [],
            "errors": [],
        }
        extractor._create_response.return_value = {"output_text": json.dumps(mock_llm_json)}

        result = pipeline.process_message(message, config, extractor)
        header = result.data.get("header") or {}

        assert header.get("kundennummer", {}).get("value") == "68939"
        assert header.get("kundennummer", {}).get("source") == "derived"
        assert header.get("kundennummer", {}).get("derived_from") == "excel_lookup_momax_bg_address"
        assert header.get("kom_nr", {}).get("value") == "88801711"
        assert header.get("reply_needed", {}).get("value") is False

        extractor.extract.assert_not_called()
        extractor.extract_article_details.assert_not_called()

        print("SUCCESS: Mömax BG two-PDF special-case path used and detail extraction skipped.")
    finally:
        pipeline._prepare_images = original_prepare_images


def test_momax_bg_allowlist_address_matching() -> None:
    varna = lookup.find_momax_bg_customer_by_address("Varna, Blvd. Vladislav Varnenchik 277A")
    assert varna is not None
    assert varna["kundennummer"] == "68939"
    assert varna["tour"] == "D2"
    assert varna["adressnummer"] == "0"

    slivnitza = lookup.find_momax_bg_customer_by_address("Slivnitza (Evropa) Blvd. 441\n1331 Sofia")
    assert slivnitza is not None
    assert slivnitza["kundennummer"] == "68935"

    plovdiv = lookup.find_momax_bg_customer_by_address("Asenovgradsko Shose Str.14\n4004 Plovdiv")
    assert plovdiv is not None
    assert plovdiv["kundennummer"] == "68941"

    print("SUCCESS: momax_bg allowlist address matching picks expected rows.")


def test_momax_bg_allowlist_match_without_rapidfuzz() -> None:
    original_fuzz = lookup.fuzz
    try:
        lookup.fuzz = None
        varna = lookup.find_momax_bg_customer_by_address("Varna, Blvd. Viadislav Varnenchik 277A")
        assert varna is not None
        assert varna["kundennummer"] == "68939"
        assert varna["tour"] == "D2"
        assert varna["adressnummer"] == "0"
        print("SUCCESS: momax_bg address matching works even without rapidfuzz.")
    finally:
        lookup.fuzz = original_fuzz


def test_momax_bg_no_match_does_not_fallback_to_standard_lookup() -> None:
    data = {
        "header": {
            "store_address": {"value": "Skopie Blvd 6\n1233 Sofia", "source": "pdf", "confidence": 0.95},
            "lieferanschrift": {"value": "Skopie Blvd 6\n1233 Sofia", "source": "pdf", "confidence": 0.95},
            "reply_needed": {"value": False, "source": "derived", "confidence": 1.0},
            "human_review_needed": {"value": False, "source": "derived", "confidence": 1.0},
            "post_case": {"value": False, "source": "derived", "confidence": 1.0},
        },
        "items": [
            {
                "line_no": 1,
                "artikelnummer": {"value": "181", "source": "pdf", "confidence": 0.9},
                "modellnummer": {"value": "SN/SN/71/SP/91", "source": "pdf", "confidence": 0.9},
                "menge": {"value": 1, "source": "pdf", "confidence": 0.9},
                "furncloud_id": {"value": "", "source": "derived", "confidence": 0.0},
            }
        ],
    }
    warnings: list[str] = []
    normalized = normalize_output(
        data,
        message_id="test_momax_bg_fallback",
        received_at="2026-02-13T12:00:00+00:00",
        dayfirst=True,
        warnings=warnings,
        email_body="",
        sender="bg@example.com",
        is_momax_bg=True,
    )
    header = normalized.get("header") or {}
    assert header.get("kundennummer", {}).get("value") == ""
    assert header.get("kundennummer", {}).get("derived_from") == "excel_lookup_failed"
    all_warnings = normalized.get("warnings") or []
    assert any("row-restricted address match failed" in str(w) for w in all_warnings)
    print("SUCCESS: momax_bg no-match path does not fallback to standard lookup.")


def test_non_bg_regression_calls_standard_extract() -> None:
    pdf = _make_pdf_bytes("Some other PDF content")
    message = IngestedEmail(
        message_id="test_non_bg",
        received_at="2026-02-13T12:00:00+00:00",
        subject="Regular order",
        sender="test@example.com",
        body_text="",
        attachments=[Attachment(filename="x.pdf", content_type="application/pdf", data=pdf)],
    )
    config = Config.from_env()

    original_prepare_images = pipeline._prepare_images
    pipeline._prepare_images = lambda attachments, config, warnings: [
        ImageInput(name="dummy_pdf_page.png", source="pdf", data_url="data:image/png;base64,")
    ]

    try:
        extractor = MagicMock()
        extractor._create_response.side_effect = RuntimeError("Non-BG must not use _create_response path")
        extractor.extract.return_value = json.dumps(
            {
                "header": {
                    "kundennummer": {"value": "123", "source": "email", "confidence": 1.0},
                    "kom_nr": {"value": "KOM-1", "source": "email", "confidence": 1.0},
                    "reply_needed": {"value": False, "source": "derived", "confidence": 1.0},
                    "human_review_needed": {"value": False, "source": "derived", "confidence": 1.0},
                    "post_case": {"value": False, "source": "derived", "confidence": 1.0},
                },
                "items": [],
                "warnings": [],
                "errors": [],
                "status": "ok",
            }
        )
        extractor.extract_article_details.return_value = json.dumps({})

        pipeline.process_message(message, config, extractor)
        extractor.extract.assert_called()
        extractor.extract_article_details.assert_called()
        extractor._create_response.assert_not_called()
        print("SUCCESS: Non-BG case uses standard extractor.extract().")
    finally:
        pipeline._prepare_images = original_prepare_images


def test_momax_bg_single_pdf_detection() -> None:
    pdf = _make_pdf_bytes(
        "Recipient: MOEMAX BULGARIA\n"
        "MOMAX - ORDER\n"
        "VARNA - 88801711/12.12.25\n"
        "Term for delivery: 20.03.26\n"
        "Address: Varna, Blvd. Vladislav Varnenchik 277A\n"
    )
    att = Attachment(filename="single.pdf", content_type="application/pdf", data=pdf)
    assert momax_bg.is_momax_bg_two_pdf_case([att]) is True
    assert momax_bg.extract_momax_bg_kom_nr([att]) == "88801711"
    assert momax_bg.extract_momax_bg_order_date([att]) == "12.12.25"
    print("SUCCESS: momax_bg detection works with single PDF too.")


def test_momax_bg_bestelldatum_fallback_from_pdf_suffix() -> None:
    pdf_a = _make_pdf_bytes(
        "Recipient: MOMAX BULGARIA\n"
        "IDENT No: 20197304\n"
        "ORDER\n"
        "No 1711/12.12.25\n"
        "Term for delivery: 20.03.26\n"
        "Store: VARNA\n"
        "Address: Varna, Blvd. Vladislav Varnenchik 277A\n"
    )
    pdf_b = _make_pdf_bytes(
        "MOMAX - ORDER\n"
        "VARNA - 88801711/12.12.25\n"
        "Code/Type Quantity\n"
        "SN/SN/71/SP/91/181 1\n"
    )
    message = IngestedEmail(
        message_id="test_momax_bg_date_fallback",
        received_at="2026-02-13T12:00:00+00:00",
        subject="MOMAX BG order",
        sender="bg@example.com",
        body_text="",
        attachments=[
            Attachment(filename="bg_a.pdf", content_type="application/pdf", data=pdf_a),
            Attachment(filename="bg_b.pdf", content_type="application/pdf", data=pdf_b),
        ],
    )
    config = Config.from_env()

    original_prepare_images = pipeline._prepare_images
    pipeline._prepare_images = lambda attachments, config, warnings: [
        ImageInput(name="dummy_pdf_page.png", source="pdf", data_url="data:image/png;base64,")
    ]

    try:
        extractor = MagicMock()
        extractor.extract.side_effect = RuntimeError("BG case must NOT call extractor.extract()")
        extractor.extract_article_details.side_effect = RuntimeError(
            "BG case must skip detail extraction"
        )
        extractor._create_response.return_value = {
            "output_text": json.dumps(
                {
                    "message_id": "test_momax_bg_date_fallback",
                    "received_at": "2026-02-13T12:00:00+00:00",
                    "header": {
                        "kundennummer": {"value": "20197304", "source": "pdf", "confidence": 0.99},
                        "kom_nr": {"value": "", "source": "pdf", "confidence": 0.0},
                        "kom_name": {"value": "VARNA", "source": "pdf", "confidence": 0.9},
                        "liefertermin": {"value": "20.03.26", "source": "pdf", "confidence": 0.9},
                        "bestelldatum": {"value": "", "source": "pdf", "confidence": 0.0},
                        "store_name": {"value": "MOMAX BULGARIA - VARNA", "source": "pdf", "confidence": 0.9},
                        "store_address": {"value": "Varna, Blvd. Vladislav Varnenchik 277A", "source": "pdf", "confidence": 0.9},
                        "lieferanschrift": {"value": "Varna, Blvd. Vladislav Varnenchik 277A", "source": "pdf", "confidence": 0.9},
                        "reply_needed": {"value": False, "source": "derived", "confidence": 1.0},
                        "human_review_needed": {"value": False, "source": "derived", "confidence": 1.0},
                        "post_case": {"value": False, "source": "derived", "confidence": 1.0},
                    },
                    "items": [
                        {
                            "line_no": 1,
                            "artikelnummer": {"value": "181", "source": "pdf", "confidence": 0.9},
                            "modellnummer": {"value": "SN/SN/71/SP/91", "source": "pdf", "confidence": 0.9},
                            "menge": {"value": 1, "source": "pdf", "confidence": 0.9},
                            "furncloud_id": {"value": "", "source": "derived", "confidence": 0.0},
                        }
                    ],
                    "status": "ok",
                    "warnings": [],
                    "errors": [],
                }
            )
        }

        result = pipeline.process_message(message, config, extractor)
        header = result.data.get("header") or {}
        assert header.get("kom_nr", {}).get("value") == "88801711"
        assert header.get("bestelldatum", {}).get("value") == "12.12.25"
        assert header.get("bestelldatum", {}).get("derived_from") == "pdf_order_suffix"
        print("SUCCESS: momax_bg derives bestelldatum from PDF order suffix when missing.")
    finally:
        pipeline._prepare_images = original_prepare_images


def test_momax_bg_no_raw_kdnr_fallback_from_pdf() -> None:
    pdf_a = _make_pdf_bytes(
        "Recipient: MOMAX BULGARIA\n"
        "IDENT No: 20197304\n"
        "ORDER\n"
        "No 1711/12.12.25\n"
        "Term for delivery: 20.03.26\n"
        "Store: TEST\n"
        "Address: Unknown Street 999, Unknown City\n"
    )
    pdf_b = _make_pdf_bytes(
        "MOMAX - ORDER\n"
        "TEST - 88801711/12.12.25Ð³.\n"
        "Code/Type Quantity\n"
        "SN/SN/71/SP/91/181 1\n"
    )
    message = IngestedEmail(
        message_id="test_momax_bg_no_raw_fallback",
        received_at="2026-02-13T12:00:00+00:00",
        subject="MOMAX BG order",
        sender="bg@example.com",
        body_text="",
        attachments=[
            Attachment(filename="bg_a.pdf", content_type="application/pdf", data=pdf_a),
            Attachment(filename="bg_b.pdf", content_type="application/pdf", data=pdf_b),
        ],
    )
    config = Config.from_env()

    original_prepare_images = pipeline._prepare_images
    pipeline._prepare_images = lambda attachments, config, warnings: [
        ImageInput(name="dummy_pdf_page.png", source="pdf", data_url="data:image/png;base64,")
    ]

    try:
        extractor = MagicMock()
        extractor.extract.side_effect = RuntimeError("BG case must NOT call extractor.extract()")
        extractor.extract_article_details.side_effect = RuntimeError(
            "BG case must skip detail extraction"
        )
        extractor._create_response.return_value = {
            "output_text": json.dumps(
                {
                    "message_id": "test_momax_bg_no_raw_fallback",
                    "received_at": "2026-02-13T12:00:00+00:00",
                    "header": {
                        "kundennummer": {"value": "20197304", "source": "pdf", "confidence": 0.99},
                        "kom_nr": {"value": "", "source": "pdf", "confidence": 0.0},
                        "kom_name": {"value": "TEST", "source": "pdf", "confidence": 0.9},
                        "liefertermin": {"value": "20.03.26", "source": "pdf", "confidence": 0.9},
                        "bestelldatum": {"value": "12.12.25", "source": "derived", "confidence": 0.9},
                        "store_name": {"value": "MOMAX BULGARIA - TEST", "source": "pdf", "confidence": 0.9},
                        "store_address": {"value": "Unknown Street 999, Unknown City", "source": "pdf", "confidence": 0.9},
                        "lieferanschrift": {"value": "Unknown Street 999, Unknown City", "source": "pdf", "confidence": 0.9},
                        "reply_needed": {"value": False, "source": "derived", "confidence": 1.0},
                        "human_review_needed": {"value": False, "source": "derived", "confidence": 1.0},
                        "post_case": {"value": False, "source": "derived", "confidence": 1.0},
                    },
                    "items": [
                        {
                            "line_no": 1,
                            "artikelnummer": {"value": "181", "source": "pdf", "confidence": 0.9},
                            "modellnummer": {"value": "SN/SN/71/SP/91", "source": "pdf", "confidence": 0.9},
                            "menge": {"value": 1, "source": "pdf", "confidence": 0.9},
                            "furncloud_id": {"value": "", "source": "derived", "confidence": 0.0},
                        }
                    ],
                    "status": "ok",
                    "warnings": [],
                    "errors": [],
                }
            )
        }

        result = pipeline.process_message(message, config, extractor)
        header = result.data.get("header") or {}
        assert header.get("kundennummer", {}).get("value") == ""
        assert header.get("kundennummer", {}).get("derived_from") == "excel_lookup_failed"
        print("SUCCESS: momax_bg does not fallback to raw PDF kundennummer when address lookup fails.")
    finally:
        pipeline._prepare_images = original_prepare_images


if __name__ == "__main__":
    test_momax_bg_two_pdf_special_case()
    test_momax_bg_allowlist_address_matching()
    test_momax_bg_allowlist_match_without_rapidfuzz()
    test_momax_bg_no_match_does_not_fallback_to_standard_lookup()
    test_momax_bg_single_pdf_detection()
    test_momax_bg_bestelldatum_fallback_from_pdf_suffix()
    test_non_bg_regression_calls_standard_extract()
    test_momax_bg_no_raw_kdnr_fallback_from_pdf()
