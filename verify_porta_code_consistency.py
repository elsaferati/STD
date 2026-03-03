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


def test_porta_explicit_pair_prune_drops_ambiguous_rows_and_forces_reply() -> None:
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

    removed = pipeline._prune_porta_items_without_explicit_pdf_pairs(  # type: ignore[attr-defined]
        normalized,
        page_texts,
    )

    assert removed == 3
    items = normalized.get("items") or []
    assert len(items) == 2
    assert items[0].get("line_no") == 1
    assert items[1].get("line_no") == 2
    assert (items[0].get("modellnummer") or {}).get("value") == "CQ9191XA"
    assert (items[0].get("artikelnummer") or {}).get("value") == "42889"
    assert (items[1].get("modellnummer") or {}).get("value") == "OJ9191"
    assert (items[1].get("artikelnummer") or {}).get("value") == "53669"

    header = normalized.get("header") or {}
    reply = header.get("reply_needed") or {}
    review = header.get("human_review_needed") or {}
    assert reply.get("value") is True
    assert reply.get("derived_from") == "porta_ambiguous_code_reply_needed"
    assert review.get("value") is True
    assert review.get("derived_from") == "porta_explicit_pair_prune"

    warnings = normalized.get("warnings") or []
    assert any(
        "Reply needed: Porta ambiguous standalone code token(s) removed" in str(w)
        for w in warnings
    )
    assert any("Porta explicit-pair prune removed" in str(w) for w in warnings)
    print("SUCCESS: explicit-pair prune drops ambiguous rows and forces reply_needed.")


def test_porta_ambiguous_ignore_warning_forces_reply_needed() -> None:
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
    reply = header.get("reply_needed") or {}
    review = header.get("human_review_needed") or {}
    assert reply.get("value") is True
    assert reply.get("derived_from") == "porta_ambiguous_code_reply_needed"
    assert review.get("value") is True
    warnings = normalized.get("warnings") or []
    assert any(
        str(w).startswith("Reply needed: Porta ambiguous standalone code token(s)")
        for w in warnings
    )
    assert any("Porta ambiguous-code reply trigger activated" in str(w) for w in warnings)
    print("SUCCESS: ambiguous ignore warning path forces reply_needed for Porta.")


def test_porta_numeric_tokens_without_model_prefix_warning_forces_reply_needed() -> None:
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
    reply = header.get("reply_needed") or {}
    review = header.get("human_review_needed") or {}
    assert reply.get("value") is True
    assert reply.get("derived_from") == "porta_ambiguous_code_reply_needed"
    assert review.get("value") is True
    warnings = normalized.get("warnings") or []
    assert any(
        str(w).startswith("Reply needed: Porta ambiguous standalone code token(s)")
        for w in warnings
    )
    assert any("Porta ambiguous-code reply trigger activated" in str(w) for w in warnings)
    print(
        "SUCCESS: numerische-tokens warning path forces reply_needed for Porta."
    )


def test_porta_standalone_numeric_rule10_warning_forces_reply_needed() -> None:
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
    reply = header.get("reply_needed") or {}
    review = header.get("human_review_needed") or {}
    assert reply.get("value") is True
    assert reply.get("derived_from") == "porta_ambiguous_code_reply_needed"
    assert review.get("value") is True
    warnings = normalized.get("warnings") or []
    assert any(
        str(w).startswith("Reply needed: Porta ambiguous standalone code token(s)")
        for w in warnings
    )
    assert any("Porta ambiguous-code reply trigger activated" in str(w) for w in warnings)
    print("SUCCESS: standalone Regel-10 warning path forces reply_needed for Porta.")


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
    test_inline_pair_reconciliation_adds_missing_item_non_bestehend()
    test_inline_pair_reconciliation_hyphen_and_space_supported()
    test_inline_pair_reconciliation_idempotent()
    test_inline_pair_reconciliation_skips_footer_legal_tokens()
    test_inline_pair_reconciliation_sets_human_review_and_warning()
    test_porta_explicit_pair_prune_drops_ambiguous_rows_and_forces_reply()
    test_porta_ambiguous_ignore_warning_forces_reply_needed()
    test_porta_numeric_tokens_without_model_prefix_warning_forces_reply_needed()
    test_porta_standalone_numeric_rule10_warning_forces_reply_needed()
