import copy

import pipeline


def _item(line_no: int, modell: str, artikel: str, menge: int = 1) -> dict:
    return {
        "line_no": line_no,
        "modellnummer": {"value": modell, "source": "pdf", "confidence": 1.0},
        "artikelnummer": {"value": artikel, "source": "pdf", "confidence": 1.0},
        "menge": {"value": menge, "source": "pdf", "confidence": 1.0},
        "furncloud_id": {"value": "", "source": "derived", "confidence": 0.0},
    }


def _normalized(items: list[dict]) -> dict:
    return {
        "header": {
            "human_review_needed": {
                "value": False,
                "source": "derived",
                "confidence": 1.0,
            }
        },
        "items": items,
        "warnings": [],
    }


def _porta_component_block_text() -> str:
    return (
        "1 4624469 / 64 Liefermodell: SinfoniePlus Aus.3\n"
        "bestehend aus je:\n"
        "1 Stk CQEG4112G5 85951K Startelement 42/240\n"
        "1 Stk CQ1212 09377G Stollen-Grundregal\n"
        "1 Stk CQEG12 09341G Einteilungsboden\n"
    )


def test_suffix_restoration_sets_review() -> None:
    normalized = _normalized([_item(1, "CQEG4112G5", "85951")])
    page_texts = {"order-1.png": "1 Stk CQEG4112G5 85951K Startelement 42/240\n"}

    changed = pipeline._apply_porta_code_consistency_corrections(  # type: ignore[attr-defined]
        normalized,
        page_texts,
    )

    assert changed == 1
    item = normalized["items"][0]
    assert item["artikelnummer"]["value"] == "85951K"
    assert item["artikelnummer"]["derived_from"] == "porta_pdf_code_consistency_correction"
    review = (normalized.get("header") or {}).get("human_review_needed", {})
    assert review.get("value") is True
    assert review.get("derived_from") == "porta_pdf_code_consistency_correction"
    warnings = normalized.get("warnings") or []
    assert any("Porta code consistency correction item line 1 field artikelnummer" in str(w) for w in warnings)
    print("SUCCESS: deterministic suffix restoration corrects artikelnummer and forces review.")


def test_multiple_suffix_restorations() -> None:
    normalized = _normalized(
        [
            _item(1, "CQEG4112G5", "85951"),
            _item(2, "CQ1212", "09377"),
            _item(3, "CQEG12", "09341"),
            _item(4, "CQEG1299", "76947"),
        ]
    )
    page_texts = {
        "order-1.png": (
            "1 Stk CQEG4112G5 85951K Startelement 42/240\n"
            "1 Stk CQ1212 09377G Stollen-Grundregal\n"
            "1 Stk CQEG12 09341G Einteilungsboden\n"
            "1 Stk CQEG1299 76947G Nachtkonsole\n"
        )
    }

    changed = pipeline._apply_porta_code_consistency_corrections(  # type: ignore[attr-defined]
        normalized,
        page_texts,
    )

    assert changed == 4
    items = normalized.get("items") or []
    assert items[0]["artikelnummer"]["value"] == "85951K"
    assert items[1]["artikelnummer"]["value"] == "09377G"
    assert items[2]["artikelnummer"]["value"] == "09341G"
    assert items[3]["artikelnummer"]["value"] == "76947G"
    print("SUCCESS: multiple suffix-bearing artikelnummer values are corrected deterministically.")


def test_reconciliation_duplicate_prevention() -> None:
    base = _normalized(
        [
            _item(1, "CQEG4112G5", "85951"),
            _item(2, "CQ1212", "09377"),
            _item(3, "CQEG12", "09341"),
        ]
    )
    page_texts = {"order-1.png": _porta_component_block_text()}

    without_correction = copy.deepcopy(base)
    added_without = pipeline._reconcile_porta_component_occurrences(  # type: ignore[attr-defined]
        without_correction,
        page_texts,
    )
    assert added_without > 0

    with_correction = copy.deepcopy(base)
    pipeline._apply_porta_code_consistency_corrections(  # type: ignore[attr-defined]
        with_correction,
        page_texts,
    )
    added_with = pipeline._reconcile_porta_component_occurrences(  # type: ignore[attr-defined]
        with_correction,
        page_texts,
    )
    assert added_with == 0
    assert len(with_correction.get("items") or []) == 3
    print("SUCCESS: code-consistency corrections prevent reconciliation over-insert for same component pairs.")


def test_ambiguity_guard_for_article_suffix() -> None:
    normalized = _normalized([_item(1, "CQEG4112G5", "85951A")])
    page_texts = {
        "order-1.png": (
            "1 Stk CQEG4112G5 85951 Startelement\n"
            "1 Stk CQEG4112G5 85951K Startelement\n"
        )
    }

    changed = pipeline._apply_porta_code_consistency_corrections(  # type: ignore[attr-defined]
        normalized,
        page_texts,
    )

    assert changed == 0
    item = normalized["items"][0]
    assert item["artikelnummer"]["value"] == "85951A"
    print("SUCCESS: ambiguous same-base article candidates do not trigger correction.")


def test_unique_model_correction_by_article() -> None:
    normalized = _normalized([_item(1, "CQEG4112GS", "85951K")])
    page_texts = {"order-1.png": "1 Stk CQEG4112G5 85951K Startelement 42/240\n"}

    changed = pipeline._apply_porta_code_consistency_corrections(  # type: ignore[attr-defined]
        normalized,
        page_texts,
    )

    assert changed == 1
    item = normalized["items"][0]
    assert item["modellnummer"]["value"] == "CQEG4112G5"
    assert item["modellnummer"]["derived_from"] == "porta_pdf_code_consistency_correction"
    print("SUCCESS: modellnummer is corrected when article maps to a unique PDF model.")


def test_ambiguous_model_candidates_no_correction() -> None:
    normalized = _normalized([_item(1, "CQEGXXXXXX", "85951K")])
    page_texts = {
        "order-1.png": (
            "1 Stk CQEG4112G5 85951K Startelement\n"
            "1 Stk CQEG4112G6 85951K Startelement\n"
        )
    }

    changed = pipeline._apply_porta_code_consistency_corrections(  # type: ignore[attr-defined]
        normalized,
        page_texts,
    )

    assert changed == 0
    item = normalized["items"][0]
    assert item["modellnummer"]["value"] == "CQEGXXXXXX"
    print("SUCCESS: modellnummer remains unchanged when article maps to multiple models.")


