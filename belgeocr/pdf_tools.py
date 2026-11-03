"""PDF page operations: merge, split, rotate, delete, extract."""

from __future__ import annotations

import io
import re
from pathlib import Path

from PIL import Image
from pypdf import PdfReader, PdfWriter

from belgeocr import loader


def _open(path: str | Path) -> PdfReader:
    reader = PdfReader(str(path))
    if reader.is_encrypted and not reader.decrypt(""):
        raise ValueError(f"Şifreli PDF açılamadı: {Path(path).name}")
    return reader


def parse_page_ranges(spec: str, total: int) -> list[int]:
    """Parse '1-3, 5, 8-' style ranges (1-based) into 0-based page indices."""
    spec = spec.strip()
    if not spec:
        return list(range(total))
    pages: list[int] = []
    for part in re.split(r"[,\s]+", spec):
        if not part:
            continue
        m = re.fullmatch(r"(\d*)-(\d*)|(\d+)", part)
        if not m:
            raise ValueError(f"Geçersiz sayfa aralığı: '{part}'")
        if m.group(3):
            start = end = int(m.group(3))
        else:
            start = int(m.group(1)) if m.group(1) else 1
            end = int(m.group(2)) if m.group(2) else total
        if start < 1 or end > total or start > end:
            raise ValueError(f"Sayfa aralığı belge dışında: '{part}' (toplam {total} sayfa)")
        pages.extend(range(start - 1, end))
    return pages


def _image_to_pdf_reader(path: str | Path) -> PdfReader:
    buf = io.BytesIO()
    frames = []
    with Image.open(path) as img:
        for i in range(getattr(img, "n_frames", 1)):
            img.seek(i)
            frame = img.convert("RGB")
            dpi = img.info.get("dpi", (300, 300))
            frames.append((frame, dpi))
    first, dpi = frames[0]
    first.save(
        buf, "PDF", resolution=float(dpi[0]) if dpi[0] > 1 else 300.0,
        save_all=True, append_images=[f for f, _ in frames[1:]],
    )
    buf.seek(0)
    return PdfReader(buf)


def merge(paths: list[str | Path], dst: str | Path) -> Path:
    """Merge PDFs (and images, converted to pages) in the given order."""
    writer = PdfWriter()
    for path in paths:
        reader = _open(path) if loader.is_pdf(path) else _image_to_pdf_reader(path)
        writer.append(reader)
    return _write(writer, dst)


def split(src: str | Path, out_dir: str | Path, groups: list[str] | None = None) -> list[Path]:
    """Split a PDF. Without ``groups`` every page becomes its own file;
    otherwise each range spec in ``groups`` (e.g. ['1-3', '4-']) is one file."""
    reader = _open(src)
    total = len(reader.pages)
    out_dir = Path(out_dir)
    stem = Path(src).stem
    outputs = []
    specs = groups or [str(i) for i in range(1, total + 1)]
    for n, spec in enumerate(specs, start=1):
        writer = PdfWriter()
        for index in parse_page_ranges(spec, total):
            writer.add_page(reader.pages[index])
        label = spec.replace(" ", "") if groups else f"{n:03d}"
        outputs.append(_write(writer, out_dir / f"{stem}_{label}.pdf"))
    return outputs


def rotate(src: str | Path, dst: str | Path, degrees: int, pages: str = "") -> Path:
    if degrees % 90:
        raise ValueError("Döndürme açısı 90'ın katı olmalı.")
    reader = _open(src)
    selected = set(parse_page_ranges(pages, len(reader.pages)))
    writer = PdfWriter()
    for index, page in enumerate(reader.pages):
        if index in selected:
            page.rotate(degrees)
        writer.add_page(page)
    return _write(writer, dst)


def delete_pages(src: str | Path, dst: str | Path, pages: str) -> Path:
    reader = _open(src)
    removed = set(parse_page_ranges(pages, len(reader.pages)))
    if len(removed) == len(reader.pages):
        raise ValueError("Tüm sayfalar silinemez.")
    writer = PdfWriter()
    for index, page in enumerate(reader.pages):
        if index not in removed:
            writer.add_page(page)
    return _write(writer, dst)


def extract_pages(src: str | Path, dst: str | Path, pages: str) -> Path:
    reader = _open(src)
    writer = PdfWriter()
    for index in parse_page_ranges(pages, len(reader.pages)):
        writer.add_page(reader.pages[index])
    return _write(writer, dst)


def _write(writer: PdfWriter, dst: str | Path) -> Path:
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(dst, "wb") as fh:
        writer.write(fh)
    return dst
