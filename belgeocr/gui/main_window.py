"""Main application window."""

from __future__ import annotations

import os
import sys
from functools import partial
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QSettings, Qt, QThreadPool, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QImage, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStyle,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from belgeocr import APP_NAME, __version__, export_docx, loader, ocr, tables, tesseract_setup
from belgeocr.gui.pdf_tools_dialog import PdfToolsDialog
from belgeocr.gui.workers import Worker

FILE_FILTER = (
    "Belgeler (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp *.gif);;"
    "PDF (*.pdf);;Resimler (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp *.gif)"
)


def resource_path(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "resources" / name


def pil_to_pixmap(img) -> QPixmap:
    img = img.convert("RGB")
    data = img.tobytes("raw", "RGB")
    qimg = QImage(data, img.width, img.height, img.width * 3, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimg.copy())


def page_from_text(page: ocr.OcrPage, text: str) -> ocr.OcrPage:
    """Rebuild an OcrPage from user-edited text, keeping font size info."""
    height = page.paragraphs[0].line_height if page.paragraphs else page.dpi / 6
    heights = {p.text.strip(): p.line_height for p in page.paragraphs}
    paragraphs = []
    for block in text.split("\n\n"):
        block = block.strip()
        if block:
            line_h = heights.get(block, height)
            paragraphs.append(
                ocr.OcrParagraph([ocr.OcrLine(line, line_h) for line in block.split("\n")])
            )
    return ocr.OcrPage(paragraphs, page.confidence, page.dpi, page.size)


class MainWindow(QMainWindow):
    def __init__(self, ocr_available: bool = True):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(1400, 860)
        self.setAcceptDrops(True)
        self.settings = QSettings(APP_NAME, APP_NAME)
        self.ocr_available = ocr_available
        self.pool = QThreadPool.globalInstance()
        self.worker: Worker | None = None
        self.results: dict[str, list[ocr.OcrPage]] = {}
        self.edits: dict[tuple[str, int], str] = {}
        self.current_page = 0
        self._loading_text = False
        self._preview_cache: tuple[str, int, QPixmap] | None = None

        self._build_toolbar()
        self._build_central()
        self._build_statusbar()
        self._update_actions()

    # ----------------------------------------------------------------- UI
    def _build_toolbar(self) -> None:
        tb = QToolBar("Ana araç çubuğu")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.addToolBar(tb)
        style = self.style()

        def action(text, icon, slot, shortcut=None, tip=None):
            act = QAction(style.standardIcon(icon), text, self)
            act.triggered.connect(slot)
            if shortcut:
                act.setShortcut(QKeySequence(shortcut))
            act.setToolTip(tip or text)
            tb.addAction(act)
            return act

        SP = QStyle.StandardPixmap
        self.act_open = action("Dosya Ekle", SP.SP_DialogOpenButton, self.open_files, "Ctrl+O")
        tb.addSeparator()
        self.act_ocr = action("Metni Tanı (OCR)", SP.SP_MediaPlay, self.run_ocr, "F5",
                              "Seçili belgedeki metni tanı")
        self.act_pdf = action("Aranabilir PDF", SP.SP_FileDialogDetailedView, self.make_searchable,
                              tip="Taranmış belgeyi aranabilir/kopyalanabilir PDF'ye çevir")
        self.act_docx = action("Word'e Aktar", SP.SP_FileIcon, self.export_word, "Ctrl+W")
        self.act_xlsx = action("Tabloları Excel'e", SP.SP_FileDialogListView, self.export_excel,
                               tip="Tabloları tanı ve Excel dosyasına aktar")
        self.act_txt = action("Metni Kaydet", SP.SP_DialogSaveButton, self.export_text, "Ctrl+S")
        tb.addSeparator()
        self.act_tools = action("PDF Araçları", SP.SP_DirIcon, self.open_pdf_tools,
                                tip="Birleştir, böl, döndür, sayfa sil/çıkar")
        tb.addSeparator()
        self.act_about = action("Hakkında", SP.SP_MessageBoxInformation, self.about)

    def _build_central(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)

        opts = QHBoxLayout()
        opts.addWidget(QLabel("Dil:"))
        self.lang_combo = QComboBox()
        self._fill_languages()
        opts.addWidget(self.lang_combo)
        opts.addSpacing(12)
        opts.addWidget(QLabel("Çözünürlük:"))
        self.dpi_combo = QComboBox()
        for dpi in (200, 300, 400):
            self.dpi_combo.addItem(f"{dpi} DPI", dpi)
        self.dpi_combo.setCurrentIndex(1)
        opts.addWidget(self.dpi_combo)
        opts.addSpacing(12)
        self.deskew_box = QCheckBox("Eğikliği düzelt")
        self.deskew_box.setChecked(True)
        opts.addWidget(self.deskew_box)
        self.borderless_box = QCheckBox("Çizgisiz tabloları da ara")
        self.borderless_box.setChecked(True)
        opts.addWidget(self.borderless_box)
        self.skiptext_box = QCheckBox("Metin içeren PDF sayfalarını atla")
        self.skiptext_box.setChecked(True)
        self.skiptext_box.setToolTip("Aranabilir PDF oluştururken zaten metni olan sayfalara dokunma")
        opts.addWidget(self.skiptext_box)
        opts.addStretch()
        layout.addLayout(opts)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(0, 0, 0, 0)
        left_l.addWidget(QLabel("Belgeler (sürükleyip bırakabilirsiniz)"))
        self.file_list = QListWidget()
        self.file_list.currentItemChanged.connect(self._on_file_changed)
        left_l.addWidget(self.file_list)
        btns = QHBoxLayout()
        add_btn = QPushButton("Ekle")
        add_btn.clicked.connect(self.open_files)
        rm_btn = QPushButton("Kaldır")
        rm_btn.clicked.connect(self.remove_selected)
        btns.addWidget(add_btn)
        btns.addWidget(rm_btn)
        left_l.addLayout(btns)
        splitter.addWidget(left)

        middle = QWidget()
        mid_l = QVBoxLayout(middle)
        mid_l.setContentsMargins(0, 0, 0, 0)
        nav = QHBoxLayout()
        self.prev_btn = QPushButton("◀")
        self.prev_btn.clicked.connect(partial(self._step_page, -1))
        self.next_btn = QPushButton("▶")
        self.next_btn.clicked.connect(partial(self._step_page, 1))
        self.page_label = QLabel("Belge yok")
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav.addWidget(self.prev_btn)
        nav.addWidget(self.page_label, 1)
        nav.addWidget(self.next_btn)
        mid_l.addLayout(nav)
        self.preview = QLabel("Başlamak için bir PDF veya resim ekleyin")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet("background:#5a5a5a; color:#eee;")
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(True)
        self.preview_scroll.setWidget(self.preview)
        mid_l.addWidget(self.preview_scroll)
        splitter.addWidget(middle)

        right = QWidget()
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(0, 0, 0, 0)
        self.text_label = QLabel("Tanınan metin")
        right_l.addWidget(self.text_label)
        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText("OCR sonucu burada görünecek. Metni düzenleyebilirsiniz.")
        self.text_edit.textChanged.connect(self._on_text_edited)
        right_l.addWidget(self.text_edit)
        copy_btn = QPushButton("Tümünü Kopyala")
        copy_btn.clicked.connect(self._copy_text)
        right_l.addWidget(copy_btn)
        splitter.addWidget(right)

        splitter.setSizes([260, 620, 520])
        layout.addWidget(splitter, 1)
        self.setCentralWidget(root)

    def _build_statusbar(self) -> None:
        sb = self.statusBar()
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(320)
        self.progress.setVisible(False)
        self.cancel_btn = QPushButton("İptal")
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self._cancel_worker)
        sb.addPermanentWidget(self.progress)
        sb.addPermanentWidget(self.cancel_btn)
        sb.showMessage("Hazır" if self.ocr_available else "Tesseract bulunamadı: OCR devre dışı")

    def _fill_languages(self) -> None:
        langs = []
        if self.ocr_available:
            try:
                langs = tesseract_setup.available_languages()
            except Exception:  # noqa: BLE001
                langs = []
        options = []
        if "tur" in langs and "eng" in langs:
            options.append("tur+eng")
        options += [lang for lang in ("tur", "eng") if lang in langs]
        options += [lang for lang in langs if lang not in ("tur", "eng")]
        for code in options or ["eng"]:
            self.lang_combo.addItem(tesseract_setup.language_label(code), code)
        saved = self.settings.value("lang")
        if saved and (i := self.lang_combo.findData(saved)) >= 0:
            self.lang_combo.setCurrentIndex(i)
        self.lang_combo.currentIndexChanged.connect(
            lambda: self.settings.setValue("lang", self.lang_combo.currentData())
        )

    # -------------------------------------------------------------- state
    def options(self) -> ocr.OcrOptions:
        return ocr.OcrOptions(
            lang=self.lang_combo.currentData(),
            dpi=self.dpi_combo.currentData(),
            deskew=self.deskew_box.isChecked(),
        )

    def current_file(self) -> str | None:
        item = self.file_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def page_total(self) -> int:
        path = self.current_file()
        if not path:
            return 0
        try:
            return loader.page_count(path)
        except Exception:  # noqa: BLE001
            return 0

    def _busy(self) -> bool:
        return self.worker is not None

    def _update_actions(self) -> None:
        has_file = self.current_file() is not None
        idle = not self._busy()
        for act in (self.act_ocr, self.act_pdf, self.act_docx, self.act_xlsx):
            act.setEnabled(has_file and idle and self.ocr_available)
        self.act_txt.setEnabled(has_file and idle)
        self.act_open.setEnabled(idle)
        self.act_tools.setEnabled(idle)

    # -------------------------------------------------------------- files
    def open_files(self) -> None:
        start = self.settings.value("last_dir", str(Path.home()))
        paths, _ = QFileDialog.getOpenFileNames(self, "Belge seç", start, FILE_FILTER)
        if paths:
            self.settings.setValue("last_dir", str(Path(paths[0]).parent))
            self.add_files(paths)

    def add_files(self, paths: list[str]) -> None:
        existing = {self.file_list.item(i).data(Qt.ItemDataRole.UserRole)
                    for i in range(self.file_list.count())}
        added = None
        for path in paths:
            path = str(Path(path).resolve())
            if not loader.is_supported(path) or path in existing or not os.path.isfile(path):
                continue
            existing.add(path)
            item = QListWidgetItem(Path(path).name)
            item.setToolTip(path)
            item.setData(Qt.ItemDataRole.UserRole, path)
            self.file_list.addItem(item)
            added = item
        if added:
            self.file_list.setCurrentItem(added)

    def remove_selected(self) -> None:
        row = self.file_list.currentRow()
        if row >= 0:
            item = self.file_list.takeItem(row)
            path = item.data(Qt.ItemDataRole.UserRole)
            self.results.pop(path, None)
            self.edits = {k: v for k, v in self.edits.items() if k[0] != path}
        if self.file_list.count() == 0:
            self._show_empty()

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        self.add_files([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Delete and self.file_list.hasFocus():
            self.remove_selected()
        elif event.key() == Qt.Key.Key_PageDown:
            self._step_page(1)
        elif event.key() == Qt.Key.Key_PageUp:
            self._step_page(-1)
        else:
            super().keyPressEvent(event)

    # ------------------------------------------------------------ preview
    def _show_empty(self) -> None:
        self.preview.setPixmap(QPixmap())
        self.preview.setText("Başlamak için bir PDF veya resim ekleyin")
        self.page_label.setText("Belge yok")
        self._set_text("")
        self._update_actions()

    def _on_file_changed(self, *_):
        self.current_page = 0
        self._preview_cache = None
        self._refresh_page()
        self._update_actions()

    def _step_page(self, delta: int) -> None:
        total = self.page_total()
        if total:
            self.current_page = max(0, min(total - 1, self.current_page + delta))
            self._refresh_page()

    def _refresh_page(self) -> None:
        path = self.current_file()
        if not path:
            self._show_empty()
            return
        total = self.page_total()
        self.page_label.setText(f"{Path(path).name} — Sayfa {self.current_page + 1} / {total}")
        self.prev_btn.setEnabled(self.current_page > 0)
        self.next_btn.setEnabled(self.current_page < total - 1)
        try:
            img = loader.load_page(path, self.current_page, dpi=110)
            pix = pil_to_pixmap(img)
            width = max(200, self.preview_scroll.viewport().width() - 20)
            if pix.width() > width:
                pix = pix.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)
            self.preview.setPixmap(pix)
        except Exception as exc:  # noqa: BLE001
            self.preview.setPixmap(QPixmap())
            self.preview.setText(f"Önizleme açılamadı:\n{exc}")
        self._show_page_text()

    def _show_page_text(self) -> None:
        path = self.current_file()
        pages = self.results.get(path or "")
        key = (path, self.current_page)
        if key in self.edits:
            text = self.edits[key]
        elif pages and self.current_page < len(pages):
            text = pages[self.current_page].text
        else:
            text = ""
        if pages and self.current_page < len(pages):
            conf = pages[self.current_page].confidence
            self.text_label.setText(f"Tanınan metin — güven: %{conf:.0f}")
        else:
            self.text_label.setText("Tanınan metin")
        self._set_text(text)

    def _set_text(self, text: str) -> None:
        self._loading_text = True
        self.text_edit.setPlainText(text)
        self._loading_text = False

    def _on_text_edited(self) -> None:
        path = self.current_file()
        if self._loading_text or not path or path not in self.results:
            return
        self.edits[(path, self.current_page)] = self.text_edit.toPlainText()

    def _copy_text(self) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(self.text_edit.toPlainText())
        self.statusBar().showMessage("Metin panoya kopyalandı", 3000)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.current_file():
            self._refresh_page()

    # ------------------------------------------------------------- tasks
    def _start(self, fn: Callable, *args, on_done: Callable, **kwargs) -> None:
        self.worker = Worker(fn, *args, **kwargs)
        self.worker.signals.progress.connect(self._on_progress)
        self.worker.signals.finished.connect(lambda result: self._finish(on_done, result))
        self.worker.signals.error.connect(self._on_error)
        self.worker.signals.cancelled.connect(self._on_cancelled)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.cancel_btn.setVisible(True)
        self._update_actions()
        self.pool.start(self.worker)

    def _end(self) -> None:
        self.worker = None
        self.progress.setVisible(False)
        self.cancel_btn.setVisible(False)
        self._update_actions()

    def _finish(self, on_done: Callable, result) -> None:
        self._end()
        on_done(result)

    def _on_progress(self, i: int, n: int, msg: str) -> None:
        self.progress.setMaximum(max(n, 1))
        self.progress.setValue(i)
        self.statusBar().showMessage(msg)

    def _on_error(self, msg: str) -> None:
        self._end()
        self.statusBar().showMessage("Hata")
        QMessageBox.critical(self, APP_NAME, f"İşlem başarısız oldu:\n{msg}")

    def _on_cancelled(self) -> None:
        self._end()
        self.statusBar().showMessage("İşlem iptal edildi", 5000)

    def _cancel_worker(self) -> None:
        if self.worker:
            self.worker.cancel()
            self.statusBar().showMessage("İptal ediliyor...")

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.worker:
            self.worker.cancel()
            self.pool.waitForDone(5000)
        super().closeEvent(event)

    # ---------------------------------------------------------- actions
    def run_ocr(self, then: Callable[[], None] | None = None) -> None:
        path = self.current_file()
        if not path:
            return

        def done(pages):
            self.results[path] = pages
            self.edits = {k: v for k, v in self.edits.items() if k[0] != path}
            mean = sum(p.confidence for p in pages) / max(len(pages), 1)
            self.statusBar().showMessage(f"{len(pages)} sayfa tanındı, ortalama güven %{mean:.0f}", 8000)
            if self.current_file() == path:
                self._show_page_text()
            if callable(then):
                then()

        self._start(ocr.ocr_file, path, self.options(), on_done=done)

    def _pages_for_export(self, path: str) -> list[ocr.OcrPage]:
        pages = self.results[path]
        return [
            page_from_text(page, self.edits[(path, i)]) if (path, i) in self.edits else page
            for i, page in enumerate(pages)
        ]

    def _save_path(self, title: str, suffix: str, filt: str) -> str | None:
        path = self.current_file()
        default_dir = self.settings.value("save_dir", str(Path(path).parent))
        default = str(Path(default_dir) / (Path(path).stem + suffix))
        out, _ = QFileDialog.getSaveFileName(self, title, default, filt)
        if out:
            self.settings.setValue("save_dir", str(Path(out).parent))
        return out or None

    def _saved(self, out: str | Path, what: str) -> None:
        self.statusBar().showMessage(f"{what} kaydedildi: {out}", 10000)
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setText(f"{what} kaydedildi:\n{out}")
        open_btn = box.addButton("Dosyayı Aç", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Kapat", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is open_btn:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(out)))

    def _with_ocr(self, fn: Callable[[], None]) -> None:
        if self.current_file() in self.results:
            fn()
        else:
            self.run_ocr(then=fn)

    def export_word(self) -> None:
        if not self.current_file():
            return
        out = self._save_path("Word olarak kaydet", ".docx", "Word belgesi (*.docx)")
        if not out:
            return
        path = self.current_file()

        def write():
            try:
                export_docx.export_docx(self._pages_for_export(path), out)
            except Exception as exc:  # noqa: BLE001
                self._on_error(str(exc))
                return
            self._saved(out, "Word belgesi")

        self._with_ocr(write)

    def export_text(self) -> None:
        if not self.current_file():
            return
        out = self._save_path("Metin olarak kaydet", ".txt", "Metin dosyası (*.txt)")
        if not out:
            return
        path = self.current_file()

        def write():
            export_docx.export_txt(self._pages_for_export(path), out)
            self._saved(out, "Metin dosyası")

        if path in self.results:
            write()
        elif self.ocr_available:
            self.run_ocr(then=write)

    def make_searchable(self) -> None:
        path = self.current_file()
        if not path:
            return
        out = self._save_path("Aranabilir PDF kaydet", "_aranabilir.pdf", "PDF (*.pdf)")
        if not out:
            return
        if Path(out).resolve() == Path(path).resolve():
            QMessageBox.warning(self, APP_NAME, "Kaynak dosyanın üzerine yazılamaz. Farklı bir ad seçin.")
            return
        self._start(
            ocr.make_searchable_pdf, path, out, self.options(),
            skip_text_pages=self.skiptext_box.isChecked(),
            on_done=lambda result: self._saved(result, "Aranabilir PDF"),
        )

    def export_excel(self) -> None:
        path = self.current_file()
        if not path:
            return
        out = self._save_path("Tabloları Excel'e kaydet", ".xlsx", "Excel çalışma kitabı (*.xlsx)")
        if not out:
            return

        def done(found):
            if not found:
                QMessageBox.information(self, APP_NAME, "Belgede tablo bulunamadı.")
                return
            tables.export_xlsx(found, out)
            self._saved(out, f"{len(found)} tablo içeren Excel dosyası")

        self._start(
            tables.extract_tables_from_file, path, self.options(),
            borderless=self.borderless_box.isChecked(), on_done=done,
        )

    def open_pdf_tools(self) -> None:
        files = [self.file_list.item(i).data(Qt.ItemDataRole.UserRole)
                 for i in range(self.file_list.count())]
        dialog = PdfToolsDialog(self, files, self.settings)
        dialog.exec()
        if dialog.created:
            self.add_files([str(p) for p in dialog.created if loader.is_supported(p)][:20])

    def about(self) -> None:
        QMessageBox.about(
            self,
            f"{APP_NAME} hakkında",
            f"<b>{APP_NAME} {__version__}</b><br>"
            "Taranmış belgelerden metin tanıma, aranabilir PDF, Word ve Excel'e aktarma, "
            "PDF düzenleme.<br><br>OCR motoru: Tesseract (Apache 2.0)",
        )
