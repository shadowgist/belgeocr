import gc
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from docx import Document  # noqa: E402
from openpyxl import load_workbook  # noqa: E402
from pypdf import PdfReader  # noqa: E402
from PySide6.QtCore import QEvent, QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from belgeocr import ai, loader  # noqa: E402
from belgeocr.gui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _wait(app, window):
    while window.worker is not None or window.pool.activeThreadCount():
        window.pool.waitForDone(100)
        app.processEvents()
    app.processEvents()


@pytest.fixture
def window(app, monkeypatch, tmp_path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    w = MainWindow(settings=settings)
    saved = []
    monkeypatch.setattr(w, "_saved", lambda out, what: saved.append(str(out)))
    monkeypatch.setattr(w, "_on_error", lambda msg: pytest.fail(msg))
    monkeypatch.setattr(w, "_confirm_discard", lambda: True)
    w.saved = saved
    yield w
    _wait(app, w)
    w.close()
    w.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()
    gc.collect()


def test_open_rotate_delete_undo_save(app, window, multi_page_pdf, tmp_path, monkeypatch):
    window.open_files([str(multi_page_pdf)])
    assert window.thumbs.count() == 5
    window.thumbs.clearSelection()
    window.thumbs.item(1).setSelected(True)
    window.rotate(90)
    assert window.doc.pages[1].rotation == 90
    window.rotate(-90)
    window.rotate(-90)
    assert window.doc.pages[1].rotation == 270
    window.thumbs.clearSelection()
    window.thumbs.item(0).setSelected(True)
    window.thumbs.item(2).setSelected(True)
    window.delete_pages()
    assert window.thumbs.count() == 3
    window.undo()
    assert window.thumbs.count() == 5
    window.thumbs.clearSelection()
    window.thumbs.item(4).setSelected(True)
    window.delete_pages()
    out = tmp_path / "kayit.pdf"
    monkeypatch.setattr(window, "_save_path", lambda *a, **k: str(out))
    window.save_as()
    _wait(app, window)
    reader = PdfReader(str(out))
    assert len(reader.pages) == 4
    assert reader.pages[1].rotation == 270
    assert window.doc_path == out.resolve()
    assert all(p.rotation == 0 and p.source == out.resolve() for p in window.doc.pages)
    assert not window.doc.modified


def test_ocr_edit_and_export_word(app, window, scanned_pdf, tmp_path, monkeypatch):
    window.open_files([str(scanned_pdf)])
    window.run_ocr()
    _wait(app, window)
    assert "öğleden" in window.text_edit.toPlainText()
    window.text_edit.setPlainText("Düzenlenmiş başlık\n\nİkinci paragraf")
    out = tmp_path / "out.docx"
    monkeypatch.setattr(window, "_save_path", lambda *a, **k: str(out))
    window.export_word()
    _wait(app, window)
    assert window.saved == [str(out)]
    texts = [p.text for p in Document(str(out)).paragraphs if p.text]
    assert texts[:2] == ["Düzenlenmiş başlık", "İkinci paragraf"]


def test_tables_edit_and_excel(app, window, scanned_pdf, tmp_path, monkeypatch):
    window.open_files([str(scanned_pdf)])
    window.run_tables()
    _wait(app, window)
    editor = window.table_editor
    assert len(editor.tables()) == 1
    editor.grid.item(2, 1).setText("8")
    editor.grid.setCurrentCell(3, 0)
    editor.add_row()
    assert editor.current().n_rows == 5
    xlsx = tmp_path / "t.xlsx"
    monkeypatch.setattr(window, "_save_path", lambda *a, **k: str(xlsx))
    window.export_excel()
    ws = load_workbook(xlsx).active
    assert ws["A3"].value == "Şeftali"
    assert ws["B3"].value == 8


def test_searchable_pdf_with_rotation(app, window, scanned_pdf, tmp_path, monkeypatch):
    window.open_files([str(scanned_pdf)])
    window.thumbs.clearSelection()
    window.thumbs.item(0).setSelected(True)
    window.rotate(90)
    out = tmp_path / "s.pdf"
    monkeypatch.setattr(window, "_save_path", lambda *a, **k: str(out))
    window.export_searchable()
    _wait(app, window)
    assert "Güneşli" in loader.pdf_page_text(out, 0)
    page = PdfReader(str(out)).pages[0]
    assert float(page.mediabox.width) > float(page.mediabox.height)


def test_ai_analysis_merges_tables(app, window, multi_page_pdf, monkeypatch):
    window.settings.setValue("ai/api_key", "test-key")
    pages = iter([
        ai.AiPageResult("Başlık", [[["Ürün", "Adet"], ["Elma", "1"]]]),
        ai.AiPageResult("", [[["Ürün", "Adet"], ["Armut", "2"]]]),
        ai.AiPageResult("Son", []),
        ai.AiPageResult("", []),
        ai.AiPageResult("", []),
    ])
    monkeypatch.setattr(ai, "analyze_page", lambda img, settings: next(pages))
    window.open_files([str(multi_page_pdf)])
    window.run_ai()
    _wait(app, window)
    tables = window.table_editor.tables()
    assert len(tables) == 1
    assert tables[0].to_grid() == [["Ürün", "Adet"], ["Elma", "1"], ["Armut", "2"]]
    assert tables[0].page_label == "1-2"
    assert window.doc.pages[0].text == "Başlık"
    assert window.thumbs.item(0).text().endswith("✦")


def test_cancel(app, window, scanned_pdf):
    window.open_files([str(scanned_pdf)])
    window.run_ocr()
    window._cancel_worker()
    _wait(app, window)
    assert window.worker is None
    assert window.a_ocr.isEnabled()
