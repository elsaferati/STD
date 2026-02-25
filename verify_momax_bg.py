import json
from pathlib import Path
from unittest.mock import MagicMock

import fitz  # PyMuPDF

import lookup
import momax_bg
import pipeline
from config import Config
from email_ingest import Attachment, IngestedEmail
from normalize import (
    apply_momax_bg_strict_item_code_corrections,
    normalize_output,
)
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

    # Force at least one PDF image so extraction continues through PDF-related post-processing.
    original_prepare_images = pipeline._prepare_images
    pipeline._prepare_images = lambda attachments, config, warnings: [
        ImageInput(name="dummy_pdf_page.png", source="pdf", data_url="data:image/png;base64,")
    ]

    try:
        extractor = MagicMock()
        extractor.complete_text.return_value = json.dumps(
            {"branch_id": "momax_bg", "confidence": 1.0, "reason": "test"}
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
        extractor.extract_with_prompts.return_value = json.dumps(mock_llm_json)

        result = pipeline.process_message(message, config, extractor)
        header = result.data.get("header") or {}
        warnings = result.data.get("warnings") or []

        assert header.get("kundennummer", {}).get("value") == "68934"
        assert header.get("kundennummer", {}).get("source") == "derived"
        assert header.get("kundennummer", {}).get("derived_from") == "excel_lookup_momax_bg_address"
        assert header.get("kom_nr", {}).get("value") == "88801711"
        assert header.get("kom_name", {}).get("value") == ""
        assert header.get("kom_name", {}).get("source") == "derived"
        assert header.get("kom_name", {}).get("confidence") == 0.0
        assert header.get("kom_name", {}).get("derived_from") == "momax_bg_policy"
        assert header.get("reply_needed", {}).get("value") is False
        items = result.data.get("items") or []
        assert items[0].get("modellnummer", {}).get("value") == "SNSN71SP91"
        missing_header_warnings = [
            str(w) for w in warnings if str(w).startswith("Missing header fields:")
        ]
        assert all("kom_name" not in w for w in missing_header_warnings)

        extractor.extract_with_prompts.assert_called_once()

        print("SUCCESS: Mömax BG two-PDF special-case path used.")
    finally:
        pipeline._prepare_images = original_prepare_images


def test_momax_bg_excel_address_matching() -> None:
    varna = lookup.find_momax_bg_customer_by_address(
        "Varna, Blvd. Vladislav Varnenchik 277A",
        store_name="AIKO VARNA",
    )
    assert varna is not None
    assert varna["kundennummer"] == "68939"
    assert varna["tour"] == "D2"
    assert varna["adressnummer"] == "0"

    slivnitza = lookup.find_momax_bg_customer_by_address(
        "Slivnitza (Evropa) Blvd. 441\n1331 Sofia",
        store_name="AIKO SOFIA",
    )
    assert slivnitza is not None
    assert slivnitza["kundennummer"] == "68936"

    plovdiv = lookup.find_momax_bg_customer_by_address(
        "Asenovgradsko Shose Str.14\n4004 Plovdiv",
        store_name="AIKO PLOVDIV",
    )
    assert plovdiv is not None
    assert plovdiv["kundennummer"] == "68941"

    print("SUCCESS: momax_bg address matching uses Kunden_Bulgarien.xlsx rows.")


def test_momax_bg_typo_match_without_rapidfuzz() -> None:
    original_fuzz = lookup.fuzz
    try:
        lookup.fuzz = None
        varna = lookup.find_momax_bg_customer_by_address(
            "Varna, Blvd. Viadislav Varnenchik 277A",
            store_name="MOMAX BULGARIA VARNA",
        )
        assert varna is not None
        assert varna["kundennummer"] == "68934"
        assert varna["tour"] == "D2"
        assert varna["adressnummer"] == "0"
        print("SUCCESS: momax_bg address matching works even without rapidfuzz.")
    finally:
        lookup.fuzz = original_fuzz


def test_momax_bg_duplicate_address_disambiguation_by_store_name() -> None:
    momax = lookup.find_momax_bg_customer_by_address(
        "Asenovgradsko Shose Str.14\n4004 Plovdiv",
        store_name="MOMAX BULGARIA - PLOVDIV",
    )
    assert momax is not None
    assert momax["kundennummer"] == "68940"
    assert momax["tour"] == "D2"
    assert momax["adressnummer"] == "0"

    aiko = lookup.find_momax_bg_customer_by_address(
        "Asenovgradsko Shose Str.14\n4004 Plovdiv",
        store_name="AIKO PLOVDIV",
    )
    assert aiko is not None
    assert aiko["kundennummer"] == "68941"
    assert aiko["tour"] == "D2"
    assert aiko["adressnummer"] == "0"
    print("SUCCESS: momax_bg duplicate addresses are resolved by store_name brand intent.")


def test_momax_bg_ambiguous_store_name_uses_deterministic_tie_break() -> None:
    varna = lookup.find_momax_bg_customer_by_address(
        "Varna, Vladislav Varnechnik Blvd.277a\n9009 Varna",
        store_name="VARNA STORE",
    )
    assert varna is not None
    assert varna["kundennummer"] == "68934"
    assert varna["tour"] == "D2"
    assert varna["adressnummer"] == "0"
    print("SUCCESS: momax_bg ambiguous store_name uses deterministic fallback tie-break.")


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
    assert any("Kunden_Bulgarien.xlsx" in str(w) for w in all_warnings)
    print("SUCCESS: momax_bg no-match path does not fallback to standard lookup.")


def test_non_bg_regression_uses_single_extraction_path() -> None:
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
        extractor.complete_text.return_value = json.dumps(
            {"branch_id": "xxxlutz_default", "confidence": 1.0, "reason": "test"}
        )
        extractor._create_response.side_effect = RuntimeError("Non-BG must not use _create_response path")
        extractor.extract_with_prompts.return_value = json.dumps(
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

        pipeline.process_message(message, config, extractor)
        extractor.extract_with_prompts.assert_called()
        extractor._create_response.assert_not_called()
        print("SUCCESS: Non-BG case uses standard single extraction path.")
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


def test_aiko_bg_detection() -> None:
    pdf = _make_pdf_bytes(
        "Recipient: AIKO\n"
        "AIKO - ORDER\n"
        "VARNA - 88801739/29.10.25\n"
        "Term of delivery: 20.11.25\n"
        "Address: Varna, Blvd. Vladislav Varnenchik 277A\n"
    )
    att = Attachment(filename="aiko_single.pdf", content_type="application/pdf", data=pdf)
    assert momax_bg.is_momax_bg_two_pdf_case([att]) is True
    assert momax_bg.extract_momax_bg_kom_nr([att]) == "88801739"
    assert momax_bg.extract_momax_bg_order_date([att]) == "29.10.25"
    print("SUCCESS: AIKO BG detection activates the same special-case path.")


def test_aiko_bg_pipeline_special_case_and_kom_recovery() -> None:
    pdf_a = _make_pdf_bytes(
        "Recipient: AIKO BULGARIA\n"
        "IDENT No: 20197304\n"
        "ORDER\n"
        "No 1739/29.10.25\n"
        "Term of delivery: 20.11.25\n"
        "Store: VARNA\n"
        "Address: Varna, Blvd. Vladislav Varnenchik 277A\n"
    )
    pdf_b = _make_pdf_bytes(
        "AIKO - ORDER\n"
        "VARNA - 88801739/29.10.25\n"
        "Code/Type Quantity\n"
        "30156 OJOO 2\n"
    )
    message = IngestedEmail(
        message_id="test_aiko_bg_special",
        received_at="2026-02-13T12:00:00+00:00",
        subject="AIKO BG order",
        sender="bg@example.com",
        body_text="",
        attachments=[
            Attachment(filename="aiko_a.pdf", content_type="application/pdf", data=pdf_a),
            Attachment(filename="aiko_b.pdf", content_type="application/pdf", data=pdf_b),
        ],
    )
    config = Config.from_env()

    original_prepare_images = pipeline._prepare_images
    pipeline._prepare_images = lambda attachments, config, warnings: [
        ImageInput(name="dummy_pdf_page.png", source="pdf", data_url="data:image/png;base64,")
    ]

    try:
        extractor = MagicMock()
        extractor.complete_text.return_value = json.dumps(
            {"branch_id": "momax_bg", "confidence": 1.0, "reason": "test"}
        )
        extractor.extract_with_prompts.return_value = json.dumps(
            {
                "message_id": "test_aiko_bg_special",
                "received_at": "2026-02-13T12:00:00+00:00",
                "header": {
                    "kundennummer": {"value": "20197304", "source": "pdf", "confidence": 0.99},
                    "kom_nr": {"value": "", "source": "pdf", "confidence": 0.0},
                    "kom_name": {"value": "VARNA", "source": "pdf", "confidence": 0.9},
                    "liefertermin": {"value": "20.11.25", "source": "pdf", "confidence": 0.9},
                    "bestelldatum": {"value": "", "source": "pdf", "confidence": 0.0},
                    "store_name": {"value": "AIKO BULGARIA - VARNA", "source": "pdf", "confidence": 0.9},
                    "store_address": {"value": "Varna, Blvd. Vladislav Varnenchik 277A", "source": "pdf", "confidence": 0.9},
                    "lieferanschrift": {"value": "Varna, Blvd. Vladislav Varnenchik 277A", "source": "pdf", "confidence": 0.9},
                    "reply_needed": {"value": False, "source": "derived", "confidence": 1.0},
                    "human_review_needed": {"value": False, "source": "derived", "confidence": 1.0},
                    "post_case": {"value": False, "source": "derived", "confidence": 1.0},
                },
                "items": [
                    {
                        "line_no": 1,
                        "artikelnummer": {"value": "30156 OJOO", "source": "pdf", "confidence": 0.9},
                        "modellnummer": {"value": "", "source": "pdf", "confidence": 0.0},
                        "menge": {"value": 2, "source": "pdf", "confidence": 0.9},
                        "furncloud_id": {"value": "", "source": "derived", "confidence": 0.0},
                    }
                ],
                "status": "ok",
                "warnings": [],
                "errors": [],
            }
        )

        result = pipeline.process_message(message, config, extractor)
        header = result.data.get("header") or {}
        items = result.data.get("items") or []

        assert header.get("kundennummer", {}).get("value") == "68939"
        assert header.get("kundennummer", {}).get("derived_from") == "excel_lookup_momax_bg_address"
        assert header.get("kom_nr", {}).get("value") == "88801739"
        assert header.get("bestelldatum", {}).get("value") == "29.10.25"
        assert header.get("bestelldatum", {}).get("derived_from") == "pdf_order_suffix"
        assert items[0].get("artikelnummer", {}).get("value") == "30156"
        assert items[0].get("modellnummer", {}).get("value") == "OJOO"

        extractor.extract_with_prompts.assert_called_once()
        print("SUCCESS: AIKO BG case uses special path with kom/date recovery and item split.")
    finally:
        pipeline._prepare_images = original_prepare_images


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
        extractor.complete_text.return_value = json.dumps(
            {"branch_id": "momax_bg", "confidence": 1.0, "reason": "test"}
        )
        extractor.extract_with_prompts.return_value = json.dumps(
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

        result = pipeline.process_message(message, config, extractor)
        header = result.data.get("header") or {}
        assert header.get("kom_nr", {}).get("value") == "88801711"
        assert header.get("bestelldatum", {}).get("value") == "12.12.25"
        assert header.get("bestelldatum", {}).get("derived_from") == "pdf_order_suffix"
        print("SUCCESS: momax_bg derives bestelldatum from PDF order suffix when missing.")
    finally:
        pipeline._prepare_images = original_prepare_images


def test_momax_bg_modellnummer_compaction() -> None:
    data = {
        "header": {
            "store_address": {"value": "Varna, Blvd. Vladislav Varnenchik 277A", "source": "pdf", "confidence": 0.95},
            "lieferanschrift": {"value": "Varna, Blvd. Vladislav Varnenchik 277A", "source": "pdf", "confidence": 0.95},
            "reply_needed": {"value": False, "source": "derived", "confidence": 1.0},
            "human_review_needed": {"value": False, "source": "derived", "confidence": 1.0},
            "post_case": {"value": False, "source": "derived", "confidence": 1.0},
        },
        "items": [
            {
                "line_no": 1,
                "artikelnummer": {"value": "22448", "source": "pdf", "confidence": 0.9},
                "modellnummer": {"value": "SN/SN/61/91", "source": "pdf", "confidence": 0.9},
                "menge": {"value": 1, "source": "pdf", "confidence": 0.9},
                "furncloud_id": {"value": "", "source": "derived", "confidence": 0.0},
            },
            {
                "line_no": 2,
                "artikelnummer": {"value": "18100", "source": "pdf", "confidence": 0.9},
                "modellnummer": {"value": "SN/SN/71/SP/91", "source": "pdf", "confidence": 0.9},
                "menge": {"value": 1, "source": "pdf", "confidence": 0.9},
                "furncloud_id": {"value": "", "source": "derived", "confidence": 0.0},
            },
        ],
    }
    normalized = normalize_output(
        data,
        message_id="test_momax_bg_modell_compact",
        received_at="2026-02-13T12:00:00+00:00",
        dayfirst=True,
        warnings=[],
        email_body="",
        sender="bg@example.com",
        is_momax_bg=True,
    )
    items = normalized.get("items") or []
    assert items[0].get("modellnummer", {}).get("value") == "SNSN6191"
    assert items[1].get("modellnummer", {}).get("value") == "SNSN71SP91"
    print("SUCCESS: momax_bg compacts modellnummer by removing slash separators.")


def test_aiko_bg_item_whitespace_pair_normalization() -> None:
    data = {
        "header": {
            "store_name": {"value": "AIKO BULGARIA - VARNA", "source": "pdf", "confidence": 0.95},
            "store_address": {"value": "Varna, Blvd. Vladislav Varnenchik 277A", "source": "pdf", "confidence": 0.95},
            "lieferanschrift": {"value": "Varna, Blvd. Vladislav Varnenchik 277A", "source": "pdf", "confidence": 0.95},
            "reply_needed": {"value": False, "source": "derived", "confidence": 1.0},
            "human_review_needed": {"value": False, "source": "derived", "confidence": 1.0},
            "post_case": {"value": False, "source": "derived", "confidence": 1.0},
        },
        "items": [
            {
                "line_no": 1,
                "artikelnummer": {"value": "30156 OJOO", "source": "pdf", "confidence": 0.9},
                "modellnummer": {"value": "", "source": "pdf", "confidence": 0.0},
                "menge": {"value": 1, "source": "pdf", "confidence": 0.9},
                "furncloud_id": {"value": "", "source": "derived", "confidence": 0.0},
            },
        ],
    }
    normalized = normalize_output(
        data,
        message_id="test_aiko_whitespace_split",
        received_at="2026-02-13T12:00:00+00:00",
        dayfirst=True,
        warnings=[],
        email_body="",
        sender="bg@example.com",
        is_momax_bg=True,
    )
    items = normalized.get("items") or []
    assert items[0].get("artikelnummer", {}).get("value") == "30156"
    assert items[0].get("modellnummer", {}).get("value") == "OJOO"
    print("SUCCESS: AIKO BG whitespace pair Code/Type is split into article/model.")


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
        extractor.complete_text.return_value = json.dumps(
            {"branch_id": "momax_bg", "confidence": 1.0, "reason": "test"}
        )
        extractor.extract_with_prompts.return_value = json.dumps(
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

        result = pipeline.process_message(message, config, extractor)
        header = result.data.get("header") or {}
        assert header.get("kundennummer", {}).get("value") == ""
        assert header.get("kundennummer", {}).get("derived_from") == "excel_lookup_failed"
        print("SUCCESS: momax_bg does not fallback to raw PDF kundennummer when address lookup fails.")
    finally:
        pipeline._prepare_images = original_prepare_images


def test_momax_bg_wrapped_article_map_extracts_suffix() -> None:
    pdf = _make_pdf_bytes(
        "MOMAX - ORDER\n"
        "Code/Type Quantity\n"
        "SN/SN/71/SP/91/180 98 1\n"
    )
    att = Attachment(filename="spec.pdf", content_type="application/pdf", data=pdf)
    mapping = momax_bg.extract_momax_bg_wrapped_article_map([att])
    assert mapping.get("180") == "18098"
    print("SUCCESS: momax_bg wrapped Code/Type map extracts article suffix.")


def test_momax_bg_pipeline_corrects_wrapped_article_suffix() -> None:
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
        "SN/SN/71/SP/91/180 98 1\n"
    )
    message = IngestedEmail(
        message_id="test_momax_bg_wrapped_article",
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
    pipeline._prepare_images = lambda attachments, config, warnings: ([], {})

    try:
        extractor = MagicMock()
        extractor.complete_text.return_value = json.dumps(
            {"branch_id": "momax_bg", "confidence": 1.0, "reason": "test"}
        )
        extractor.extract_with_prompts.return_value = json.dumps(
            {
                "message_id": "test_momax_bg_wrapped_article",
                "received_at": "2026-02-13T12:00:00+00:00",
                "header": {
                    "kundennummer": {"value": "20197304", "source": "pdf", "confidence": 0.99},
                    "kom_nr": {"value": "88801711", "source": "pdf", "confidence": 0.99},
                    "kom_name": {"value": "VARNA", "source": "pdf", "confidence": 0.9},
                    "liefertermin": {"value": "20.03.26", "source": "pdf", "confidence": 0.9},
                    "bestelldatum": {"value": "12.12.25", "source": "derived", "confidence": 0.9},
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
                        "artikelnummer": {"value": "180", "source": "pdf", "confidence": 0.9},
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

        result = pipeline.process_message(message, config, extractor)
        items = result.data.get("items") or []
        warnings = result.data.get("warnings") or []
        assert items[0].get("artikelnummer", {}).get("value") == "18098"
        assert (
            items[0].get("artikelnummer", {}).get("derived_from")
            == "momax_bg_pdf_wrapped_article_correction"
        )
        assert any("wrapped Code/Type correction" in str(w) for w in warnings)
        print("SUCCESS: momax_bg pipeline corrects wrapped article suffix from PDF text.")
    finally:
        pipeline._prepare_images = original_prepare_images


def _momax_bg_item_data(artikel: str, modell: str) -> dict:
    return {
        "header": {
            "store_name": {"value": "MOMAX BULGARIA - VARNA", "source": "pdf", "confidence": 0.95},
            "store_address": {"value": "Varna, Blvd. Vladislav Varnenchik 277A", "source": "pdf", "confidence": 0.95},
            "lieferanschrift": {"value": "Varna, Blvd. Vladislav Varnenchik 277A", "source": "pdf", "confidence": 0.95},
            "reply_needed": {"value": False, "source": "derived", "confidence": 1.0},
            "human_review_needed": {"value": False, "source": "derived", "confidence": 1.0},
            "post_case": {"value": False, "source": "derived", "confidence": 1.0},
            "kom_name": {"value": "", "source": "derived", "confidence": 0.0, "derived_from": "momax_bg_policy"},
        },
        "items": [
            {
                "line_no": 1,
                "artikelnummer": {"value": artikel, "source": "pdf", "confidence": 0.95},
                "modellnummer": {"value": modell, "source": "pdf", "confidence": 0.95},
                "menge": {"value": 1, "source": "pdf", "confidence": 0.95},
                "furncloud_id": {"value": "", "source": "derived", "confidence": 0.0},
            }
        ],
    }


def test_momax_bg_strict_code_ticket_regressions() -> None:
    cases = [
        ("74430XB", "CQ9191", "74430", "CQ9191XB"),
        ("CQ1616", "42821KXB", "42821K", "CQ1616XB"),
        ("CQ9191", "74405XB", "74405", "CQ9191XB"),
        ("XP", "CQ222206363", "06363", "CQ2222XP"),
        ("91", "60812XPCQSN", "60812", "CQSN91XP"),
        ("", "BEAN41343665372", "65372", "BEAN413436"),
    ]
    for artikel_in, modell_in, artikel_out, modell_out in cases:
        normalized = normalize_output(
            _momax_bg_item_data(artikel_in, modell_in),
            message_id=f"strict_{artikel_in}_{modell_in}",
            received_at="2026-02-13T12:00:00+00:00",
            dayfirst=True,
            warnings=[],
            email_body="",
            sender="bg@example.com",
            is_momax_bg=True,
        )
        item = (normalized.get("items") or [{}])[0]
        artikel_entry = item.get("artikelnummer", {})
        modell_entry = item.get("modellnummer", {})
        assert artikel_entry.get("value") == artikel_out
        assert modell_entry.get("value") == modell_out
        assert artikel_entry.get("derived_from") in {
            "momax_bg_strict_code_parser",
            "momax_bg_suffix_relocation",
        }
        assert modell_entry.get("derived_from") in {
            "momax_bg_strict_code_parser",
            "momax_bg_suffix_relocation",
        }
    print("SUCCESS: momax_bg strict rules fix six known ticket patterns.")


def test_momax_bg_strict_slash_reorder_policy() -> None:
    data = _momax_bg_item_data("91", "60812/XP/CQSN")
    corrected = apply_momax_bg_strict_item_code_corrections(data)
    item = (data.get("items") or [{}])[0]
    assert corrected == 1
    assert item.get("artikelnummer", {}).get("value") == "60812"
    assert item.get("modellnummer", {}).get("value") == "CQSN91XP"

    data_alt = _momax_bg_item_data("60812", "XP/CQSN/91")
    corrected_alt = apply_momax_bg_strict_item_code_corrections(data_alt)
    item_alt = (data_alt.get("items") or [{}])[0]
    assert corrected_alt == 1
    assert item_alt.get("artikelnummer", {}).get("value") == "60812"
    assert item_alt.get("modellnummer", {}).get("value") == "CQSN91XP"
    print("SUCCESS: momax_bg strict slash reorder policy is applied.")


def test_momax_bg_strict_leading_zero_preserved() -> None:
    data = _momax_bg_item_data("XP", "CQ222206363")
    corrected = apply_momax_bg_strict_item_code_corrections(data)
    item = (data.get("items") or [{}])[0]
    assert corrected == 1
    assert item.get("artikelnummer", {}).get("value") == "06363"
    assert item.get("modellnummer", {}).get("value") == "CQ2222XP"
    print("SUCCESS: momax_bg strict correction preserves leading-zero artikelnummer.")


def test_momax_bg_wrapped_article_merge_still_passes() -> None:
    normalized = normalize_output(
        _momax_bg_item_data("180 98", "SN/SN/71/SP/91"),
        message_id="strict_wrapped_article",
        received_at="2026-02-13T12:00:00+00:00",
        dayfirst=True,
        warnings=[],
        email_body="",
        sender="bg@example.com",
        is_momax_bg=True,
    )
    item = (normalized.get("items") or [{}])[0]
    assert item.get("artikelnummer", {}).get("value") == "18098"
    assert item.get("modellnummer", {}).get("value") == "SNSN71SP91"
    print("SUCCESS: momax_bg wrapped article merge still works with strict parser.")


def test_momax_bg_slash_split_tail_digits_merge_to_strict_article() -> None:
    normalized = normalize_output(
        _momax_bg_item_data("", "BE/AN//41/34/36/653 72"),
        message_id="strict_slash_tail_digits",
        received_at="2026-02-13T12:00:00+00:00",
        dayfirst=True,
        warnings=[],
        email_body="",
        sender="bg@example.com",
        is_momax_bg=True,
    )
    item = (normalized.get("items") or [{}])[0]
    assert item.get("artikelnummer", {}).get("value") == "65372"
    assert item.get("modellnummer", {}).get("value") == "BEAN413436"
    print("SUCCESS: momax_bg slash token split tail digits are merged into strict article.")


def test_momax_bg_pipeline_strict_after_verifier_conflict() -> None:
    pdf_a = _make_pdf_bytes(
        "Recipient: MOMAX BULGARIA\n"
        "IDENT No: 20197304\n"
        "ORDER\n"
        "No 1823/20.12.25\n"
        "Term for delivery: 24.03.26\n"
        "Store: VARNA\n"
        "Address: Varna, Blvd. Vladislav Varnenchik 277A\n"
    )
    pdf_b = _make_pdf_bytes(
        "MOMAX - ORDER\n"
        "VARNA - 88801823/20.12.25\n"
        "Code/Type Quantity\n"
        "60812/XP/CQSN/91 1\n"
    )
    message = IngestedEmail(
        message_id="test_momax_bg_verifier_conflict",
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
    pipeline._prepare_images = lambda attachments, config, warnings: (
        [ImageInput(name="dummy_pdf_page.png", source="pdf", data_url="data:image/png;base64,")],
        {"dummy_pdf_page.png": "Code/Type Quantity\n60812/XP/CQSN/91 1"},
    )

    try:
        extractor = MagicMock()
        extractor.complete_text.return_value = json.dumps(
            {"branch_id": "momax_bg", "confidence": 1.0, "reason": "test"}
        )
        extractor.extract_with_prompts.return_value = json.dumps(
            {
                "message_id": "test_momax_bg_verifier_conflict",
                "received_at": "2026-02-13T12:00:00+00:00",
                "header": {
                    "kundennummer": {"value": "20197304", "source": "pdf", "confidence": 0.99},
                    "kom_nr": {"value": "88801823", "source": "pdf", "confidence": 0.99},
                    "kom_name": {"value": "VARNA", "source": "pdf", "confidence": 0.9},
                    "liefertermin": {"value": "24.03.26", "source": "pdf", "confidence": 0.9},
                    "bestelldatum": {"value": "20.12.25", "source": "pdf", "confidence": 0.9},
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
                        "artikelnummer": {"value": "60812", "source": "pdf", "confidence": 0.95},
                        "modellnummer": {"value": "CQSN91XP", "source": "pdf", "confidence": 0.95},
                        "menge": {"value": 1, "source": "pdf", "confidence": 0.95},
                        "furncloud_id": {"value": "", "source": "derived", "confidence": 0.0},
                    }
                ],
                "status": "ok",
                "warnings": [],
                "errors": [],
            }
        )
        extractor.verify_items_from_text.return_value = json.dumps(
            {
                "verified_items": [
                    {
                        "line_no": 1,
                        "modellnummer": "60812XPCQSN",
                        "artikelnummer": "91",
                        "confidence": 0.99,
                        "reason": "conflicting test payload",
                    }
                ],
                "warnings": [],
            }
        )

        result = pipeline.process_message(message, config, extractor)
        extractor.verify_items_from_text.assert_not_called()
        item = (result.data.get("items") or [{}])[0]
        assert item.get("artikelnummer", {}).get("value") == "60812"
        assert item.get("modellnummer", {}).get("value") == "CQSN91XP"
        assert result.data.get("header", {}).get("human_review_needed", {}).get("value") is False
        print("SUCCESS: momax_bg pipeline skips text-only verifier and keeps strict parsing result.")
    finally:
        pipeline._prepare_images = original_prepare_images


if __name__ == "__main__":
    test_momax_bg_two_pdf_special_case()
    test_momax_bg_excel_address_matching()
    test_momax_bg_typo_match_without_rapidfuzz()
    test_momax_bg_duplicate_address_disambiguation_by_store_name()
    test_momax_bg_ambiguous_store_name_uses_deterministic_tie_break()
    test_momax_bg_no_match_does_not_fallback_to_standard_lookup()
    test_momax_bg_single_pdf_detection()
    test_aiko_bg_detection()
    test_aiko_bg_pipeline_special_case_and_kom_recovery()
    test_momax_bg_bestelldatum_fallback_from_pdf_suffix()
    test_momax_bg_modellnummer_compaction()
    test_aiko_bg_item_whitespace_pair_normalization()
    test_non_bg_regression_uses_single_extraction_path()
    test_momax_bg_no_raw_kdnr_fallback_from_pdf()
    test_momax_bg_wrapped_article_map_extracts_suffix()
    test_momax_bg_pipeline_corrects_wrapped_article_suffix()
    test_momax_bg_strict_code_ticket_regressions()
    test_momax_bg_strict_slash_reorder_policy()
    test_momax_bg_strict_leading_zero_preserved()
    test_momax_bg_wrapped_article_merge_still_passes()
    test_momax_bg_slash_split_tail_digits_merge_to_strict_article()
    test_momax_bg_pipeline_strict_after_verifier_conflict()