def test_component_pair_parser_accepts_hyphen_separator() -> None:
    page_texts = {
        "order-1.png": (
            "1 4574199 / 19 Liefermodell: Includo PD7771SP91 80010\n"
            "bestehend aus je:\n"
            "1 Stk PD7771SP91 80010\n"
            "1 Stk PD7871SP36-80010\n"
            "1 Stk PD96713696/54415\n"
            "Anlieferung:\n"
        )
    }
    occurrences = pipeline._extract_porta_component_occurrences_from_page_texts(  # type: ignore[attr-defined]
        page_texts
    )
    got_pairs = {
        (str(entry.get("modellnummer")), str(entry.get("artikelnummer")))
        for entry in occurrences
        if isinstance(entry, dict)
    }
    assert ("PD7771SP91", "80010") in got_pairs
    assert ("PD7871SP36", "80010") in got_pairs
    assert ("PD96713696", "54415") in got_pairs
    print("SUCCESS: component parser captures whitespace, hyphen, and slash separated model/article pairs.")


def test_component_pair_parser_strips_numeric_x_prefix_from_model() -> None:
    page_texts = {
        "order-1.png": (
            "1 4574199 / 19 Liefermodell: Includo PDSL61SP96 57383\n"
            "bestehend aus je:\n"
            "1 Stk 1xPDSL71SP44-57383\n"
            "1 Stk 2xCQ1212-09377G\n"
            "Anlieferung:\n"
        )
    }
    occurrences = pipeline._extract_porta_component_occurrences_from_page_texts(  # type: ignore[attr-defined]
        page_texts
    )
    got_pairs = {
        (str(entry.get("modellnummer")), str(entry.get("artikelnummer")))
        for entry in occurrences
        if isinstance(entry, dict)
    }
    assert ("PDSL71SP44", "57383") in got_pairs
    assert ("CQ1212", "09377G") in got_pairs
    print("SUCCESS: component parser strips '<number>x' quantity prefixes from model tokens.")


def test_collect_pairs_strips_numeric_x_prefix_and_keeps_standard_pairs() -> None:
    page_texts = {
        "order-1.png": (
            "1 Stk 1xPDSL71SP44-57383\n"
            "1 Stk 2xCQ1212-09377G\n"
            "1 Stk CQ1616XP-00943\n"
        )
    }
    _model_to_articles, _article_to_models, pair_set = pipeline._collect_porta_pdf_code_pairs(  # type: ignore[attr-defined]
        page_texts
    )
    assert ("PDSL71SP44", "57383") in pair_set
    assert ("CQ1212", "09377G") in pair_set
    assert ("CQ1616XP", "00943") in pair_set
    print("SUCCESS: pair collector strips '<number>x' prefixes and keeps regular pairs unchanged.")


def test_collect_pairs_rejects_sonate_4008_and_keeps_valid_pair() -> None:
    page_texts = {
        "order-1.png": (
            "1 3053006 / 88 Liefermodell: Sonate 4008\n"
            "Modell-Nr: OPGPZB2020 ArtNr: 72797\n"
            "1 Stk CQ9191XA 42889\n"
        )
    }

    _model_to_articles, _article_to_models, pair_set = pipeline._collect_porta_pdf_code_pairs(  # type: ignore[attr-defined]
        page_texts
    )

    assert ("SONATE", "4008") not in pair_set
    assert ("CQ9191XA", "42889") in pair_set
    print("SUCCESS: pair collector rejects descriptor pair SONATE/4008 and keeps valid 5-digit article pair.")


def test_collect_pairs_accepts_liefermodell_article_model_order() -> None:
    page_texts = {
        "order-1.png": (
            "2 Stk 3060817 / 13 Liefermodell: Sonate 13505 OGAW819696\n"
            "Anlieferung:\n"
        )
    }

    _model_to_articles, _article_to_models, pair_set = pipeline._collect_porta_pdf_code_pairs(  # type: ignore[attr-defined]
        page_texts
    )

    assert ("OGAW819696", "13505") in pair_set
    assert ("SONATE", "13505") not in pair_set
    print("SUCCESS: pair collector accepts Liefermodell ARTICLE MODEL order deterministically.")


def test_collect_pairs_accepts_spaced_prefix_fused_code() -> None:
    page_texts = {
        "order-1.png": (
            "1 Stk CQ 9696XA56062\n"
            "Anlieferung:\n"
        )
    }

    _model_to_articles, _article_to_models, pair_set = pipeline._collect_porta_pdf_code_pairs(  # type: ignore[attr-defined]
        page_texts
    )

    assert ("CQ9696XA", "56062") in pair_set
    print("SUCCESS: pair collector splits spaced-prefix fused Porta code CQ 9696XA56062.")


def test_collect_pairs_accepts_labeled_fused_oj_token() -> None:
    page_texts = {
        "order-1.png": (
            "Nr. OJ363612782\n"
            "Anlieferung:\n"
        )
    }

    _model_to_articles, _article_to_models, pair_set = pipeline._collect_porta_pdf_code_pairs(  # type: ignore[attr-defined]
        page_texts
    )

    assert ("OJ3636", "12782") in pair_set
    print("SUCCESS: pair collector splits labeled fused OJ token Nr. OJ363612782.")


def test_collect_pairs_accepts_article_prefix_or_suffix_only() -> None:
    page_texts = {
        "order-1.png": (
            "1 Stk CQ9191XA A34555\n"
            "1 Stk CQ9191XB 56A789\n"
            "1 Stk DMAW 12345A\n"
        )
    }

    _model_to_articles, _article_to_models, pair_set = pipeline._collect_porta_pdf_code_pairs(  # type: ignore[attr-defined]
        page_texts
    )

    assert ("CQ9191XA", "A34555") in pair_set
    assert ("DMAW", "12345A") in pair_set
    assert ("CQ9191XB", "56A789") not in pair_set
    print("SUCCESS: pair collector accepts prefix/suffix article letters and rejects embedded-letter variants.")


def test_inline_pair_reconciliation_adds_missing_item_non_bestehend() -> None:
    normalized = _normalized([_item(1, "PD7871SP36", "80010")])
    page_texts = {
        "order-1.png": (
            "1 4574199 / 19 Liefermodell: Includo PD7771SP91 80010\n"
            "Schwebetuerschrank\n"
            "PD7871SP36-80010\n"
            "Anlieferung:\n"
        )
    }

    added = pipeline._reconcile_porta_inline_pair_occurrences(  # type: ignore[attr-defined]
        normalized,
        page_texts,
    )

    assert added == 1
    items = normalized.get("items") or []
    assert len(items) == 2
    pairs = {
        (
            str(item.get("modellnummer", {}).get("value", "")),
            str(item.get("artikelnummer", {}).get("value", "")),
        )
        for item in items
        if isinstance(item, dict)
    }
    assert ("PD7771SP91", "80010") in pairs
    assert ("PD7871SP36", "80010") in pairs
    print("SUCCESS: inline reconciliation adds missing non-'bestehend aus je' pair occurrence.")


