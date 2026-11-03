"""Locate the Tesseract executable (bundled, configured or system-wide)."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytesseract

LANGUAGE_NAMES = {
    "tur": "Türkçe",
    "eng": "İngilizce",
    "deu": "Almanca",
    "fra": "Fransızca",
    "ara": "Arapça",
    "rus": "Rusça",
    "spa": "İspanyolca",
    "ita": "İtalyanca",
}


class TesseractNotFound(RuntimeError):
    pass


def _exe_name() -> str:
    return "tesseract.exe" if os.name == "nt" else "tesseract"


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _candidates() -> list[Path]:
    found: list[Path] = []
    env = os.environ.get("BELGEOCR_TESSERACT")
    if env:
        found.append(Path(env))
    exe = _exe_name()
    found.append(_app_dir() / "tesseract" / exe)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        found.append(Path(meipass) / "tesseract" / exe)
    if os.name == "nt":
        for var in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            base = os.environ.get(var)
            if base:
                found.append(Path(base) / "Tesseract-OCR" / exe)
                found.append(Path(base) / "Programs" / "Tesseract-OCR" / exe)
    on_path = shutil.which("tesseract")
    if on_path:
        found.append(Path(on_path))
    return found


def configure() -> Path:
    """Point pytesseract at a working Tesseract binary and return its path."""
    for candidate in _candidates():
        if candidate.is_file():
            pytesseract.pytesseract.tesseract_cmd = str(candidate)
            tessdata = candidate.parent / "tessdata"
            if tessdata.is_dir() and "TESSDATA_PREFIX" not in os.environ:
                os.environ["TESSDATA_PREFIX"] = str(tessdata)
            return candidate
    raise TesseractNotFound(
        "Tesseract OCR bulunamadı. Uygulamayı kurulum paketiyle yükleyin veya "
        "BELGEOCR_TESSERACT ortam değişkenine tesseract yolunu yazın."
    )


def available_languages() -> list[str]:
    langs = pytesseract.get_languages(config="")
    return sorted(lang for lang in langs if lang not in ("osd", "equ"))


def language_label(code: str) -> str:
    parts = code.split("+")
    return " + ".join(LANGUAGE_NAMES.get(p, p) for p in parts)
