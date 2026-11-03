from __future__ import annotations

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from belgeocr import APP_NAME, tesseract_setup
from belgeocr.gui.main_window import MainWindow, resource_path


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    icon = resource_path("icon.png")
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    tesseract_error = None
    try:
        tesseract_setup.configure()
    except tesseract_setup.TesseractNotFound as exc:
        tesseract_error = str(exc)
    window = MainWindow(ocr_available=tesseract_error is None)
    window.show()
    if tesseract_error:
        QMessageBox.warning(window, APP_NAME, tesseract_error)
    files = [p for p in argv[1:] if not p.startswith("-")]
    if files:
        window.open_files(files)
    return app.exec()
