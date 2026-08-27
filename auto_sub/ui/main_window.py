from __future__ import annotations

import os
import tempfile
import sys

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QSizePolicy,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStatusBar,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core.ass_writer import write_ass
from ..core.burn import assets_dir, burn, probe_video
from ..core.models import Segment
from ..core.transcribe import ensure_model, transcribe
from ..core.translate_io import apply_translation
from .burn_options_dialog import BurnOptions, BurnOptionsDialog
from .player import VideoPlayer
from .style_panel import StylePanel
from .timeline import TimelineTable
from .translate_dialog import TranslateDialog


class _TranscribeWorker(QThread):
    progress = Signal(float, float)  # done, total
    stage = Signal(str)              # user-facing status line
    segment = Signal(object)         # Segment
    error = Signal(str)
    done = Signal()

    def __init__(self, video_path: str) -> None:
        super().__init__()
        self._video = video_path

    def run(self) -> None:  # noqa: D401
        try:
            # First launch on a new machine fetches ~1.6 GB of weights. Show it
            # as real progress — a silent ten-minute stall reads as a crash.
            self.stage.emit(
                "Downloading the speech model (about 1.6 GB). This happens once; "
                "leave it running."
            )
            ensure_model(progress=lambda d, t: self.progress.emit(d, t))
            self.stage.emit("Transcribing…")
            self.progress.emit(0, 0)
            for seg in transcribe(
                self._video,
                progress=lambda d, t: self.progress.emit(d, t),
            ):
                self.segment.emit(seg)
            self.done.emit()
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))


class _BurnWorker(QThread):
    line = Signal(str)
    error = Signal(str)
    done = Signal(str)

    def __init__(
        self,
        video: str,
        ass_path: str,
        out: str,
        extra_pre_filter: str | None = None,
    ) -> None:
        super().__init__()
        self._video, self._ass, self._out = video, ass_path, out
        self._pre = extra_pre_filter

    def run(self) -> None:  # noqa: D401
        try:
            burn(
                self._video, self._ass, self._out,
                fonts_dir=assets_dir(),
                progress=lambda ln: self.line.emit(ln),
                extra_pre_filter=self._pre,
            )
            self.done.emit(self._out)
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))


class _ReframeWorker(QThread):
    """Runs face/person tracking off the UI thread; emits the ffmpeg filter chain."""
    error = Signal(str)
    done = Signal(str, int, int)  # filter_chain, out_w, out_h

    def __init__(
        self, video: str, target_w: int, target_h: int, method: str = "face",
        cmd_path: str | None = None,
    ) -> None:
        super().__init__()
        self._video, self._tw, self._th = video, target_w, target_h
        self._method = method
        self._cmd_path = cmd_path

    def run(self) -> None:  # noqa: D401
        try:
            from ..core.reframe import reframe_filter_chain
            chain, (ow, oh) = reframe_filter_chain(
                self._video, self._tw, self._th, method=self._method,
                cmd_path=self._cmd_path,
            )
            self.done.emit(chain, ow, oh)
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))


