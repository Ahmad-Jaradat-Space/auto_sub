from __future__ import annotations

from PySide6.QtCore import QRectF, QSizeF, QUrl, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QKeySequence, QPainter, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..core.models import Segment, Style


def _fmt(ms: int) -> str:
    s = max(0, ms) // 1000
    return f"{s // 60:02d}:{s % 60:02d}"


class VideoPlayer(QWidget):
    """Live video preview using a QGraphicsScene so subtitle text composites
    correctly on top of the video item on macOS (QVideoWidget child widgets
    don't render reliably under the native layer-backed view)."""

    positionChanged = Signal(float)  # seconds
    timeClicked = Signal(float)

    def __init__(self) -> None:
        super().__init__()
        self._segments: list[Segment] = []
        self._style: Style | None = None

        # --- media + scene ---
        self.player = QMediaPlayer(self)
        self.audio_out = QAudioOutput(self)
        self.audio_out.setVolume(0.7)
        self.player.setAudioOutput(self.audio_out)

        self.scene = QGraphicsScene(self)
        self.scene.setBackgroundBrush(QBrush(QColor(0, 0, 0)))

        self.video_item = QGraphicsVideoItem()
        self.video_item.setAspectRatioMode(Qt.KeepAspectRatio)
        self.scene.addItem(self.video_item)
        self.player.setVideoOutput(self.video_item)

        # Background rectangle for subtitle (drawn behind text).
        self.sub_bg = QGraphicsRectItem()
        self.sub_bg.setPen(Qt.NoPen)
        self.sub_bg.setZValue(10)
        self.sub_bg.setVisible(False)
        self.scene.addItem(self.sub_bg)

        # Subtitle text item.
        self.sub_text = QGraphicsSimpleTextItem()
        self.sub_text.setZValue(11)
        self.sub_text.setVisible(False)
        self.scene.addItem(self.sub_text)

        self.view = QGraphicsView(self.scene)
        self.view.setStyleSheet("border:0; background:#000;")
        self.view.setRenderHint(QPainter.Antialiasing, True)
        self.view.setRenderHint(QPainter.SmoothPixmapTransform, True)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setMinimumHeight(320)
        self.view.setFrameShape(QFrame.NoFrame)

        # --- transport ---
        self.btn_play = QPushButton("▶")
        self.btn_play.setFixedWidth(44)
        self.btn_play.clicked.connect(self.toggle_play)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.sliderMoved.connect(self.player.setPosition)
        self.slider.sliderPressed.connect(lambda: setattr(self, "_scrubbing", True))
        self.slider.sliderReleased.connect(lambda: setattr(self, "_scrubbing", False))
        self._scrubbing = False

        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setStyleSheet("color:#aaa; min-width:90px;")

        transport = QHBoxLayout()
        transport.addWidget(self.btn_play)
        transport.addWidget(self.slider, 1)
        transport.addWidget(self.time_label)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        outer.addWidget(self.view, 1)
        outer.addLayout(transport)

        # --- wiring ---
        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)
        self.player.playbackStateChanged.connect(self._on_state)
        self.player.errorOccurred.connect(self._on_error)
        self.video_item.nativeSizeChanged.connect(self._fit_video)

        sc = QShortcut(QKeySequence(Qt.Key_Space), self)
        sc.activated.connect(self.toggle_play)

    # ---- public API ----

    def load(self, path: str) -> None:
        self.player.setSource(QUrl.fromLocalFile(path))
        # Nudge the player into "buffered first frame, paused at 0" so the
        # user sees something before clicking play.
        self.player.play()
        self.player.pause()
        self.player.setPosition(0)

    def set_segments(self, segs: list[Segment]) -> None:
        self._segments = segs
        self._refresh_overlay()

    def set_style(self, style: Style) -> None:
        self._style = style
        self._apply_text_style()
        self._refresh_overlay()

    def seek_seconds(self, t: float) -> None:
        self.player.setPosition(int(t * 1000))

    def toggle_play(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    # ---- internals ----

    def _on_position(self, ms: int) -> None:
        if not self._scrubbing:
            self.slider.setValue(ms)
        dur = self.player.duration() or 0
        self.time_label.setText(f"{_fmt(ms)} / {_fmt(dur)}")
        self._refresh_overlay()
        self.positionChanged.emit(ms / 1000.0)

    def _on_duration(self, ms: int) -> None:
        self.slider.setRange(0, max(0, ms))

    def _on_state(self, state) -> None:
        self.btn_play.setText("⏸" if state == QMediaPlayer.PlayingState else "▶")

    def _on_error(self, err, msg) -> None:
        import sys
        print(f"[auto_sub] player error: {err} {msg}", file=sys.stderr, flush=True)

    def _fit_video(self, _size=None) -> None:
        native = self.video_item.nativeSize()
        if native.isEmpty():
            native = QSizeF(1920, 1080)
        # Fit the video item into the view's viewport.
        vw = self.view.viewport().width()
        vh = self.view.viewport().height()
        if vw <= 0 or vh <= 0:
            return
        scale = min(vw / native.width(), vh / native.height())
        w = native.width() * scale
        h = native.height() * scale
        self.video_item.setSize(QSizeF(w, h))
        x = (vw - w) / 2.0
        y = (vh - h) / 2.0
        self.video_item.setPos(x, y)
        self.scene.setSceneRect(0, 0, vw, vh)
        self._position_overlay()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit_video()

    def _apply_text_style(self) -> None:
        if not self._style:
            return
        s = self._style
        # Pick a font size proportional to the displayed video height.
        view_h = max(self.view.viewport().height(), 200)
        scale = view_h / 1080.0
        px = max(12, int(s.font_size * scale))
        font = QFont(s.font_name, px)
        font.setBold(s.bold)
        font.setItalic(s.italic)
        self.sub_text.setFont(font)
        self.sub_text.setBrush(QBrush(QColor(s.primary_color)))
        # No outline on QGraphicsSimpleTextItem; emulate with a small shadow
        # via pen would work but keep simple — outline color used as pen.
        from PySide6.QtGui import QPen
        pen = QPen(QColor(s.outline_color))
        pen.setWidthF(max(0.5, s.outline_width * scale * 0.6))
        self.sub_text.setPen(pen)
        # Background box
        r, g, b = (
            int(s.back_color[1:3], 16),
            int(s.back_color[3:5], 16),
            int(s.back_color[5:7], 16),
        )
        self.sub_bg.setBrush(QBrush(QColor(r, g, b, s.back_alpha)))

    def _refresh_overlay(self) -> None:
        t = self.player.position() / 1000.0
        cur = next((s for s in self._segments if s.start <= t < s.end), None)
        if cur is None or self._style is None:
            self.sub_text.setVisible(False)
            self.sub_bg.setVisible(False)
            return
        self.sub_text.setText(cur.text)
        self.sub_text.setVisible(True)
        self.sub_bg.setVisible(self._style.back_alpha > 0)
        self._position_overlay()

    def _position_overlay(self) -> None:
        if not self._style or not self.sub_text.isVisible():
            return
        s = self._style
        # Position relative to the displayed video item, not the scene.
        vrect = self.video_item.boundingRect()
        vpos = self.video_item.pos()
        # video rect on scene:
        vx, vy, vw, vh = vpos.x(), vpos.y(), vrect.width(), vrect.height()
        scale = vh / 1080.0 if vh > 0 else 1
        margin = max(4, s.margin_v * scale)
        tw = self.sub_text.boundingRect().width()
        th = self.sub_text.boundingRect().height()

        x = vx + (vw - tw) / 2.0
        if s.alignment == 8:  # top
            y = vy + margin
        elif s.alignment == 5:  # middle
            y = vy + (vh - th) / 2.0
        else:  # bottom
            y = vy + vh - th - margin

        self.sub_text.setPos(x, y)
        pad = 6 * scale
        self.sub_bg.setRect(x - pad, y - pad / 2, tw + pad * 2, th + pad)