def test_inline_pair_reconciliation_hyphen_and_space_supported() -> None:
    normalized = _normalized([_item(1, "EXISTINGX1", "99999")])
    page_texts = {
        "order-1.png": (
            "1 4574199 / 19 Liefermodell: Includo PD7771SP91 80010\n"
            "PD7871SP36-80010\n"
            "PD96713696/54415\n"
            "Anlieferung:\n"
        )
    }

    added = pipeline._reconcile_porta_inline_pair_occurrences(  # type: ignore[attr-defined]
        normalized,
        page_texts,
    )

    assert added == 3
    items = normalized.get("items") or []
    assert len(items) == 4
    pairs = {
        (
            str(item.get("modellnummer", {}).get("value", "")),
            str(item.get("artikelnummer", {}).get("value", "")),
        )
        for item in items
        if isinstance(item, dict)
    }
    assert ("PD7771SP91", "80010") in pairs
    assert ("PD7871SP36", "80010") in pairs
    assert ("PD96713696", "54415") in pairs
    print("SUCCESS: inline reconciliation supports whitespace, hyphen, and slash separators.")


def test_inline_pair_reconciliation_idempotent() -> None:
    normalized = _normalized([_item(1, "PD7871SP36", "80010")])
    page_texts = {
        "order-1.png": (
            "1 4574199 / 19 Liefermodell: Includo PD7771SP91 80010\n"
            "PD7871SP36-80010\n"
            "Anlieferung:\n"
        )
    }

    added_first = pipeline._reconcile_porta_inline_pair_occurrences(  # type: ignore[attr-defined]
        normalized,
        page_texts,
    )
    count_after_first = len(normalized.get("items") or [])
    added_second = pipeline._reconcile_porta_inline_pair_occurrences(  # type: ignore[attr-defined]
        normalized,
        page_texts,
    )
    count_after_second = len(normalized.get("items") or [])

    assert added_first == 1
    assert added_second == 0
    assert count_after_first == count_after_second
    print("SUCCESS: inline reconciliation is idempotent.")


def test_inline_pair_reconciliation_skips_footer_legal_tokens() -> None:
    normalized = _normalized([_item(1, "PD7771SP91", "80010")])
    page_texts = {
        "order-1.png": (
            "1 4574199 / 19 Liefermodell: Includo PD7771SP91 80010\n"
            "Amtsgericht Koeln HRA 9684\n"
            "Anlieferung:\n"
        )
    }

    added = pipeline._reconcile_porta_inline_pair_occurrences(  # type: ignore[attr-defined]
        normalized,
        page_texts,
    )

    assert added == 0
    assert len(normalized.get("items") or []) == 1
    print("SUCCESS: inline reconciliation ignores legal/footer tokens like HRA/HRB.")


def test_inline_pair_reconciliation_sets_human_review_and_warning() -> None:
    normalized = _normalized([_item(1, "PD7871SP36", "80010")])
    page_texts = {
        "order-1.png": (
            "1 4574199 / 19 Liefermodell: Includo PD7771SP91 80010\n"
            "PD7871SP36-80010\n"
            "Anlieferung:\n"
        )
    }

    added = pipeline._reconcile_porta_inline_pair_occurrences(  # type: ignore[attr-defined]
        normalized,
        page_texts,
    )

    assert added == 1
    review = (normalized.get("header") or {}).get("human_review_needed", {})
    assert review.get("value") is True
    assert review.get("derived_from") == "porta_inline_pair_reconciliation"
    warnings = normalized.get("warnings") or []
    assert any("Porta inline pair reconciliation added" in str(w) for w in warnings)
    print("SUCCESS: inline reconciliation sets review flag and warning trace.")


def test_inline_pair_reconciliation_skips_qtyless_duplicate_when_pair_exists() -> None:
    normalized = _normalized([_item(1, "CQEG1299", "76947G", menge=2)])
    page_texts = {
        "order-1.png": (
            "2 Stk 4624469 / 67 Liefermodell: Sinfonie Plus CQEG1299 76947G\n"
            "Konsole\n"
            "Anlieferung:\n"
        )
    }

    added = pipeline._reconcile_porta_inline_pair_occurrences(  # type: ignore[attr-defined]
        normalized,
        page_texts,
    )

    assert added == 0
    items = normalized.get("items") or []
    assert len(items) == 1
    assert (items[0].get("modellnummer") or {}).get("value") == "CQEG1299"
    assert (items[0].get("artikelnummer") or {}).get("value") == "76947G"
    assert (items[0].get("menge") or {}).get("value") == 2
    print("SUCCESS: qty-less inline pair mention does not create duplicate when pair already exists.")


def test_inline_pair_reconciliation_keeps_explicit_qty_non_regression() -> None:
    normalized = _normalized([_item(1, "CQEG1299", "76947G", menge=2)])
    page_texts = {
        "order-1.png": (
            "2 Stk 4624469 / 67 Liefermodell: Sinfonie Plus CQEG1299 76947G\n"
            "1 Stk CQEG1299 76947G\n"
            "Anlieferung:\n"
        )
    }

    added = pipeline._reconcile_porta_inline_pair_occurrences(  # type: ignore[attr-defined]
        normalized,
        page_texts,
    )

    assert added == 1
    items = normalized.get("items") or []
    assert len(items) == 2
    qty_values = sorted(
        [
            (item.get("menge") or {}).get("value")
            for item in items
            if isinstance(item, dict)
        ]
    )
    assert qty_values == [1, 2]
    print("SUCCESS: explicit inline qty occurrence is still added as a distinct item.")


def test_inline_pair_reconciliation_rejects_sonate_4008_descriptor() -> None:
    normalized = _normalized([_item(1, "CQ9191XA", "42889")])
    page_texts = {
        "order-1.png": (
            "1 3053006 / 88 Liefermodell: Sonate 4008\n"
            "Anlieferung:\n"
        )
    }

    added = pipeline._reconcile_porta_inline_pair_occurrences(  # type: ignore[attr-defined]
        normalized,
        page_texts,
    )

    assert added == 0
    items = normalized.get("items") or []
    assert len(items) == 1
    assert (items[0].get("modellnummer") or {}).get("value") == "CQ9191XA"
    assert (items[0].get("artikelnummer") or {}).get("value") == "42889"
    print("SUCCESS: inline reconciliation does not create SONATE/4008 from descriptor text.")


