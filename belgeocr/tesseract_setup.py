"""Locate and run the Tesseract executable.

Tesseract 5 on Windows crashes ("filesystem error: Cannot convert character
sequence") when an image, output or tessdata path contains non-ASCII
characters, e.g. a Turkish user name in %TEMP%. To avoid that, images are fed
through stdin, results are read from stdout, and tessdata is passed as a
relative path from Tesseract's own directory.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

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

_tesseract: Path | None = None


class TesseractNotFound(RuntimeError):
    pass


class TesseractError(RuntimeError):
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
    """Find a Tesseract binary and return its path."""
    global _tesseract
    for candidate in _candidates():
        if candidate.is_file():
            _tesseract = candidate.resolve()
            return _tesseract
    raise TesseractNotFound(
        "Tesseract OCR bulunamadı. Uygulamayı kurulum paketiyle yükleyin veya "
        "BELGEOCR_TESSERACT ortam değişkenine tesseract yolunu yazın."
    )


def _run(args: list[str], stdin: bytes | None = None) -> bytes:
    exe = _tesseract or configure()
    cmd = [str(exe)]
    env = os.environ.copy()
    if (exe.parent / "tessdata").is_dir():
        cmd += ["--tessdata-dir", "tessdata"]
        env.pop("TESSDATA_PREFIX", None)
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    proc = subprocess.run(
        cmd + args,
        input=stdin,
        capture_output=True,
        cwd=str(exe.parent),
        env=env,
        creationflags=flags,
    )
    if proc.returncode != 0:
        message = proc.stderr.decode("utf-8", errors="replace").strip()
        raise TesseractError(message or f"Tesseract hata kodu {proc.returncode}")
    return proc.stdout


def run_image(
    img: Image.Image,
    lang: str,
    psm: int,
    dpi: int,
    renderer: str | None = None,
    extra: list[str] | None = None,
) -> bytes:
    """OCR ``img`` and return the renderer output (text, tsv, pdf...)."""
    buf = io.BytesIO()
    img.save(buf, format="PNG", dpi=(dpi, dpi))
    args = ["stdin", "stdout", "-l", lang, "--psm", str(psm), "--dpi", str(dpi)]
    args += extra or []
    if renderer:
        args.append(renderer)
    return _run(args, buf.getvalue())


def image_to_data(img: Image.Image, lang: str, psm: int, dpi: int = 300) -> dict[str, list]:
    """Word-level OCR results as column lists (like pytesseract's Output.DICT)."""
    tsv = run_image(img, lang, psm, dpi, "tsv").decode("utf-8", errors="replace")
    rows = [line.split("\t") for line in tsv.splitlines() if line]
    if not rows:
        return {}
    header = rows[0]
    data: dict[str, list] = {key: [] for key in header}
    for row in rows[1:]:
        row += [""] * (len(header) - len(row))
        for key, value in zip(header, row):
            if key == "text":
                data[key].append(value)
            elif key == "conf":
                data[key].append(float(value) if value else -1.0)
            else:
                data[key].append(int(value) if value else 0)
    return data


def available_languages() -> list[str]:
    out = _run(["--list-langs"]).decode("utf-8", errors="replace")
    langs = [line.strip() for line in out.splitlines()[1:] if line.strip()]
    return sorted(lang for lang in langs if lang not in ("osd", "equ"))


def language_label(code: str) -> str:
    parts = code.split("+")
    return " + ".join(LANGUAGE_NAMES.get(p, p) for p in parts)
