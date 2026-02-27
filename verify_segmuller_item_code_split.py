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


def test_segmuller_does_not_modify_item_codes() -> None:
    cases = [
        ("SINUNU0658XB-89320C", "-"),
        ("ZB00-38337", "46518"),
        ("", "ZB99-56848"),
        ("", "ZB99/56848"),
        ("", "SIEG9199-44182G"),
        ("56847-ZB99", ""),
        ("12345-AB12", ""),
    ]
    for model_in, article_in in cases:
        item = _run_case(model_in, article_in, branch_id="segmuller")
        artikel = item.get("artikelnummer", {})
        modell = item.get("modellnummer", {})
        assert artikel.get("value") == article_in
        assert modell.get("value") == model_in
        assert artikel.get("source") == "image"
        assert modell.get("source") == "image"
    print("SUCCESS: Segmuller item codes remain unchanged in normalize; splitting is prompt-driven.")


def test_non_segmuller_also_keeps_original_values() -> None:
    item = _run_case("ZB00-38337", "", branch_id="xxxlutz_default")
    assert item.get("artikelnummer", {}).get("value") == ""
    assert item.get("modellnummer", {}).get("value") == "ZB00-38337"
    print("SUCCESS: Non-Segmuller branch behavior remains unchanged.")


if __name__ == "__main__":
    test_segmuller_does_not_modify_item_codes()
    test_non_segmuller_also_keeps_original_values()
