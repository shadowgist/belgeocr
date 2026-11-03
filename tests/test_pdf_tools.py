import pytest
from pypdf import PdfReader

from belgeocr import pdf_tools


def test_parse_page_ranges():
    assert pdf_tools.parse_page_ranges("1-3, 5", 6) == [0, 1, 2, 4]
    assert pdf_tools.parse_page_ranges("4-", 6) == [3, 4, 5]
    assert pdf_tools.parse_page_ranges("", 3) == [0, 1, 2]
    with pytest.raises(ValueError):
        pdf_tools.parse_page_ranges("7", 6)
    with pytest.raises(ValueError):
        pdf_tools.parse_page_ranges("a", 6)


def test_merge_with_images(multi_page_pdf, text_png, tmp_path):
    out = pdf_tools.merge([multi_page_pdf, text_png, multi_page_pdf], tmp_path / "m.pdf")
    assert len(PdfReader(str(out)).pages) == 11


def test_split_each_and_groups(multi_page_pdf, tmp_path):
    each = pdf_tools.split(multi_page_pdf, tmp_path / "each")
    assert len(each) == 5
    groups = pdf_tools.split(multi_page_pdf, tmp_path / "g", ["1-2", "3-"])
    assert [len(PdfReader(str(p)).pages) for p in groups] == [2, 3]


def test_rotate_delete_extract(multi_page_pdf, tmp_path):
    rot = pdf_tools.rotate(multi_page_pdf, tmp_path / "r.pdf", 90, "2")
    pages = PdfReader(str(rot)).pages
    assert pages[1].rotation == 90 and pages[0].rotation == 0
    deleted = pdf_tools.delete_pages(multi_page_pdf, tmp_path / "d.pdf", "1,3")
    assert len(PdfReader(str(deleted)).pages) == 3
    with pytest.raises(ValueError):
        pdf_tools.delete_pages(multi_page_pdf, tmp_path / "x.pdf", "1-5")
    ext = pdf_tools.extract_pages(multi_page_pdf, tmp_path / "e.pdf", "5,1")
    assert len(PdfReader(str(ext)).pages) == 2
