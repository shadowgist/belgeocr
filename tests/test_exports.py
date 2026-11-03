from docx import Document
from openpyxl import load_workbook

from belgeocr import export_docx, ocr, tables, tesseract_setup
from tests.conftest import TABLE_ROWS, make_table_image, make_text_image


def _lang():
    return "tur" if "tur" in tesseract_setup.available_languages() else "eng"


def test_docx_export(tmp_path):
    pages = [ocr.ocr_image(make_text_image(), ocr.OcrOptions(lang=_lang()))] * 2
    out = export_docx.export_docx(pages, tmp_path / "out.docx")
    doc = Document(str(out))
    texts = [p.text for p in doc.paragraphs if p.text]
    assert any("Çağdaş" in t for t in texts) or _lang() != "tur"
    title = next(p for p in doc.paragraphs if p.text)
    assert title.runs[0].bold
    body = [p for p in doc.paragraphs if p.text][1]
    assert title.runs[0].font.size > body.runs[0].font.size


def test_txt_export(tmp_path):
    pages = [ocr.ocr_image(make_text_image(), ocr.OcrOptions(lang=_lang()))]
    out = export_docx.export_txt(pages, tmp_path / "out.txt")
    assert "Güneşli" in out.read_text(encoding="utf-8") or _lang() != "tur"


def test_ruled_table_detection_and_xlsx(tmp_path):
    found = tables.extract_tables(make_table_image(), ocr.OcrOptions(lang=_lang()))
    assert len(found) == 1
    table = found[0]
    assert (table.n_rows, table.n_cols) == (4, 3)
    grid = table.to_grid()
    if _lang() == "tur":
        assert grid == TABLE_ROWS
    out = tables.export_xlsx(found, tmp_path / "t.xlsx")
    ws = load_workbook(out).active
    assert ws["B2"].value == 12
    assert ws["C3"].value == 1250.75
    assert ws["C2"].value == 4.5


def test_merged_cells():
    from PIL import ImageDraw

    img = make_table_image([["Başlık", "", ""], ["a", "b", "c"], ["d", "e", "f"]])
    draw = ImageDraw.Draw(img)
    # erase inner vertical lines of first row to form a merged header
    for x in (800, 1400):
        draw.rectangle([x - 4, 304, x + 4, 436], fill=255)
    table = tables.extract_tables(img, ocr.OcrOptions(lang=_lang()))[0]
    header = next(c for c in table.cells if c.row == 0)
    assert header.colspan == 3
    assert len([c for c in table.cells if c.row == 0]) == 1


def test_borderless_table():
    from PIL import Image, ImageDraw
    from tests.conftest import _font

    img = Image.new("L", (2480, 1000), 255)
    draw = ImageDraw.Draw(img)
    font = _font(44)
    for r, row in enumerate(TABLE_ROWS):
        for c, text in enumerate(row):
            draw.text((200 + c * 600, 200 + r * 120), text, font=font, fill=0)
    img.info["dpi"] = (300, 300)
    found = tables.extract_tables(img, ocr.OcrOptions(lang=_lang()))
    assert len(found) == 1 and not found[0].ruled
    assert found[0].n_cols == 3 and found[0].n_rows == 4


def test_parse_number():
    assert tables.parse_number("1.250,75") == 1250.75
    assert tables.parse_number("12") == 12
    assert tables.parse_number("4,50") == 4.5
    assert tables.parse_number("3.14") == 3.14
    assert tables.parse_number("1.234") == 1234
    assert tables.parse_number("0012") is None
    assert tables.parse_number("abc") is None
    assert tables.parse_number("0,5") == 0.5
