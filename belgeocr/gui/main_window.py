"""Main application window."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

import qtawesome as qta
from PySide6.QtCore import QItemSelectionModel, QSettings, QSize, Qt, QThreadPool, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QIcon, QImage, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from belgeocr import APP_NAME, __version__, ai, export_docx, loader, ocr, tables, tesseract_setup
from belgeocr.document import Document, PageItem, build_pdf
from belgeocr.gui import settings_dialog as sd
from belgeocr.gui.table_editor import TableEditor
from belgeocr.gui.theme import apply_theme, icon_color
from belgeocr.gui.workers import Worker

FILE_FILTER = (
    "Belgeler (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp *.gif);;"
    "PDF (*.pdf);;Resimler (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp *.gif)"
)
THUMB_DPI = 24
VIEW_DPI = 110


def resource_path(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "resources" / name


def pil_to_pixmap(img) -> QPixmap:
    img = img.convert("RGB")
    data = img.tobytes("raw", "RGB")
    qimg = QImage(data, img.width, img.height, img.width * 3, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimg.copy())


class ThumbList(QListWidget):
    def __init__(self, on_reorder: Callable[[], None]):
        super().__init__()
        self.setObjectName("thumbs")
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setFlow(QListView.Flow.TopToBottom)
        self.setWrapping(False)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Snap)
        self.setIconSize(QSize(130, 170))
        self.setSpacing(4)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setUniformItemSizes(True)
        self.setMinimumWidth(170)
        self._on_reorder = on_reorder

    def dropEvent(self, event) -> None:  # noqa: N802
        if event.source() is self:
            super().dropEvent(event)
            QTimer.singleShot(0, self._on_reorder)
        else:
            event.ignore()


class MainWindow(QMainWindow):
    def __init__(self, ocr_available: bool = True, settings: QSettings | None = None):
        super().__init__()
        self.resize(1440, 900)
        self.setAcceptDrops(True)
        self.settings = settings or QSettings(APP_NAME, APP_NAME)
        self.ocr_available = ocr_available
        self.pool = QThreadPool.globalInstance()
        self.worker: Worker | None = None
        self.doc = Document()
        self.doc_path: Path | None = None
        self.zoom = 1.0
        self.fit_width = True
        self._loading_text = False
        self._thumb_cache: dict[tuple[int, int], QIcon] = {}
        self._view_cache: tuple[tuple, QPixmap] | None = None
        self._icon_actions: list[tuple[QAction, str]] = []
        self.languages = self._languages()

        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_central()
        self._build_statusbar()
        self.apply_theme()
        self._refresh_all()

    # ------------------------------------------------------------ helpers
    def icon(self, name: str) -> QIcon:
        return qta.icon(f"mdi6.{name}", color=icon_color(sd.value(self.settings, "theme")),
                        color_disabled="#8a8f99")

    def _languages(self) -> list[str]:
        if not self.ocr_available:
            return []
        try:
            return tesseract_setup.available_languages()
        except Exception:  # noqa: BLE001
            return []

    def options(self) -> ocr.OcrOptions:
        opts = sd.ocr_options(self.settings)
        if self.languages and not all(p in self.languages for p in opts.lang.split("+")):
            opts.lang = "tur+eng" if {"tur", "eng"} <= set(self.languages) else self.languages[0]
        return opts

    def selected_pages(self) -> list[PageItem]:
        rows = sorted(self.thumbs.row(i) for i in self.thumbs.selectedItems())
        return [self.doc.pages[r] for r in rows if r < len(self.doc.pages)]

    def current_page(self) -> PageItem | None:
        row = self.thumbs.currentRow()
        return self.doc.pages[row] if 0 <= row < len(self.doc.pages) else None

    def _busy(self) -> bool:
        return self.worker is not None

    # ---------------------------------------------------------------- UI
    def _act(self, text: str, icon: str | None, slot, shortcut=None, tip: str | None = None) -> QAction:
        act = QAction(text, self)
        act.triggered.connect(lambda checked=False: slot())
        if shortcut:
            act.setShortcuts([QKeySequence(s) for s in (shortcut if isinstance(shortcut, list) else [shortcut])])
        act.setToolTip(f"{tip or text}" + (f" ({act.shortcut().toString()})" if shortcut else ""))
        act.setStatusTip(tip or text)
        if icon:
            self._icon_actions.append((act, icon))
        return act

    def _build_actions(self) -> None:
        self.a_open = self._act("Aç", "folder-open-outline", self.open_files, "Ctrl+O", "Belge aç")
        self.a_add = self._act("Sayfa Ekle", "file-plus-outline", self.add_pages_dialog, "Ctrl+Shift+O",
                               "Başka bir PDF veya resmin sayfalarını sona ekle")
        self.a_save = self._act("Kaydet", "content-save-outline", self.save, "Ctrl+S",
                                "Belgeyi PDF olarak kaydet (döndürme/silme dahil)")
        self.a_save_as = self._act("Farklı Kaydet...", None, self.save_as, "Ctrl+Shift+S")
        self.a_extract = self._act("Seçili Sayfaları PDF Olarak Kaydet...", "file-export-outline",
                                   self.export_selected, None)
        self.a_searchable = self._act("Aranabilir PDF", "file-pdf-box", self.export_searchable, None,
                                      "Taranmış belgeyi aranabilir/kopyalanabilir PDF olarak kaydet")
        self.a_word = self._act("Word", "microsoft-word", self.export_word, "Ctrl+Shift+W",
                                "Metni Word belgesi olarak dışa aktar")
        self.a_excel = self._act("Excel", "microsoft-excel", self.export_excel, "Ctrl+Shift+E",
                                 "Tabloları Excel'e aktar")
        self.a_txt = self._act("Metin (TXT)...", None, self.export_text, None)
        self.a_quit = self._act("Çıkış", None, self.close, "Ctrl+Q")

        self.a_undo = self._act("Geri Al", "undo", self.undo, "Ctrl+Z")
        self.a_rot_l = self._act("Sola Döndür", "rotate-left", lambda: self.rotate(-90), "Ctrl+L",
                                 "Seçili sayfaları 90° sola döndür")
        self.a_rot_r = self._act("Sağa Döndür", "rotate-right", lambda: self.rotate(90), "Ctrl+R",
                                 "Seçili sayfaları 90° sağa döndür")
        self.a_delete = self._act("Sayfayı Sil", "delete-outline", self.delete_pages, "Delete",
                                  "Seçili sayfaları sil")
        self.a_select_all = self._act("Tüm Sayfaları Seç", "select-all", self.thumbs_select_all, None)

        self.a_ocr = self._act("Metni Tanı", "text-recognition", self.run_ocr, "F5",
                               "Tüm sayfalardaki metni tanı (OCR)")
        self.a_tables = self._act("Tabloları Tanı", "table-search", self.run_tables, "F6",
                                  "Tüm sayfalardaki tabloları tanı")
        self.a_ai = self._act("Yapay Zekâ", "creation", self.run_ai, "F7",
                              "Yapay zekâ ile tüm sayfaları incele: metin ve tabloları en yüksek doğrulukla çıkar")
        self.a_ai_sel = self._act("Seçili Sayfaları Yapay Zekâ ile İncele", None,
                                  lambda: self.run_ai(selected_only=True), "Shift+F7")

        self.a_zoom_in = self._act("Yakınlaştır", "magnify-plus-outline", lambda: self.set_zoom(1.25), "Ctrl++")
        self.a_zoom_out = self._act("Uzaklaştır", "magnify-minus-outline", lambda: self.set_zoom(0.8), "Ctrl+-")
        self.a_fit = self._act("Genişliğe Sığdır", "fit-to-page-outline", self.set_fit, "Ctrl+0")
        self.a_theme = self._act("Açık/Koyu Tema", "theme-light-dark", self.toggle_theme, None)
        self.a_settings = self._act("Ayarlar", "cog-outline", self.open_settings, "Ctrl+,")
        self.a_about = self._act("Hakkında", "information-outline", self.about, None)

    def _build_menus(self) -> None:
        mb = self.menuBar()
        m = mb.addMenu("&Dosya")
        m.addActions([self.a_open, self.a_add])
        m.addSeparator()
        m.addActions([self.a_save, self.a_save_as, self.a_extract])
        exp = m.addMenu("Dışa Aktar")
        exp.addActions([self.a_word, self.a_excel, self.a_searchable, self.a_txt])
        m.addSeparator()
        m.addAction(self.a_quit)
        m = mb.addMenu("Dü&zen")
        m.addActions([self.a_undo])
        m.addSeparator()
        m.addActions([self.a_rot_l, self.a_rot_r, self.a_delete, self.a_select_all])
        m = mb.addMenu("&Tanıma")
        m.addActions([self.a_ocr, self.a_tables])
        m.addSeparator()
        m.addActions([self.a_ai, self.a_ai_sel])
        m = mb.addMenu("&Görünüm")
        m.addActions([self.a_zoom_in, self.a_zoom_out, self.a_fit])
        m.addSeparator()
        m.addAction(self.a_theme)
        m = mb.addMenu("&Araçlar")
        m.addAction(self.a_settings)
        m = mb.addMenu("&Yardım")
        m.addAction(self.a_about)

    def _build_toolbar(self) -> None:
        tb = QToolBar("Ana araç çubuğu")
        tb.setObjectName("main_toolbar")
        tb.setMovable(False)
        tb.setIconSize(QSize(26, 26))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.addToolBar(tb)
        for group in (
            [self.a_open, self.a_add, self.a_save],
            [self.a_undo, self.a_rot_l, self.a_rot_r, self.a_delete],
            [self.a_ocr, self.a_tables, self.a_ai],
            [self.a_word, self.a_excel, self.a_searchable],
            [self.a_zoom_out, self.a_zoom_in, self.a_fit],
            [self.a_settings],
        ):
            tb.addActions(group)
            tb.addSeparator()
        self.toolbar = tb

    def _build_central(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.thumbs = ThumbList(self._on_reorder)
        self.thumbs.currentRowChanged.connect(lambda _: self._show_current())
        self.thumbs.itemSelectionChanged.connect(self._update_actions)
        splitter.addWidget(self.thumbs)

        self.viewer = QLabel()
        self.viewer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.viewer_scroll = QScrollArea()
        self.viewer_scroll.setWidgetResizable(True)
        self.viewer_scroll.setWidget(self.viewer)
        self.viewer_scroll.setStyleSheet("QScrollArea { background: #6b7280; } QLabel { background: #6b7280; color: #f3f4f6; }")
        splitter.addWidget(self.viewer_scroll)

        self.side_tabs = QTabWidget()
        text_tab = QWidget()
        tl = QVBoxLayout(text_tab)
        tl.setContentsMargins(4, 4, 4, 4)
        self.text_info = QLabel()
        tl.addWidget(self.text_info)
        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText("Tanınan metin burada görünür ve düzenlenebilir.")
        self.text_edit.textChanged.connect(self._on_text_edited)
        tl.addWidget(self.text_edit, 1)
        copy_btn = QPushButton("Sayfa Metnini Kopyala")
        copy_btn.clicked.connect(lambda: (QApplication.clipboard().setText(self.text_edit.toPlainText()),
                                          self.statusBar().showMessage("Metin panoya kopyalandı", 3000)))
        tl.addWidget(copy_btn)
        self.side_tabs.addTab(text_tab, "Metin")
        self.table_editor = TableEditor(self.icon)
        self.side_tabs.addTab(self.table_editor, "Tablolar")
        splitter.addWidget(self.side_tabs)

        splitter.setStretchFactor(1, 1)
        splitter.setSizes([190, 760, 490])
        self.setCentralWidget(splitter)

    def _build_statusbar(self) -> None:
        sb = self.statusBar()
        self.page_status = QLabel()
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(280)
        self.progress.setVisible(False)
        self.cancel_btn = QPushButton("İptal")
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self._cancel_worker)
        sb.addPermanentWidget(self.page_status)
        sb.addPermanentWidget(self.progress)
        sb.addPermanentWidget(self.cancel_btn)
        sb.showMessage("Hazır" if self.ocr_available else "Tesseract bulunamadı: OCR devre dışı")

    def apply_theme(self) -> None:
        apply_theme(QApplication.instance(), sd.value(self.settings, "theme"))
        for act, name in self._icon_actions:
            act.setIcon(self.icon(name))
        self.table_editor.refresh_icons()

    def toggle_theme(self) -> None:
        mode = "dark" if sd.value(self.settings, "theme") == "light" else "light"
        self.settings.setValue("theme", mode)
        self.apply_theme()

    # ------------------------------------------------------------ refresh
    def _refresh_all(self) -> None:
        self._rebuild_thumbs()
        self._show_current()
        self._update_title()
        self._update_actions()

    def _update_title(self) -> None:
        name = self.doc_path.name if self.doc_path else (
            self.doc.sources[0].name if self.doc.sources else "Yeni belge")
        mark = " •" if self.doc.modified and self.doc.pages else ""
        self.setWindowTitle(f"{name}{mark} — {APP_NAME} {__version__}")

    def _update_actions(self) -> None:
        idle = not self._busy()
        has = bool(self.doc.pages)
        sel = bool(self.selected_pages())
        ocr_ok = self.ocr_available and has and idle
        for a in (self.a_open, self.a_add, self.a_settings, self.a_theme):
            a.setEnabled(idle)
        for a in (self.a_save, self.a_save_as, self.a_txt, self.a_select_all):
            a.setEnabled(has and idle)
        for a in (self.a_rot_l, self.a_rot_r, self.a_delete, self.a_extract):
            a.setEnabled(sel and idle)
        self.a_undo.setEnabled(self.doc.can_undo and idle)
        for a in (self.a_ocr, self.a_tables, self.a_word, self.a_excel, self.a_searchable):
            a.setEnabled(ocr_ok)
        self.a_ai.setEnabled(has and idle)
        self.a_ai_sel.setEnabled(sel and idle)
        self.thumbs.setDragEnabled(idle)
        n = len(self.doc.pages)
        cur = self.thumbs.currentRow()
        self.page_status.setText(f"Sayfa {cur + 1} / {n}" if n and cur >= 0 else "")

    def _thumb_icon(self, item: PageItem) -> QIcon:
        key = (id(item), item.rotation)
        if key not in self._thumb_cache:
            try:
                img = item.image(THUMB_DPI)
                img.thumbnail((130, 170))
                icon = QIcon()
                pix = pil_to_pixmap(img)
                icon.addPixmap(pix, QIcon.Mode.Normal)
                icon.addPixmap(pix, QIcon.Mode.Selected)
                self._thumb_cache[key] = icon
            except Exception:  # noqa: BLE001
                self._thumb_cache[key] = self.icon("file-alert-outline")
        return self._thumb_cache[key]

    @staticmethod
    def _thumb_label(pos: int, item: PageItem) -> str:
        marks = ""
        if item.ai_text or item.ai_tables:
            marks += " ✦"
        elif item.ocr or item.tables is not None:
            marks += " ✓"
        return f"{pos + 1}{marks}"

    def _rebuild_thumbs(self, select: list[PageItem] | None = None, current: PageItem | None = None) -> None:
        current = current or self.current_page()
        selected = {id(p) for p in (select if select is not None else self.selected_pages())}
        self.thumbs.blockSignals(True)
        self.thumbs.clear()
        cur_row = -1
        for pos, item in enumerate(self.doc.pages):
            w = QListWidgetItem(self._thumb_icon(item), self._thumb_label(pos, item))
            w.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            w.setToolTip(item.label)
            w.setData(Qt.ItemDataRole.UserRole, id(item))
            self.thumbs.addItem(w)
            if id(item) in selected:
                w.setSelected(True)
            if item is current:
                cur_row = pos
        if self.doc.pages:
            row = cur_row if cur_row >= 0 else 0
            self.thumbs.setCurrentRow(row, QItemSelectionModel.SelectionFlag.NoUpdate)
            if not selected:
                self.thumbs.item(row).setSelected(True)
        self.thumbs.blockSignals(False)

    def _refresh_labels(self) -> None:
        for pos, item in enumerate(self.doc.pages):
            if pos < self.thumbs.count():
                self.thumbs.item(pos).setText(self._thumb_label(pos, item))

    def _show_current(self) -> None:
        item = self.current_page()
        self._update_actions()
        if item is None:
            self.viewer.setPixmap(QPixmap())
            self.viewer.setText("Başlamak için bir PDF veya resim açın ya da buraya sürükleyin")
            self._set_text("")
            self.text_info.setText("")
            return
        self._render_view(item)
        self._set_text(item.text)
        if item.ai_text:
            self.text_info.setText("Kaynak: Yapay zekâ")
        elif item.ocr:
            self.text_info.setText(f"Kaynak: OCR — güven %{item.ocr.confidence:.0f}")
        else:
            self.text_info.setText("Bu sayfa henüz tanınmadı (F5: Metni Tanı, F7: Yapay Zekâ)")

    def _render_view(self, item: PageItem) -> None:
        width = max(200, self.viewer_scroll.viewport().width() - 24)
        key = (id(item), item.rotation, round(self.zoom, 3), self.fit_width, width if self.fit_width else 0)
        if self._view_cache and self._view_cache[0] == key:
            pix = self._view_cache[1]
        else:
            try:
                dpi = int(VIEW_DPI * (1 if self.fit_width else self.zoom))
                pix = pil_to_pixmap(item.image(max(40, min(dpi, 400))))
                if self.fit_width and pix.width() != width:
                    pix = pix.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)
            except Exception as exc:  # noqa: BLE001
                self.viewer.setPixmap(QPixmap())
                self.viewer.setText(f"Sayfa görüntülenemedi:\n{exc}")
                return
            self._view_cache = (key, pix)
        self.viewer.setPixmap(pix)

    def _set_text(self, text: str) -> None:
        self._loading_text = True
        self.text_edit.setPlainText(text)
        self._loading_text = False

    def _on_text_edited(self) -> None:
        item = self.current_page()
        if not self._loading_text and item is not None:
            item.edited_text = self.text_edit.toPlainText()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.fit_width and self.current_page():
            QTimer.singleShot(0, lambda: self.current_page() and self._render_view(self.current_page()))

    def set_zoom(self, factor: float) -> None:
        if self.fit_width:
            self.zoom = max(0.2, (self.viewer_scroll.viewport().width() - 24) / (8.27 * VIEW_DPI))
        self.fit_width = False
        self.zoom = max(0.25, min(4.0, self.zoom * factor))
        self._show_current()

    def set_fit(self) -> None:
        self.fit_width = True
        self.zoom = 1.0
        self._show_current()

    # -------------------------------------------------------------- files
    def _confirm_discard(self) -> bool:
        if not (self.doc.modified and self.doc.pages):
            return True
        res = QMessageBox.question(
            self, APP_NAME, "Belgede kaydedilmemiş değişiklikler var. Devam edilsin mi?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return res == QMessageBox.StandardButton.Yes

    def _pick_files(self, title: str) -> list[str]:
        start = self.settings.value("last_dir", str(Path.home()))
        paths, _ = QFileDialog.getOpenFileNames(self, title, start, FILE_FILTER)
        if paths:
            self.settings.setValue("last_dir", str(Path(paths[0]).parent))
        return paths

    def open_files(self, paths: list[str] | None = None) -> None:
        if not self._confirm_discard():
            return
        paths = paths if paths is not None else self._pick_files("Belge aç")
        if not paths:
            return
        self.doc = Document()
        self.doc_path = None
        self._thumb_cache.clear()
        self._view_cache = None
        self.table_editor.set_tables([])
        self.add_files(paths)
        self.doc.modified = False
        self.doc._undo.clear()
        if len(paths) == 1 and loader.is_pdf(paths[0]):
            self.doc_path = Path(paths[0]).resolve()
        self._refresh_all()

    def add_pages_dialog(self) -> None:
        paths = self._pick_files("Eklenecek dosyaları seç")
        if paths:
            self.add_files(paths)

    def add_files(self, paths: list[str]) -> None:
        added = []
        for path in paths:
            if not loader.is_supported(path) or not Path(path).is_file():
                continue
            try:
                added += self.doc.add_file(path)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.warning(self, APP_NAME, f"{Path(path).name} açılamadı:\n{exc}")
        if added:
            self._rebuild_thumbs(select=[added[0]], current=added[0])
            self._show_current()
            self._update_title()

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if self.doc.pages:
            self.add_files(paths)
        else:
            self.open_files(paths)

    def _save_path(self, title: str, suffix: str, filt: str, default_stem: str | None = None) -> str | None:
        base = self.doc_path or (self.doc.sources[0] if self.doc.sources else Path.home() / "belge")
        folder = self.settings.value("save_dir", str(base.parent))
        default = str(Path(folder) / ((default_stem or base.stem) + suffix))
        out, _ = QFileDialog.getSaveFileName(self, title, default, filt)
        if out:
            self.settings.setValue("save_dir", str(Path(out).parent))
        return out or None

    def _saved(self, out: str | Path, what: str) -> None:
        self.statusBar().showMessage(f"{what} kaydedildi: {out}", 10000)
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(f"{what} kaydedildi:\n{out}")
        open_btn = box.addButton("Dosyayı Aç", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Kapat", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is open_btn:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(out)))

    def save(self) -> None:
        if self.doc_path is None:
            self.save_as()
        else:
            self._write_pdf(self.doc_path)

    def save_as(self) -> None:
        out = self._save_path("PDF olarak kaydet", ".pdf", "PDF (*.pdf)")
        if out:
            self._write_pdf(Path(out))

    def _write_pdf(self, out: Path) -> None:
        pages = list(self.doc.pages)

        def done(path):
            # Reload from the saved file so page indices match the new PDF,
            # keeping recognition results (rotation is now baked in).
            new_doc = Document()
            for i, old in enumerate(pages):
                item = PageItem(Path(path).resolve(), i, 0, old.ocr, old.edited_text, old.tables,
                                old.ai_text, old.ai_tables)
                new_doc.pages.append(item)
            cur = self.thumbs.currentRow()
            self.doc = new_doc
            self.doc_path = Path(path).resolve()
            self._thumb_cache.clear()
            self._view_cache = None
            self._rebuild_thumbs(select=[], current=new_doc.pages[max(0, min(cur, len(new_doc.pages) - 1))])
            self._show_current()
            self._update_title()
            self.statusBar().showMessage(f"Kaydedildi: {path}", 8000)

        self._start(build_pdf, pages, out, on_done=done)

    def export_selected(self) -> None:
        pages = self.selected_pages()
        if not pages:
            return
        out = self._save_path("Seçili sayfaları kaydet", "_secilen.pdf", "PDF (*.pdf)")
        if out:
            self._start(build_pdf, pages, out, on_done=lambda p: self._saved(p, f"{len(pages)} sayfalık PDF"))

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self._confirm_discard():
            event.ignore()
            return
        if self.worker:
            self.worker.cancel()
            self.pool.waitForDone(5000)
        super().closeEvent(event)

    # ---------------------------------------------------------- page ops
    def thumbs_select_all(self) -> None:
        self.thumbs.selectAll()

    def _on_reorder(self) -> None:
        by_id = {id(p): p for p in self.doc.pages}
        order = [by_id[self.thumbs.item(i).data(Qt.ItemDataRole.UserRole)] for i in range(self.thumbs.count())]
        self.doc.reorder(order)
        self._refresh_labels()
        self._update_title()
        self._update_actions()
        self._invalidate_tables()

    def rotate(self, degrees: int) -> None:
        pages = self.selected_pages()
        if not pages or self._busy():
            return
        self.doc.rotate(pages, degrees)
        self._view_cache = None
        self._rebuild_thumbs(select=pages)
        self._show_current()
        self._update_title()
        self._invalidate_tables()

    def delete_pages(self) -> None:
        pages = self.selected_pages()
        if not pages or self._busy():
            return
        if len(pages) == len(self.doc.pages):
            QMessageBox.warning(self, APP_NAME, "Belgedeki tüm sayfalar silinemez.")
            return
        row = self.doc.position(pages[0])
        self.doc.delete(pages)
        nxt = self.doc.pages[min(row, len(self.doc.pages) - 1)]
        self._rebuild_thumbs(select=[nxt], current=nxt)
        self._show_current()
        self._update_title()
        self._invalidate_tables()
        self.statusBar().showMessage(f"{len(pages)} sayfa silindi (Geri Al: Ctrl+Z)", 5000)

    def undo(self) -> None:
        if self._busy() or not self.doc.can_undo:
            return
        self.doc.undo()
        self._view_cache = None
        self._rebuild_thumbs(select=[])
        self._show_current()
        self._update_title()
        self._invalidate_tables()

    def _invalidate_tables(self) -> None:
        self._load_tables_from_pages()

    def _load_tables_from_pages(self) -> None:
        found = self.doc.all_tables()
        if sd.value(self.settings, "merge_tables"):
            found = tables.merge_tables(found)
        self.table_editor.set_tables(found)

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
        self._refresh_labels()
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
        self._show_current()
        self.statusBar().showMessage("Hata")
        QMessageBox.critical(self, APP_NAME, f"İşlem başarısız oldu:\n{msg}")

    def _on_cancelled(self) -> None:
        self._end()
        self._show_current()
        self.statusBar().showMessage("İşlem iptal edildi", 5000)

    def _cancel_worker(self) -> None:
        if self.worker:
            self.worker.cancel()
            self.statusBar().showMessage("İptal ediliyor...")

    # ------------------------------------------------------ recognition
    @staticmethod
    def _ocr_job(items, options, force, progress=None, cancel=None):
        todo = [i for i in items if force or (i.ocr is None and i.edited_text is None)]
        for n, item in enumerate(todo):
            if cancel():
                raise ocr.Cancelled()
            progress(n, len(todo), f"Metin tanınıyor: sayfa {n + 1}/{len(todo)}")
            item.ocr = ocr.ocr_image(item.image(options.dpi), options)
            item.edited_text = None
            item.ai_text = False
        progress(len(todo), len(todo), "Tamamlandı")
        return len(todo)

    @staticmethod
    def _tables_job(items, options, borderless, progress=None, cancel=None):
        for n, item in enumerate(items):
            if cancel():
                raise ocr.Cancelled()
            progress(n, len(items), f"Tablolar aranıyor: sayfa {n + 1}/{len(items)}")
            item.tables = tables.extract_tables(item.image(options.dpi), options, borderless)
            item.ai_tables = False
        progress(len(items), len(items), "Tamamlandı")
        return sum(len(i.tables or []) for i in items)

    @staticmethod
    def _ai_job(items, settings, progress=None, cancel=None):
        for n, item in enumerate(items):
            if cancel():
                raise ocr.Cancelled()
            progress(n, len(items), f"Yapay zekâ inceliyor: sayfa {n + 1}/{len(items)}")
            result = ai.analyze_page(item.image(200), settings)
            item.edited_text = result.text
            item.ai_text = True
            item.tables = [tables.Table.from_grid(rows, source="ai") for rows in result.tables]
            item.ai_tables = True
        progress(len(items), len(items), "Tamamlandı")
        return len(items)

    def run_ocr(self, then: Callable[[], None] | None = None, force: bool = True) -> None:
        if not self.doc.pages or self._busy():
            return

        def done(count):
            self._show_current()
            self.side_tabs.setCurrentIndex(0)
            self.statusBar().showMessage(f"{count} sayfanın metni tanındı", 8000)
            if callable(then):
                then()

        self._start(self._ocr_job, list(self.doc.pages), self.options(), force, on_done=done)

    def run_tables(self, then: Callable[[], None] | None = None) -> None:
        if not self.doc.pages or self._busy():
            return

        def done(count):
            self._load_tables_from_pages()
            self.side_tabs.setCurrentIndex(1)
            n = len(self.table_editor.tables())
            self.statusBar().showMessage(f"{n} tablo bulundu", 8000)
            if callable(then):
                then()

        self._start(self._tables_job, list(self.doc.pages), self.options(),
                    sd.value(self.settings, "borderless"), on_done=done)

    def run_ai(self, selected_only: bool = False) -> None:
        if not self.doc.pages or self._busy():
            return
        settings = sd.ai_settings(self.settings)
        if not settings.configured:
            QMessageBox.information(
                self, APP_NAME,
                "Yapay zekâ özelliğini kullanmak için bir API anahtarı girmeniz gerekiyor.\n"
                "Ayarlar penceresi açılıyor.")
            if not self.open_settings(tab=1):
                return
            settings = sd.ai_settings(self.settings)
            if not settings.configured:
                return
        pages = self.selected_pages() if selected_only else list(self.doc.pages)

        def done(count):
            self._load_tables_from_pages()
            self._show_current()
            n = len(self.table_editor.tables())
            if n:
                self.side_tabs.setCurrentIndex(1)
            self.statusBar().showMessage(
                f"Yapay zekâ {count} sayfayı inceledi, {n} tablo hazır. Kontrol edip düzenleyebilirsiniz.", 10000)

        self._start(self._ai_job, pages, settings, on_done=done)

    # ------------------------------------------------------------ export
    def export_word(self) -> None:
        if not self.doc.pages:
            return
        out = self._save_path("Word olarak kaydet", ".docx", "Word belgesi (*.docx)")
        if not out:
            return

        def write():
            try:
                export_docx.export_docx([p.export_page() for p in self.doc.pages], out)
            except Exception as exc:  # noqa: BLE001
                self._on_error(str(exc))
                return
            self._saved(out, "Word belgesi")

        self.run_ocr(then=write, force=False)

    def export_text(self) -> None:
        if not self.doc.pages:
            return
        out = self._save_path("Metin olarak kaydet", ".txt", "Metin dosyası (*.txt)")
        if not out:
            return

        def write():
            export_docx.export_txt([p.export_page() for p in self.doc.pages], out)
            self._saved(out, "Metin dosyası")

        if self.ocr_available:
            self.run_ocr(then=write, force=False)
        else:
            write()

    def export_searchable(self) -> None:
        if not self.doc.pages:
            return
        out = self._save_path("Aranabilir PDF kaydet", "_aranabilir.pdf", "PDF (*.pdf)")
        if not out:
            return
        if any(Path(out).resolve() == s for s in self.doc.sources):
            QMessageBox.warning(self, APP_NAME, "Kaynak dosyanın üzerine yazılamaz. Farklı bir ad seçin.")
            return
        self._start(build_pdf, list(self.doc.pages), out, True, self.options(),
                    sd.value(self.settings, "skip_text"),
                    on_done=lambda p: self._saved(p, "Aranabilir PDF"))

    def export_excel(self) -> None:
        if not self.doc.pages:
            return
        out = self._save_path("Tabloları Excel'e kaydet", ".xlsx", "Excel çalışma kitabı (*.xlsx)")
        if not out:
            return

        def write():
            found = self.table_editor.tables()
            if not found:
                QMessageBox.information(self, APP_NAME, "Belgede tablo bulunamadı.")
                return
            try:
                tables.export_xlsx(found, out)
            except Exception as exc:  # noqa: BLE001
                self._on_error(str(exc))
                return
            self._saved(out, f"{len(found)} tablo içeren Excel dosyası")

        if any(p.tables is not None for p in self.doc.pages) or self.table_editor.tables():
            write()
        else:
            self.run_tables(then=write)

    # ------------------------------------------------------------- misc
    def open_settings(self, tab: int = 0) -> bool:
        old_merge = sd.value(self.settings, "merge_tables")
        dlg = SettingsDialogProxy(self, tab)
        accepted = dlg.exec() == SettingsDialogProxy.DialogCode.Accepted
        if accepted:
            self.apply_theme()
            if old_merge != sd.value(self.settings, "merge_tables"):
                self._load_tables_from_pages()
        return accepted

    def about(self) -> None:
        QMessageBox.about(
            self, f"{APP_NAME} hakkında",
            f"<h3>{APP_NAME} {__version__}</h3>"
            "<p>Taranmış belgelerden metin ve tablo tanıma, yapay zekâ destekli analiz, "
            "Word/Excel/aranabilir PDF dışa aktarma ve PDF sayfa düzenleme.</p>"
            "<p>OCR motoru: Tesseract (Apache 2.0)</p>",
        )


class SettingsDialogProxy(sd.SettingsDialog):
    def __init__(self, window: MainWindow, tab: int):
        super().__init__(window, window.settings, window.languages, tab)
