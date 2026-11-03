"""Load images and PDF pages as PIL images."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pypdfium2 as pdfium
from PIL import Image, ImageOps

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".gif"}
PDF_EXTS = {".pdf"}
SUPPORTED_EXTS = IMAGE_EXTS | PDF_EXTS


def is_pdf(path: str | Path) -> bool:
    return Path(path).suffix.lower() in PDF_EXTS


def is_supported(path: str | Path) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_EXTS


def page_count(path: str | Path) -> int:
    path = Path(path)
    if is_pdf(path):
        doc = pdfium.PdfDocument(str(path))
        try:
            return len(doc)
        finally:
            doc.close()
    with Image.open(path) as img:
        return getattr(img, "n_frames", 1)


def _normalize(img: Image.Image) -> Image.Image:
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    return img


def load_page(path: str | Path, index: int, dpi: int = 300) -> Image.Image:
    """Return page ``index`` (0-based) rendered/loaded at ``dpi``."""
    path = Path(path)
    if is_pdf(path):
        doc = pdfium.PdfDocument(str(path))
        try:
            page = doc[index]
            img = page.render(scale=dpi / 72).to_pil()
            page.close()
        finally:
            doc.close()
        img = _normalize(img)
        img.info["dpi"] = (dpi, dpi)
        return img
    with Image.open(path) as src:
        if index:
            src.seek(index)
        src_dpi = src.info.get("dpi")
        img = _normalize(src.copy())
    resolution = int(round(src_dpi[0])) if src_dpi and src_dpi[0] > 1 else dpi
    img.info["dpi"] = (resolution, resolution)
    return img


def iter_pages(
    path: str | Path, dpi: int = 300, pages: list[int] | None = None
) -> Iterator[tuple[int, Image.Image]]:
    indices = pages if pages is not None else range(page_count(path))
    for i in indices:
        yield i, load_page(path, i, dpi)


def pdf_page_text(path: str | Path, index: int) -> str:
    """Return the embedded (digital) text of a PDF page, if any."""
    doc = pdfium.PdfDocument(str(path))
    try:
        page = doc[index]
        textpage = page.get_textpage()
        text = textpage.get_text_range()
        textpage.close()
        page.close()
        return text.replace("\r\n", "\n")
    finally:
        doc.close()
