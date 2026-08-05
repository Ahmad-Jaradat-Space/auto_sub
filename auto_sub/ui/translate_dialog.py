from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..core.models import Segment
from ..core.translate_io import build_prompt, parse_numbered


def _has_arabic(s: str) -> bool:
    for ch in s:
        cp = ord(ch)
        if (
            0x0600 <= cp <= 0x06FF
            or 0x0750 <= cp <= 0x077F
            or 0x08A0 <= cp <= 0x08FF
            or 0xFB50 <= cp <= 0xFDFF
            or 0xFE70 <= cp <= 0xFEFF
        ):
            return True
    return False


class TranslateDialog(QDialog):
    """Side-by-side translation editor.

    Flow:
      1. Copy the prompt → paste into Claude/ChatGPT.
      2. Paste the Arabic reply into the bulk-paste box, click "Fill Arabic
         column". This is best-effort — it autofills as many cells as it can.
      3. Manually fix any row that didn't autofill (or just type directly).
      4. Click OK. Every row with non-empty Arabic is applied; rows still in
         English are left alone (with a confirmation).
    """

    def __init__(self, segments: list[Segment], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Translate to Arabic")
        self.resize(1100, 800)
        self._segments = segments
        self._translated: list[str] | None = None

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(
            "<b>Step 1.</b> Copy the prompt → paste into Claude/ChatGPT.<br>"
            "<b>Step 2.</b> Paste the Arabic reply into the bulk box and click "
            "<b>Fill Arabic column</b> (auto-pairs by line). "
            "Or just type Arabic directly into any cell.<br>"
            "<b>Step 3.</b> Click OK to apply."
        ))

        # --- Prompt block ---
        self.prompt_view = QPlainTextEdit()
        self.prompt_view.setReadOnly(True)
        self.prompt_view.setPlainText(build_prompt(segments))
        self.prompt_view.setMaximumHeight(140)
        layout.addWidget(self.prompt_view)

        row = QHBoxLayout()
        self.copy_btn = QPushButton("Copy prompt")
        self.copy_btn.clicked.connect(self._copy_prompt)
        row.addWidget(self.copy_btn)
        row.addStretch()
        layout.addLayout(row)

        # --- Bulk paste ---
        layout.addWidget(QLabel("Paste Arabic translation here:"))
        self.bulk_input = QPlainTextEdit()
        self.bulk_input.setMaximumHeight(140)
        layout.addWidget(self.bulk_input)

        fill_row = QHBoxLayout()
        self.fill_btn = QPushButton("⬇  Fill Arabic column from paste")
        self.fill_btn.clicked.connect(self._fill_from_bulk)
        fill_row.addWidget(self.fill_btn)
        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("color:#aaa;")
        fill_row.addWidget(self.status_lbl, 1)
        layout.addLayout(fill_row)

        # --- Side-by-side table ---
        self.table = QTableWidget(len(segments), 2)
        self.table.setHorizontalHeaderLabels(["English (read-only)", "Arabic (editable)"])
        self.table.verticalHeader().setVisible(True)
        self.table.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        for i, seg in enumerate(segments):
            en = QTableWidgetItem(seg.text)
            en.setFlags(en.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(i, 0, en)
            self.table.setItem(i, 1, QTableWidgetItem(""))
        layout.addWidget(self.table, 1)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._on_ok)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

    def _copy_prompt(self) -> None:
        QGuiApplication.clipboard().setText(self.prompt_view.toPlainText())
        self.copy_btn.setText("Copied ✓")

    def _fill_from_bulk(self) -> None:
        text = self.bulk_input.toPlainText()
        n = self.table.rowCount()

        # Try strict numbered parsing first; fall back to non-empty lines.
        parsed: list[str] | None = None
        try:
            parsed = parse_numbered(text, n)
        except ValueError:
            parsed = None

        if parsed is None:
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            # Strip any leading "N." even if count mismatches.
            import re
            num_re = re.compile(r"^\s*[\(\[]?\d+[\.\)\-:،]\s*")
            lines = [num_re.sub("", ln, count=1).strip() for ln in lines]
            parsed = lines

        filled = 0
        for i in range(min(len(parsed), n)):
            if parsed[i]:
                self.table.item(i, 1).setText(parsed[i])
                filled += 1

        arabic_rows = sum(
            1 for r in range(n) if _has_arabic(self.table.item(r, 1).text())
        )
        if filled == 0:
            msg = "❌ Nothing to fill. Paste the Arabic reply above and try again."
            color = "#ff8"
        elif arabic_rows == 0:
            msg = (
                f"⚠️ Filled {filled}/{n} cells but found NO Arabic characters. "
                "Did you paste the prompt by accident?"
            )
            color = "#fc8"
        else:
            msg = f"✓ Filled {filled}/{n} cells, {arabic_rows} contain Arabic."
            color = "#8f8"
        self.status_lbl.setStyleSheet(f"color:{color};")
        self.status_lbl.setText(msg)

    def _on_ok(self) -> None:
        n = self.table.rowCount()
        out: list[str] = []
        empty_rows: list[int] = []
        for r in range(n):
            t = self.table.item(r, 1).text().strip()
            if not t:
                empty_rows.append(r + 1)
                # Fall back to English so the row isn't blank in the burn.
                t = self.table.item(r, 0).text()
            out.append(t)

        if empty_rows:
            res = QMessageBox.question(
                self, "Some rows empty",
                f"Rows {empty_rows} have no Arabic — they will keep their English text.\n\n"
                "Apply anyway?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if res != QMessageBox.Yes:
                return

        self._translated = out
        self.accept()

    def translated_lines(self) -> list[str] | None:
        return self._translated
