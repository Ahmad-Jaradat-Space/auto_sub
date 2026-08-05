from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import Literal

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)


@dataclass
class BurnOptions:
    reframe: Literal["none", "vertical"]
    method: Literal["face", "person"]
    target_w: int
    target_h: int


_VERTICAL_RES = [("1080 × 1920", 1080, 1920), ("720 × 1280", 720, 1280)]

# (label, reframe, method)
_ASPECT_OPTIONS = [
    ("Source (no reframe)", "none", "face"),
    ("Vertical 9:16", "vertical", "face"),
]

# The whole-body tracker needs ultralytics (+ PyTorch, ~500 MB), which the
# packaged release deliberately leaves out. Only offer it when it is importable
# so users are never shown an option that errors out.
_HAS_YOLO = importlib.util.find_spec("ultralytics") is not None
if _HAS_YOLO:
    _ASPECT_OPTIONS.append(("Vertical 9:16 — whole body (YOLO)", "vertical", "person"))


class BurnOptionsDialog(QDialog):
    """Per-export dialog: pick source-aspect or smart-cropped 9:16."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export options")

        self.aspect = QComboBox(self)
        for label, reframe, method in _ASPECT_OPTIONS:
            self.aspect.addItem(label, (reframe, method))

        self.resolution = QComboBox(self)
        for label, w, h in _VERTICAL_RES:
            self.resolution.addItem(label, (w, h))
        self.resolution.setEnabled(False)

        self.aspect.currentIndexChanged.connect(self._on_aspect_changed)

        form = QFormLayout()
        form.addRow("Aspect:", self.aspect)
        form.addRow("Resolution:", self.resolution)

        hint = (
            "Vertical 9:16 crops the video to follow the speaker's face — "
            "for TikTok / Reels / Shorts."
        )
        if _HAS_YOLO:
            hint += (
                "\nWhole body: YOLOv8n via ultralytics — better for non-frontal / "
                "full-body subjects. First run downloads ~6 MB."
            )
        self.hint = QLabel(hint, self)
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: #888; font-size: 11px;")

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self
        )
        buttons.button(QDialogButtonBox.Ok).setText("Burn")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.hint)
        layout.addWidget(buttons)

    def _on_aspect_changed(self) -> None:
        reframe, _ = self.aspect.currentData()
        self.resolution.setEnabled(reframe == "vertical")

    def options(self) -> BurnOptions:
        reframe, method = self.aspect.currentData()
        if reframe == "vertical":
            w, h = self.resolution.currentData()
        else:
            w, h = 0, 0
        return BurnOptions(reframe=reframe, method=method, target_w=w, target_h=h)
