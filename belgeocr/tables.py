"""Table detection/recognition and Excel export."""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.utils import get_column_letter
from PIL import Image

from belgeocr import loader, tesseract_setup
from belgeocr.ocr import CancelFn, OcrOptions, ProgressFn, _check_cancel, preprocess


@dataclass
class Cell:
    row: int
    col: int
    text: str = ""
    rowspan: int = 1
    colspan: int = 1


@dataclass
class Table:
    bbox: tuple[int, int, int, int]
    n_rows: int
    n_cols: int
    cells: list[Cell] = field(default_factory=list)
    page: int = 0
    ruled: bool = True

    def to_grid(self) -> list[list[str]]:
        grid = [["" for _ in range(self.n_cols)] for _ in range(self.n_rows)]
        for cell in self.cells:
            grid[cell.row][cell.col] = cell.text
        return grid


@dataclass
class _Word:
    text: str
    x: int
    y: int
    w: int
    h: int

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2


# ---------------------------------------------------------------- utilities


def _line_positions(profile: np.ndarray, threshold: float) -> list[int]:
    """Centers of runs where ``profile`` exceeds ``threshold``."""
    above = profile > threshold
    positions, start = [], None
    for i, flag in enumerate(above):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            positions.append((start + i - 1) // 2)
            start = None
    if start is not None:
        positions.append((start + len(above) - 1) // 2)
    merged: list[int] = []
    for p in positions:
        if merged and p - merged[-1] < 8:
            merged[-1] = (merged[-1] + p) // 2
        else:
            merged.append(p)
    return merged


def _words(img: np.ndarray, lang: str, psm: int) -> list[_Word]:
    data = tesseract_setup.image_to_data(Image.fromarray(img), lang, psm)
    words = []
    for i, text in enumerate(data["text"]):
        text = text.strip()
        if text and float(data["conf"][i]) > 10:
            words.append(
                _Word(text, data["left"][i], data["top"][i], data["width"][i], data["height"][i])
            )
    return words


def _join_words(words: list[_Word]) -> str:
    """Join words in reading order, keeping line breaks inside a cell."""
    if not words:
        return ""
    words = sorted(words, key=lambda w: w.cy)
    lines: list[list[_Word]] = []
    for word in words:
        if lines and abs(word.cy - statistics.mean(w.cy for w in lines[-1])) < word.h * 0.6:
            lines[-1].append(word)
        else:
            lines.append([word])
    return "\n".join(" ".join(w.text for w in sorted(line, key=lambda w: w.x)) for line in lines)


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, a: int) -> int:
        while self.parent[a] != a:
            self.parent[a] = self.parent[self.parent[a]]
            a = self.parent[a]
        return a

    def union(self, a: int, b: int) -> None:
        self.parent[self.find(a)] = self.find(b)


# ------------------------------------------------------------ ruled tables


def _line_masks(gray: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    binary = cv2.adaptiveThreshold(
        255 - gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 15, -2
    )
    h, w = gray.shape
    # Kernels must be longer than glyph strokes (~45px at 300 dpi) but shorter
    # than a single cell so that partial (merged-cell) borders survive.
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(60, min(w // 35, 120)), 1))
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(50, min(h // 40, 80))))
    horizontal = cv2.dilate(cv2.erode(binary, h_kernel), h_kernel)
    vertical = cv2.dilate(cv2.erode(binary, v_kernel), v_kernel)
    # close small gaps in scanned lines
    horizontal = cv2.dilate(horizontal, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 3)))
    vertical = cv2.dilate(vertical, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 5)))
    return horizontal, vertical


def _has_border(mask: np.ndarray, fixed: int, start: int, end: int, vertical: bool) -> bool:
    margin = max(2, (end - start) // 6)
    a, b = start + margin, end - margin
    if b <= a:
        return True
    lo, hi = max(0, fixed - 4), fixed + 5
    band = mask[a:b, lo:hi] if vertical else mask[lo:hi, a:b]
    if band.size == 0:
        return True
    covered = band.max(axis=1 if vertical else 0) > 0
    return covered.mean() > 0.6


def detect_ruled_tables(gray: np.ndarray) -> list[tuple[tuple[int, int, int, int], list[int], list[int], list[list[tuple[int, int]]]]]:
    """Find bordered tables. Returns (bbox, col_xs, row_ys, cell groups) per table."""
    horizontal, vertical = _line_masks(gray)
    grid = cv2.bitwise_or(horizontal, vertical)
    contours, _ = cv2.findContours(grid, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    page_area = gray.shape[0] * gray.shape[1]
    found = []
    for contour in sorted(contours, key=lambda c: cv2.boundingRect(c)[1]):
        x, y, w, h = cv2.boundingRect(contour)
        if w * h < page_area * 0.005 or w < 60 or h < 30:
            continue
        hm = horizontal[y : y + h, x : x + w]
        vm = vertical[y : y + h, x : x + w]
        ys = _line_positions((hm > 0).sum(axis=1), w * 0.25)
        xs = _line_positions((vm > 0).sum(axis=0), h * 0.25)
        if len(ys) < 2 or len(xs) < 2 or (len(ys) - 1) * (len(xs) - 1) < 2:
            continue
        n_rows, n_cols = len(ys) - 1, len(xs) - 1
        uf = _UnionFind(n_rows * n_cols)
        for r in range(n_rows):
            for c in range(n_cols - 1):
                if not _has_border(vm, xs[c + 1], ys[r], ys[r + 1], vertical=True):
                    uf.union(r * n_cols + c, r * n_cols + c + 1)
        for r in range(n_rows - 1):
            for c in range(n_cols):
                if not _has_border(hm, ys[r + 1], xs[c], xs[c + 1], vertical=False):
                    uf.union(r * n_cols + c, (r + 1) * n_cols + c)
        groups: dict[int, list[tuple[int, int]]] = {}
        for r in range(n_rows):
            for c in range(n_cols):
                groups.setdefault(uf.find(r * n_cols + c), []).append((r, c))
        cell_groups = []
        for members in groups.values():
            rows = [m[0] for m in members]
            cols = [m[1] for m in members]
            area = (max(rows) - min(rows) + 1) * (max(cols) - min(cols) + 1)
            if area == len(members):
                cell_groups.append(members)
            else:  # non-rectangular merge: keep cells separate
                cell_groups.extend([[m] for m in members])
        found.append(((x, y, w, h), xs, ys, cell_groups))
    return found


def _ocr_cell(crop: np.ndarray, lang: str) -> str:
    """OCR a single cell; catches short tokens that sparse page OCR misses."""
    inset = 6
    crop = crop[inset:-inset, inset:-inset] if min(crop.shape) > 3 * inset else crop
    if crop.size == 0 or (crop < 128).mean() < 0.002:
        return ""
    padded = cv2.copyMakeBorder(crop, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    return _join_words(_words(padded, lang, psm=7))


def _recognize_ruled(gray: np.ndarray, lang: str) -> list[Table]:
    tables = []
    horizontal, vertical = _line_masks(gray)
    cleaned = gray.copy()
    cleaned[(horizontal > 0) | (vertical > 0)] = 255
    for (x, y, w, h), xs, ys, groups in detect_ruled_tables(gray):
        region = cleaned[y : y + h, x : x + w]
        words = _words(region, lang, psm=11)
        n_rows, n_cols = len(ys) - 1, len(xs) - 1
        cells = []
        assigned: dict[int, list[_Word]] = {}
        spans = []
        for gi, members in enumerate(groups):
            r0 = min(m[0] for m in members)
            r1 = max(m[0] for m in members)
            c0 = min(m[1] for m in members)
            c1 = max(m[1] for m in members)
            spans.append((r0, r1, c0, c1))
        for word in words:
            for gi, (r0, r1, c0, c1) in enumerate(spans):
                if xs[c0] <= word.cx <= xs[c1 + 1] and ys[r0] <= word.cy <= ys[r1 + 1]:
                    assigned.setdefault(gi, []).append(word)
                    break
        for gi, (r0, r1, c0, c1) in enumerate(spans):
            text = _join_words(assigned.get(gi, []))
            if not text:
                text = _ocr_cell(region[ys[r0] : ys[r1 + 1], xs[c0] : xs[c1 + 1]], lang)
            cells.append(Cell(r0, c0, text, r1 - r0 + 1, c1 - c0 + 1))
        cells.sort(key=lambda c: (c.row, c.col))
        tables.append(Table((x, y, w, h), n_rows, n_cols, cells, ruled=True))
    return tables


# --------------------------------------------------------- borderless tables


def _recognize_borderless(gray: np.ndarray, lang: str) -> list[Table]:
    """Heuristic column clustering for tables without ruling lines."""
    words = _words(gray, lang, psm=6)
    if len(words) < 4:
        return []
    med_h = statistics.median(w.h for w in words)
    words.sort(key=lambda w: w.cy)
    rows: list[list[_Word]] = []
    for word in words:
        if rows and abs(word.cy - statistics.mean(w.cy for w in rows[-1])) < med_h * 0.6:
            rows[-1].append(word)
        else:
            rows.append([word])
    gap = med_h * 1.2
    row_segments: list[list[list[_Word]]] = []
    for row in rows:
        row.sort(key=lambda w: w.x)
        segments = [[row[0]]]
        for word in row[1:]:
            prev = segments[-1][-1]
            if word.x - (prev.x + prev.w) > gap:
                segments.append([word])
            else:
                segments[-1].append(word)
        row_segments.append(segments)
    intervals = sorted(
        (min(w.x for w in s), max(w.x + w.w for w in s))
        for segs in row_segments
        if len(segs) > 1
        for s in segs
    )
    if not intervals:
        return []
    columns: list[list[int]] = []
    for start, end in intervals:
        if columns and start <= columns[-1][1]:
            columns[-1][1] = max(columns[-1][1], end)
        else:
            columns.append([start, end])
    if len(columns) < 2:
        return []
    cells = []
    for r, segs in enumerate(row_segments):
        texts: dict[int, list[str]] = {}
        for seg in segs:
            cx = (min(w.x for w in seg) + max(w.x + w.w for w in seg)) / 2
            col = min(
                range(len(columns)),
                key=lambda i: 0 if columns[i][0] <= cx <= columns[i][1]
                else min(abs(cx - columns[i][0]), abs(cx - columns[i][1])),
            )
            texts.setdefault(col, []).append(" ".join(w.text for w in seg))
        for col, parts in texts.items():
            cells.append(Cell(r, col, " ".join(parts)))
    h, w = gray.shape
    return [Table((0, 0, w, h), len(row_segments), len(columns), cells, ruled=False)]


# ------------------------------------------------------------------ public


def extract_tables(
    img: Image.Image, options: OcrOptions | None = None, borderless: bool = True
) -> list[Table]:
    options = options or OcrOptions()
    gray = np.array(preprocess(img, options.deskew))
    tables = _recognize_ruled(gray, options.lang)
    if not tables and borderless:
        tables = _recognize_borderless(gray, options.lang)
    return tables


def extract_tables_from_file(
    path: str | Path,
    options: OcrOptions | None = None,
    borderless: bool = True,
    progress: ProgressFn | None = None,
    cancel: CancelFn | None = None,
) -> list[Table]:
    options = options or OcrOptions()
    total = loader.page_count(path)
    found = []
    for index in range(total):
        _check_cancel(cancel)
        if progress:
            progress(index, total, f"Sayfa {index + 1}/{total}: tablolar aranıyor...")
        for table in extract_tables(loader.load_page(path, index, options.dpi), options, borderless):
            table.page = index
            found.append(table)
    if progress:
        progress(total, total, "Tamamlandı")
    return found


_TR_NUMBER = re.compile(r"^-?(\d{1,3}(\.\d{3})+|\d+)(,\d+)?$")
_EN_DECIMAL = re.compile(r"^-?\d+\.\d{1,2}$|^-?\d+\.\d{4,}$")


def parse_number(text: str) -> float | int | None:
    """Parse numbers in Turkish (1.234,56) or plain (12.5) notation."""
    t = text.strip().replace(" ", "")
    if not t or (len(t) > 1 and t.lstrip("-").startswith("0") and not t.lstrip("-").startswith("0,")
                 and not t.lstrip("-").startswith("0.")):
        return None
    if _TR_NUMBER.match(t):
        value = float(t.replace(".", "").replace(",", "."))
    elif _EN_DECIMAL.match(t):
        value = float(t)
    else:
        return None
    return int(value) if value.is_integer() and "," not in t and not _EN_DECIMAL.match(t) else value


def export_xlsx(tables: list[Table], dst: str | Path, convert_numbers: bool = True) -> Path:
    dst = Path(dst)
    wb = Workbook()
    wb.remove(wb.active)
    thin = Side(style="thin", color="999999")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    per_page: dict[int, int] = {}
    for table in tables:
        per_page[table.page] = per_page.get(table.page, 0) + 1
        ws = wb.create_sheet(f"Sayfa{table.page + 1}_Tablo{per_page[table.page]}")
        widths = [8] * table.n_cols
        for cell in table.cells:
            xl = ws.cell(row=cell.row + 1, column=cell.col + 1)
            number = parse_number(cell.text) if convert_numbers else None
            xl.value = number if number is not None else cell.text
            xl.alignment = Alignment(wrap_text=True, vertical="top")
            if cell.rowspan > 1 or cell.colspan > 1:
                ws.merge_cells(
                    start_row=cell.row + 1,
                    start_column=cell.col + 1,
                    end_row=cell.row + cell.rowspan,
                    end_column=cell.col + cell.colspan,
                )
            longest = max((len(line) for line in cell.text.split("\n")), default=0)
            widths[cell.col] = max(widths[cell.col], min(60, longest + 2) // cell.colspan)
        if table.ruled:
            for row in ws.iter_rows(min_row=1, max_row=table.n_rows, max_col=table.n_cols):
                for xl in row:
                    xl.border = border
            for xl in ws[1]:
                xl.font = Font(bold=True)
        for i, width in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(i)].width = width
    if not wb.sheetnames:
        raise ValueError("Dışa aktarılacak tablo bulunamadı.")
    dst.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(dst))
    return dst
