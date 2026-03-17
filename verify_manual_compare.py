from __future__ import annotations

import json
from unittest.mock import patch

import order_store


ORDER_ID = "manual-compare-order"


def _entry(value: str) -> dict[str, object]:
    return {
        "value": value,
        "source": "manual" if value else "pdf",
        "confidence": 1.0 if value else 0.0,
        "derived_from": "manual_edit" if value else "",
    }


def _item(artikelnummer: str, modellnummer: str, menge: str, furncloud_id: str, line_no: int) -> dict[str, object]:
    return {
        "line_no": line_no,
        "artikelnummer": _entry(artikelnummer),
        "modellnummer": _entry(modellnummer),
        "menge": _entry(menge),
        "furncloud_id": _entry(furncloud_id),
    }


def _payload(*, kom_name: str = "JANKER", kundennummer: str = "21653", items: list[dict[str, object]]) -> dict[str, object]:
    return {
        "header": {
            "kom_name": _entry(kom_name),
            "kundennummer": _entry(kundennummer),
        },
        "items": items,
        "warnings": [],
        "errors": [],
        "status": "human_in_the_loop",
        "extraction_branch": "xxxlutz_default",
    }


def _revision(
    revision_no: int,
    change_type: str,
    payload: dict[str, object],
    diff_json: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "id": f"rev-{revision_no}",
        "revision_no": revision_no,
        "change_type": change_type,
        "payload_json": json.dumps(payload),
        "diff_json": json.dumps(diff_json or {}),
        "created_at": None,
    }


def _revision_rows() -> list[dict[str, object]]:
    base_items = [
        _item("78710", "PD917191SP91", "1", "jf2hjb7f", 1),
        _item("12345", "ABC", "2", "delrow", 2),
    ]
    rev1_payload = _payload(items=base_items)
    rev2_payload = _payload(
        kom_name="JANKER GmbH",
        items=[
            _item("78710", "PD917191SP92", "1", "jf2hjb7f", 1),
            _item("99999", "NEW-1", "1", "newrow", 2),
        ],
    )
    rev3_payload = _payload(
        kom_name="JANKER GmbH",
        kundennummer="21654",
        items=[
            _item("78710", "PD917191SP92", "1", "jf2hjb7f", 1),
            _item("99999", "NEW-1", "3", "newrow", 2),
        ],
    )
    return [
        _revision(1, "ingested", rev1_payload),
        _revision(
            2,
            "manual_edit",
            rev2_payload,
            {
                "header": {"kom_name": "JANKER GmbH"},
                "items": {"0": {"modellnummer": "PD917191SP92"}},
                "deleted_item_indexes": [1],
                "new_items": [
                    {
                        "line_no": 2,
                        "artikelnummer": "99999",
                        "modellnummer": "NEW-1",
                        "menge": "1",
                        "furncloud_id": "newrow",
                    },
                ],
            },
        ),
        _revision(
            3,
            "manual_edit",
            rev3_payload,
            {
                "header": {"kundennummer": "21654"},
                "items": {"1": {"menge": "3"}},
                "deleted_item_indexes": [],
                "new_items": [],
            },
        ),
    ]


def test_first_manual_header_edit_returns_correct_header_changes() -> None:
    rows = _revision_rows()[:2]
    with patch("order_store.fetch_all", return_value=rows):
        compare = order_store.build_manual_compare(ORDER_ID)
    assert compare is not None
    baseline = compare["baselines"]["original_extraction"]
    assert baseline["header_changes"] == {
        "kom_name": {"before": "JANKER", "after": "JANKER GmbH"},
    }
    assert baseline["header_snapshot"]["kom_name"]["value"] == "JANKER"


def test_first_manual_item_edit_returns_modified_added_and_deleted_rows() -> None:
    rows = _revision_rows()[:2]
    with patch("order_store.fetch_all", return_value=rows):
        compare = order_store.build_manual_compare(ORDER_ID)
    assert compare is not None

    original = compare["baselines"]["original_extraction"]
    assert original["counts"] == {
        "header_fields": 1,
        "modified_item_rows": 1,
        "added_item_rows": 1,
        "deleted_item_rows": 1,
    }
    assert original["item_snapshot"][0]["modellnummer"]["value"] == "PD917191SP91"
    assert original["item_changes_by_baseline_index"] == {
        "0": {
            "row_status": "modified",
            "field_changes": {
                "modellnummer": {"before": "PD917191SP91", "after": "PD917191SP92"},
            },
            "current_index": 0,
            "current_line_no": 1,
        },
        "1": {
            "row_status": "deleted",
            "field_changes": {},
            "current_index": None,
            "current_line_no": None,
        },
    }
    assert original["added_rows"] == [
        {
            "row_status": "added",
            "current_index": 1,
            "current_line_no": 2,
            "values": {
                "artikelnummer": "99999",
                "modellnummer": "NEW-1",
                "menge": "1",
                "furncloud_id": "newrow",
            },
        },
    ]


def test_previous_revision_compare_is_limited_to_latest_manual_save() -> None:
    with patch("order_store.fetch_all", return_value=_revision_rows()):
        compare = order_store.build_manual_compare(ORDER_ID)
    assert compare is not None

    previous = compare["baselines"]["previous_revision"]
    assert previous["header_changes"] == {
        "kundennummer": {"before": "21653", "after": "21654"},
    }
    assert previous["counts"] == {
        "header_fields": 1,
        "modified_item_rows": 1,
        "added_item_rows": 0,
        "deleted_item_rows": 0,
    }
    assert previous["item_snapshot"][1]["menge"]["value"] == "1"
    assert previous["item_changes_by_baseline_index"] == {
        "1": {
            "row_status": "modified",
            "field_changes": {
                "menge": {"before": "1", "after": "3"},
            },
            "current_index": 1,
            "current_line_no": 2,
        },
    }
    assert previous["added_rows"] == []


def test_original_extraction_compare_stays_cumulative_against_revision_one() -> None:
    with patch("order_store.fetch_all", return_value=_revision_rows()):
        compare = order_store.build_manual_compare(ORDER_ID)
    assert compare is not None

    original = compare["baselines"]["original_extraction"]
    assert original["header_changes"] == {
        "kom_name": {"before": "JANKER", "after": "JANKER GmbH"},
        "kundennummer": {"before": "21653", "after": "21654"},
    }
    assert original["counts"] == {
        "header_fields": 2,
        "modified_item_rows": 1,
        "added_item_rows": 1,
        "deleted_item_rows": 1,
    }
    assert original["item_snapshot"][1]["artikelnummer"]["value"] == "12345"


def test_no_manual_saves_returns_no_manual_compare() -> None:
    with patch("order_store.fetch_all", return_value=_revision_rows()[:1]):
        compare = order_store.build_manual_compare(ORDER_ID)
    assert compare is None


if __name__ == "__main__":
    test_first_manual_header_edit_returns_correct_header_changes()
    test_first_manual_item_edit_returns_modified_added_and_deleted_rows()
    test_previous_revision_compare_is_limited_to_latest_manual_save()
    test_original_extraction_compare_stays_cumulative_against_revision_one()
    test_no_manual_saves_returns_no_manual_compare()
