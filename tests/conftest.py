from __future__ import annotations


import pytest
from PIL import Image, ImageDraw, ImageFont

from belgeocr import tesseract_setup

TURKISH_LINES = [
    "Çağdaş Türkiye'de şehir yaşamı",
    "Güneşli bir öğleden sonra ışık değişti.",
    "Öğrenciler kütüphanede çalışıyordu.",
]

TABLE_ROWS = [
    ["Ürün", "Adet", "Fiyat"],
    ["Elma", "12", "4,50"],
    ["Şeftali", "7", "1.250,75"],
    ["Üzüm", "30", "18"],
]


def _font(size: int) -> ImageFont.FreeTypeFont:
    for name in ("DejaVuSans.ttf", "LiberationSans-Regular.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    pytest.skip("No TrueType font available")


@pytest.fixture(scope="session", autouse=True)
def tesseract():
    try:
        return tesseract_setup.configure()
    except tesseract_setup.TesseractNotFound:
        pytest.skip("Tesseract not installed")


def make_text_image(lines=TURKISH_LINES, size=(2480, 1200), angle=0.0) -> Image.Image:
    img = Image.new("L", size, 255)
    draw = ImageDraw.Draw(img)
    title = _font(72)
    body = _font(48)
    draw.text((150, 120), lines[0], font=title, fill=0)
    y = 320
    for line in lines[1:]:
        draw.text((150, y), line, font=body, fill=0)
        y += 110
    if angle:
        img = img.rotate(angle, fillcolor=255, expand=False)
    img.info["dpi"] = (300, 300)
    return img


def make_table_image(rows=TABLE_ROWS) -> Image.Image:
    img = Image.new("L", (2480, 1400), 255)
    draw = ImageDraw.Draw(img)
    font = _font(44)
    draw.text((200, 100), "Satış Raporu", font=_font(64), fill=0)
    x0, y0, cw, rh = 200, 300, 600, 140
    n_rows, n_cols = len(rows), len(rows[0])
    for r in range(n_rows + 1):
        draw.line([(x0, y0 + r * rh), (x0 + n_cols * cw, y0 + r * rh)], fill=0, width=4)
    for c in range(n_cols + 1):
        draw.line([(x0 + c * cw, y0), (x0 + c * cw, y0 + n_rows * rh)], fill=0, width=4)
    for r, row in enumerate(rows):
        for c, text in enumerate(row):
            draw.text((x0 + c * cw + 30, y0 + r * rh + 45), text, font=font, fill=0)
    img.info["dpi"] = (300, 300)
    return img


@pytest.fixture
def text_png(tmp_path):
    path = tmp_path / "metin.png"
    make_text_image().save(path, dpi=(300, 300))
    return path


@pytest.fixture
def table_png(tmp_path):
    path = tmp_path / "tablo.png"
    make_table_image().save(path, dpi=(300, 300))
    return path


@pytest.fixture
def scanned_pdf(tmp_path):
    """Image-only (no text layer) two-page PDF, like a scanner produces."""
    path = tmp_path / "taranmis.pdf"
    first = make_text_image(size=(2480, 3508)).convert("RGB")
    second = make_table_image().convert("RGB")
    first.save(path, "PDF", resolution=300.0, save_all=True, append_images=[second])
    return path


@pytest.fixture
def multi_page_pdf(tmp_path):
    path = tmp_path / "cok_sayfa.pdf"
    pages = [
        make_text_image([f"Sayfa {i}", "deneme"], size=(1240, 1754)).convert("RGB")
        for i in range(1, 6)
    ]
    pages[0].save(path, "PDF", resolution=150.0, save_all=True, append_images=pages[1:])
    return path


def has_lang(code: str) -> bool:
    return code in tesseract_setup.available_languages()


