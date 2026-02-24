from normalize import normalize_output


def _make_data(lieferanschrift_value: str) -> dict:
    return {
        "header": {
            "lieferanschrift": {"value": lieferanschrift_value, "source": "pdf", "confidence": 0.95}
        },
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


def _normalize_for_branch(lieferanschrift_value: str, branch_id: str) -> str:
    warnings: list[str] = []
    normalized = normalize_output(
        _make_data(lieferanschrift_value),
        message_id="msg-1",
        received_at="2026-02-24T00:00:00Z",
        dayfirst=True,
        warnings=warnings,
        email_body="",
        sender="",
        is_momax_bg=False,
        branch_id=branch_id,
    )
    return normalized["header"]["lieferanschrift"]["value"]


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


if __name__ == "__main__":
    test_porta_removes_company_prefix_line()
    test_porta_removes_iln_and_company_lines()
    test_porta_keeps_clean_two_line_address()
    test_porta_fallback_preserves_ambiguous_raw_text()
    test_non_porta_regression_behavior_unchanged()
