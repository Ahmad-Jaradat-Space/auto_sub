from __future__ import annotations

import os
import tempfile

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from ..core.ass_writer import write_ass
from ..core.burn import render_preview_frame
from ..core.models import Segment, Style


class PreviewPane(QWidget):
    """Renders 3 sample frames (start / middle / latest end) with current style."""

    def __init__(self) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        self._labels = [QLabel("(no preview)") for _ in range(3)]
        for lab in self._labels:
            lab.setAlignment(Qt.AlignCenter)
            lab.setMinimumHeight(160)
            lab.setMaximumHeight(260)
            lab.setMinimumWidth(120)
            lab.setWordWrap(True)
            lab.setScaledContents(False)
            lab.setStyleSheet("background:#111;color:#888;padding:4px;font-size:11px;")
            layout.addWidget(lab, 1)

        self._video: str | None = None
        self._segments: list[Segment] = []
        self._style: Style | None = None
        self._video_w = 1920
        self._video_h = 1080

        self._tmp_dir = tempfile.mkdtemp(prefix="auto_sub_preview_")
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(300)
        self._debounce.timeout.connect(self._render_now)

    def configure(self, video_path: str, video_w: int, video_h: int) -> None:
        self._video = video_path
        self._video_w = video_w
        self._video_h = video_h

    def update_state(self, segments: list[Segment], style: Style) -> None:
        self._segments = segments
        self._style = style
        if self._video and segments:
            self._debounce.start()

    def _pick_timestamps(self) -> list[float]:
        if not self._segments:
            return []
        # pick three segments evenly spread; preview at their midpoints.
        n = len(self._segments)
        idxs = [0, n // 2, n - 1] if n >= 3 else list(range(n))
        return [(self._segments[i].start + self._segments[i].end) / 2 for i in idxs]

    def _render_now(self) -> None:
        if not (self._video and self._style and self._segments):
            return
        from ..core.burn import assets_dir

        ass_path = os.path.join(self._tmp_dir, "preview.ass")
        write_ass(ass_path, self._segments, self._style, self._video_w, self._video_h)

        timestamps = self._pick_timestamps()
        for i, lab in enumerate(self._labels):
            if i >= len(timestamps):
                lab.setText("—")
                lab.setPixmap(QPixmap())
                continue
            out = os.path.join(self._tmp_dir, f"frame_{i}.png")
            try:
                render_preview_frame(
                    self._video,
                    ass_path,
                    timestamps[i],
                    out,
                    fonts_dir=assets_dir(),
                    width=320,
                )
                pix = QPixmap(out)
                if not pix.isNull():
                    target_w = max(lab.width() - 8, 120)
                    lab.setPixmap(pix.scaledToWidth(target_w, Qt.SmoothTransformation))
                    lab.setText("")
            except Exception as e:  # noqa: BLE001
                lab.setText(f"preview err\n{e}")