class _DropOverlay(QLabel):
    """Full-window drop target shown only when no video is loaded."""

    file_dropped = Signal(str)

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        open_key = "⌘O" if sys.platform == "darwin" else "Ctrl+O"
        self.setText(f"⬇\n\nDrop a video here\n\nor press {open_key}")
        self.setAlignment(Qt.AlignCenter)
        self.setAcceptDrops(True)
        self.setStyleSheet(
            "QLabel{background:rgba(20,20,20,235); color:#bbb; font-size:18px;"
            " border:2px dashed #555; border-radius:14px; padding:40px;}"
        )

    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self.setStyleSheet(
                "QLabel{background:rgba(40,60,40,235); color:#fff; font-size:18px;"
                " border:3px dashed #6c6; border-radius:14px; padding:40px;}"
            )

    def dragLeaveEvent(self, _e) -> None:
        self.setStyleSheet(
            "QLabel{background:rgba(20,20,20,235); color:#bbb; font-size:18px;"
            " border:2px dashed #555; border-radius:14px; padding:40px;}"
        )

    def dropEvent(self, e) -> None:
        urls = e.mimeData().urls()
        if urls:
            self.file_dropped.emit(urls[0].toLocalFile())


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("auto_sub")
        self.resize(1500, 920)
        self.setAcceptDrops(True)

        self._video_path: str | None = None
        self._video_w = 1920
        self._video_h = 1080

        # Dark base style + pipeline-step button styling.
        # A step is "next" (the recommended next action) when its objectName
        # is set to "step-next"; the QSS lights it up with an accent color.
        self.setStyleSheet(
            "QMainWindow{background:#181818;}"
            "QToolBar{background:#1f1f1f; border:0; padding:6px; spacing:6px;}"
            "QToolBar::separator{background:#333; width:1px; margin:4px 4px;}"
            "QStatusBar{background:#1f1f1f; color:#aaa;}"
            "QSplitter::handle{background:#2a2a2a;}"
            "QSplitter::handle:horizontal{width:3px;}"
            "QLabel{color:#ddd;}"
            "QComboBox, QSpinBox{background:#2a2a2a; color:#eee; border:1px solid #3a3a3a;"
            " border-radius:4px; padding:3px 6px;}"
            "QGroupBox{color:#ddd;}"
            # Pipeline step buttons
            "QToolButton#step{color:#aaa; padding:6px 12px; border-radius:6px;"
            " font-weight:500; border:1px solid transparent;}"
            "QToolButton#step:hover:!disabled{background:#2a2a2a;}"
            "QToolButton#step:disabled{color:#555;}"
            # The currently recommended next action: bright accent
            "QToolButton#step-next{color:#fff; padding:6px 12px; border-radius:6px;"
            " font-weight:600; background:#2563eb; border:1px solid #3b82f6;}"
            "QToolButton#step-next:hover{background:#1d4ed8;}"
            # A completed step: subdued green tick
            "QToolButton#step-done{color:#9bd99b; padding:6px 12px; border-radius:6px;"
            " font-weight:500; border:1px solid #2f4a2f; background:#1d2a1d;}"
        )

        # --- toolbar with numbered pipeline steps ---
        tb = QToolBar()
        tb.setMovable(False)
        self.addToolBar(tb)

        def step_btn(label: str, shortcut: str, handler) -> QToolButton:
            b = QToolButton()
            b.setObjectName("step")
            b.setText(label)
            b.setShortcut(QKeySequence(shortcut))
            b.setToolTip(f"{label}  ({shortcut})")
            b.clicked.connect(handler)
            tb.addWidget(b)
            return b

        self.btn_open = step_btn("1 · 📂 Open video", "Ctrl+O", self._pick_video)
        self._arrow(tb)
        self.btn_transcribe = step_btn("2 · 📝 Transcribe", "Ctrl+T", self._start_transcribe)
        self.btn_transcribe.setEnabled(False)
        self._arrow(tb)
        self.btn_translate = step_btn("3 · 🌐 Translate", "Ctrl+E", self._open_translate)
        self.btn_translate.setEnabled(False)
        self._arrow(tb)
        self.btn_burn = step_btn("4 · 🔥 Burn & Export", "Ctrl+B", self._start_burn)
        self.btn_burn.setEnabled(False)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)

        # --- central splitter ---
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        outer.addWidget(splitter, 1)

        self.timeline = TimelineTable()
        self.timeline.setMinimumWidth(360)
        splitter.addWidget(self.timeline)

        self.player = VideoPlayer()
        self.player.setMinimumWidth(480)
        splitter.addWidget(self.player)

        self.style_panel = StylePanel()
        self.style_panel.setMinimumWidth(280)
        self.style_panel.setMaximumWidth(360)
        splitter.addWidget(self.style_panel)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 4)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([460, 700, 320])

        # --- drop overlay (covers everything until a video loads) ---
        self.drop_overlay = _DropOverlay(central)
        self.drop_overlay.file_dropped.connect(self._load_video)
        self.drop_overlay.setGeometry(0, 0, self.width(), self.height())
        self.drop_overlay.raise_()
        central.installEventFilter(self)

        # --- status bar ---
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(220)
        self.progress_bar.hide()
        self.status.addPermanentWidget(self.progress_bar)

        # --- wiring ---
        self.style_panel.changed.connect(self._on_style_changed)
        self.timeline.changed.connect(self._on_timeline_changed)
        self.timeline.rowClicked.connect(self.player.seek_seconds)
        self.player.positionChanged.connect(self.timeline.highlight_active)
        self.player.playbackError.connect(
            lambda m: self.status.showMessage(f"Cannot play this video: {m}")
        )

        # Initial style push so overlay has CSS.
        self.player.set_style(self.style_panel.current_style())

        self._segments_buffer: list[Segment] = []
        self._language = "en"
        self._update_pipeline()

    # Resize the drop overlay along with the window.
    def eventFilter(self, obj, event):
        if event.type() == event.Type.Resize and obj is self.centralWidget():
            self.drop_overlay.setGeometry(0, 0, obj.width(), obj.height())
        return super().eventFilter(obj, event)

    # Top-level drag-and-drop falls through to the overlay even after it hides.
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        urls = e.mimeData().urls()
        if urls:
            self._load_video(urls[0].toLocalFile())

    def _arrow(self, tb) -> None:
        """Small arrow separator between pipeline-step buttons."""
        a = QLabel("›")
        a.setStyleSheet("color:#555; padding:0 4px; font-size:18px;")
        tb.addWidget(a)

    def _update_lang_label(self) -> None:
        flag = "🇬🇧 EN" if self._language == "en" else "🇸🇦 AR"
        self.status.showMessage(f"Subtitles: {flag}")

    def _set_step_state(self, btn: QToolButton, state: str) -> None:
        """state ∈ {'idle', 'next', 'done'} — drives the QSS object-name styling."""
        btn.setObjectName("step" if state == "idle" else f"step-{state}")
        # Force Qt to re-apply the stylesheet for the new object name.
        btn.style().unpolish(btn)
        btn.style().polish(btn)
        btn.update()

    def _update_pipeline(self) -> None:
        """Mark each step as done/next/idle based on current progress and
        update the status-bar hint."""
        has_video = self._video_path is not None
        has_segments = self.timeline.rowCount() > 0
        is_translated = self._language == "ar"
        # done if completed, next if it's the recommended next action
        steps = [
            (self.btn_open, has_video, not has_video),
            (self.btn_transcribe, has_segments, has_video and not has_segments),
            (self.btn_translate, is_translated, has_segments and not is_translated),
            (self.btn_burn, False, has_segments),
        ]
        next_label = None
        for btn, done, is_next in steps:
            if done:
                state = "done"
            elif is_next:
                state = "next"
                if next_label is None:
                    next_label = btn.text()
            else:
                state = "idle"
            self._set_step_state(btn, state)
        if next_label:
            self.status.showMessage(f"Next  →  {next_label}")
        elif is_translated:
            self.status.showMessage("Pipeline ready  ·  🇸🇦 AR  ·  Burn to export")

    # ---- video loading ----

    def _pick_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose video", "", "Video files (*.mp4 *.mov *.mkv *.m4v *.webm)"
        )
        if path:
            self._load_video(path)

    def _load_video(self, path: str) -> None:
        try:
            info = probe_video(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "ffprobe failed", str(e))
            return
        self._video_path = path
        self._video_w = info["width"]
        self._video_h = info["height"]
        # Hide drop overlay now that a video is loaded.
        self.drop_overlay.hide()
        # Push video into the live player.
        self.player.load(path)
        self.btn_transcribe.setEnabled(True)
        self.status.showMessage(
            f"Loaded {os.path.basename(path)}  ·  {info['width']}×{info['height']}  ·  "
            f"{int(info['duration'])}s"
        )
        self._update_pipeline()

    # ---- transcription ----

    def _start_transcribe(self) -> None:
        if not self._video_path:
            return
        self.timeline.load([])
        self._segments_buffer = []
        self.btn_transcribe.setEnabled(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.status.showMessage("Starting…")

        self._worker = _TranscribeWorker(self._video_path)
        self._worker.stage.connect(self.status.showMessage)
        self._worker.segment.connect(self._on_segment)
        self._worker.progress.connect(self._on_transcribe_progress)
        self._worker.error.connect(self._on_transcribe_error)
        self._worker.done.connect(self._on_transcribe_done)
        self._worker.start()

    def _on_segment(self, seg: Segment) -> None:
        self._segments_buffer.append(seg)
        # Re-load incrementally — cheap for typical clip sizes.
        self.timeline.load(self._segments_buffer)

    def _on_transcribe_progress(self, done: float, total: float) -> None:
        if total > 0:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(int(done / total * 100))
        else:
            # No scale yet (e.g. between download and transcription) — spin.
            self.progress_bar.setRange(0, 0)

    def _on_transcribe_error(self, msg: str) -> None:
        self.progress_bar.hide()
        self.btn_transcribe.setEnabled(True)
        QMessageBox.critical(self, "Transcription failed", msg)

    def _on_transcribe_done(self) -> None:
        self.progress_bar.hide()
        self.btn_transcribe.setEnabled(True)
        self.btn_translate.setEnabled(True)
        self.btn_burn.setEnabled(True)
        self._language = "en"
        self._update_pipeline()

    # ---- translate ----

    def _open_translate(self) -> None:
        segs = self.timeline.dump()
        if not segs:
            return
        dlg = TranslateDialog(segs, self)
        if dlg.exec() == QDialog.Accepted:
            translated = dlg.translated_lines()
            if translated is None:
                return
            try:
                self.timeline.replace_texts(translated)
            except ValueError as e:
                QMessageBox.warning(self, "Apply failed", str(e))
                return
            self._language = "ar"
            self.status.showMessage(
                f"🇸🇦 AR applied to {len(translated)} segments — tweak style, then Burn & Export."
            )
            # Visual confirmation: scroll to first row, select it.
            self.timeline.selectRow(0)
            self._update_pipeline()
        else:
            QMessageBox.information(
                self, "Translation cancelled",
                "No changes applied — the timeline still shows English. "
                "Open Export → Translate again to retry."
            )

    # ---- live preview wiring ----

    def _on_style_changed(self) -> None:
        self.player.set_style(self.style_panel.current_style())

    def _on_timeline_changed(self) -> None:
        self.player.set_segments(self.timeline.dump())

    # ---- burn ----

    def _start_burn(self) -> None:
        if not self._video_path:
            return
        segs = self.timeline.dump()
        if not segs:
            QMessageBox.warning(self, "Nothing to burn", "Transcribe first.")
            return
        import sys
        sample = [s.text for s in segs[:2]]
        print(f"[auto_sub] burning {len(segs)} segments. First texts: {sample!r}",
              file=sys.stderr, flush=True)
        default = os.path.splitext(self._video_path)[0] + ".subbed.mp4"
        out, _ = QFileDialog.getSaveFileName(self, "Export burned video", default, "MP4 (*.mp4)")
        if not out:
            return

        dlg = BurnOptionsDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        opts = dlg.options()
        print(f"[auto_sub] burn opts: reframe={opts.reframe} method={opts.method} {opts.target_w}x{opts.target_h}",
              file=sys.stderr, flush=True)

        # We write a .ass and, for vertical, a .crop.txt next to the output.
        # Find out now whether that folder takes writes. The vertical path used
        # to run several minutes of face detection first and only then fail.
        # mkstemp, not a fixed name: a fixed name would truncate and delete a
        # real file if the user happened to have one called that, and the
        # default output folder is the one holding their video.
        try:
            fd, probe = tempfile.mkstemp(
                prefix=".auto_sub_write_test", dir=os.path.dirname(out) or "."
            )
            os.close(fd)
            os.unlink(probe)
        except OSError as e:
            QMessageBox.critical(
                self, "Cannot write there",
                f"That folder will not accept new files:\n\n{e}\n\n"
                "Pick a different output folder, for example your Desktop.",
            )
            return

        self._pending_burn_segs = segs
        self._pending_burn_out = out

        if opts.reframe == "vertical":
            self.btn_burn.setEnabled(False)
            self.progress_bar.setRange(0, 0)
            self.progress_bar.show()
            self.status.showMessage("Analyzing speaker position…")
            # Next to the output, like the .ass: inspectable, and no temp litter.
            self._reframer = _ReframeWorker(
                self._video_path, opts.target_w, opts.target_h, opts.method,
                cmd_path=os.path.splitext(out)[0] + ".crop.txt",
            )
            self._reframer.error.connect(self._on_burn_error)
            self._reframer.done.connect(self._on_reframe_done)
            self._reframer.start()
        else:
            self._launch_burn(extra_pre_filter=None, play_res=None)

    def _on_reframe_done(self, filter_chain: str, out_w: int, out_h: int) -> None:
        import sys
        print(f"[auto_sub] reframe chain: {filter_chain}", file=sys.stderr, flush=True)
        self._launch_burn(extra_pre_filter=filter_chain, play_res=(out_w, out_h))

    def _launch_burn(
        self,
        extra_pre_filter: str | None,
        play_res: tuple[int, int] | None,
    ) -> None:
        segs = self._pending_burn_segs
        out = self._pending_burn_out
        ass_path = os.path.splitext(out)[0] + ".ass"
        try:
            write_ass(
                ass_path, segs, self.style_panel.current_style(),
                self._video_w, self._video_h, play_res=play_res,
            )
        except OSError as e:
            # Read-only USB stick, network share, or a locked-down folder. Without
            # this the UI thread raises and the user gets nothing at all.
            QMessageBox.critical(
                self, "Cannot write there",
                f"Could not write the subtitle file next to your video:\n\n{e}\n\n"
                "Pick a different output folder, for example your Desktop.",
            )
            # The vertical path already disabled Export and started the bar.
            # Without this the user cannot retry without restarting the app.
            self.btn_burn.setEnabled(True)
            self.progress_bar.hide()
            self.status.showMessage("Export cancelled: that folder is not writable.")
            return

        self.btn_burn.setEnabled(False)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.show()
        self.status.showMessage("Burning subtitles with ffmpeg…")

        self._burner = _BurnWorker(
            self._video_path, ass_path, out, extra_pre_filter=extra_pre_filter,
        )
        self._burner.error.connect(self._on_burn_error)
        self._burner.done.connect(self._on_burn_done)
        self._burner.start()

    def _on_burn_error(self, msg: str) -> None:
        self.progress_bar.hide()
        self.btn_burn.setEnabled(True)
        QMessageBox.critical(self, "Burn failed", msg)

    def _on_burn_done(self, out_path: str) -> None:
        self.progress_bar.hide()
        self.btn_burn.setEnabled(True)
        ass_path = os.path.splitext(out_path)[0] + ".ass"
        self.status.showMessage(f"Exported {out_path}")
        QMessageBox.information(
            self, "Done",
            f"Exported:\n{out_path}\n\nSubtitle source kept at:\n{ass_path}\n"
            "(Open it to verify the exact text + timings that were burned.)"
        )
