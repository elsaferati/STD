import json
from pathlib import Path
from unittest.mock import MagicMock
import sys
import types
from datetime import datetime

try:
    import fitz  # noqa: F401
except ModuleNotFoundError:
    fitz_stub = types.ModuleType("fitz")

    def _missing_fitz(*args, **kwargs):
        raise ModuleNotFoundError("PyMuPDF (fitz) is required for PDF text helpers.")

    fitz_stub.open = _missing_fitz
    sys.modules["fitz"] = fitz_stub

try:
    from PIL import Image  # noqa: F401
except ModuleNotFoundError:
    pil_stub = types.ModuleType("PIL")

    class _ImageStub:
        @staticmethod
        def open(*args, **kwargs):
            raise ModuleNotFoundError("Pillow (PIL) is required for image helpers.")

    pil_stub.Image = _ImageStub
    sys.modules["PIL"] = pil_stub

try:
    from openai import OpenAI  # noqa: F401
except ModuleNotFoundError:
    openai_stub = types.ModuleType("openai")

    class _OpenAIStub:
        def __init__(self, *args, **kwargs):
            raise ModuleNotFoundError("openai package is required for live API calls.")

    openai_stub.OpenAI = _OpenAIStub
    sys.modules["openai"] = openai_stub

try:
    from dateutil.parser import parse as _dateutil_parse  # noqa: F401
except ModuleNotFoundError:
    dateutil_stub = types.ModuleType("dateutil")
    parser_stub = types.ModuleType("dateutil.parser")

    class _ParserError(Exception):
        pass

    def _parse_stub(value, *args, **kwargs):
        text = str(value or "").strip()
        if not text:
            raise _ParserError("empty date")
        return datetime.now()

    parser_stub.parse = _parse_stub
    parser_stub.ParserError = _ParserError
    dateutil_stub.parser = parser_stub
    sys.modules["dateutil"] = dateutil_stub
    sys.modules["dateutil.parser"] = parser_stub

import pipeline
import prompts_porta
import prompts_verify_items
from config import Config
from email_ingest import IngestedEmail
from openai_extract import ImageInput


def _item(line_no: int, modell: str, artikel: str, menge: int = 1) -> dict:
    return {
        "line_no": line_no,
        "modellnummer": {"value": modell, "source": "pdf", "confidence": 1.0},
        "artikelnummer": {"value": artikel, "source": "pdf", "confidence": 1.0},
        "menge": {"value": menge, "source": "pdf", "confidence": 1.0},
        "furncloud_id": {"value": "", "source": "derived", "confidence": 0.0},
    }


def _config() -> Config:
    config = Config.from_env()
    config.output_dir = Path("./tmp_porta_bestehend_cleanup")
    config.output_dir.mkdir(exist_ok=True)
    return config


