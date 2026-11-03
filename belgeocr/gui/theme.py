"""Light/dark Fusion themes."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

ACCENT = "#1E64C8"

_COMMON_QSS = """
QToolBar { spacing: 4px; padding: 4px; border: none; }
QToolButton { padding: 4px 6px; border-radius: 6px; }
QToolButton:hover { background: rgba(30, 100, 200, 0.15); }
QToolButton:pressed { background: rgba(30, 100, 200, 0.30); }
QListWidget#thumbs::item { border-radius: 6px; padding: 4px; margin: 2px; }
QListWidget#thumbs::item:selected { background: rgba(30, 100, 200, 0.35); color: palette(text); }
QTabWidget::pane { border: 1px solid palette(mid); border-radius: 4px; }
QStatusBar QLabel { padding: 0 6px; }
"""


def icon_color(mode: str) -> str:
    return "#E6E6E6" if mode == "dark" else "#2B3A55"


def apply_theme(app: QApplication, mode: str) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    if mode == "dark":
        colors = {
            QPalette.ColorRole.Window: "#2B2D31",
            QPalette.ColorRole.WindowText: "#E6E6E6",
            QPalette.ColorRole.Base: "#1E1F22",
            QPalette.ColorRole.AlternateBase: "#2B2D31",
            QPalette.ColorRole.ToolTipBase: "#3A3D42",
            QPalette.ColorRole.ToolTipText: "#E6E6E6",
            QPalette.ColorRole.Text: "#E6E6E6",
            QPalette.ColorRole.Button: "#36393F",
            QPalette.ColorRole.ButtonText: "#E6E6E6",
            QPalette.ColorRole.BrightText: "#FF6B6B",
            QPalette.ColorRole.Highlight: ACCENT,
            QPalette.ColorRole.HighlightedText: "#FFFFFF",
            QPalette.ColorRole.Mid: "#4A4D52",
            QPalette.ColorRole.PlaceholderText: "#8A8D93",
        }
        disabled = "#6D7076"
    else:
        colors = {
            QPalette.ColorRole.Window: "#F3F5F9",
            QPalette.ColorRole.WindowText: "#1F2937",
            QPalette.ColorRole.Base: "#FFFFFF",
            QPalette.ColorRole.AlternateBase: "#F0F3F8",
            QPalette.ColorRole.ToolTipBase: "#FFFFFF",
            QPalette.ColorRole.ToolTipText: "#1F2937",
            QPalette.ColorRole.Text: "#1F2937",
            QPalette.ColorRole.Button: "#E9EDF4",
            QPalette.ColorRole.ButtonText: "#1F2937",
            QPalette.ColorRole.BrightText: "#C62828",
            QPalette.ColorRole.Highlight: ACCENT,
            QPalette.ColorRole.HighlightedText: "#FFFFFF",
            QPalette.ColorRole.Mid: "#C9D1DE",
            QPalette.ColorRole.PlaceholderText: "#8A94A6",
        }
        disabled = "#A0A7B4"
    for role, color in colors.items():
        pal.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor(disabled))
    app.setPalette(pal)
    app.setStyleSheet(_COMMON_QSS)