def test_porta_code_shape_validation_clears_invalid_descriptor_codes() -> None:
    normalized = _normalized([_item(1, "SONATE", "4008", menge=1)])

    changed = pipeline._apply_porta_code_shape_validation(  # type: ignore[attr-defined]
        normalized
    )

    assert changed == 2
    item = (normalized.get("items") or [])[0]
    assert (item.get("modellnummer") or {}).get("value") == ""
    assert (item.get("artikelnummer") or {}).get("value") == ""
    assert (item.get("modellnummer") or {}).get("derived_from") == "porta_code_shape_validation"
    assert (item.get("artikelnummer") or {}).get("derived_from") == "porta_code_shape_validation"
    assert (item.get("menge") or {}).get("value") == 1
    review = (normalized.get("header") or {}).get("human_review_needed", {})
    assert review.get("value") is True
    assert review.get("derived_from") == "porta_code_shape_validation"
    warnings = normalized.get("warnings") or []
    assert any("Porta code-shape validation cleared invalid item code(s)" in str(w) for w in warnings)
    print("SUCCESS: code-shape validation clears SONATE/4008 while keeping row quantity.")


def test_porta_code_shape_validation_keeps_valid_codes() -> None:
    normalized = _normalized([_item(1, "CQ9191XA", "42889", menge=2)])

    changed = pipeline._apply_porta_code_shape_validation(  # type: ignore[attr-defined]
        normalized
    )

    assert changed == 0
    item = (normalized.get("items") or [])[0]
    assert (item.get("modellnummer") or {}).get("value") == "CQ9191XA"
    assert (item.get("artikelnummer") or {}).get("value") == "42889"
    assert (item.get("menge") or {}).get("value") == 2
    review = (normalized.get("header") or {}).get("human_review_needed", {})
    assert review.get("value") is False
    print("SUCCESS: code-shape validation leaves valid code-like pairs unchanged.")


def test_porta_code_shape_validation_keeps_prefix_suffix_articles_and_clears_embedded_letter() -> None:
    normalized = _normalized(
        [
            _item(1, "CQ9191XA", "A34555", menge=1),
            _item(2, "CQ9191XB", "56A789", menge=1),
            _item(3, "DMAW", "12345A", menge=1),
        ]
    )

    changed = pipeline._apply_porta_code_shape_validation(  # type: ignore[attr-defined]
        normalized
    )

    assert changed == 1
    items = normalized.get("items") or []
    assert (items[0].get("artikelnummer") or {}).get("value") == "A34555"
    assert (items[1].get("artikelnummer") or {}).get("value") == ""
    assert (items[1].get("artikelnummer") or {}).get("derived_from") == "porta_code_shape_validation"
    assert (items[2].get("modellnummer") or {}).get("value") == "DMAW"
    assert (items[2].get("artikelnummer") or {}).get("value") == "12345A"
    print("SUCCESS: code-shape validation keeps prefix/suffix articles, accepts rare alpha-only models, and clears embedded-letter articles.")


def test_porta_code_shape_helpers_accept_and_reject_expected_forms() -> None:
    assert pipeline._is_porta_article_code_like("09387")  # type: ignore[attr-defined]
    assert pipeline._is_porta_article_code_like("76808G")  # type: ignore[attr-defined]
    assert pipeline._is_porta_article_code_like("A12345")  # type: ignore[attr-defined]
    assert pipeline._is_porta_article_code_like("12345A")  # type: ignore[attr-defined]
    assert not pipeline._is_porta_article_code_like("56A789")  # type: ignore[attr-defined]
    assert not pipeline._is_porta_article_code_like("4008")  # type: ignore[attr-defined]
    assert not pipeline._is_porta_article_code_like("4611217 / 841")  # type: ignore[attr-defined]

    assert pipeline._is_porta_model_code_like("CQEG5899")  # type: ignore[attr-defined]
    assert pipeline._is_porta_model_code_like("CQEG00")  # type: ignore[attr-defined]
    assert pipeline._is_porta_model_code_like("PD96713696")  # type: ignore[attr-defined]
    assert pipeline._is_porta_model_code_like("DMAW")  # type: ignore[attr-defined]
    assert not pipeline._is_porta_model_code_like("SONATE")  # type: ignore[attr-defined]
    assert not pipeline._is_porta_model_code_like("HRB")  # type: ignore[attr-defined]
    assert not pipeline._is_porta_model_code_like("9684")  # type: ignore[attr-defined]
    assert not pipeline._is_porta_model_code_like("STK")  # type: ignore[attr-defined]
    print("SUCCESS: helper validators enforce strict Porta article formats and model-code shapes.")


def test_porta_code_shape_validation_normalizes_ojoo_to_oj00() -> None:
    normalized = _normalized([_item(2, "OJOO", "30156", menge=1)])

    changed = pipeline._apply_porta_code_shape_validation(  # type: ignore[attr-defined]
        normalized
    )

    assert changed == 1
    item = (normalized.get("items") or [])[0]
    assert (item.get("modellnummer") or {}).get("value") == "OJ00"
    assert (item.get("modellnummer") or {}).get("derived_from") == "porta_code_shape_validation"
    assert (item.get("artikelnummer") or {}).get("value") == "30156"
    review = (normalized.get("header") or {}).get("human_review_needed", {})
    assert review.get("value") is False
    warnings = normalized.get("warnings") or []
    assert any("normalized modellnummer" in str(w) for w in warnings)
    assert not any("cleared invalid item code(s)" in str(w) for w in warnings)
    print("SUCCESS: code-shape validation normalizes OJOO accessory OCR to OJ00.")


def test_porta_code_shape_validation_splits_fused_oj_model_when_article_missing() -> None:
    normalized = _normalized([_item(1, "OJ363612782", "", menge=1)])

    changed = pipeline._apply_porta_code_shape_validation(  # type: ignore[attr-defined]
        normalized
    )

    assert changed == 2
    item = (normalized.get("items") or [])[0]
    assert (item.get("modellnummer") or {}).get("value") == "OJ3636"
    assert (item.get("artikelnummer") or {}).get("value") == "12782"
    assert (item.get("modellnummer") or {}).get("derived_from") == "porta_code_shape_validation"
    assert (item.get("artikelnummer") or {}).get("derived_from") == "porta_code_shape_validation"
    warnings = normalized.get("warnings") or []
    assert any("split fused OJ model/article token" in str(w) for w in warnings)
    print("SUCCESS: code-shape validation splits fused OJ model token into modellnummer/artikelnummer.")


