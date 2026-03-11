from segmuller_rules import summarize_vendor_sections


def test_mixed_vendor_sections_detect_staud_and_non_staud() -> None:
    summary = summarize_vendor_sections(
        {
            "Bestellung_page_1": (
                "B E S T E L L U N G\n"
                "Pos Upo Seg-Nr. Ihre Art.-Nr.\n"
                "001 000 2148807    14 Sinfonie Plus SINFONIE      Stueck      1,00\n"
            ),
            "Skizze_page_1": (
                "Wiemann Phoenix (Seg.Nr. 3857141)\n"
                "1 B36H49 Schwebetuerenschrank\n"
                "Stäud Sinfonie Plus (Seg.Nr. 2148807)\n"
                "1 SINU1699-44168G Kombikommode\n"
            ),
        }
    )

    assert summary.vendor_sections_found is True
    assert summary.staud_section_found is True
    assert summary.matched_staud_section_found is True
    assert summary.non_staud_vendors == ("Wiemann",)


def test_non_staud_only_sections_mark_staud_absent() -> None:
    summary = summarize_vendor_sections(
        {
            "Bestellung_page_1": (
                "B E S T E L L U N G\n"
                "Pos Upo Seg-Nr. Ihre Art.-Nr.\n"
                "001 000 2148807    14 Sinfonie Plus SINFONIE      Stueck      1,00\n"
            ),
            "Skizze_page_1": (
                "Wiemann Phoenix (Seg.Nr. 2148807)\n"
                "1 B36H49 Schwebetuerenschrank\n"
            ),
        }
    )

    assert summary.vendor_sections_found is True
    assert summary.staud_section_found is False
    assert summary.matched_staud_section_found is False
    assert summary.non_staud_vendors == ("Wiemann",)


def test_ocr_variant_wiemman_is_non_staud() -> None:
    summary = summarize_vendor_sections(
        {
            "Skizze_page_1": (
                "Wiemman Phoenix (Seg.Nr. 2148807)\n"
                "1 B36H49 Schwebetuerenschrank\n"
            ),
        }
    )

    assert summary.vendor_sections_found is True
    assert summary.staud_section_found is False
    assert summary.non_staud_vendors == ("Wiemman",)


if __name__ == "__main__":
    test_mixed_vendor_sections_detect_staud_and_non_staud()
    test_non_staud_only_sections_mark_staud_absent()
    test_ocr_variant_wiemman_is_non_staud()
    print("SUCCESS: Segmuller vendor section summary detects Staud vs non-Staud furnplan blocks.")
