from normalize import normalize_output


def _run_case(modellnummer: str, artikelnummer: str, branch_id: str = "segmuller") -> dict:
    data = {
        "header": {
            "reply_needed": {"value": False, "source": "derived", "confidence": 1.0},
            "human_review_needed": {"value": False, "source": "derived", "confidence": 1.0},
            "post_case": {"value": False, "source": "derived", "confidence": 1.0},
        },
        "items": [
            {
                "line_no": 1,
                "artikelnummer": {"value": artikelnummer, "source": "image", "confidence": 0.9},
                "modellnummer": {"value": modellnummer, "source": "image", "confidence": 0.9},
                "menge": {"value": 1, "source": "image", "confidence": 0.9},
                "furncloud_id": {"value": "", "source": "derived", "confidence": 0.0},
            }
        ],
    }
    normalized = normalize_output(
        data,
        message_id="verify_segmuller_split",
        received_at="2026-02-26T12:00:00+00:00",
        dayfirst=True,
        warnings=[],
        email_body="",
        sender="orders@segmueller.de",
        is_momax_bg=False,
        branch_id=branch_id,
    )
    return (normalized.get("items") or [{}])[0]


def test_segmuller_model_article_split_examples() -> None:
    cases = [
        ("SINUNU0658XB-89320C", "-", "89320C", "SINUNU0658XB"),
        ("ZB00-38337", "-", "38337", "ZB00"),
        ("SI9191XP-04695", "", "04695", "SI9191XP"),
        ("ZB99-14412", "", "14412", "ZB99"),
    ]
    for model_in, article_in, article_out, model_out in cases:
        item = _run_case(model_in, article_in, branch_id="segmuller")
        assert item.get("artikelnummer", {}).get("value") == article_out
        assert item.get("modellnummer", {}).get("value") == model_out
    print("SUCCESS: Segmuller MODEL-ARTICLE values are split into strict artikelnummer/modellnummer.")


def test_segmuller_split_overrides_wrong_existing_article() -> None:
    item = _run_case("ZB00-38337", "46518", branch_id="segmuller")
    assert item.get("artikelnummer", {}).get("value") == "38337"
    assert item.get("modellnummer", {}).get("value") == "ZB00"
    print("SUCCESS: Segmuller split rule overrides mismatched existing artikelnummer.")


def test_non_segmuller_keeps_original_model_value() -> None:
    item = _run_case("ZB00-38337", "", branch_id="xxxlutz_default")
    assert item.get("artikelnummer", {}).get("value") == ""
    assert item.get("modellnummer", {}).get("value") == "ZB00-38337"
    print("SUCCESS: Non-Segmuller branches are unchanged by Segmuller split rule.")


if __name__ == "__main__":
    test_segmuller_model_article_split_examples()
    test_segmuller_split_overrides_wrong_existing_article()
    test_non_segmuller_keeps_original_model_value()