def test_porta_explicit_pair_prune_retains_model_inferred_rows_and_sets_human_review() -> None:
    normalized = _normalized(
        [
            _item(1, "CQ9191XA", "42889"),
            _item(2, "", "66015"),
            _item(3, "OJ00", "30156"),
            _item(4, "OJ00", "15237"),
            _item(5, "OJ9191", "53669"),
        ]
    )
    page_texts = {
        "order-1.png": (
            "1 4609952 / 04 Liefermodell: Sinfonie Plus CQ9191XA 42889\n"
            "66015\n"
            "30156+15237\n"
            "OJ9191-53669\n"
            "Anlieferung:\n"
        )
    }

    flagged = pipeline._prune_porta_items_without_explicit_pdf_pairs(  # type: ignore[attr-defined]
        normalized,
        page_texts,
    )

    assert flagged == 2
    items = normalized.get("items") or []
    assert len(items) == 5
    pairs = [
        (
            str(item.get("modellnummer", {}).get("value", "")),
            str(item.get("artikelnummer", {}).get("value", "")),
        )
        for item in items
        if isinstance(item, dict)
    ]
    assert ("CQ9191XA", "42889") in pairs
    assert ("OJ00", "30156") in pairs
    assert ("OJ00", "15237") in pairs
    assert ("OJ9191", "53669") in pairs
    assert pairs.count(("OJ9191", "53669")) == 1

    header = normalized.get("header") or {}
    review = header.get("human_review_needed") or {}
    assert review.get("value") is True
    assert review.get("derived_from") == "porta_ambiguous_code_human_review"
    reply = header.get("reply_needed") or {}
    assert reply.get("value") is not True

    warnings = normalized.get("warnings") or []
    assert any(
        "Human review needed: Porta ambiguous standalone code token(s) retained for human confirmation" in str(w)
        for w in warnings
    )
    assert any("Porta explicit-pair review retained" in str(w) for w in warnings)
    assert not any("Porta explicit-pair prune removed" in str(w) for w in warnings)
    assert not any("standalone code token(s) removed" in str(w) for w in warnings)
    print("SUCCESS: explicit-pair review retains unsupported model-inferred rows and sets human_review_needed.")


def test_porta_article_only_reconciliation_adds_standalone_article_rows() -> None:
    normalized = _normalized(
        [
            _item(1, "CQ9191XA", "42889"),
            _item(2, "OJ9191", "53669"),
        ]
    )
    page_texts = {
        "order-1.png": (
            "1 4609952 / 04 Liefermodell: Sinfonie Plus CQ9191XA 42889\n"
            "66015\n"
            "30156+15237\n"
            "OJ9191-53669\n"
            "Anlieferung:\n"
        )
    }

    added = pipeline._reconcile_porta_article_only_occurrences(  # type: ignore[attr-defined]
        normalized,
        page_texts,
    )

    assert added == 3
    items = normalized.get("items") or []
    assert len(items) == 5
    article_only = [
        (
            str((item.get("modellnummer") or {}).get("value") or ""),
            str((item.get("artikelnummer") or {}).get("value") or ""),
        )
        for item in items
        if isinstance(item, dict)
        and not str((item.get("modellnummer") or {}).get("value") or "").strip()
    ]
    assert ("", "66015") in article_only
    assert ("", "30156") in article_only
    assert ("", "15237") in article_only
    warnings = normalized.get("warnings") or []
    assert any("Porta article-only reconciliation added 3 item(s)" in str(w) for w in warnings)
    print("SUCCESS: standalone Porta article lines are added as article-only item rows.")


def test_porta_model_only_reconciliation_adds_standalone_model_rows() -> None:
    normalized = _normalized(
        [
            _item(1, "CQ0606XA", "42912"),
            _item(2, "OJ00", "13076"),
        ]
    )
    page_texts = {
        "order-1.png": (
            "1 4609952 / 04 Liefermodell: Sinfonie Plus CQ0606XA 42912\n"
            "1 Stk OJ00-13076\n"
            "1 Stk Kommode mit 4 Schubkasten OFSN0699\n"
            "Anlieferung:\n"
        )
    }

    added = pipeline._reconcile_porta_model_only_occurrences(  # type: ignore[attr-defined]
        normalized,
        page_texts,
    )

    assert added == 1
    items = normalized.get("items") or []
    assert len(items) == 3
    model_only = [
        (
            str((item.get("modellnummer") or {}).get("value") or ""),
            str((item.get("artikelnummer") or {}).get("value") or ""),
        )
        for item in items
        if isinstance(item, dict)
        and not str((item.get("artikelnummer") or {}).get("value") or "").strip()
    ]
    assert ("OFSN0699", "") in model_only
    warnings = normalized.get("warnings") or []
    assert any("Porta model-only reconciliation added 1 item(s)" in str(w) for w in warnings)
    print("SUCCESS: standalone Porta model lines are added as model-only item rows.")


def test_porta_explicit_pair_prune_accepts_article_only_rows() -> None:
    normalized = _normalized(
        [
            _item(1, "CQ9191XA", "42889"),
            _item(2, "", "66015"),
            _item(3, "", "30156"),
            _item(4, "", "15237"),
            _item(5, "OJ9191", "53669"),
        ]
    )
    page_texts = {
        "order-1.png": (
            "1 4609952 / 04 Liefermodell: Sinfonie Plus CQ9191XA 42889\n"
            "66015\n"
            "30156+15237\n"
            "OJ9191-53669\n"
            "Anlieferung:\n"
        )
    }

    flagged = pipeline._prune_porta_items_without_explicit_pdf_pairs(  # type: ignore[attr-defined]
        normalized,
        page_texts,
    )

    assert flagged == 0
    header = normalized.get("header") or {}
    review = header.get("human_review_needed") or {}
    assert review.get("value") is not True
    print("SUCCESS: explicit-pair review accepts standalone article-only rows when they exist in PDF text.")


def test_porta_explicit_pair_prune_accepts_model_only_rows() -> None:
    normalized = _normalized(
        [
            _item(1, "CQ0606XA", "42912"),
            _item(2, "OJ00", "13076"),
            _item(3, "OFSN0699", ""),
        ]
    )
    page_texts = {
        "order-1.png": (
            "1 4609952 / 04 Liefermodell: Sinfonie Plus CQ0606XA 42912\n"
            "1 Stk OJ00-13076\n"
            "1 Stk Kommode mit 4 Schubkasten OFSN0699\n"
            "Anlieferung:\n"
        )
    }

    flagged = pipeline._prune_porta_items_without_explicit_pdf_pairs(  # type: ignore[attr-defined]
        normalized,
        page_texts,
    )

    assert flagged == 0
    header = normalized.get("header") or {}
    review = header.get("human_review_needed") or {}
    assert review.get("value") is not True
    print("SUCCESS: explicit-pair review accepts standalone model-only rows when they exist in PDF text.")


