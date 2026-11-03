"""Preferences dialog (OCR options, theme, AI provider)."""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from belgeocr import ai, tesseract_setup
from belgeocr.ocr import OcrOptions

DEFAULTS = {
    "lang": "tur+eng",
    "dpi": 300,
    "deskew": True,
    "borderless": True,
    "merge_tables": True,
    "skip_text": True,
    "theme": "light",
    "ai/provider": "gemini",
    "ai/api_key": "",
    "ai/model": "",
}


def value(settings: QSettings, key: str):
    default = DEFAULTS[key]
    raw = settings.value(key, default)
    if isinstance(default, bool):
        return raw if isinstance(raw, bool) else str(raw).lower() in ("1", "true", "yes")
    if isinstance(default, int):
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default
    return str(raw) if raw is not None else default


def ocr_options(settings: QSettings) -> OcrOptions:
    return OcrOptions(lang=value(settings, "lang"), dpi=value(settings, "dpi"),
                      deskew=value(settings, "deskew"))


def ai_settings(settings: QSettings) -> ai.AiSettings:
    return ai.AiSettings(value(settings, "ai/provider"), value(settings, "ai/api_key"),
                         value(settings, "ai/model"))


class SettingsDialog(QDialog):
    def __init__(self, parent, settings: QSettings, languages: list[str], tab: int = 0):
        super().__init__(parent)
        self.setWindowTitle("Ayarlar")
        self.setMinimumWidth(560)
        self.settings = settings
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._general_tab(languages), "Genel")
        self.tabs.addTab(self._ai_tab(), "Yapay Zekâ")
        self.tabs.setCurrentIndex(tab)
        layout.addWidget(self.tabs)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Kaydet")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("İptal")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _general_tab(self, languages: list[str]) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.lang = QComboBox()
        options = []
        if "tur" in languages and "eng" in languages:
            options.append("tur+eng")
        options += [l for l in ("tur", "eng") if l in languages]
        options += [l for l in languages if l not in ("tur", "eng")]
        for code in options or [value(self.settings, "lang")]:
            self.lang.addItem(tesseract_setup.language_label(code), code)
        idx = self.lang.findData(value(self.settings, "lang"))
        self.lang.setCurrentIndex(max(idx, 0))
        form.addRow("OCR dili:", self.lang)
        self.dpi = QComboBox()
        for dpi in (200, 300, 400):
            self.dpi.addItem(f"{dpi} DPI", dpi)
        self.dpi.setCurrentIndex(max(self.dpi.findData(value(self.settings, "dpi")), 0))
        form.addRow("Tanıma çözünürlüğü:", self.dpi)
        self.deskew = QCheckBox("Eğik taramaları otomatik düzelt")
        self.borderless = QCheckBox("Çizgisiz tabloları da ara")
        self.merge = QCheckBox("Sayfalara bölünmüş tabloları tek tabloda birleştir")
        self.skip_text = QCheckBox("Aranabilir PDF'te zaten metni olan sayfaları atla")
        for box, key in ((self.deskew, "deskew"), (self.borderless, "borderless"),
                         (self.merge, "merge_tables"), (self.skip_text, "skip_text")):
            box.setChecked(value(self.settings, key))
            form.addRow(box)
        self.theme = QComboBox()
        self.theme.addItem("Açık", "light")
        self.theme.addItem("Koyu", "dark")
        self.theme.setCurrentIndex(max(self.theme.findData(value(self.settings, "theme")), 0))
        form.addRow("Tema:", self.theme)
        return w

    def _ai_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        info = QLabel(
            "Yapay zekâ, sayfa görüntüsünü seçtiğiniz servise gönderip metni ve tabloları "
            "yüksek doğrulukla okur. Belgeleriniz bu servisin sunucularına gönderilir."
        )
        info.setWordWrap(True)
        form.addRow(info)
        self.provider = QComboBox()
        for p in ai.PROVIDERS.values():
            self.provider.addItem(p.name, p.key)
        self.provider.setCurrentIndex(max(self.provider.findData(value(self.settings, "ai/provider")), 0))
        self.provider.currentIndexChanged.connect(self._provider_changed)
        form.addRow("Servis:", self.provider)
        key_row = QHBoxLayout()
        self.api_key = QLineEdit(value(self.settings, "ai/api_key"))
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("API anahtarını yapıştırın")
        show = QCheckBox("Göster")
        show.toggled.connect(lambda on: self.api_key.setEchoMode(
            QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        key_row.addWidget(self.api_key, 1)
        key_row.addWidget(show)
        form.addRow("API anahtarı:", key_row)
        self.get_key = QPushButton()
        self.get_key.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl(ai.PROVIDERS[self.provider.currentData()].key_url)))
        form.addRow("", self.get_key)
        self.model = QLineEdit(value(self.settings, "ai/model"))
        form.addRow("Model:", self.model)
        test = QPushButton("Bağlantıyı test et")
        test.clicked.connect(self._test)
        form.addRow("", test)
        self._provider_changed()
        return w

    def _provider_changed(self) -> None:
        p = ai.PROVIDERS[self.provider.currentData()]
        self.model.setPlaceholderText(f"Varsayılan: {p.default_model}")
        self.get_key.setText(f"{p.name} API anahtarı al...")

    def _current_ai(self) -> ai.AiSettings:
        return ai.AiSettings(self.provider.currentData(), self.api_key.text(), self.model.text())

    def _test(self) -> None:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            reply = ai.test_connection(self._current_ai())
        except ai.AiError as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Yapay Zekâ", f"Bağlantı başarısız:\n{exc}")
            return
        QApplication.restoreOverrideCursor()
        QMessageBox.information(self, "Yapay Zekâ",
                                f"Bağlantı başarılı ({self._current_ai().model_name}).\nYanıt: {reply}")

    def _save(self) -> None:
        s = self.settings
        s.setValue("lang", self.lang.currentData())
        s.setValue("dpi", self.dpi.currentData())
        s.setValue("deskew", self.deskew.isChecked())
        s.setValue("borderless", self.borderless.isChecked())
        s.setValue("merge_tables", self.merge.isChecked())
        s.setValue("skip_text", self.skip_text.isChecked())
        s.setValue("theme", self.theme.currentData())
        s.setValue("ai/provider", self.provider.currentData())
        s.setValue("ai/api_key", self.api_key.text().strip())
        s.setValue("ai/model", self.model.text().strip())
        self.accept()
