"""Text recognition and searchable PDF creation using Tesseract."""

from __future__ import annotations

import io
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
import pytesseract
from PIL import Image
from pypdf import PdfReader, PdfWriter, Transformation

from belgeocr import loader

ProgressFn = Callable[[int, int, str], None]
CancelFn = Callable[[], bool]


class Cancelled(Exception):
    pass


@dataclass
class OcrLine:
    text: str
    height: float


@dataclass
class OcrParagraph:
    lines: list[OcrLine] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(line.text for line in self.lines)

    @property
    def line_height(self) -> float:
        return statistics.median(line.height for line in self.lines) if self.lines else 0


@dataclass
class OcrPage:
    paragraphs: list[OcrParagraph]
    confidence: float
    dpi: int
    size: tuple[int, int]

    @property
    def text(self) -> str:
        return "\n\n".join(p.text for p in self.paragraphs if p.text.strip())


@dataclass
class OcrOptions:
    lang: str = "tur+eng"
    dpi: int = 300
    deskew: bool = True
    psm: int = 3


def _check_cancel(cancel: CancelFn | None) -> None:
    if cancel and cancel():
        raise Cancelled()


def detect_skew(gray: np.ndarray) -> float:
    """Estimate text skew angle in degrees (positive = counter-clockwise)."""
    small = gray
    scale = 1.0
    if max(gray.shape) > 2000:
        scale = 2000 / max(gray.shape)
        small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    binary = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(15, small.shape[1] // 60), 3))
    lines = cv2.dilate(binary, kernel)
    contours, _ = cv2.findContours(lines, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    angles, weights = [], []
    for c in contours:
        (_, _), (w, h), angle = cv2.minAreaRect(c)
        if w < h:
            w, h = h, w
            angle -= 90
        if w < small.shape[1] * 0.1 or h == 0 or w / h < 4:
            continue
        if angle > 45:
            angle -= 90
        elif angle < -45:
            angle += 90
        angles.append(angle)
        weights.append(w)
    if not angles:
        return 0.0
    order = np.argsort(angles)
    cum = np.cumsum(np.array(weights)[order])
    median = float(np.array(angles)[order][np.searchsorted(cum, cum[-1] / 2)])
    return -median


def preprocess(img: Image.Image, deskew: bool = True) -> Image.Image:
    """Grayscale + deskew + upscale tiny images."""
    dpi = img.info.get("dpi", (300, 300))
    gray = np.array(img.convert("L"))
    if deskew:
        angle = detect_skew(gray)
        if 0.3 < abs(angle) < 15:
            h, w = gray.shape
            matrix = cv2.getRotationMatrix2D((w / 2, h / 2), -angle, 1.0)
            gray = cv2.warpAffine(
                gray, matrix, (w, h), flags=cv2.INTER_CUBIC, borderValue=255
            )
    if max(gray.shape) < 1200:
        gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        dpi = (dpi[0] * 2, dpi[1] * 2)
    out = Image.fromarray(gray)
    out.info["dpi"] = (int(dpi[0]), int(dpi[1]))
    return out


def _config(dpi: int, psm: int) -> str:
    return f"--psm {psm} --dpi {dpi}"


def ocr_image(img: Image.Image, options: OcrOptions | None = None) -> OcrPage:
    options = options or OcrOptions()
    prepared = preprocess(img, options.deskew)
    dpi = prepared.info["dpi"][0]
    data = pytesseract.image_to_data(
        prepared,
        lang=options.lang,
        config=_config(dpi, options.psm),
        output_type=pytesseract.Output.DICT,
    )
    paragraphs: dict[tuple[int, int], OcrParagraph] = {}
    lines: dict[tuple[int, int, int], list[tuple[str, int]]] = {}
    confs: list[float] = []
    for i, word in enumerate(data["text"]):
        word = word.strip()
        if not word:
            continue
        conf = float(data["conf"][i])
        if conf >= 0:
            confs.append(conf)
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(key, []).append((word, data["height"][i]))
    for (block, par, _), words in lines.items():
        para = paragraphs.setdefault((block, par), OcrParagraph())
        heights = [h for _, h in words]
        para.lines.append(
            OcrLine(" ".join(w for w, _ in words), float(statistics.median(heights)))
        )
    return OcrPage(
        paragraphs=list(paragraphs.values()),
        confidence=statistics.mean(confs) if confs else 0.0,
        dpi=dpi,
        size=prepared.size,
    )


def ocr_file(
    path: str | Path,
    options: OcrOptions | None = None,
    progress: ProgressFn | None = None,
    cancel: CancelFn | None = None,
    pages: list[int] | None = None,
) -> list[OcrPage]:
    options = options or OcrOptions()
    indices = pages if pages is not None else list(range(loader.page_count(path)))
    results = []
    for n, index in enumerate(indices):
        _check_cancel(cancel)
        if progress:
            progress(n, len(indices), f"Sayfa {index + 1} tanınıyor...")
        img = loader.load_page(path, index, options.dpi)
        results.append(ocr_image(img, options))
    if progress:
        progress(len(indices), len(indices), "Tamamlandı")
    return results


def _text_only_pdf(img: Image.Image, options: OcrOptions) -> bytes:
    """Return a one-page PDF containing only the invisible OCR text layer."""
    dpi = img.info.get("dpi", (options.dpi, options.dpi))[0]
    return pytesseract.image_to_pdf_or_hocr(
        img,
        lang=options.lang,
        extension="pdf",
        config=_config(dpi, options.psm) + " -c textonly_pdf=1",
    )


def _image_pdf(img: Image.Image, options: OcrOptions) -> bytes:
    """Return a one-page PDF with the page image plus an invisible text layer."""
    dpi = img.info.get("dpi", (options.dpi, options.dpi))[0]
    return pytesseract.image_to_pdf_or_hocr(
        img, lang=options.lang, extension="pdf", config=_config(dpi, options.psm)
    )


def make_searchable_pdf(
    src: str | Path,
    dst: str | Path,
    options: OcrOptions | None = None,
    skip_text_pages: bool = True,
    progress: ProgressFn | None = None,
    cancel: CancelFn | None = None,
) -> Path:
    """Create a searchable PDF from a scanned PDF or image file.

    For PDF input the original pages are kept untouched and an invisible text
    layer is overlaid, so image quality and file size are preserved.
    """
    options = options or OcrOptions()
    src, dst = Path(src), Path(dst)
    writer = PdfWriter()
    total = loader.page_count(src)

    if loader.is_pdf(src):
        reader = PdfReader(str(src))
        for index, page in enumerate(reader.pages):
            _check_cancel(cancel)
            if progress:
                progress(index, total, f"Sayfa {index + 1}/{total} işleniyor...")
            if skip_text_pages and loader.pdf_page_text(src, index).strip():
                writer.add_page(page)
                continue
            img = loader.load_page(src, index, options.dpi)
            text_pdf = PdfReader(io.BytesIO(_text_only_pdf(img, options)))
            text_page = text_pdf.pages[0]
            page = writer.add_page(page)
            page.transfer_rotation_to_content()
            box = page.cropbox
            sx = float(box.width) / float(text_page.mediabox.width)
            sy = float(box.height) / float(text_page.mediabox.height)
            transform = Transformation().scale(sx, sy).translate(
                float(box.left), float(box.bottom)
            )
            page.merge_transformed_page(text_page, transform)
    else:
        for index in range(total):
            _check_cancel(cancel)
            if progress:
                progress(index, total, f"Sayfa {index + 1}/{total} işleniyor...")
            img = preprocess(loader.load_page(src, index, options.dpi), options.deskew)
            writer.append(PdfReader(io.BytesIO(_image_pdf(img, options))))

    _check_cancel(cancel)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(dst, "wb") as fh:
        writer.write(fh)
    if progress:
        progress(total, total, "Tamamlandı")
    return dst
