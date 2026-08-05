from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..core.models import Style


class _ColorSwatch(QPushButton):
    """Always-readable color picker: solid colored square + hex on the right."""

    changed = Signal(str)

    def __init__(self, initial: str = "#FFFFFF") -> None:
        super().__init__()
        self._color = initial.upper()
        self.setMinimumHeight(28)
        self.setCursor(Qt.PointingHandCursor)
        self.clicked.connect(self._pick)
        self._refresh()

    def _refresh(self) -> None:
        # Build a CSS that shows a colored block on the left and the hex code
        # on a neutral background — always readable regardless of color.
        self.setText(self._color)
        self.setStyleSheet(
            "QPushButton{"
            f"text-align:right; padding-right:8px; padding-left:36px;"
            f"background:#2a2a2a; color:#eee; border:1px solid #3a3a3a;"
            f"border-radius:4px; font-family:monospace;"
            "}"
            "QPushButton::indicator{width:0;}"
        )
        # Draw the swatch via a child frame.
        if not hasattr(self, "_swatch"):
            self._swatch = QFrame(self)
            self._swatch.setGeometry(4, 4, 24, 20)
            self._swatch.setFrameShape(QFrame.NoFrame)
        self._swatch.setStyleSheet(
            f"background:{self._color}; border:1px solid #555; border-radius:3px;"
        )
        self._swatch.show()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        h = self.height()
        self._swatch.setGeometry(4, (h - 20) // 2, 24, 20)

    def _pick(self) -> None:
        c = QColorDialog.getColor(QColor(self._color), self)
        if c.isValid():
            self._color = c.name().upper()
            self._refresh()
            self.changed.emit(self._color)

    def color(self) -> str:
        return self._color


def _section(title: str) -> tuple[QGroupBox, QFormLayout]:
    box = QGroupBox(title)
    box.setStyleSheet(
        "QGroupBox{font-weight:600; margin-top:14px; padding-top:8px;"
        " border:1px solid #333; border-radius:6px;}"
        "QGroupBox::title{subcontrol-origin:margin; left:10px; padding:0 4px;}"
    )
    form = QFormLayout(box)
    form.setLabelAlignment(Qt.AlignLeft)
    form.setSpacing(8)
    return box, form


class StylePanel(QWidget):
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._style = Style()

        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(8, 4, 8, 8)
        v.setSpacing(6)

        # ----- Font section -----
        font_box, font_form = _section("Text")
        self.font_combo = QComboBox()
        fonts = sorted(set(QFontDatabase.families()))
        if "Noto Sans Arabic" not in fonts:
            fonts.insert(0, "Noto Sans Arabic")
        self.font_combo.addItems(fonts)
        idx = self.font_combo.findText(self._style.font_name)
        if idx >= 0:
            self.font_combo.setCurrentIndex(idx)
        self.font_combo.currentTextChanged.connect(self._emit)
        font_form.addRow("Font", self.font_combo)

        self.size_spin = QSpinBox()
        self.size_spin.setRange(10, 200)
        self.size_spin.setValue(self._style.font_size)
        self.size_spin.valueChanged.connect(self._emit)
        font_form.addRow("Size", self.size_spin)

        self.primary_btn = _ColorSwatch(self._style.primary_color)
        self.primary_btn.changed.connect(self._emit)
        font_form.addRow("Color", self.primary_btn)

        bi = QHBoxLayout()
        self.bold_cb = QCheckBox("Bold")
        self.bold_cb.toggled.connect(self._emit)
        self.italic_cb = QCheckBox("Italic")
        self.italic_cb.toggled.connect(self._emit)
        bi.addWidget(self.bold_cb)
        bi.addWidget(self.italic_cb)
        bi.addStretch()
        bi_w = QWidget()
        bi_w.setLayout(bi)
        font_form.addRow("Style", bi_w)
        v.addWidget(font_box)

        # ----- Outline -----
        out_box, out_form = _section("Outline")
        self.outline_btn = _ColorSwatch(self._style.outline_color)
        self.outline_btn.changed.connect(self._emit)
        out_form.addRow("Color", self.outline_btn)

        self.outline_spin = QSpinBox()
        self.outline_spin.setRange(0, 10)
        self.outline_spin.setValue(int(self._style.outline_width))
        self.outline_spin.valueChanged.connect(self._emit)
        out_form.addRow("Width", self.outline_spin)
        v.addWidget(out_box)

        # ----- Background box -----
        bg_box, bg_form = _section("Background box")
        self.back_btn = _ColorSwatch(self._style.back_color)
        self.back_btn.changed.connect(self._emit)
        bg_form.addRow("Color", self.back_btn)

        row = QHBoxLayout()
        self.alpha_slider = QSlider(Qt.Horizontal)
        self.alpha_slider.setRange(0, 255)
        self.alpha_slider.setValue(self._style.back_alpha)
        self.alpha_slider.valueChanged.connect(self._emit)
        self.alpha_label = QLabel(str(self._style.back_alpha))
        self.alpha_label.setMinimumWidth(28)
        self.alpha_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.alpha_slider.valueChanged.connect(lambda v: self.alpha_label.setText(str(v)))
        row.addWidget(self.alpha_slider)
        row.addWidget(self.alpha_label)
        wrap = QWidget()
        wrap.setLayout(row)
        bg_form.addRow("Opacity", wrap)
        v.addWidget(bg_box)

        # ----- Position -----
        pos_box, pos_form = _section("Position")
        self.align_combo = QComboBox()
        self.align_combo.addItem("Bottom", 2)
        self.align_combo.addItem("Top", 8)
        self.align_combo.addItem("Middle", 5)
        self.align_combo.currentIndexChanged.connect(self._emit)
        pos_form.addRow("Anchor", self.align_combo)

        self.margin_v_spin = QSpinBox()
        self.margin_v_spin.setRange(0, 500)
        self.margin_v_spin.setValue(self._style.margin_v)
        self.margin_v_spin.valueChanged.connect(self._emit)
        pos_form.addRow("Margin V", self.margin_v_spin)
        v.addWidget(pos_box)

        v.addStretch(1)

        # Scrollable so it never overflows on smaller screens.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(inner)
        outer.addWidget(scroll)

    def _emit(self, *_) -> None:
        self.changed.emit()

    def current_style(self) -> Style:
        return Style(
            font_name=self.font_combo.currentText(),
            font_size=self.size_spin.value(),
            primary_color=self.primary_btn.color(),
            outline_color=self.outline_btn.color(),
            back_color=self.back_btn.color(),
            back_alpha=self.alpha_slider.value(),
            outline_width=float(self.outline_spin.value()),
            bold=self.bold_cb.isChecked(),
            italic=self.italic_cb.isChecked(),
            alignment=self.align_combo.currentData(),
            margin_v=self.margin_v_spin.value(),
        )