def test_porta_explicit_pair_prune_backfills_liefermodell_article_model_order() -> None:
    normalized = _normalized([_item(1, "", "", menge=2)])
    page_texts = {
        "order-1.png": (
            "2 Stk 3060817 / 13 Liefermodell: Sonate 13505 OGAW819696\n"
            "Anlieferung:\n"
        )
    }

    flagged = pipeline._prune_porta_items_without_explicit_pdf_pairs(  # type: ignore[attr-defined]
        normalized,
        page_texts,
    )

    assert flagged == 0
    item = (normalized.get("items") or [])[0]
    assert (item.get("modellnummer") or {}).get("value") == "OGAW819696"
    assert (item.get("artikelnummer") or {}).get("value") == "13505"
    assert (item.get("modellnummer") or {}).get("derived_from") == "porta_explicit_pair_backfill"
    assert (item.get("artikelnummer") or {}).get("derived_from") == "porta_explicit_pair_backfill"
    print("SUCCESS: explicit-pair prune backfills Liefermodell ARTICLE MODEL order deterministically.")


def test_porta_explicit_pair_prune_backfill_is_idempotent_for_article_model_order() -> None:
    normalized = _normalized([_item(1, "", "", menge=2)])
    page_texts = {
        "order-1.png": (
            "2 Stk 3060817 / 13 Liefermodell: Sonate 13505 OGAW819696\n"
            "Anlieferung:\n"
        )
    }

    flagged_first = pipeline._prune_porta_items_without_explicit_pdf_pairs(  # type: ignore[attr-defined]
        normalized,
        page_texts,
    )
    item_after_first = (normalized.get("items") or [])[0]
    pair_after_first = (
        (item_after_first.get("modellnummer") or {}).get("value"),
        (item_after_first.get("artikelnummer") or {}).get("value"),
    )

    flagged_second = pipeline._prune_porta_items_without_explicit_pdf_pairs(  # type: ignore[attr-defined]
        normalized,
        page_texts,
    )
    item_after_second = (normalized.get("items") or [])[0]
    pair_after_second = (
        (item_after_second.get("modellnummer") or {}).get("value"),
        (item_after_second.get("artikelnummer") or {}).get("value"),
    )

    assert flagged_first == 0
    assert flagged_second == 0
    assert pair_after_first == ("OGAW819696", "13505")
    assert pair_after_second == pair_after_first
    print("SUCCESS: ARTICLE MODEL backfill remains stable across repeated prune passes.")


def test_porta_explicit_pair_prune_accepts_spaced_prefix_fused_code() -> None:
    normalized = _normalized([_item(1, "CQ9696XA", "56062", menge=1)])
    page_texts = {
        "order-1.png": (
            "1 Stk CQ 9696XA56062\n"
            "Anlieferung:\n"
        )
    }

    flagged = pipeline._prune_porta_items_without_explicit_pdf_pairs(  # type: ignore[attr-defined]
        normalized,
        page_texts,
    )

    assert flagged == 0
    header = normalized.get("header") or {}
    review = header.get("human_review_needed") or {}
    assert review.get("value") is not True
    print("SUCCESS: explicit-pair review accepts spaced-prefix fused Porta code without flagging ambiguity.")


def test_porta_model_only_extraction_rejects_descriptor_finish_word() -> None:
    model = pipeline._extract_porta_model_only_token_from_line(  # type: ignore[attr-defined]
        "Kristallspiegel/GL+ZL schwarz matt"
    )

    assert model == ""
    print("SUCCESS: standalone Porta model-only extraction rejects descriptor finish words like MATT.")


def test_porta_typ_adjacent_spaced_model_line_compacts_only_in_typ_context() -> None:
    compact = pipeline._compact_porta_spaced_model_line(  # type: ignore[attr-defined]
        "PD SL 61 SP 96"
    )
    pair = pipeline._extract_porta_typ_adjacent_spaced_model_pair(  # type: ignore[attr-defined]
        [
            "Includo Typ 57382",
            "PD SL 61 SP 96",
            "inkl. schubl 2er set",
        ],
        0,
    )

    assert compact == "PDSL61SP96"
    assert pair == ("PDSL61SP96", "57382")
    assert not pipeline._extract_porta_pdf_pairs_from_line("PD SL 61 SP 96")  # type: ignore[attr-defined]
    print("SUCCESS: spaced Porta model compacts only when consumed from Typ-adjacent context.")


def test_porta_typ_adjacent_spaced_model_region_extracts_expected_pairs_without_matt() -> None:
    page_texts = {
        "order-1.png": (
            "1 4574199 / 04 Liefermodell: Includo PDSL61SP96 57383\n"
            "Includo Typ 57382\n"
            "PD SL 61 SP 96\n"
            "inkl. schubl 2er set\n"
            "T einteilung Stopper\n"
            "Kristallspiegel/GL+ZL schwarz matt\n"
            "Anlieferung:\n"
        )
    }

    occurrences = pipeline._extract_porta_inline_pair_occurrences_from_page_texts(  # type: ignore[attr-defined]
        page_texts
    )
    model_only = pipeline._extract_porta_model_only_occurrences_from_page_texts(  # type: ignore[attr-defined]
        page_texts
    )

    pairs = {
        (
            str(occurrence.get("modellnummer") or ""),
            str(occurrence.get("artikelnummer") or ""),
        )
        for occurrence in occurrences
    }
    assert ("PDSL61SP96", "57383") in pairs
    assert ("PDSL61SP96", "57382") in pairs
    assert not model_only
    print("SUCCESS: Typ-adjacent spaced Porta model produces the expected pairs without a false MATT model-only row.")


