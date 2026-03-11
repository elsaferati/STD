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


def _extraction_payload(items: list[dict], header_updates: dict | None = None) -> str:
    header = {
        "kundennummer": {"value": "123456", "source": "email", "confidence": 1.0},
        "kom_nr": {"value": "KOM-1", "source": "email", "confidence": 1.0},
        "reply_needed": {"value": False, "source": "derived", "confidence": 1.0},
        "human_review_needed": {"value": False, "source": "derived", "confidence": 1.0},
        "post_case": {"value": False, "source": "derived", "confidence": 1.0},
    }
    if isinstance(header_updates, dict):
        header.update(header_updates)
    return json.dumps(
        {
            "header": header,
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


def _component_block_text_with_slash_component(parent_artikel_nr: str = "4574199 / 00") -> str:
    return (
        f"1 {parent_artikel_nr} Liefermodell: Includo Kleiderschrank\n"
        "bestehend aus je:\n"
        "1 Stk Liefermodell: Includo\n"
        "PD96713696/54415 Schwebetuerschrank\n"
        "Anlieferung:\n"
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


def _run_pipeline_with_items(
    branch_id: str,
    items: list[dict],
    page_text_map: dict[str, str],
    header_updates: dict | None = None,
) -> dict:
    extractor = MagicMock()
    extractor.complete_text.return_value = json.dumps(
        {"branch_id": branch_id, "confidence": 1.0, "reason": "test"}
    )
    extractor.extract_with_prompts.return_value = _extraction_payload(
        items, header_updates=header_updates
    )
    extractor.verify_items_from_text.return_value = json.dumps(
        {"verified_items": [], "warnings": []}
    )

    original_prepare_images = pipeline._prepare_images
    original_route_message = pipeline.extraction_router.route_message
    pipeline._prepare_images = lambda attachments, config, warnings: (
        [ImageInput(name=name, source="pdf", data_url="data:image/png;base64,") for name in page_text_map.keys()],
        page_text_map,
    )
    pipeline.extraction_router.route_message = lambda *_args, **_kwargs: pipeline.extraction_router.RouteDecision(
        selected_branch_id=branch_id,
        classifier_branch_id=branch_id,
        confidence=1.0,
        reason="test",
        forced_by_detector=False,
        used_fallback=False,
    )
    try:
        result = pipeline.process_message(_message(), _config(), extractor)
        return result.data
    finally:
        pipeline._prepare_images = original_prepare_images
        pipeline.extraction_router.route_message = original_route_message


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


def test_slash_component_pair_is_extracted_from_bestehend_block() -> None:
    page_texts = {
        "order-1.png": _component_block_text_with_slash_component("4574199 / 00"),
    }
    extracted = pipeline._extract_porta_component_occurrences_from_page_texts(  # type: ignore[attr-defined]
        page_texts
    )
    keys = [
        (
            item.get("modellnummer"),
            item.get("artikelnummer"),
            str(item.get("menge")),
        )
        for item in extracted
    ]
    assert ("PD96713696", "54415", "1") in keys
    assert all(key[:2] != ("4574199", "00") for key in keys)
    print("SUCCESS: slash-separated component pair is extracted; parent table Artikel-Nr is ignored.")


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


def test_porta_store_address_uses_lieferanschrift_when_verkaufshaus_missing() -> None:
    page_texts = {
        "order-1.png": (
            "Anlieferung:\n"
            "Porta Moebel Bad Vilbel\n"
            "4040051017219\n"
            "Industriestrasse 2\n"
            "61118 Bad Vilbel\n"
            "\n"
            "Rechnungsadresse:\n"
            "FuG Handelsgesellschaft West mbH & Co. KG\n"
            "Bakenweg 16-20\n"
            "32457 Porta Westfalica\n"
        )
    }
    data = _run_pipeline_with_items(
        branch_id="porta",
        items=[_item(1, "CQEG00", "09387")],
        page_text_map=page_texts,
        header_updates={
            "lieferanschrift": {
                "value": "Industriestrasse 2\n61118 Bad Vilbel",
                "source": "pdf",
                "confidence": 0.95,
            },
            "store_address": {
                "value": "Bakenweg 16-20\n32457 Porta Westfalica",
                "source": "pdf",
                "confidence": 0.85,
            },
        },
    )
    header = data.get("header") or {}
    store_entry = header.get("store_address") or {}
    store_value = str((store_entry.get("value") if isinstance(store_entry, dict) else store_entry) or "").strip()
    assert store_value == "Industriestrasse 2\n61118 Bad Vilbel"
    assert isinstance(store_entry, dict)
    assert store_entry.get("source") == "derived"
    assert store_entry.get("derived_from") == "porta_store_address_from_lieferanschrift_no_verkaufshaus"
    print("SUCCESS: missing Verkaufshaus block forces store_address fallback to lieferanschrift.")


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
    assert "PD96713696/54415 -> modellnummer='PD96713696', artikelnummer='54415'" in porta_prompt
    assert "PD96713696/54415 -> modellnummer='PD96713696', artikelnummer='54415'" in verify_prompt
    assert "Example: 'Typ 77171' and 'Ausf. CQ1616'" in porta_prompt
    assert "Example: 'Typ 77171' and 'Ausf. CQ1616'" in verify_prompt
    assert "'Typ' is an article label and is NEVER a modellnummer token." in porta_prompt
    assert "'Typ' is an article label and is NEVER a modellnummer token." in verify_prompt
    assert "This rule does NOT make table-column 'Artikel-Nr.' valid" in porta_prompt
    assert "This rule does NOT make table-column 'Artikel-Nr.' valid" in verify_prompt
    assert "Standalone numeric tokens (e.g., '66015') and plus-joined numeric tokens (e.g., '30156+15237')" in porta_prompt
    assert "Standalone numeric tokens (e.g., '66015') and plus-joined numeric tokens (e.g., '30156+15237')" in verify_prompt
    assert "1xPDSL71SP44-57383" in porta_prompt
    assert "2xCQ1212-09377G" in porta_prompt
    assert "strip it from modellnummer" in porta_prompt
    assert "1xPDSL71SP44-57383" in verify_prompt
    assert "2xCQ1212-09377G" in verify_prompt
    assert "strip it from modellnummer" in verify_prompt
    assert "Standalone unlabeled code-like token in Porta article/description/sketch context, e.g., 'muba 4nuh'." in porta_prompt
    assert "'Siehe Skizze vcrr kwkk' and 'Siehe Skizze: vcrr kwkk' style phrases" in porta_prompt
    assert "For 'Siehe Skizze ...' phrases, accept only when the extracted candidate is exactly 8 alphanumeric characters after cleanup." in porta_prompt
    assert "If the Verkaufshaus store address is missing, use lieferanschrift for store_address." in porta_prompt
    assert "If an explicit Verkaufshaus store address is present, keep it and do not overwrite it with lieferanschrift." in porta_prompt
    assert "NEVER copy delivery address into store_address." not in porta_prompt
    print("SUCCESS: prompt contract explicitly enforces cross-page no-dedupe behavior.")


def test_porta_typ_ausf_backfill_fills_missing_codes() -> None:
    normalized = {
        "header": {"human_review_needed": {"value": False, "source": "derived", "confidence": 1.0}},
        "items": [_item(1, "", "")],
        "warnings": [],
    }
    page_texts = {
        "order-1.png": (
            "Menge Artikel-Nr. Bezeichnung des Artikels\n"
            "1 1005141 / 88 Liefermodell: Sinfonie Plus\n"
            "Typ 77171\n"
            "Kopfteil Polster Mocca mit Raute\n"
            "Ausf CQ1616\n"
        )
    }

    pipeline._apply_porta_typ_ausf_backfill(  # type: ignore[attr-defined]
        normalized, page_texts
    )

    item = (normalized.get("items") or [])[0]
    modell_entry = item.get("modellnummer") or {}
    artikel_entry = item.get("artikelnummer") or {}
    assert modell_entry.get("value") == "CQ1616"
    assert artikel_entry.get("value") == "77171"
    assert modell_entry.get("derived_from") == "porta_typ_ausf_backfill"
    assert artikel_entry.get("derived_from") == "porta_typ_ausf_backfill"
    assert artikel_entry.get("value") != "1005141"
    header = normalized.get("header") or {}
    assert (header.get("human_review_needed") or {}).get("value") is True
    assert (header.get("human_review_needed") or {}).get("derived_from") == "porta_typ_ausf_backfill"
    print("SUCCESS: Typ/Ausf fallback fills missing item codes and ignores table Artikel-Nr.")


def test_porta_typ_ausf_backfill_does_not_overwrite_partial_item() -> None:
    normalized = {
        "header": {"human_review_needed": {"value": False, "source": "derived", "confidence": 1.0}},
        "items": [_item(1, "CQSD58", "")],
        "warnings": [],
    }
    page_texts = {
        "order-1.png": (
            "Typ 77171\n"
            "Ausf CQ1616\n"
        )
    }

    pipeline._apply_porta_typ_ausf_backfill(  # type: ignore[attr-defined]
        normalized, page_texts
    )

    item = (normalized.get("items") or [])[0]
    assert (item.get("modellnummer") or {}).get("value") == "CQSD58"
    assert (item.get("artikelnummer") or {}).get("value") == ""
    assert (item.get("artikelnummer") or {}).get("derived_from") != "porta_typ_ausf_backfill"
    assert (normalized.get("header") or {}).get("human_review_needed", {}).get("value") is False
    print("SUCCESS: Typ/Ausf fallback does not overwrite partially filled items.")


def test_porta_typ_ausf_backfill_repairs_placeholder_model_from_matching_article() -> None:
    normalized = {
        "header": {"human_review_needed": {"value": False, "source": "derived", "confidence": 1.0}},
        "items": [_item(1, "TYP", "77171")],
        "warnings": [],
    }
    page_texts = {
        "order-1.png": (
            "Menge Artikel-Nr. Bezeichnung des Artikels\n"
            "1 1005141 / 88 Liefermodell: Sinfonie Plus\n"
            "Typ 77171\n"
            "Ausf: CQ1616\n"
        )
    }

    pipeline._apply_porta_typ_ausf_backfill(  # type: ignore[attr-defined]
        normalized, page_texts
    )

    item = (normalized.get("items") or [])[0]
    assert (item.get("artikelnummer") or {}).get("value") == "77171"
    assert (item.get("modellnummer") or {}).get("value") == "CQ1616"
    assert (item.get("modellnummer") or {}).get("derived_from") == "porta_typ_ausf_backfill"
    assert (normalized.get("header") or {}).get("human_review_needed", {}).get("value") is True
    print("SUCCESS: Typ/Ausf fallback repairs placeholder model token 'TYP' to CQ1616.")


def test_porta_typ_ausf_backfill_keeps_non_placeholder_model() -> None:
    normalized = {
        "header": {"human_review_needed": {"value": False, "source": "derived", "confidence": 1.0}},
        "items": [_item(1, "CQSD58", "77171")],
        "warnings": [],
    }
    page_texts = {
        "order-1.png": (
            "Typ 77171\n"
            "Ausf: CQ1616\n"
        )
    }

    pipeline._apply_porta_typ_ausf_backfill(  # type: ignore[attr-defined]
        normalized, page_texts
    )

    item = (normalized.get("items") or [])[0]
    assert (item.get("modellnummer") or {}).get("value") == "CQSD58"
    assert (item.get("modellnummer") or {}).get("derived_from") != "porta_typ_ausf_backfill"
    assert (normalized.get("header") or {}).get("human_review_needed", {}).get("value") is False
    print("SUCCESS: Typ/Ausf fallback does not overwrite non-placeholder modellnummer values.")


def test_porta_collect_pairs_ignores_typ_label_as_model() -> None:
    page_texts = {
        "order-1.png": (
            "Typ 77171\n"
            "Ausf: CQ1616\n"
        )
    }

    _model_to_articles, _article_to_models, pair_set = pipeline._collect_porta_pdf_code_pairs(  # type: ignore[attr-defined]
        page_texts
    )
    assert ("TYP", "77171") not in pair_set
    print("SUCCESS: PDF pair collector ignores Typ label token as modellnummer.")


def test_porta_typ_ausf_backfill_skips_when_pair_count_mismatch() -> None:
    normalized = {
        "header": {"human_review_needed": {"value": False, "source": "derived", "confidence": 1.0}},
        "items": [_item(1, "", ""), _item(2, "", "")],
        "warnings": [],
    }
    page_texts = {
        "order-1.png": (
            "Typ 77171\n"
            "Ausf CQ1616\n"
        )
    }

    pipeline._apply_porta_typ_ausf_backfill(  # type: ignore[attr-defined]
        normalized, page_texts
    )

    items = normalized.get("items") or []
    assert (items[0].get("modellnummer") or {}).get("value") == ""
    assert (items[0].get("artikelnummer") or {}).get("value") == ""
    assert (items[1].get("modellnummer") or {}).get("value") == ""
    assert (items[1].get("artikelnummer") or {}).get("value") == ""
    assert (normalized.get("header") or {}).get("human_review_needed", {}).get("value") is False
    print("SUCCESS: Typ/Ausf fallback skips writes when detected pair count mismatches missing rows.")


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


def test_porta_ojoo_accessory_article_backfill_from_hyphen_pair() -> None:
    normalized = {
        "header": {"human_review_needed": {"value": False, "source": "derived", "confidence": 1.0}},
        "items": [
            _item(1, "CQEG4112G5", "85951K"),
            _item(2, "OJOO", ""),
        ],
        "warnings": [],
    }
    page_texts = {
        "order-1.png": (
            "1 Stk CQEG4112G5 85951K Startelement 42/240\n"
            "1 Stk OJOO-30156 LED Schrankbeleuchtung\n"
        )
    }

    pipeline._apply_porta_oj_accessory_article_backfill(  # type: ignore[attr-defined]
        normalized, page_texts
    )
    items = normalized.get("items") or []
    assert (items[1].get("modellnummer") or {}).get("value") == "OJOO"
    assert (items[1].get("artikelnummer") or {}).get("value") == "30156"
    assert (items[1].get("artikelnummer") or {}).get("derived_from") == "porta_oj_accessory_backfill"
    assert (normalized.get("header") or {}).get("human_review_needed", {}).get("value") is True
    print("SUCCESS: OJOO accessory article number is backfilled from hyphen-separated PDF pair.")


def _qty_for_pair(normalized: dict, modell: str, artikel: str) -> int | float | str | None:
    items = normalized.get("items") or []
    for item in items:
        if not isinstance(item, dict):
            continue
        model = str((item.get("modellnummer") or {}).get("value") or "").strip().upper()
        article_no = str((item.get("artikelnummer") or {}).get("value") or "").strip().upper()
        if model == modell.upper() and article_no == artikel.upper():
            return (item.get("menge") or {}).get("value")
    return None


def test_qty_correction_no_adjacent_swap_for_cq12_cq1212_pairs() -> None:
    normalized = {
        "header": {"human_review_needed": {"value": False, "source": "derived", "confidence": 1.0}},
        "items": [
            _item(1, "CQ12", "86087", menge=1),
            _item(2, "CQ1212", "09611", menge=2),
        ],
        "warnings": [],
    }
    page_texts = {
        "order-1.png": (
            "1 4624469 / 64 Liefermodell: SinfoniePlus\n"
            "bestehend aus je:\n"
            "2 Stk CQ12 86087 Aussenseite Standard 240\n"
            "1 Stk CQ1212 09611 Stollen-Grundregal\n"
        )
    }

    pipeline._apply_porta_quantity_corrections(  # type: ignore[attr-defined]
        normalized, page_texts
    )
    assert _qty_for_pair(normalized, "CQ12", "86087") == 2
    assert _qty_for_pair(normalized, "CQ1212", "09611") == 1
    print("SUCCESS: strict quantity correction keeps CQ12/CQ1212 rows from adjacent swap.")


def test_qty_correction_no_adjacent_swap_for_cq124112g5_cq12411212g1_pairs() -> None:
    normalized = {
        "header": {"human_review_needed": {"value": False, "source": "derived", "confidence": 1.0}},
        "items": [
            _item(1, "CQ124112G5", "86047", menge=1),
            _item(2, "CQ12411212G1", "86080", menge=2),
        ],
        "warnings": [],
    }
    page_texts = {
        "order-1.png": (
            "1 4624469 / 64 Liefermodell: SinfoniePlus\n"
            "bestehend aus je:\n"
            "2 Stk CQ124112G5 86047 Anbauelement 83/240\n"
            "1 Stk CQ12411212G1 86080 Anbauelement 83/240\n"
        )
    }

    pipeline._apply_porta_quantity_corrections(  # type: ignore[attr-defined]
        normalized, page_texts
    )
    assert _qty_for_pair(normalized, "CQ124112G5", "86047") == 2
    assert _qty_for_pair(normalized, "CQ12411212G1", "86080") == 1
    print("SUCCESS: strict quantity correction keeps CQ124112G5/CQ12411212G1 rows from adjacent swap.")


def test_qty_correction_keeps_parent_row_qty_for_cqeg1299_76947g() -> None:
    normalized = {
        "header": {"human_review_needed": {"value": False, "source": "derived", "confidence": 1.0}},
        "items": [
            _item(1, "CQEG1299", "76947G", menge=2),
        ],
        "warnings": [],
    }
    page_texts = {
        "order-1.png": (
            "1 4624469 / 66 Liefermodell: Sinfonie Plus Bett\n"
            "bestehend aus je:\n"
            "1 Stk CQ1212 09377G Bettrahmen\n"
            "1 Stk CQEG12 09341G Bettkopfteil\n"
            "2 Stk 4624469 / 67 Liefermodell: Sinfonie Plus CQEG1299 76947G\n"
            "Konsole\n"
        )
    }

    pipeline._apply_porta_quantity_corrections(  # type: ignore[attr-defined]
        normalized, page_texts
    )
    assert _qty_for_pair(normalized, "CQEG1299", "76947G") == 2
    print("SUCCESS: parent-row qty for CQEG1299/76947G is not overwritten by unrelated component rows.")


def test_qty_correction_skips_ambiguous_pair_and_warns() -> None:
    normalized = {
        "header": {"human_review_needed": {"value": False, "source": "derived", "confidence": 1.0}},
        "items": [
            _item(1, "CQ1212", "09377G", menge=3),
        ],
        "warnings": [],
    }
    page_texts = {
        "order-1.png": (
            "1 4624469 / 66 Liefermodell: Sinfonie Plus Bett\n"
            "bestehend aus je:\n"
            "1 Stk CQ1212 09377G Bettrahmen\n"
        ),
        "order-2.png": (
            "1 4624469 / 66 Liefermodell: Sinfonie Plus Bett\n"
            "bestehend aus je:\n"
            "2 Stk CQ1212 09377G Bettrahmen\n"
        ),
    }

    pipeline._apply_porta_quantity_corrections(  # type: ignore[attr-defined]
        normalized, page_texts
    )
    assert _qty_for_pair(normalized, "CQ1212", "09377G") == 3
    warnings = normalized.get("warnings") or []
    assert any("ambiguous PDF quantity signals" in str(w) for w in warnings)
    print("SUCCESS: ambiguous quantity signals are skipped and warned (no forced correction).")


if __name__ == "__main__":
    test_cross_page_repeated_block_is_counted_again()
    test_identical_artikel_nr_and_parent_still_count_as_new_occurrence()
    test_slash_component_pair_is_extracted_from_bestehend_block()
    test_qty_marker_split_across_lines_is_extracted()
    test_cross_page_repeated_split_qty_block_is_counted_again()
    test_repeated_block_with_partial_second_page_is_backfilled()
    test_legal_footer_pair_is_not_extracted()
    test_no_overinsert_when_occurrences_already_complete()
    test_reconciliation_does_not_insert_legal_footer_row()
    test_no_backfill_without_parent_signature_match()
    test_non_porta_branch_no_reconciliation()
    test_extract_porta_store_name_prefers_full_legal_line()
    test_porta_store_address_uses_lieferanschrift_when_verkaufshaus_missing()
    test_prompt_contract_mentions_cross_page_no_dedupe()
    test_porta_typ_ausf_backfill_fills_missing_codes()
    test_porta_typ_ausf_backfill_does_not_overwrite_partial_item()
    test_porta_typ_ausf_backfill_repairs_placeholder_model_from_matching_article()
    test_porta_typ_ausf_backfill_keeps_non_placeholder_model()
    test_porta_collect_pairs_ignores_typ_label_as_model()
    test_porta_typ_ausf_backfill_skips_when_pair_count_mismatch()
    test_porta_oj_accessory_article_backfill_from_space_separated_pair()
    test_porta_ojoo_accessory_article_backfill_from_hyphen_pair()
    test_qty_correction_no_adjacent_swap_for_cq12_cq1212_pairs()
    test_qty_correction_no_adjacent_swap_for_cq124112g5_cq12411212g1_pairs()
    test_qty_correction_keeps_parent_row_qty_for_cqeg1299_76947g()
    test_qty_correction_skips_ambiguous_pair_and_warns()
