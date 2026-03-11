from email_ingest import Attachment
from segmuller_rules import has_supporting_layout_pdf


def _pdf(name: str) -> Attachment:
    return Attachment(filename=name, content_type="application/pdf", data=b"%PDF-1.4")


def test_segmuller_requires_second_pdf() -> None:
    assert has_supporting_layout_pdf([_pdf("Bestellung_150160748001.pdf")], is_pdf=lambda _: True) is False
    print("SUCCESS: single Segmuller order PDF is treated as missing furnplan/sketch support.")


def test_segmuller_accepts_order_plus_supporting_pdf() -> None:
    attachments = [
        _pdf("Bestellung_150160748001.pdf"),
        _pdf("E19RUF83.PDF"),
    ]
    assert has_supporting_layout_pdf(attachments, is_pdf=lambda _: True) is True
    print("SUCCESS: Segmuller order PDF plus second supporting PDF satisfies the guard.")


def test_segmuller_rejects_multiple_order_pdfs_without_layout() -> None:
    attachments = [
        _pdf("Bestellung_150160748001.pdf"),
        _pdf("Bestellung_150160748002.pdf"),
    ]
    assert has_supporting_layout_pdf(attachments, is_pdf=lambda _: True) is False
    print("SUCCESS: multiple Segmuller order PDFs without a supporting PDF still require human review.")


if __name__ == "__main__":
    test_segmuller_requires_second_pdf()
    test_segmuller_accepts_order_plus_supporting_pdf()
    test_segmuller_rejects_multiple_order_pdfs_without_layout()
