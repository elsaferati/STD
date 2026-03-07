from normalize import normalize_output, refresh_missing_warnings


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


if __name__ == "__main__":
    test_segmuller_missing_layout_stays_review_only()
