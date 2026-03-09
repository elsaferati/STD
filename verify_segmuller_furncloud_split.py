from normalize import normalize_output


def _run_case(
    item_furncloud_id: str,
    branch_id: str = "segmuller",
    program_furncloud_id: str = "",
) -> dict:
    data = {
        "header": {
            "reply_needed": {"value": False, "source": "derived", "confidence": 1.0},
            "human_review_needed": {"value": False, "source": "derived", "confidence": 1.0},
            "post_case": {"value": False, "source": "derived", "confidence": 1.0},
        },
        "program": {
            "furncloud_id": program_furncloud_id,
        },
        "items": [
            {
                "line_no": 1,
                "artikelnummer": {"value": "38337", "source": "image", "confidence": 0.9},
                "modellnummer": {"value": "ZB00", "source": "image", "confidence": 0.9},
                "menge": {"value": 1, "source": "image", "confidence": 0.9},
                "furncloud_id": {
                    "value": item_furncloud_id,
                    "source": "image" if item_furncloud_id else "derived",
                    "confidence": 0.9 if item_furncloud_id else 0.0,
                },
            }
        ],
    }
    return normalize_output(
        data,
        message_id="verify_segmuller_furncloud_split",
        received_at="2026-03-09T12:00:00+00:00",
        dayfirst=True,
        warnings=[],
        email_body="",
        sender="orders@segmueller.de",
        is_momax_bg=False,
        branch_id=branch_id,
    )


def test_segmuller_splits_compact_item_furncloud_id() -> None:
    normalized = _run_case("sqais3k7", branch_id="segmuller")
    item = (normalized.get("items") or [{}])[0]
    furncloud = item.get("furncloud_id", {})
    assert furncloud.get("value") == "sqai s3k7"
    assert furncloud.get("derived_from") == "segmuller_furncloud_id_split"
    print("SUCCESS: Segmuller compact item furncloud_id is split into two 4-character groups.")


def test_segmuller_splits_compact_program_furncloud_id_for_items_and_export() -> None:
    normalized = _run_case("", branch_id="segmuller", program_furncloud_id="sqais3k7")
    item = (normalized.get("items") or [{}])[0]
    assert item.get("furncloud_id", {}).get("value") == "sqai s3k7"
    assert (normalized.get("program") or {}).get("furncloud_id") == "sqai s3k7"
    print("SUCCESS: Segmuller compact program furncloud_id is normalized before item propagation/export.")


def test_non_segmuller_keeps_compact_furncloud_id() -> None:
    normalized = _run_case("sqais3k7", branch_id="xxxlutz_default")
    item = (normalized.get("items") or [{}])[0]
    assert item.get("furncloud_id", {}).get("value") == "sqais3k7"
    print("SUCCESS: Non-Segmuller branches keep compact furncloud_id values unchanged.")


if __name__ == "__main__":
    test_segmuller_splits_compact_item_furncloud_id()
    test_segmuller_splits_compact_program_furncloud_id_for_items_and_export()
    test_non_segmuller_keeps_compact_furncloud_id()
