"""In-memory document: an ordered list of pages from one or more files.

Page operations (rotate, delete, reorder) are non-destructive until the
document is written with :func:`build_pdf`.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image
from pypdf import PdfReader, PdfWriter, Transformation

from belgeocr import loader
from belgeocr.ocr import (
    CancelFn,
    OcrOptions,
    OcrPage,
    ProgressFn,
    _check_cancel,
    _text_only_pdf,
    page_from_text,
)
from belgeocr.tables import Table


@dataclass(eq=False)
class PageItem:
    source: Path
    index: int
    rotation: int = 0  # clockwise, multiple of 90
    ocr: OcrPage | None = None
    edited_text: str | None = None
    tables: list[Table] | None = None
    ai_text: bool = False
    ai_tables: bool = False

    @property
    def is_pdf(self) -> bool:
        return loader.is_pdf(self.source)

    @property
    def label(self) -> str:
        return f"{self.source.name} s.{self.index + 1}"

    def image(self, dpi: int = 300) -> Image.Image:
        img = loader.load_page(self.source, self.index, dpi)
        if self.rotation % 360:
            info_dpi = img.info.get("dpi", (dpi, dpi))
            img = img.rotate(-self.rotation, expand=True)
            img.info["dpi"] = info_dpi
        return img

    def reset_results(self) -> None:
        self.ocr = None
        self.edited_text = None
        self.tables = None
        self.ai_text = self.ai_tables = False

    @property
    def text(self) -> str:
        if self.edited_text is not None:
            return self.edited_text
        return self.ocr.text if self.ocr else ""

    def export_page(self) -> OcrPage:
        base = self.ocr or OcrPage([], 0.0, 300, (0, 0))
        if self.edited_text is not None:
            return page_from_text(base, self.edited_text)
        return base


@dataclass
class Document:
    pages: list[PageItem] = field(default_factory=list)
    modified: bool = False
    _undo: list[list[tuple[PageItem, int]]] = field(default_factory=list)

    def add_file(self, path: str | Path) -> list[PageItem]:
        path = Path(path).resolve()
        items = [PageItem(path, i) for i in range(loader.page_count(path))]
        if items:
            self._snapshot()
            self.pages.extend(items)
            self.modified = True
        return items

    @property
    def sources(self) -> list[Path]:
        return list(dict.fromkeys(p.source for p in self.pages))

    def _snapshot(self) -> None:
        self._undo.append([(p, p.rotation) for p in self.pages])
        del self._undo[:-50]

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    def undo(self) -> None:
        if self._undo:
            state = self._undo.pop()
            self.pages = [p for p, _ in state]
            for page, rotation in state:
                if page.rotation != rotation:
                    page.rotation = rotation
                    page.reset_results()
            self.modified = True

    def rotate(self, items: list[PageItem], degrees: int) -> None:
        if not items:
            return
        self._snapshot()
        for item in items:
            item.rotation = (item.rotation + degrees) % 360
            item.reset_results()
        self.modified = True

    def delete(self, items: list[PageItem]) -> None:
        doomed = {id(i) for i in items}
        if not doomed:
            return
        self._snapshot()
        self.pages = [p for p in self.pages if id(p) not in doomed]
        self.modified = True

    def reorder(self, new_order: list[PageItem]) -> None:
        if [id(p) for p in new_order] != [id(p) for p in self.pages]:
            self._snapshot()
            self.pages = list(new_order)
            self.modified = True

    def position(self, item: PageItem) -> int:
        return next(i for i, p in enumerate(self.pages) if p is item)

    def all_tables(self) -> list[Table]:
        found = []
        for pos, page in enumerate(self.pages):
            for table in page.tables or []:
                table.page = pos
                table.last_page = None
                found.append(table)
        return found


def _image_page(img: Image.Image):
    """Return a PDF page showing ``img`` at its DPI."""
    dpi = img.info.get("dpi", (300, 300))[0]
    rgb = img if img.mode in ("RGB", "L", "1") else img.convert("RGB")
    buf = io.BytesIO()
    rgb.save(buf, format="PDF", resolution=float(dpi), quality=90)
    buf.seek(0)
    return PdfReader(buf).pages[0]


def _overlay_text(page, img: Image.Image, options: OcrOptions) -> None:
    """Merge an invisible OCR text layer for ``img`` onto ``page``.

    Tesseract only produces the text layer; it never has to write the page
    image itself (its JPEG temp files break on non-ASCII %TEMP% on Windows).
    """
    text_page = PdfReader(io.BytesIO(_text_only_pdf(img, options))).pages[0]
    page.transfer_rotation_to_content()
    box = page.cropbox
    sx = float(box.width) / float(text_page.mediabox.width)
    sy = float(box.height) / float(text_page.mediabox.height)
    page.merge_transformed_page(
        text_page, Transformation().scale(sx, sy).translate(float(box.left), float(box.bottom))
    )


def build_pdf(
    pages: list[PageItem],
    dst: str | Path,
    ocr_layer: bool = False,
    options: OcrOptions | None = None,
    skip_text_pages: bool = True,
    progress: ProgressFn | None = None,
    cancel: CancelFn | None = None,
) -> Path:
    """Write ``pages`` (with their rotations) to a PDF, optionally searchable."""
    options = options or OcrOptions()
    dst = Path(dst)
    writer = PdfWriter()
    readers: dict[Path, PdfReader] = {}
    total = len(pages)
    for n, item in enumerate(pages):
        _check_cancel(cancel)
        if progress:
            progress(n, total, f"Sayfa {n + 1}/{total} yazılıyor...")
        if item.is_pdf:
            if item.source not in readers:
                reader = PdfReader(str(item.source))
                if reader.is_encrypted and not reader.decrypt(""):
                    raise ValueError(f"Şifreli PDF açılamadı: {item.source.name}")
                readers[item.source] = reader
            page = writer.add_page(readers[item.source].pages[item.index])
            if item.rotation:
                page.rotate(item.rotation)
            has_text = skip_text_pages and loader.pdf_page_text(item.source, item.index).strip()
            if ocr_layer and not has_text:
                _overlay_text(page, item.image(options.dpi), options)
        else:
            img = item.image(options.dpi)
            page = writer.add_page(_image_page(img))
            if ocr_layer:
                _overlay_text(page, img, options)
    _check_cancel(cancel)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".tmp")
    with open(tmp, "wb") as fh:
        writer.write(fh)
    tmp.replace(dst)
    if progress:
        progress(total, total, "Tamamlandı")
    return dst