def _message() -> IngestedEmail:
    return IngestedEmail(
        message_id="porta_bestehend_cleanup",
        received_at="2026-02-25T10:00:00+00:00",
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


def _component_block_text(parent_artikel_nr: str = "4611217 / 83") -> str:
    return (
        f"1 {parent_artikel_nr} Liefermodell: Sinfonie Plus CQEG5899 76953G\n"
        "Nachtkonsole\n"
        "bestehend aus je:\n"
        "1 Stk Liefermodell: Sinfonie Plus CQEG5899 76953G\n"
        "CQEG5899 76953G Nachtkonsole\n"
        "ca. 58x50x40 cm\n"
        "1 Stk Liefermodell: Sinfonie Plus CQEG5899 76953G\n"
        "CQEG00 09387 Glasplatte\n"
        "ca. 58x3x40cm\n"
    )


def _component_block_text_qty_split_lines(parent_artikel_nr: str = "4611217 / 83") -> str:
    return (
        f"1 {parent_artikel_nr} Liefermodell: Sinfonie Plus CQEG5899 76953G\n"
        "Nachtkonsole\n"
        "bestehend aus je:\n"
        "Liefermodell: Sinfonie Plus CQEG5899 76953G\n"
        "CQEG5899 76953G Nachtkonsole\n"
        "ca. 58x50x40 cm\n"
        "1\n"
        "Stk\n"
        "Liefermodell: Sinfonie Plus CQEG5899 76953G\n"
        "CQEG00 09387 Glasplatte\n"
        "ca. 58x3x40cm\n"
        "1\n"
        "Stk\n"
    )


def _component_block_text_with_legal_footer(parent_artikel_nr: str = "4611217 / 83") -> str:
    return (
        _component_block_text(parent_artikel_nr)
        + "FuG Handelsgesellschaft West mbH & Co. KG\n"
        + "Amtsgericht Bad Oeynhausen HRB 9684\n"
        + "Geschaeftsfuehrer: Stephan Hermes\n"
        + "USt-IdNr. DE 121 865 890\n"
    )


def _component_block_text_partial_second_page(parent_artikel_nr: str = "4611217 / 83") -> str:
    return (
        f"1 {parent_artikel_nr} Liefermodell: Sinfonie Plus CQEG5899 76953G\n"
        "Nachtkonsole\n"
        "bestehend aus je:\n"
        "1 Stk Liefermodell: Sinfonie Plus CQEG5899 76953G CQEG00 09387 Glasplatte\n"
        "ca. 58x3x40cm\n"
    )


def _component_block_text_other_parent(parent_artikel_nr: str = "4611217 / 84") -> str:
    return (
        f"1 {parent_artikel_nr} Liefermodell: Sinfonie Plus CQEG5899 76808G\n"
        "XL Kommode\n"
        "bestehend aus je:\n"
        "1 Stk Liefermodell: Sinfonie Plus CQEG5899 76808G CQEG00 71811 Glasplatte\n"
        "ca. 160x3x40cm\n"
    )


def _run_pipeline_with_items(branch_id: str, items: list[dict], page_text_map: dict[str, str]) -> dict:
    extractor = MagicMock()
    extractor.complete_text.return_value = json.dumps(
        {"branch_id": branch_id, "confidence": 1.0, "reason": "test"}
    )
    extractor.extract_with_prompts.return_value = _extraction_payload(items)
    extractor.verify_items_from_text.return_value = json.dumps(
        {"verified_items": [], "warnings": []}
    )

    original_prepare_images = pipeline._prepare_images
    pipeline._prepare_images = lambda attachments, config, warnings: (
        [ImageInput(name=name, source="pdf", data_url="data:image/png;base64,") for name in page_text_map.keys()],
        page_text_map,
    )
    try:
        result = pipeline.process_message(_message(), _config(), extractor)
        return result.data
    finally:
        pipeline._prepare_images = original_prepare_images


def test_cross_page_repeated_block_is_counted_again() -> None:
    normalized = {
        "header": {"human_review_needed": {"value": False, "source": "derived", "confidence": 1.0}},
        "items": [
            _item(1, "CQSD58", "77171"),
            _item(2, "CQEG5899", "76808G"),
            _item(3, "CQEG00", "71811"),
            _item(4, "CQEG5899", "76953G"),
            _item(5, "CQEG00", "09387"),
        ],
        "warnings": [],
    }
    page_texts = {
        "order-1.png": _component_block_text("4611217 / 83"),
        "order-2.png": _component_block_text("4611217 / 83"),
    }

    added = pipeline._reconcile_porta_component_occurrences(  # type: ignore[attr-defined]
        normalized,
        page_texts,
    )
    assert added == 2
    items = normalized.get("items") or []
    assert len(items) == 7
    articles = [item.get("artikelnummer", {}).get("value") for item in items]
    assert articles.count("76953G") == 2
    assert articles.count("09387") == 2
    print("SUCCESS: cross-page repeated component block is counted again.")


def test_identical_artikel_nr_and_parent_still_count_as_new_occurrence() -> None:
    page_texts = {
        "order-1.png": _component_block_text("4611217 / 83"),
        "order-2.png": _component_block_text("4611217 / 83"),
    }
    extracted = pipeline._extract_porta_component_occurrences_from_page_texts(  # type: ignore[attr-defined]
        page_texts
    )
    assert len(extracted) == 4
    keys = [
        (
            item.get("modellnummer"),
            item.get("artikelnummer"),
            str(item.get("menge")),
        )
        for item in extracted
    ]
    assert keys.count(("CQEG5899", "76953G", "1")) == 2
    assert keys.count(("CQEG00", "09387", "1")) == 2
    print("SUCCESS: identical parent/Artikel-Nr. still yields new component occurrences.")


def test_qty_marker_split_across_lines_is_extracted() -> None:
    page_texts = {
        "order-1.png": _component_block_text_qty_split_lines("4611217 / 83"),
    }
    extracted = pipeline._extract_porta_component_occurrences_from_page_texts(  # type: ignore[attr-defined]
        page_texts
    )
    assert len(extracted) == 2
    keys = [
        (
            item.get("modellnummer"),
            item.get("artikelnummer"),
            str(item.get("menge")),
        )
        for item in extracted
    ]
    assert keys.count(("CQEG5899", "76953G", "1")) == 1
    assert keys.count(("CQEG00", "09387", "1")) == 1
    print("SUCCESS: split-line qty marker ('1' + 'Stk') is extracted as explicit component rows.")


def test_cross_page_repeated_split_qty_block_is_counted_again() -> None:
    normalized = {
        "header": {"human_review_needed": {"value": False, "source": "derived", "confidence": 1.0}},
        "items": [
            _item(1, "CQSD58", "77171"),
            _item(2, "CQEG5899", "76808G"),
            _item(3, "CQEG00", "71811"),
            _item(4, "CQEG5899", "76953G"),
            _item(5, "CQEG00", "09387"),
        ],
        "warnings": [],
    }
    page_texts = {
        "order-1.png": _component_block_text_qty_split_lines("4611217 / 83"),
        "order-2.png": _component_block_text_qty_split_lines("4611217 / 83"),
    }

    added = pipeline._reconcile_porta_component_occurrences(  # type: ignore[attr-defined]
        normalized,
        page_texts,
    )
    assert added == 2
    items = normalized.get("items") or []
    assert len(items) == 7
    keys = [
        (
            (item.get("modellnummer") or {}).get("value"),
            (item.get("artikelnummer") or {}).get("value"),
        )
        for item in items
        if isinstance(item, dict)
    ]
    assert keys.count(("CQEG5899", "76953G")) == 2
    assert keys.count(("CQEG00", "09387")) == 2
    print("SUCCESS: repeated split-line qty blocks across pages are counted as new occurrences.")


def test_repeated_block_with_partial_second_page_is_backfilled() -> None:
    normalized = {
        "header": {"human_review_needed": {"value": False, "source": "derived", "confidence": 1.0}},
        "items": [
            _item(1, "CQSD58", "77171"),
            _item(2, "CQEG5899", "76808G"),
            _item(3, "CQEG00", "71811"),
            _item(4, "CQEG5899", "76953G"),
            _item(5, "CQEG00", "09387"),
        ],
        "warnings": [],
    }
    page_texts = {
        "order-1.png": _component_block_text("4611217 / 83"),
        "order-2.png": _component_block_text_partial_second_page("4611217 / 83"),
    }

    added = pipeline._reconcile_porta_component_occurrences(  # type: ignore[attr-defined]
        normalized,
        page_texts,
    )
    assert added == 2
    items = normalized.get("items") or []
    assert len(items) == 7
    keys = [
        (
            (item.get("modellnummer") or {}).get("value"),
            (item.get("artikelnummer") or {}).get("value"),
        )
        for item in items
        if isinstance(item, dict)
    ]
    assert keys.count(("CQEG5899", "76953G")) == 2
    assert keys.count(("CQEG00", "09387")) == 2
    warnings = normalized.get("warnings") or []
    assert any("backfilled missing component" in str(w).lower() for w in warnings)
    print("SUCCESS: partial second-page block backfilled missing component occurrence.")


def test_legal_footer_pair_is_not_extracted() -> None:
    page_texts = {
        "order-1.png": _component_block_text_with_legal_footer("4611217 / 83"),
    }
    extracted = pipeline._extract_porta_component_occurrences_from_page_texts(  # type: ignore[attr-defined]
        page_texts
    )
    assert len(extracted) == 2
    keys = [
        (
            item.get("modellnummer"),
            item.get("artikelnummer"),
            str(item.get("menge")),
        )
        for item in extracted
    ]
    assert ("HRB", "9684", "1") not in keys
    assert keys.count(("CQEG5899", "76953G", "1")) == 1
    assert keys.count(("CQEG00", "09387", "1")) == 1
    print("SUCCESS: legal/footer pair (HRB 9684) is not extracted as component.")


def test_no_overinsert_when_occurrences_already_complete() -> None:
    normalized = {
        "header": {"human_review_needed": {"value": False, "source": "derived", "confidence": 1.0}},
        "items": [
            _item(1, "CQSD58", "77171"),
            _item(2, "CQEG5899", "76808G"),
            _item(3, "CQEG00", "71811"),
            _item(4, "CQEG5899", "76953G"),
            _item(5, "CQEG00", "09387"),
            _item(6, "CQEG5899", "76953G"),
            _item(7, "CQEG00", "09387"),
        ],
        "warnings": [],
    }
    page_texts = {
        "order-1.png": _component_block_text("4611217 / 83"),
        "order-2.png": _component_block_text("4611217 / 83"),
    }

    added = pipeline._reconcile_porta_component_occurrences(  # type: ignore[attr-defined]
        normalized,
        page_texts,
    )
    assert added == 0
    assert len(normalized.get("items") or []) == 7
    print("SUCCESS: no over-insert when occurrences are already complete.")


def test_reconciliation_does_not_insert_legal_footer_row() -> None:
    normalized = {
        "header": {"human_review_needed": {"value": False, "source": "derived", "confidence": 1.0}},
        "items": [
            _item(1, "CQSD58", "77171"),
            _item(2, "CQEG5899", "76808G"),
            _item(3, "CQEG00", "71811"),
            _item(4, "CQEG5899", "76953G"),
            _item(5, "CQEG00", "09387"),
            _item(6, "CQEG5899", "76953G"),
            _item(7, "CQEG00", "09387"),
        ],
        "warnings": [],
    }
    page_texts = {
        "order-1.png": _component_block_text_with_legal_footer("4611217 / 83"),
        "order-2.png": _component_block_text_with_legal_footer("4611217 / 83"),
    }
    added = pipeline._reconcile_porta_component_occurrences(  # type: ignore[attr-defined]
        normalized,
        page_texts,
    )
    assert added == 0
    items = normalized.get("items") or []
    assert len(items) == 7
    assert not any(
        (item.get("modellnummer", {}).get("value") == "HRB" and item.get("artikelnummer", {}).get("value") == "9684")
        for item in items
        if isinstance(item, dict)
    )
    print("SUCCESS: reconciliation does not insert legal/footer false-positive row.")


def test_no_backfill_without_parent_signature_match() -> None:
    normalized = {
        "header": {"human_review_needed": {"value": False, "source": "derived", "confidence": 1.0}},
        "items": [
            _item(1, "CQEG5899", "76953G"),
            _item(2, "CQEG00", "09387"),
        ],
        "warnings": [],
    }
    page_texts = {
        "order-1.png": _component_block_text("4611217 / 83"),
        "order-2.png": _component_block_text_other_parent("4611217 / 84"),
    }
    added = pipeline._reconcile_porta_component_occurrences(  # type: ignore[attr-defined]
        normalized,
        page_texts,
    )
    # Only explicit missing item should be inserted; no backfill from unrelated parent signature.
    assert added == 1
    items = normalized.get("items") or []
    assert len(items) == 3
    keys = [
        (
            (item.get("modellnummer") or {}).get("value"),
            (item.get("artikelnummer") or {}).get("value"),
        )
        for item in items
        if isinstance(item, dict)
    ]
    assert keys.count(("CQEG00", "71811")) == 1
    assert keys.count(("CQEG5899", "76953G")) == 1
    assert keys.count(("CQEG00", "09387")) == 1
    print("SUCCESS: no backfill is applied when parent signatures differ.")


def test_non_porta_branch_no_reconciliation() -> None:
    page_texts = {
        "order-1.png": _component_block_text("4611217 / 83"),
        "order-2.png": _component_block_text("4611217 / 83"),
    }
    data = _run_pipeline_with_items(
        branch_id="xxxlutz_default",
        items=[
            _item(1, "CQSD58", "77171"),
            _item(2, "CQEG5899", "76808G"),
            _item(3, "CQEG00", "71811"),
            _item(4, "CQEG5899", "76953G"),
            _item(5, "CQEG00", "09387"),
        ],
        page_text_map=page_texts,
    )
    assert len(data.get("items") or []) == 5
    print("SUCCESS: reconciliation is scoped to Porta branch only.")


def test_extract_porta_store_name_prefers_full_legal_line() -> None:
    page_texts = {
        "order-1.png": (
            "Verkaufshaus:\n"
            "Porta Moebel Frechen\n"
            "Porta Moebel Handels GmbH & Co. KG Frechen\n"
            "Europaallee 1\n"
            "50226 Frechen\n"
        )
    }
    got = pipeline._extract_porta_store_name_from_pdf_texts(  # type: ignore[attr-defined]
        page_texts
    )
    assert got == "Porta Moebel Handels GmbH & Co. KG Frechen"
    print("SUCCESS: Porta store_name extraction prefers full legal Verkaufshaus line.")


def test_prompt_contract_mentions_cross_page_no_dedupe() -> None:
    porta_prompt = prompts_porta.build_user_instructions_porta(["pdf", "email", "image"])
    verify_prompt = prompts_verify_items.build_verify_items_instructions("porta")

    assert "Do NOT deduplicate identical component pairs across different pages." in porta_prompt
    assert "A repeated occurrence on another page is a NEW item occurrence and must be output again." in porta_prompt
    assert "Repeated PDF table 'Artikel-Nr.' values do not suppress item creation." in porta_prompt
    assert "Use the FULL legal company/branch string exactly as shown" in porta_prompt
    assert "Do NOT shorten to city-only branch labels" in porta_prompt
    assert "Repeated identical component rows across pages are valid and must stay repeated." in verify_prompt
    assert "Do not semantically collapse rows just because modellnummer/artikelnummer are identical." in verify_prompt
    assert "OJ00 31681 -> modellnummer='OJ00', artikelnummer='31681'" in porta_prompt
    assert "OJ00 31681 -> modellnummer='OJ00', artikelnummer='31681'" in verify_prompt
    print("SUCCESS: prompt contract explicitly enforces cross-page no-dedupe behavior.")


def test_porta_oj_accessory_article_backfill_from_space_separated_pair() -> None:
    normalized = {
        "header": {"human_review_needed": {"value": False, "source": "derived", "confidence": 1.0}},
        "items": [
            _item(1, "CQEG4112G5", "85951K"),
            _item(2, "OJ00", ""),
        ],
        "warnings": [],
    }
    page_texts = {
        "order-1.png": (
            "1 Stk CQEG4112G5 85951K Startelement 42/240\n"
            "1 Stk OJ00 31681 LED Schrankbeleuchtung\n"
        )
    }

    pipeline._apply_porta_oj_accessory_article_backfill(  # type: ignore[attr-defined]
        normalized, page_texts
    )
    items = normalized.get("items") or []
    assert (items[1].get("artikelnummer") or {}).get("value") == "31681"
    assert (items[1].get("artikelnummer") or {}).get("derived_from") == "porta_oj_accessory_backfill"
    assert (normalized.get("header") or {}).get("human_review_needed", {}).get("value") is True
    print("SUCCESS: OJ/0J accessory article number is backfilled from space-separated PDF pair.")


if __name__ == "__main__":
    test_cross_page_repeated_block_is_counted_again()
    test_identical_artikel_nr_and_parent_still_count_as_new_occurrence()
    test_qty_marker_split_across_lines_is_extracted()
    test_cross_page_repeated_split_qty_block_is_counted_again()
    test_repeated_block_with_partial_second_page_is_backfilled()
    test_legal_footer_pair_is_not_extracted()
    test_no_overinsert_when_occurrences_already_complete()
    test_reconciliation_does_not_insert_legal_footer_row()
    test_no_backfill_without_parent_signature_match()
    test_non_porta_branch_no_reconciliation()
    test_extract_porta_store_name_prefers_full_legal_line()
    test_prompt_contract_mentions_cross_page_no_dedupe()
    test_porta_oj_accessory_article_backfill_from_space_separated_pair()
