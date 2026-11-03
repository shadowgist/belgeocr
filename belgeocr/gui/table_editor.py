"""Editable view of recognized tables before Excel export."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from belgeocr.tables import Table


class TableEditor(QWidget):
    changed = Signal()

    def __init__(self, icon_factory=None):
        super().__init__()
        self._tables: list[Table] = []
        self._loading = False
        self._icon = icon_factory or (lambda name: None)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        bar = QHBoxLayout()
        self.selector = QComboBox()
        self.selector.currentIndexChanged.connect(self._show_current)
        bar.addWidget(self.selector, 1)
        self.buttons: dict[str, QToolButton] = {}
        for key, icon, tip, slot in (
            ("row_add", "table-row-plus-after", "Alta satır ekle", self.add_row),
            ("row_del", "table-row-remove", "Seçili satırları sil", self.delete_rows),
            ("col_add", "table-column-plus-after", "Sağa sütun ekle", self.add_column),
            ("col_del", "table-column-remove", "Seçili sütunları sil", self.delete_columns),
            ("table_del", "table-remove", "Bu tabloyu listeden çıkar", self.delete_table),
        ):
            btn = QToolButton()
            btn.setToolTip(tip)
            btn.setAutoRaise(True)
            btn.clicked.connect(slot)
            bar.addWidget(btn)
            self.buttons[key] = btn
            btn.setProperty("icon_name", icon)
        layout.addLayout(bar)

        self.grid = QTableWidget()
        self.grid.setAlternatingRowColors(True)
        self.grid.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.grid.itemChanged.connect(self._item_changed)
        layout.addWidget(self.grid, 1)
        self.hint = QLabel("Henüz tablo yok. \"Tabloları Tanı\" veya \"Yapay Zekâ ile Analiz\" kullanın.")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.refresh_icons()
        self._update_state()

    def refresh_icons(self) -> None:
        for btn in self.buttons.values():
            icon = self._icon(btn.property("icon_name"))
            if icon is not None:
                btn.setIcon(icon)

    # --------------------------------------------------------------- data
    def set_tables(self, tables: list[Table]) -> None:
        self._tables = list(tables)
        self.selector.blockSignals(True)
        self.selector.clear()
        for i, t in enumerate(self._tables, start=1):
            origin = "Yapay zekâ" if t.source == "ai" else "OCR"
            self.selector.addItem(f"Tablo {i} — Sayfa {t.page_label} — {t.n_rows}×{t.n_cols} ({origin})")
        self.selector.blockSignals(False)
        self.selector.setCurrentIndex(0 if self._tables else -1)
        self._show_current()

    def tables(self) -> list[Table]:
        return list(self._tables)

    def current(self) -> Table | None:
        i = self.selector.currentIndex()
        return self._tables[i] if 0 <= i < len(self._tables) else None

    def _update_state(self) -> None:
        has = self.current() is not None
        for btn in self.buttons.values():
            btn.setEnabled(has)
        self.grid.setVisible(has)
        self.hint.setVisible(not has)

    def _show_current(self) -> None:
        table = self.current()
        self._loading = True
        self.grid.clear()
        self.grid.clearSpans()
        if table:
            self.grid.setRowCount(table.n_rows)
            self.grid.setColumnCount(table.n_cols)
            for cell in table.cells:
                self.grid.setItem(cell.row, cell.col, QTableWidgetItem(cell.text))
                if cell.rowspan > 1 or cell.colspan > 1:
                    self.grid.setSpan(cell.row, cell.col, cell.rowspan, cell.colspan)
            self.grid.resizeColumnsToContents()
            for c in range(table.n_cols):
                self.grid.setColumnWidth(c, min(max(self.grid.columnWidth(c), 60), 320))
        else:
            self.grid.setRowCount(0)
            self.grid.setColumnCount(0)
        self._loading = False
        self._update_state()

    def _item_changed(self, item: QTableWidgetItem) -> None:
        table = self.current()
        if self._loading or table is None:
            return
        for cell in table.cells:
            if cell.row == item.row() and cell.col == item.column():
                cell.text = item.text()
                break
        else:
            from belgeocr.tables import Cell

            table.cells.append(Cell(item.row(), item.column(), item.text()))
        self.changed.emit()

    # ----------------------------------------------------- structure edits
    def _replace_current(self, grid: list[list[str]]) -> None:
        old = self.current()
        new = Table.from_grid(grid, old.page, old.ruled, old.source)
        new.last_page = old.last_page
        if not grid or not grid[0]:
            self.delete_table()
            return
        idx = self.selector.currentIndex()
        self._tables[idx] = new
        origin = "Yapay zekâ" if new.source == "ai" else "OCR"
        self.selector.setItemText(idx, f"Tablo {idx + 1} — Sayfa {new.page_label} — "
                                       f"{new.n_rows}×{new.n_cols} ({origin})")
        self._show_current()
        self.changed.emit()

    def _selected(self, axis: str) -> list[int]:
        idx = self.grid.selectedIndexes() or ([self.grid.currentIndex()] if self.grid.currentIndex().isValid() else [])
        return sorted({i.row() if axis == "row" else i.column() for i in idx})

    def add_row(self) -> None:
        table = self.current()
        if table:
            grid = table.to_grid()
            rows = self._selected("row")
            at = rows[-1] + 1 if rows else len(grid)
            grid.insert(at, [""] * table.n_cols)
            self._replace_current(grid)

    def delete_rows(self) -> None:
        table = self.current()
        rows = set(self._selected("row"))
        if table and rows:
            self._replace_current([r for i, r in enumerate(table.to_grid()) if i not in rows])

    def add_column(self) -> None:
        table = self.current()
        if table:
            cols = self._selected("col")
            at = cols[-1] + 1 if cols else table.n_cols
            self._replace_current([r[:at] + [""] + r[at:] for r in table.to_grid()])

    def delete_columns(self) -> None:
        table = self.current()
        cols = set(self._selected("col"))
        if table and cols:
            self._replace_current([[v for i, v in enumerate(r) if i not in cols] for r in table.to_grid()])

    def delete_table(self) -> None:
        idx = self.selector.currentIndex()
        if 0 <= idx < len(self._tables):
            del self._tables[idx]
            self.set_tables(self._tables)
            self.changed.emit()
