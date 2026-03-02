from normalize import normalize_output


def _make_data(lieferanschrift_value: str, store_address_value: str | None = None) -> dict:
    header = {
        "lieferanschrift": {"value": lieferanschrift_value, "source": "pdf", "confidence": 0.95}
    }
    if store_address_value is not None:
        header["store_address"] = {
            "value": store_address_value,
            "source": "pdf",
            "confidence": 0.95,
        }
    return {
        "header": header,
        "items": [
            {
                "line_no": 1,
                "artikelnummer": {"value": "A1", "source": "pdf", "confidence": 1.0},
                "modellnummer": {"value": "M1", "source": "pdf", "confidence": 1.0},
                "menge": {"value": 1, "source": "pdf", "confidence": 1.0},
                "furncloud_id": {"value": "abcd ef12", "source": "pdf", "confidence": 1.0},
            }
        ],
    }


def _normalize_header_for_branch(
    lieferanschrift_value: str,
    branch_id: str,
    store_address_value: str | None = None,
) -> dict:
    warnings: list[str] = []
    normalized = normalize_output(
        _make_data(lieferanschrift_value, store_address_value=store_address_value),
        message_id="msg-1",
        received_at="2026-02-24T00:00:00Z",
        dayfirst=True,
        warnings=warnings,
        email_body="",
        sender="",
        is_momax_bg=False,
        branch_id=branch_id,
    )
    return normalized["header"]


def _normalize_for_branch(lieferanschrift_value: str, branch_id: str) -> str:
    return _normalize_header_for_branch(lieferanschrift_value, branch_id)["lieferanschrift"]["value"]


def test_porta_removes_company_prefix_line() -> None:
    value = "Lager Porta Möbel Görlitz\nRobert-Bosch Str.1\n02828 Goerlitz/Klingewalde"
    got = _normalize_for_branch(value, "porta")
    assert got == "Robert-Bosch Str. 1\n02828 Goerlitz/Klingewalde"
    print("SUCCESS: Porta removes company line from lieferanschrift.")


def test_porta_removes_iln_and_company_lines() -> None:
    value = "Anlieferung:\n4040051001140\nLager Porta Möbel Görlitz\nRobert-Bosch Str.1\n02828 Goerlitz/Klingewalde"
    got = _normalize_for_branch(value, "porta")
    assert got == "Robert-Bosch Str. 1\n02828 Goerlitz/Klingewalde"
    print("SUCCESS: Porta removes ILN and company lines from lieferanschrift.")


def test_porta_keeps_clean_two_line_address() -> None:
    value = "Robert-Bosch Str.1\n02828 Goerlitz/Klingewalde"
    got = _normalize_for_branch(value, "porta")
    assert got == "Robert-Bosch Str. 1\n02828 Goerlitz/Klingewalde"
    print("SUCCESS: Porta keeps clean two-line lieferanschrift unchanged.")


def test_porta_fallback_preserves_ambiguous_raw_text() -> None:
    value = "Lager Porta Möbel Görlitz"
    got = _normalize_for_branch(value, "porta")
    assert got == value
    print("SUCCESS: Porta fallback keeps ambiguous lieferanschrift raw text.")


def test_non_porta_regression_behavior_unchanged() -> None:
    value = "Lager Porta Möbel Görlitz\nRobert-Bosch Str.1\n02828 Goerlitz/Klingewalde"
    got = _normalize_for_branch(value, "xxxlutz_default")
    assert "Lager Porta" in got
    assert "Robert-Bosch" in got
    assert "02828" in got
    print("SUCCESS: Non-Porta behavior unchanged for lieferanschrift.")


def test_porta_store_address_fallback_from_lieferanschrift_when_missing() -> None:
    value = "Robert-Bosch Str.1\n02828 Goerlitz/Klingewalde"
    header = _normalize_header_for_branch(value, "porta", store_address_value=None)
    store_entry = header["store_address"]
    assert store_entry["value"] == "Robert-Bosch Str. 1\n02828 Goerlitz/Klingewalde"
    assert store_entry["source"] == "derived"
    assert store_entry["confidence"] == 1.0
    assert store_entry.get("derived_from") == "porta_store_address_from_lieferanschrift"
    print("SUCCESS: Porta fills missing store_address from lieferanschrift.")


def test_porta_explicit_store_address_is_preserved() -> None:
    liefer = "Robert-Bosch Str.1\n02828 Goerlitz/Klingewalde"
    store = "Europaallee 1\n50226 Frechen"
    header = _normalize_header_for_branch(liefer, "porta", store_address_value=store)
    store_entry = header["store_address"]
    store_value = str(store_entry["value"] or "")
    assert "Europaallee" in store_value
    assert "50226 Frechen" in store_value
    assert store_entry.get("derived_from") != "porta_store_address_from_lieferanschrift"
    print("SUCCESS: Porta keeps explicit store_address unchanged.")


def test_porta_matching_store_and_delivery_is_not_cleared() -> None:
    value = "Robert-Bosch Str.1\n02828 Goerlitz/Klingewalde"
    header = _normalize_header_for_branch(value, "porta", store_address_value=value)
    store_entry = header["store_address"]
    store_value = str(store_entry["value"] or "")
    assert store_value != ""
    assert "Robert-Bosch" in store_value
    assert "Goerlitz/Klingewalde" in store_value
    assert store_entry.get("derived_from") != "porta_store_address_from_lieferanschrift"
    print("SUCCESS: Porta no longer clears store_address when it matches lieferanschrift.")


def test_non_porta_missing_store_address_does_not_fallback() -> None:
    value = "Robert-Bosch Str.1\n02828 Goerlitz/Klingewalde"
    header = _normalize_header_for_branch(value, "xxxlutz_default", store_address_value=None)
    store_entry = header["store_address"]
    assert store_entry["value"] == ""
    print("SUCCESS: Non-Porta branch keeps missing store_address empty.")


if __name__ == "__main__":
    test_porta_removes_company_prefix_line()
    test_porta_removes_iln_and_company_lines()
    test_porta_keeps_clean_two_line_address()
    test_porta_fallback_preserves_ambiguous_raw_text()
    test_non_porta_regression_behavior_unchanged()
    test_porta_store_address_fallback_from_lieferanschrift_when_missing()
    test_porta_explicit_store_address_is_preserved()
    test_porta_matching_store_and_delivery_is_not_cleared()
    test_non_porta_missing_store_address_does_not_fallback()
