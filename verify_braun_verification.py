from item_code_verification import apply_item_code_verification


def test_apply_braun_item_code_verification() -> None:
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
            }
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
                "confidence": 0.95,
                "reason": "digital PDF text confirmed code characters",
            }
        ],
        "warnings": [],
    }

    changed = apply_item_code_verification(
        normalized,
        verification_data,
        confidence_threshold=0.75,
        verification_profile="braun",
    )

    assert changed is True
    item_1 = normalized["items"][0]
    assert item_1["modellnummer"]["value"] == "M-NEW"
    assert item_1["modellnummer"]["derived_from"] == "braun_item_code_verification"
    assert item_1["artikelnummer"]["value"] == "A-NEW"
    assert item_1["artikelnummer"]["derived_from"] == "braun_item_code_verification"

    review_entry = normalized["header"]["human_review_needed"]
    warnings = normalized.get("warnings") or []
    assert review_entry.get("value") is True
    assert review_entry.get("derived_from") == "braun_item_code_verification"
    assert any("Braun verification corrected item line 1 field artikelnummer" in str(w) for w in warnings)
    assert any("Braun verification applied automatic item-code correction(s)" in str(w) for w in warnings)
    print("SUCCESS: Braun verification applies high-confidence corrections and forces human review.")


if __name__ == "__main__":
    test_apply_braun_item_code_verification()
