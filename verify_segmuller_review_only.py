from normalize import normalize_output, refresh_missing_warnings
from pipeline import _apply_segmuller_vendor_section_guard


def test_segmuller_missing_layout_stays_review_only() -> None:
    data = {
        "header": {
            "reply_needed": {"value": False, "source": "derived", "confidence": 1.0},
            "human_review_needed": {"value": False, "source": "derived", "confidence": 1.0},
            "post_case": {"value": False, "source": "derived", "confidence": 1.0},
        },
        "items": [
            {
                "line_no": 1,
                "artikelnummer": {"value": "", "source": "image", "confidence": 0.0},
                "modellnummer": {"value": "", "source": "image", "confidence": 0.0},
                "menge": {"value": 1, "source": "image", "confidence": 1.0},
                "furncloud_id": {"value": "", "source": "derived", "confidence": 0.0},
            }
        ],
    }

    normalized = normalize_output(
        data,
        message_id="verify_segmuller_review_only",
        received_at="2026-03-07T12:00:00+00:00",
        dayfirst=True,
        warnings=[],
        email_body="",
        sender="orders@segmueller.de",
        is_momax_bg=False,
        branch_id="segmuller",
    )

    assert normalized["status"] == "reply"
    header = normalized["header"]
    assert header["reply_needed"]["value"] is True

    header["human_review_needed"] = {
        "value": True,
        "source": "derived",
        "confidence": 1.0,
        "derived_from": "segmuller_missing_furnplan_pdf",
    }
    normalized["extraction_branch"] = "segmuller"

    refresh_missing_warnings(normalized)

    assert normalized["status"] == "human_in_the_loop"
    assert normalized["header"]["reply_needed"]["value"] is False
    warnings = normalized.get("warnings") or []
    assert not any(
        str(w).startswith("Reply needed: Missing critical item fields:")
        for w in warnings
    )
    print("SUCCESS: Segmuller missing layout review path clears reply_needed and keeps human_in_the_loop.")


def test_segmuller_no_staud_section_stays_review_only() -> None:
    data = {
        "header": {
            "reply_needed": {"value": False, "source": "derived", "confidence": 1.0},
            "human_review_needed": {"value": False, "source": "derived", "confidence": 1.0},
            "post_case": {"value": False, "source": "derived", "confidence": 1.0},
        },
        "items": [],
    }

    normalized = normalize_output(
        data,
        message_id="verify_segmuller_no_staud",
        received_at="2026-03-07T12:00:00+00:00",
        dayfirst=True,
        warnings=[],
        email_body="",
        sender="orders@segmueller.de",
        is_momax_bg=False,
        branch_id="segmuller",
    )

    assert normalized["status"] == "reply"
    assert normalized["header"]["reply_needed"]["value"] is True

    _apply_segmuller_vendor_section_guard(
        normalized,
        {
            "Bestellung_page_1": (
                "B E S T E L L U N G\n"
                "Pos Upo Seg-Nr. Ihre Art.-Nr.\n"
                "001 000 2148807    14 Sinfonie Plus SINFONIE      Stueck      1,00\n"
            ),
            "Skizze_page_1": (
                "Wiemann Phoenix (Seg.Nr. 2148807)\n"
                "1 B36H49 Schwebetuerenschrank\n"
            ),
        },
    )
    normalized["extraction_branch"] = "segmuller"

    refresh_missing_warnings(normalized)

    assert normalized["status"] == "human_in_the_loop"
    assert normalized["header"]["reply_needed"]["value"] is False
    assert (
        normalized["header"]["human_review_needed"]["derived_from"]
        == "segmuller_no_staud_section"
    )
    warnings = normalized.get("warnings") or []
    assert any("no Staud vendor section" in str(w) for w in warnings)
    print("SUCCESS: Segmuller no-Staud review path clears reply_needed and keeps human_in_the_loop.")


def test_segmuller_mixed_vendor_warning_without_review() -> None:
    normalized = {
        "header": {
            "reply_needed": {"value": False, "source": "derived", "confidence": 1.0},
            "human_review_needed": {"value": False, "source": "derived", "confidence": 1.0},
            "post_case": {"value": False, "source": "derived", "confidence": 1.0},
        },
        "items": [
            {
                "line_no": 1,
                "artikelnummer": {"value": "44168G", "source": "image", "confidence": 0.8},
                "modellnummer": {"value": "SINU1699", "source": "image", "confidence": 0.8},
                "menge": {"value": 1, "source": "image", "confidence": 1.0},
                "furncloud_id": {"value": "", "source": "derived", "confidence": 0.0},
            }
        ],
    }

    _apply_segmuller_vendor_section_guard(
        normalized,
        {
            "Bestellung_page_1": (
                "B E S T E L L U N G\n"
                "Pos Upo Seg-Nr. Ihre Art.-Nr.\n"
                "001 000 2148807    14 Sinfonie Plus SINFONIE      Stueck      1,00\n"
            ),
            "Skizze_page_1": (
                "Wiemman Phoenix (Seg.Nr. 3857141)\n"
                "1 B36H49 Schwebetuerenschrank\n"
                "Staud Sinfonie Plus (Seg.Nr. 2148807)\n"
                "1 SINU1699-44168G Kombikommode\n"
            ),
        },
    )

    header = normalized["header"]
    assert header["human_review_needed"]["value"] is False
    warnings = normalized.get("warnings") or []
    assert any("ignored: Wiemman" in str(w) for w in warnings)
    print("SUCCESS: Segmuller mixed-vendor furnplan ignores non-Staud sections without forcing review.")


if __name__ == "__main__":
    test_segmuller_missing_layout_stays_review_only()
    test_segmuller_no_staud_section_stays_review_only()
    test_segmuller_mixed_vendor_warning_without_review()
