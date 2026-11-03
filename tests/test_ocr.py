import pytest
from pypdf import PdfReader

from belgeocr import loader, ocr, tesseract_setup
from tests.conftest import make_text_image


@pytest.fixture(scope="module")
def lang():
    langs = tesseract_setup.available_languages()
    return "tur" if "tur" in langs else "eng"


def test_ocr_image_turkish(lang):
    page = ocr.ocr_image(make_text_image(), ocr.OcrOptions(lang=lang))
    text = page.text
    assert "kütüphanede" in text or lang != "tur"
    assert "Güneşli" in text or lang != "tur"
    assert page.confidence > 70
    assert len(page.paragraphs) >= 2


def test_deskew_detects_rotation():
    import numpy as np

    gray = np.array(make_text_image(angle=4))
    assert abs(ocr.detect_skew(gray) - 4) < 1.0


def test_ocr_skewed_image(lang):
    page = ocr.ocr_image(make_text_image(angle=5), ocr.OcrOptions(lang=lang))
    assert "öğleden" in page.text or lang != "tur"


def test_ocr_file_pdf_progress_and_cancel(scanned_pdf, lang):
    calls = []
    pages = ocr.ocr_file(scanned_pdf, ocr.OcrOptions(lang=lang, dpi=200), progress=lambda *a: calls.append(a))
    assert len(pages) == 2
    assert calls[-1][0] == calls[-1][1] == 2
    with pytest.raises(ocr.Cancelled):
        ocr.ocr_file(scanned_pdf, ocr.OcrOptions(lang=lang), cancel=lambda: True)


def test_searchable_pdf_from_scanned_pdf(scanned_pdf, tmp_path, lang):
    assert loader.pdf_page_text(scanned_pdf, 0).strip() == ""
    out = ocr.make_searchable_pdf(scanned_pdf, tmp_path / "out.pdf", ocr.OcrOptions(lang=lang, dpi=200))
    reader = PdfReader(str(out))
    assert len(reader.pages) == 2
    src = PdfReader(str(scanned_pdf))
    assert reader.pages[0].mediabox == src.pages[0].mediabox
    text = loader.pdf_page_text(out, 0)
    assert "Güneşli" in text or lang != "tur"
    # text layer must line up with the page: search hit near original position
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(out))
    tp = doc[0].get_textpage()
    searcher = tp.search("kütüphanede" if lang == "tur" else "Ogrenciler")
    hit = searcher.get_next()
    assert hit is not None
    left, bottom, right, top = tp.get_charbox(hit[0])
    page_h = doc[0].get_height()
    # third line drawn at y=430px (300 dpi) from top -> ~103pt from top
    assert abs((page_h - top) - 430 * 72 / 300) < 10
    doc.close()


def test_searchable_pdf_skips_text_pages(scanned_pdf, tmp_path, lang):
    once = ocr.make_searchable_pdf(scanned_pdf, tmp_path / "1.pdf", ocr.OcrOptions(lang=lang, dpi=150))
    calls = []
    ocr.make_searchable_pdf(once, tmp_path / "2.pdf", ocr.OcrOptions(lang=lang), progress=lambda *a: calls.append(a))
    assert loader.pdf_page_text(tmp_path / "2.pdf", 0) == loader.pdf_page_text(once, 0)


def test_searchable_pdf_from_image(text_png, tmp_path, lang):
    out = ocr.make_searchable_pdf(text_png, tmp_path / "img.pdf", ocr.OcrOptions(lang=lang))
    assert "öğleden" in loader.pdf_page_text(out, 0) or lang != "tur"


def test_searchable_pdf_rotated_page(scanned_pdf, tmp_path, lang):
    from belgeocr import pdf_tools

    rotated = pdf_tools.rotate(scanned_pdf, tmp_path / "rot.pdf", 90, "1")
    out = ocr.make_searchable_pdf(rotated, tmp_path / "rot_ocr.pdf", ocr.OcrOptions(lang=lang, dpi=150))
    assert "kütüphanede" in loader.pdf_page_text(out, 0) or lang != "tur"
