"""Dialog for PDF page operations."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from belgeocr import APP_NAME, loader, pdf_tools

PDF_FILTER = "PDF (*.pdf)"
MERGE_FILTER = "PDF ve resimler (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp)"


class _FilePicker(QWidget):
    def __init__(self, files: list[str], settings: QSettings, save: bool = False):
        super().__init__()
        self.settings, self.save = settings, save
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.edit = QComboBox() if not save else None
        self.line = QLineEdit()
        if self.edit is not None:
            self.edit.setEditable(True)
            self.edit.addItems([f for f in files if loader.is_pdf(f)])
            layout.addWidget(self.edit, 1)
        else:
            layout.addWidget(self.line, 1)
        btn = QPushButton("Gözat...")
        btn.clicked.connect(self._browse)
        layout.addWidget(btn)

    def path(self) -> str:
        return (self.edit.currentText() if self.edit is not None else self.line.text()).strip()

    def set_path(self, path: str) -> None:
        if self.edit is not None:
            self.edit.setEditText(path)
        else:
            self.line.setText(path)

    def _browse(self) -> None:
        start = self.path() or self.settings.value("last_dir", str(Path.home()))
        if self.save:
            path, _ = QFileDialog.getSaveFileName(self, "Kaydet", start, PDF_FILTER)
        else:
            path, _ = QFileDialog.getOpenFileName(self, "PDF seç", start, PDF_FILTER)
        if path:
            self.set_path(path)


class PdfToolsDialog(QDialog):
    def __init__(self, parent, files: list[str], settings: QSettings):
        super().__init__(parent)
        self.setWindowTitle("PDF Araçları")
        self.resize(640, 440)
        self.files, self.settings = files, settings
        self.created: list[Path] = []

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._merge_tab(), "Birleştir")
        self.tabs.addTab(self._split_tab(), "Böl")
        self.tabs.addTab(self._rotate_tab(), "Döndür")
        self.tabs.addTab(self._pages_tab("delete"), "Sayfa Sil")
        self.tabs.addTab(self._pages_tab("extract"), "Sayfa Çıkar")
        layout.addWidget(self.tabs)
        hint = QLabel("Sayfa aralığı örnekleri: 1-3, 5, 8-  (boş = tüm sayfalar)")
        hint.setStyleSheet("color: gray")
        layout.addWidget(hint)
        buttons = QDialogButtonBox()
        run = buttons.addButton("Uygula", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("Kapat", QDialogButtonBox.ButtonRole.RejectRole)
        run.clicked.connect(self._run)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # -------------------------------------------------------------- tabs
    def _merge_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.addWidget(QLabel("Sırayla birleştirilecek dosyalar (PDF veya resim):"))
        row = QHBoxLayout()
        self.merge_list = QListWidget()
        self.merge_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        for f in self.files:
            self._add_merge_item(f)
        row.addWidget(self.merge_list, 1)
        side = QVBoxLayout()
        for text, slot in (("Ekle...", self._merge_add), ("Kaldır", self._merge_remove),
                           ("Yukarı", lambda: self._merge_move(-1)),
                           ("Aşağı", lambda: self._merge_move(1))):
            b = QPushButton(text)
            b.clicked.connect(slot)
            side.addWidget(b)
        side.addStretch()
        row.addLayout(side)
        layout.addLayout(row)
        form = QFormLayout()
        self.merge_out = _FilePicker([], self.settings, save=True)
        form.addRow("Çıktı dosyası:", self.merge_out)
        layout.addLayout(form)
        return w

    def _add_merge_item(self, path: str) -> None:
        item = QListWidgetItem(Path(path).name)
        item.setToolTip(path)
        item.setData(Qt.ItemDataRole.UserRole, path)
        self.merge_list.addItem(item)

    def _merge_add(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Dosya ekle", self.settings.value("last_dir", str(Path.home())), MERGE_FILTER
        )
        for p in paths:
            self._add_merge_item(p)

    def _merge_remove(self) -> None:
        row = self.merge_list.currentRow()
        if row >= 0:
            self.merge_list.takeItem(row)

    def _merge_move(self, delta: int) -> None:
        row = self.merge_list.currentRow()
        new = row + delta
        if row < 0 or not 0 <= new < self.merge_list.count():
            return
        item = self.merge_list.takeItem(row)
        self.merge_list.insertItem(new, item)
        self.merge_list.setCurrentRow(new)

    def _split_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.split_src = _FilePicker(self.files, self.settings)
        form.addRow("PDF:", self.split_src)
        self.split_each = QRadioButton("Her sayfayı ayrı dosya yap")
        self.split_each.setChecked(True)
        self.split_groups_radio = QRadioButton("Aralıklara göre böl:")
        self.split_groups = QLineEdit()
        self.split_groups.setPlaceholderText("ör. 1-3; 4-10; 11-")
        self.split_groups.textEdited.connect(lambda: self.split_groups_radio.setChecked(True))
        form.addRow(self.split_each)
        form.addRow(self.split_groups_radio, self.split_groups)
        self.split_dir = QLineEdit()
        self.split_dir.setPlaceholderText("Boş = kaynak dosyanın klasörü")
        browse = QPushButton("Gözat...")
        browse.clicked.connect(self._split_browse)
        row = QHBoxLayout()
        row.addWidget(self.split_dir, 1)
        row.addWidget(browse)
        form.addRow("Çıktı klasörü:", row)
        return w

    def _split_browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Klasör seç")
        if d:
            self.split_dir.setText(d)

    def _rotate_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.rot_src = _FilePicker(self.files, self.settings)
        form.addRow("PDF:", self.rot_src)
        self.rot_angle = QComboBox()
        for label, deg in (("90° saat yönünde", 90), ("180°", 180), ("90° saat yönü tersine", 270)):
            self.rot_angle.addItem(label, deg)
        form.addRow("Açı:", self.rot_angle)
        self.rot_pages = QLineEdit()
        self.rot_pages.setPlaceholderText("Boş = tüm sayfalar")
        form.addRow("Sayfalar:", self.rot_pages)
        self.rot_out = _FilePicker([], self.settings, save=True)
        form.addRow("Çıktı dosyası:", self.rot_out)
        return w

    def _pages_tab(self, kind: str) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        src = _FilePicker(self.files, self.settings)
        pages = QLineEdit()
        pages.setPlaceholderText("ör. 2, 4-6")
        out = _FilePicker([], self.settings, save=True)
        form.addRow("PDF:", src)
        form.addRow("Silinecek sayfalar:" if kind == "delete" else "Çıkarılacak sayfalar:", pages)
        form.addRow("Çıktı dosyası:", out)
        setattr(self, f"{kind}_widgets", (src, pages, out))
        return w

    # --------------------------------------------------------------- run
    @staticmethod
    def _default_out(src: str, suffix: str) -> str:
        p = Path(src)
        return str(p.with_name(f"{p.stem}_{suffix}.pdf"))

    def _check_out(self, src: str, out: str) -> None:
        if src and out and Path(src).resolve() == Path(out).resolve():
            raise ValueError("Çıktı dosyası kaynak dosyayla aynı olamaz.")

    def _require(self, src: str) -> str:
        if not src or not Path(src).is_file():
            raise ValueError("Lütfen geçerli bir PDF dosyası seçin.")
        return src

    def _run(self) -> None:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            outputs = self._execute(self.tabs.currentIndex())
        except Exception as exc:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, APP_NAME, str(exc))
            return
        QApplication.restoreOverrideCursor()
        self.created.extend(outputs)
        listing = "\n".join(str(p) for p in outputs[:10])
        more = f"\n... ve {len(outputs) - 10} dosya daha" if len(outputs) > 10 else ""
        QMessageBox.information(self, APP_NAME, f"Oluşturuldu:\n{listing}{more}")

    def _execute(self, tab: int) -> list[Path]:
        if tab == 0:
            paths = [self.merge_list.item(i).data(Qt.ItemDataRole.UserRole)
                     for i in range(self.merge_list.count())]
            if len(paths) < 2:
                raise ValueError("Birleştirmek için en az iki dosya ekleyin.")
            out = self.merge_out.path() or self._default_out(paths[0], "birlesik")
            for p in paths:
                self._check_out(p, out)
            return [pdf_tools.merge(paths, out)]
        if tab == 1:
            src = self._require(self.split_src.path())
            groups = None
            if self.split_groups_radio.isChecked():
                groups = [g.strip() for g in self.split_groups.text().split(";") if g.strip()]
                if not groups:
                    raise ValueError("Bölme aralıklarını girin, ör. 1-3; 4-")
            out_dir = self.split_dir.text().strip() or str(Path(src).parent)
            return pdf_tools.split(src, out_dir, groups)
        if tab == 2:
            src = self._require(self.rot_src.path())
            out = self.rot_out.path() or self._default_out(src, "dondurulmus")
            self._check_out(src, out)
            return [pdf_tools.rotate(src, out, self.rot_angle.currentData(), self.rot_pages.text())]
        kind = "delete" if tab == 3 else "extract"
        src_w, pages_w, out_w = getattr(self, f"{kind}_widgets")
        src = self._require(src_w.path())
        if not pages_w.text().strip():
            raise ValueError("Sayfa numaralarını girin.")
        out = out_w.path() or self._default_out(src, "duzenlenmis" if kind == "delete" else "secilen")
        self._check_out(src, out)
        fn = pdf_tools.delete_pages if kind == "delete" else pdf_tools.extract_pages
        return [fn(src, out, pages_w.text())]