def test_porta_typ_adjacent_spaced_model_reconciliation_adds_missing_pair_without_false_model_only() -> None:
    normalized = _normalized([_item(1, "PDSL61SP96", "57383")])
    page_texts = {
        "order-1.png": (
            "1 4574199 / 04 Liefermodell: Includo PDSL61SP96 57383\n"
            "Includo Typ 57382\n"
            "PD SL 61 SP 96\n"
            "inkl. schubl 2er set\n"
            "T einteilung Stopper\n"
            "Kristallspiegel/GL+ZL schwarz matt\n"
            "Anlieferung:\n"
        )
    }

    added = pipeline._reconcile_porta_inline_pair_occurrences(  # type: ignore[attr-defined]
        normalized,
        page_texts,
    )
    model_only_added = pipeline._reconcile_porta_model_only_occurrences(  # type: ignore[attr-defined]
        normalized,
        page_texts,
    )
    flagged = pipeline._prune_porta_items_without_explicit_pdf_pairs(  # type: ignore[attr-defined]
        normalized,
        page_texts,
    )

    assert added == 1
    assert model_only_added == 0
    assert flagged == 0
    items = normalized.get("items") or []
    pairs = {
        (
            str((item.get("modellnummer") or {}).get("value") or ""),
            str((item.get("artikelnummer") or {}).get("value") or ""),
        )
        for item in items
        if isinstance(item, dict)
    }
    assert ("PDSL61SP96", "57383") in pairs
    assert ("PDSL61SP96", "57382") in pairs
    assert ("MATT", "") not in pairs
    warnings = normalized.get("warnings") or []
    assert any("Porta inline pair reconciliation added" in str(w) for w in warnings)
    assert not any("Porta model-only reconciliation added" in str(w) for w in warnings)
    assert not any("Porta explicit-pair review retained" in str(w) for w in warnings)
    print("SUCCESS: Porta reconciliation adds the Typ-adjacent spaced pair and does not create a false MATT model-only row.")


def test_porta_explicit_pair_prune_skips_bestehend_aus_je_orders() -> None:
    normalized = _normalized(
        [
            _item(1, "CQ9191XA", "42889"),
            _item(2, "", "66015"),
            _item(3, "OJ00", "30156"),
            _item(4, "OJ9191", "53669"),
        ]
    )
    page_texts = {
        "order-1.png": (
            "1 4609952 / 04 Liefermodell: Sinfonie Plus CQ9191XA 42889\n"
            "bestehend aus je:\n"
            "1 Stk CQ9191XA 42889\n"
            "1 Stk OJ9191 53669\n"
            "66015\n"
            "30156\n"
            "Anlieferung:\n"
        )
    }

    removed = pipeline._prune_porta_items_without_explicit_pdf_pairs(  # type: ignore[attr-defined]
        normalized,
        page_texts,
    )

    assert removed == 0
    items = normalized.get("items") or []
    assert len(items) == 4
    assert (items[0].get("modellnummer") or {}).get("value") == "CQ9191XA"
    assert (items[1].get("modellnummer") or {}).get("value") == ""
    assert (items[2].get("modellnummer") or {}).get("value") == "OJ00"
    assert (items[3].get("modellnummer") or {}).get("value") == "OJ9191"

    header = normalized.get("header") or {}
    reply = header.get("reply_needed") or {}
    assert reply.get("value") is not True

    warnings = normalized.get("warnings") or []
    assert not any("Porta explicit-pair review retained" in str(w) for w in warnings)
    print("SUCCESS: explicit-pair prune is skipped when 'bestehend aus je:' is present.")


def test_porta_ambiguous_row_kept_while_inline_pair_is_added() -> None:
    normalized = _normalized([_item(1, "PDSL61SP96", "57382")])
    page_texts = {
        "order-1.png": (
            "1 4574199 / 19 Liefermodell: Includo PDSL61SP96 57383\n"
            "Anlieferung:\n"
        )
    }

    added = pipeline._reconcile_porta_inline_pair_occurrences(  # type: ignore[attr-defined]
        normalized,
        page_texts,
    )
    flagged = pipeline._prune_porta_items_without_explicit_pdf_pairs(  # type: ignore[attr-defined]
        normalized,
        page_texts,
    )

    assert added == 1
    assert flagged == 1
    items = normalized.get("items") or []
    assert len(items) == 2
    pairs = {
        (
            str(item.get("modellnummer", {}).get("value", "")),
            str(item.get("artikelnummer", {}).get("value", "")),
        )
        for item in items
        if isinstance(item, dict)
    }
    assert ("PDSL61SP96", "57382") in pairs
    assert ("PDSL61SP96", "57383") in pairs

    header = normalized.get("header") or {}
    review = header.get("human_review_needed") or {}
    assert review.get("value") is True
    assert review.get("derived_from") == "porta_ambiguous_code_human_review"
    reply = header.get("reply_needed") or {}
    assert reply.get("value") is not True
    warnings = normalized.get("warnings") or []
    assert any("Porta inline pair reconciliation added" in str(w) for w in warnings)
    assert any(
        "Human review needed: Porta ambiguous standalone code token(s) retained for human confirmation"
        in str(w)
        for w in warnings
    )
    print("SUCCESS: ambiguous Porta row stays while inline PDF-backed pair is added and flagged for review.")


def test_porta_ambiguous_ignore_warning_forces_human_review() -> None:
    normalized = _normalized(
        [
            _item(1, "CQ9191XA", "42889"),
            _item(2, "OJ9191", "53669"),
        ]
    )
    normalized["warnings"] = [
        "Codes '66015' und '30156+15237' ignoriert (kein expliziter Modellpräfix vorhanden)."
    ]

    changed = pipeline._force_porta_reply_needed_for_ambiguous_ignored_codes(  # type: ignore[attr-defined]
        normalized
    )

    assert changed is True
    header = normalized.get("header") or {}
    review = header.get("human_review_needed") or {}
    assert review.get("value") is True
    assert review.get("derived_from") == "porta_ambiguous_code_human_review"
    reply = header.get("reply_needed") or {}
    assert reply.get("value") is not True
    warnings = normalized.get("warnings") or []
    assert any(
        str(w).startswith("Human review needed: Porta ambiguous standalone code token(s)")
        for w in warnings
    )
    assert any("Porta ambiguous-code human-review trigger activated" in str(w) for w in warnings)
    print("SUCCESS: ambiguous ignore warning path forces human_review_needed for Porta.")


def test_porta_numeric_tokens_without_model_prefix_warning_forces_human_review() -> None:
    normalized = _normalized(
        [
            _item(1, "CQ9191XA", "42889"),
            _item(2, "OJ9191", "53669"),
        ]
    )
    normalized["warnings"] = [
        (
            "Numerische Tokens ohne Modellpr\u00e4fix (z.B. 66015, 30156+15237) "
            "gemaess Regeln nicht als Positionen extrahiert."
        )
    ]

    changed = pipeline._force_porta_reply_needed_for_ambiguous_ignored_codes(  # type: ignore[attr-defined]
        normalized
    )

    assert changed is True
    header = normalized.get("header") or {}
    review = header.get("human_review_needed") or {}
    assert review.get("value") is True
    assert review.get("derived_from") == "porta_ambiguous_code_human_review"
    reply = header.get("reply_needed") or {}
    assert reply.get("value") is not True
    warnings = normalized.get("warnings") or []
    assert any(
        str(w).startswith("Human review needed: Porta ambiguous standalone code token(s)")
        for w in warnings
    )
    assert any("Porta ambiguous-code human-review trigger activated" in str(w) for w in warnings)
    print(
        "SUCCESS: numerische-tokens warning path forces human_review_needed for Porta."
    )


