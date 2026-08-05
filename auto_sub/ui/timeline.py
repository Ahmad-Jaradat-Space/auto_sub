from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QTableWidget,
    QTableWidgetItem,
    QAbstractItemView,
    QHeaderView,
)

from ..core.models import Segment


def _fmt(t: float) -> str:
    m = int(t // 60)
    s = t % 60
    return f"{m:02d}:{s:05.2f}"


def _parse(text: str) -> float:
    text = text.strip()
    if ":" in text:
        m, s = text.split(":", 1)
        return int(m) * 60 + float(s)
    return float(text)


class TimelineTable(QTableWidget):
    """Editable table: Start | End | Text. Emits `changed` after any edit."""

    changed = Signal()
    rowClicked = Signal(float)  # emit segment start time on row click → seek

    def __init__(self) -> None:
        super().__init__(0, 3)
        self.setHorizontalHeaderLabels(["Start", "End", "Text"])
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setStyleSheet(
            "QTableWidget{background:#1a1a1a; alternate-background-color:#202020;"
            " color:#ddd; gridline-color:#2a2a2a;}"
            "QHeaderView::section{background:#252525; color:#ccc; padding:4px;"
            " border:0; border-right:1px solid #333;}"
            "QTableWidget::item:selected{background:#2d4a6e; color:#fff;}"
        )
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        self.itemChanged.connect(lambda _: self.changed.emit())
        self.cellClicked.connect(self._on_clicked)
        self._active_row = -1

    def _on_clicked(self, row: int, _col: int) -> None:
        item = self.item(row, 0)
        if item is None:
            return
        try:
            t = _parse(item.text())
        except ValueError:
            return
        self.rowClicked.emit(t)

    def highlight_active(self, t: float) -> None:
        """Pale-yellow background on whichever segment currently contains t."""
        active = -1
        for r in range(self.rowCount()):
            try:
                s = _parse(self.item(r, 0).text())
                e = _parse(self.item(r, 1).text())
            except (ValueError, AttributeError):
                continue
            if s <= t < e:
                active = r
                break
        if active == self._active_row:
            return
        # Clear old highlight.
        if 0 <= self._active_row < self.rowCount():
            for c in range(self.columnCount()):
                it = self.item(self._active_row, c)
                if it is not None:
                    it.setBackground(QColor(0, 0, 0, 0))
        # Apply new.
        if active >= 0:
            for c in range(self.columnCount()):
                it = self.item(active, c)
                if it is not None:
                    it.setBackground(QColor(80, 110, 60, 120))
        self._active_row = active

    def load(self, segments: list[Segment]) -> None:
        self.blockSignals(True)
        self.setRowCount(len(segments))
        for row, seg in enumerate(segments):
            self.setItem(row, 0, QTableWidgetItem(_fmt(seg.start)))
            self.setItem(row, 1, QTableWidgetItem(_fmt(seg.end)))
            self.setItem(row, 2, QTableWidgetItem(seg.text))
        self.blockSignals(False)
        self.changed.emit()

    def dump(self) -> list[Segment]:
        out: list[Segment] = []
        for row in range(self.rowCount()):
            try:
                start = _parse(self.item(row, 0).text())
                end = _parse(self.item(row, 1).text())
            except (ValueError, AttributeError):
                continue
            text_item = self.item(row, 2)
            text = text_item.text().strip() if text_item else ""
            if text:
                out.append(Segment(start=start, end=end, text=text))
        return out

    def replace_texts(self, texts: list[str]) -> None:
        """Replace just the text column for existing rows (used after translation)."""
        import sys
        if len(texts) != self.rowCount():
            raise ValueError(f"text count {len(texts)} != rows {self.rowCount()}")
        self.blockSignals(True)
        for row, t in enumerate(texts):
            item = self.item(row, 2)
            if item is None:
                from PySide6.QtWidgets import QTableWidgetItem
                item = QTableWidgetItem()
                self.setItem(row, 2, item)
            item.setText(t)
        self.blockSignals(False)
        # Verify what actually landed in the cells.
        sample = [self.item(r, 2).text() for r in range(min(2, self.rowCount()))]
        print(f"[auto_sub] replace_texts applied {len(texts)} rows. First rows now: {sample!r}",
              file=sys.stderr, flush=True)
        self.changed.emit()
