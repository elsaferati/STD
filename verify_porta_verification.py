import copy

from item_code_verification import apply_item_code_verification


def test_apply_porta_item_code_verification() -> None:
    normalized = {
        "header": {
            "human_review_needed": {"value": False, "source": "derived", "confidence": 1.0}
        },
        "items": [
            {
                "line_no": 1,
                "artikelnummer": {"value": "A-OLD", "source": "email", "confidence": 0.9},
                "modellnummer": {"value": "M-OLD", "source": "email", "confidence": 0.9},
                "menge": {"value": 1, "source": "email", "confidence": 0.9},
                "furncloud_id": {"value": "", "source": "derived", "confidence": 0.0},
            },
            {
                "line_no": 2,
                "artikelnummer": {"value": "A-2", "source": "email", "confidence": 0.9},
                "modellnummer": {"value": "M-2", "source": "email", "confidence": 0.9},
                "menge": {"value": 2, "source": "email", "confidence": 0.9},
                "furncloud_id": {"value": "", "source": "derived", "confidence": 0.0},
            },
        ],
        "warnings": [],
    }
    verification_data = {
        "verified_items": [
            {
                "line_no": 1,
                "modellnummer": "M-NEW",
                "artikelnummer": "A-NEW",
                "menge": 1,
                "confidence": 0.91,
                "reason": "matches PDF text",
            },
            {
                "line_no": 2,
                "modellnummer": "M-2-LOW",
                "artikelnummer": "A-2-LOW",
                "menge": 2,
                "confidence": 0.50,
                "reason": "uncertain",
            },
        ],
        "warnings": [],
    }

    before = copy.deepcopy(normalized)
    changed = apply_item_code_verification(normalized, verification_data, confidence_threshold=0.75)

    assert changed is True
    item_1 = normalized["items"][0]
    assert item_1["modellnummer"]["value"] == "M-NEW"
    assert item_1["modellnummer"]["derived_from"] == "porta_item_code_verification"
    assert item_1["artikelnummer"]["value"] == "A-NEW"
    assert item_1["artikelnummer"]["derived_from"] == "porta_item_code_verification"

    item_2 = normalized["items"][1]
    assert item_2["modellnummer"]["value"] == before["items"][1]["modellnummer"]["value"]
    assert item_2["artikelnummer"]["value"] == before["items"][1]["artikelnummer"]["value"]

    review_flag = normalized["header"]["human_review_needed"]["value"]
    review_source = normalized["header"]["human_review_needed"].get("derived_from")
    warnings = normalized.get("warnings") or []
    assert review_flag is True
    assert review_source == "porta_item_code_verification"
    assert any("Porta verification corrected item line 1 field artikelnummer" in str(w) for w in warnings)
    assert any("Porta verification applied automatic item-code correction(s)" in str(w) for w in warnings)
    print("SUCCESS: Porta verification applies high-confidence corrections and forces human review.")


if __name__ == "__main__":
    test_apply_porta_item_code_verification()
