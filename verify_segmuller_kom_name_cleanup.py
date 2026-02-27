from normalize import normalize_output


def _run_case(kom_name: str, branch_id: str = "segmuller") -> dict:
    data = {
        "header": {
            "kom_name": {"value": kom_name, "source": "pdf", "confidence": 0.95},
            "reply_needed": {"value": False, "source": "derived", "confidence": 1.0},
            "human_review_needed": {"value": False, "source": "derived", "confidence": 1.0},
            "post_case": {"value": False, "source": "derived", "confidence": 1.0},
        },
        "items": [],
    }
    normalized = normalize_output(
        data,
        message_id="verify_segmuller_kom_name",
        received_at="2026-02-27T12:00:00+00:00",
        dayfirst=True,
        warnings=[],
        email_body="",
        sender="orders@segmueller.de",
        is_momax_bg=False,
        branch_id=branch_id,
    )
    return normalized.get("header", {})


def test_segmuller_kom_name_numeric_prefix_removed() -> None:
    header = _run_case("22300 NUESSLER", branch_id="segmuller")
    kom_name = header.get("kom_name", {})
    assert kom_name.get("value") == "NUESSLER"
    assert kom_name.get("derived_from") == "segmuller_kom_name_cleanup"
    print("SUCCESS: Segmuller kom_name strips numeric prefix (22300 NUESSLER -> NUESSLER).")


def test_non_segmuller_keeps_original_kom_name() -> None:
    header = _run_case("22300 NUESSLER", branch_id="xxxlutz_default")
    kom_name = header.get("kom_name", {})
    assert kom_name.get("value") == "22300 NUESSLER"
    print("SUCCESS: Non-Segmuller branch keeps kom_name unchanged.")


if __name__ == "__main__":
    test_segmuller_kom_name_numeric_prefix_removed()
    test_non_segmuller_keeps_original_kom_name()