def test_porta_standalone_numeric_rule10_warning_forces_human_review() -> None:
    normalized = _normalized(
        [
            _item(1, "CQ9191XA", "42889"),
            _item(2, "OJ9191", "53669"),
        ]
    )
    normalized["warnings"] = [
        (
            "Standalone numerische Tokens (z.B. 66015, 30156+15237) wurden gemaess Regel 10 "
            "nicht als Positionen extrahiert."
        )
    ]

    changed = pipeline._force_porta_reply_needed_for_ambiguous_ignored_codes(  # type: ignore[attr-defined]
        normalized
    )

    assert changed is True
    header = normalized.get("header") or {}
    review = header.get("human_review_needed") or {}
    assert review.get("value") is True
    assert review.get("derived_from") == "porta_ambiguous_code_human_review"
    reply = header.get("reply_needed") or {}
    assert reply.get("value") is not True
    warnings = normalized.get("warnings") or []
    assert any(
        str(w).startswith("Human review needed: Porta ambiguous standalone code token(s)")
        for w in warnings
    )
    assert any("Porta ambiguous-code human-review trigger activated" in str(w) for w in warnings)
    print("SUCCESS: standalone Regel-10 warning path forces human_review_needed for Porta.")


def test_porta_ambiguous_article_model_rows_set_human_review() -> None:
    normalized = _normalized([_item(1, "", "")])
    page_texts = {
        "order-1.png": (
            "1 Stk 3060817 / 13 Liefermodell: Sonate 13505 OGAW819696\n"
            "Liefermodell: Sonate 13505 OGAW819697\n"
            "Anlieferung:\n"
        )
    }

    flagged = pipeline._prune_porta_items_without_explicit_pdf_pairs(  # type: ignore[attr-defined]
        normalized,
        page_texts,
    )

    assert flagged == 1
    header = normalized.get("header") or {}
    review = header.get("human_review_needed") or {}
    assert review.get("value") is True
    assert review.get("derived_from") == "porta_ambiguous_code_human_review"
    reply = header.get("reply_needed") or {}
    assert reply.get("value") is not True
    item = (normalized.get("items") or [])[0]
    assert (item.get("modellnummer") or {}).get("value") == ""
    assert (item.get("artikelnummer") or {}).get("value") == ""
    warnings = normalized.get("warnings") or []
    assert any(
        "Human review needed: Porta ambiguous standalone code token(s) retained for human confirmation"
        in str(w)
        for w in warnings
    )
    print("SUCCESS: ambiguous ARTICLE MODEL rows stay unfilled and require human review.")


if __name__ == "__main__":
    test_suffix_restoration_sets_review()
    test_multiple_suffix_restorations()
    test_reconciliation_duplicate_prevention()
    test_ambiguity_guard_for_article_suffix()
    test_unique_model_correction_by_article()
    test_ambiguous_model_candidates_no_correction()
    test_component_pair_parser_accepts_hyphen_separator()
    test_component_pair_parser_strips_numeric_x_prefix_from_model()
    test_collect_pairs_strips_numeric_x_prefix_and_keeps_standard_pairs()
    test_collect_pairs_rejects_sonate_4008_and_keeps_valid_pair()
    test_collect_pairs_accepts_liefermodell_article_model_order()
    test_collect_pairs_accepts_spaced_prefix_fused_code()
    test_collect_pairs_accepts_labeled_fused_oj_token()
    test_collect_pairs_accepts_article_prefix_or_suffix_only()
    test_inline_pair_reconciliation_adds_missing_item_non_bestehend()
    test_inline_pair_reconciliation_hyphen_and_space_supported()
    test_inline_pair_reconciliation_idempotent()
    test_inline_pair_reconciliation_skips_footer_legal_tokens()
    test_inline_pair_reconciliation_sets_human_review_and_warning()
    test_inline_pair_reconciliation_skips_qtyless_duplicate_when_pair_exists()
    test_inline_pair_reconciliation_keeps_explicit_qty_non_regression()
    test_inline_pair_reconciliation_rejects_sonate_4008_descriptor()
    test_porta_code_shape_validation_clears_invalid_descriptor_codes()
    test_porta_code_shape_validation_keeps_valid_codes()
    test_porta_code_shape_validation_keeps_prefix_suffix_articles_and_clears_embedded_letter()
    test_porta_code_shape_helpers_accept_and_reject_expected_forms()
    test_porta_code_shape_validation_normalizes_ojoo_to_oj00()
    test_porta_code_shape_validation_splits_fused_oj_model_when_article_missing()
    test_porta_explicit_pair_prune_retains_model_inferred_rows_and_sets_human_review()
    test_porta_article_only_reconciliation_adds_standalone_article_rows()
    test_porta_model_only_reconciliation_adds_standalone_model_rows()
    test_porta_explicit_pair_prune_accepts_article_only_rows()
    test_porta_explicit_pair_prune_accepts_model_only_rows()
    test_porta_explicit_pair_prune_backfills_liefermodell_article_model_order()
    test_porta_explicit_pair_prune_backfill_is_idempotent_for_article_model_order()
    test_porta_explicit_pair_prune_accepts_spaced_prefix_fused_code()
    test_porta_model_only_extraction_rejects_descriptor_finish_word()
    test_porta_typ_adjacent_spaced_model_line_compacts_only_in_typ_context()
    test_porta_typ_adjacent_spaced_model_region_extracts_expected_pairs_without_matt()
    test_porta_typ_adjacent_spaced_model_reconciliation_adds_missing_pair_without_false_model_only()
    test_porta_explicit_pair_prune_skips_bestehend_aus_je_orders()
    test_porta_ambiguous_row_kept_while_inline_pair_is_added()
    test_porta_ambiguous_ignore_warning_forces_human_review()
    test_porta_numeric_tokens_without_model_prefix_warning_forces_human_review()
    test_porta_standalone_numeric_rule10_warning_forces_human_review()
    test_porta_ambiguous_article_model_rows_set_human_review()
