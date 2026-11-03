"""Export OCR results to Word (DOCX) and plain text."""

from __future__ import annotations

import statistics
from pathlib import Path

from docx import Document
from docx.enum.text import WD_BREAK
from docx.shared import Pt

from belgeocr.ocr import OcrPage


def _font_size(line_height_px: float, dpi: int) -> float:
    # Tesseract word boxes roughly cover the x-height to descender span,
    # which is ~75% of the font's em size.
    size = line_height_px / dpi * 72 / 0.75
    return max(8.0, min(32.0, round(size * 2) / 2))


def export_docx(pages: list[OcrPage], dst: str | Path) -> Path:
    dst = Path(dst)
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    all_heights = [p.line_height for page in pages for p in page.paragraphs if p.lines]
    body_height = statistics.median(all_heights) if all_heights else 0

    for page_no, page in enumerate(pages):
        if page_no:
            doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        for para in page.paragraphs:
            text = para.text.strip()
            if not text:
                continue
            p = doc.add_paragraph()
            run = p.add_run(text)
            size = _font_size(para.line_height, page.dpi)
            run.font.size = Pt(size)
            if body_height and para.line_height > body_height * 1.35 and len(text) < 120:
                run.bold = True
    dst.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(dst))
    return dst


def export_txt(pages: list[OcrPage], dst: str | Path) -> Path:
    dst = Path(dst)
    dst.write_text("\n\n\f".join(page.text for page in pages), encoding="utf-8")
    return dst
