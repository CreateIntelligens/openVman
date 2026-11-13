import pytest

from knowledge.converters import SUPPORTED_SUFFIXES, convert_to_text

pymupdf = pytest.importorskip("pymupdf")


def test_pdf_pages_become_text(tmp_path):
    # PyMuPDF 曾經沒裝進 image，Brain 的 PDF 匯入一直失敗。
    path = tmp_path / "catalog.pdf"
    document = pymupdf.open()
    for line in ("EUS series 1 HP", "Warranty: one year"):
        page = document.new_page()
        page.insert_text((72, 72), line)
    document.save(path)
    document.close()

    text = convert_to_text(path)

    assert ".pdf" in SUPPORTED_SUFFIXES
    assert "EUS series 1 HP" in text
    assert "Warranty: one year" in text
