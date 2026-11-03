import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from docx import Document  # noqa: E402
from openpyxl import load_workbook  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from belgeocr import loader  # noqa: E402
from belgeocr.gui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, monkeypatch, tmp_path):
    w = MainWindow()
    w.settings.clear()
    saved = []
    monkeypatch.setattr(w, "_saved", lambda out, what: saved.append(out))
    monkeypatch.setattr(w, "_on_error", lambda msg: pytest.fail(msg))
    w.saved = saved
    yield w
    w.close()


def _wait(app, window):
    while window.worker is not None or window.pool.activeThreadCount():
        window.pool.waitForDone(100)
        app.processEvents()
    app.processEvents()


def test_ocr_edit_and_export_word(app, window, scanned_pdf, tmp_path, monkeypatch):
    window.add_files([str(scanned_pdf), str(scanned_pdf)])
    assert window.file_list.count() == 1
    window.run_ocr()
    _wait(app, window)
    assert "öğleden" in window.text_edit.toPlainText()
    window.text_edit.setPlainText("Düzenlenmiş başlık\n\nİkinci paragraf")
    out = tmp_path / "out.docx"
    monkeypatch.setattr(window, "_save_path", lambda *a: str(out))
    window.export_word()
    assert window.saved == [str(out)]
    texts = [p.text for p in Document(str(out)).paragraphs if p.text]
    assert texts[:2] == ["Düzenlenmiş başlık", "İkinci paragraf"]


def test_export_word_runs_ocr_first(app, window, text_png, tmp_path, monkeypatch):
    window.add_files([str(text_png)])
    out = tmp_path / "auto.docx"
    monkeypatch.setattr(window, "_save_path", lambda *a: str(out))
    window.export_word()
    _wait(app, window)
    assert out.exists()


def test_searchable_and_excel(app, window, scanned_pdf, tmp_path, monkeypatch):
    window.add_files([str(scanned_pdf)])
    out = tmp_path / "s.pdf"
    monkeypatch.setattr(window, "_save_path", lambda *a: str(out))
    window.make_searchable()
    _wait(app, window)
    assert "Güneşli" in loader.pdf_page_text(out, 0)

    xlsx = tmp_path / "t.xlsx"
    monkeypatch.setattr(window, "_save_path", lambda *a: str(xlsx))
    window.export_excel()
    _wait(app, window)
    wb = load_workbook(xlsx)
    assert "Sayfa2_Tablo1" in wb.sheetnames
    assert wb["Sayfa2_Tablo1"]["A3"].value == "Şeftali"


def test_cancel(app, window, scanned_pdf):
    window.add_files([str(scanned_pdf)])
    window.run_ocr()
    window._cancel_worker()
    _wait(app, window)
    assert window.worker is None
    assert window.act_ocr.isEnabled()


def test_page_navigation(app, window, multi_page_pdf):
    window.add_files([str(multi_page_pdf)])
    window._step_page(1)
    window._step_page(1)
    assert "Sayfa 3 / 5" in window.page_label.text()
    window._step_page(10)
    assert "Sayfa 5 / 5" in window.page_label.text()
