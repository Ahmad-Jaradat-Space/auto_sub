# auto_sub — Claude working notes

Read this before making changes. It captures the non-obvious decisions that have already cost time to discover.

## What this app is

A local Mac GUI that takes an English video clip → transcribes it with Whisper → lets a human paste-translate to Arabic via Claude/ChatGPT → burns styled Arabic subtitles into the video with ffmpeg + libass.

No cloud, no API keys, no paid services.

## Hard-won gotchas (do not re-learn these)

### ffmpeg
- **Homebrew's default `ffmpeg` (8.x) is built WITHOUT libass.** It has no `ass` or `subtitles` filter. Burn and preview both fail.
- Use `brew install ffmpeg-full` instead. It's **keg-only** at `/opt/homebrew/opt/ffmpeg-full/bin`. `core/burn.py` looks there first; only falls back to `shutil.which("ffmpeg")` afterwards.
- `_has_ass_filter()` in `core/burn.py` verifies the filter exists before any operation — raises a helpful error if not.
- ffmpeg 8.x filter syntax: `ass=f=/path/to.ass:fontsdir=/path/to/fonts`. **Do not** wrap with single quotes — ffmpeg 8 reads the quoted block as one option value and fails. Escape `:` inside paths with `\:`.

### Whisper / faster-whisper
- We use `faster-whisper` (CTranslate2 backend). **One model, `large-v3-turbo`, no dropdown** (`core/transcribe.py::MODEL_NAME`). The combo was removed deliberately: the Windows users this ships to can't reason about model trade-offs, and they transcribe on CPU where `large-v3` is ~5× slower for ~5 % more accuracy. `AUTO_SUB_MODEL` still overrides for testing.
- `ensure_model()` downloads the weights *before* transcription starts and reports progress by **polling the HuggingFace cache directory size** on a helper thread. huggingface_hub gives no usable byte callback through `faster_whisper.utils.download_model`, and a silent 1.6 GB stall on first run looks exactly like a crash to a non-technical user. `MODEL_DOWNLOAD_BYTES` is an approximation used only to scale the bar.
- `word_timestamps=True` is **mandatory** — `core/transcribe.py` uses per-word `end` times to:
  1. Trim segment `end` to `last_word.end + tail_pad` (0.30 s default) — stops subtitles lingering during silence.
  2. Split a segment when the gap between two consecutive words exceeds `split_gap` (0.80 s default) — stops one sub from spanning a long pause.
  3. Split a segment into short cues at sentence punctuation (`split_punct`) and commas (`split_comma`), capped at `max_chars` (25) and `max_dur` (3.0 s). Cues shorter than `min_dur` (0.70 s) merge forward when they still fit the caps (anti-flicker). This stops continuous speech (no long pauses) from rendering as one giant multi-line block. The user chose "TikTok-tight" defaults; loosen `max_chars`/`max_dur` for a Netflix-style 2-line look. Every cue boundary snaps to a real word start/end, so timing stays accurate. `_segment_from_words` does the splitting while word timestamps are still in hand — `Segment` only keeps start/end/text, so cues cannot be re-split downstream without re-transcribing. A final clamp pass in `_segment_from_words` caps each cue's `end` at the next cue's `start`: without it, the `tail_pad` (0.30 s) added to back-to-back cues pushes `end` past the next `start`, libass then renders two overlapping events at once and **stacks the newer one above the older one** (looks like subtitles climbing up the screen instead of staying put). The clamp is a no-op when a real `split_gap` pause separates cues, so silence-linger is preserved.
- **Do not** alter VAD parameters away from defaults. Lowering `min_silence_duration_ms` changed Whisper's segmentation and produced visibly worse phrase groupings — the user noticed and complained. Revert if you're tempted.

### Vertical reframing (9:16)
- `core/reframe.py` produces a time-varying ffmpeg `crop` chain that tracks the speaker, chained before the `ass` filter via `core/burn.py::burn(extra_pre_filter=...)`. Triggered from `ui/burn_options_dialog.py` (per-export choice, not persisted).
- Two detection methods live behind `reframe_filter_chain(method=...)`: `face` (default, Haar via cv2, no extra deps) and `person` (YOLOv8n via ultralytics — optional `[yolo]` extra, drags in PyTorch ~500 MB). Person tracker is for full-body / non-frontal subjects where Haar drops most samples. Both feed the same `smooth_track` → `build_crop_expr` pipeline; only the detector swaps. YOLO weights (`yolov8n.pt`, ~6 MB) auto-download to `~/.cache/ultralytics` on first run. Lazy-import ultralytics inside `detect_person_track` so the app starts without it installed.
- Face detection uses **OpenCV's bundled Haar cascade** (`cv2.data.haarcascades + "haarcascade_frontalface_default.xml"`). Don't switch to `mediapipe.solutions.face_detection` — that module was removed in mediapipe ≥ 0.10.35. The new Tasks API would need a `.tflite` download; Haar ships with cv2 and works for centered front-facing speakers. Detection sample rate is 5 fps on a 480px-wide downscale; EMA-smoothed (α=0.15); falls back to last known x when no face is detected.
- Inside the `crop` expression, escape `,` and `:` with backslashes (they otherwise terminate the filter arg or option). See `build_crop_expr`.
- When reframing, write the `.ass` with `play_res=(out_w, out_h)` so `PlayResX/Y` and `MarginV` are scaled to the **output** frame, not the source — otherwise margins are tiny.
- If source aspect is already ≤ target aspect, we pad with black bars instead of cropping (would lose the speaker's head).

### Windows packaging
- The Windows release is a **PyInstaller onedir folder**, built by `.github/workflows/windows-build.yml` on a `windows-latest` runner. PyInstaller cannot cross-compile — you cannot produce the `.exe` from the Mac. Trigger it from the Actions tab; the artifact is `auto_sub-windows`.
- **onedir, not onefile.** onefile unpacks ~400 MB to a temp dir on every launch (slow start) and trips antivirus far more often.
- ffmpeg is fetched by CI from **BtbN's `win64-gpl-shared`** build into `packaging/ffmpeg/`, and ends up in an `ffmpeg/` folder next to the exe. `core/burn.py::_bundle_dirs()` looks there first, before the Homebrew paths, before `PATH`. Three things pin that exact URL, all of them learned the hard way:
  - **Not gyan.dev.** It answers GitHub runners with `503 Service Unavailable`. BtbN is on GitHub releases.
  - **`gpl`, not `lgpl`.** The LGPL builds ship without **libx264**, and `burn()` encodes `-c:v libx264`. An lgpl build transcribes fine and then fails at step 4 — on the user's machine, not in CI.
  - **`shared`, not static.** The static build duplicates every codec into both `ffmpeg.exe` and `ffprobe.exe` (145 MB each).
- **ffmpeg is copied into `dist/` *after* PyInstaller runs, never listed in the spec.** PyInstaller performs a "binary vs. data reclassification" pass, so putting the DLLs in `datas` does *not* keep them out of the binary path — it moves them back, dependency-scans them, and copies each into the bundle root a second time. That was ~130 MB of pure duplication and it survived the obvious `binaries` → `datas` fix.
- CI **actually burns an Arabic `.ass` onto a generated clip** with the bundled ffmpeg, and prints the bundle size. The `ass` filter merely appearing in `-filters` is not proof it renders; the burn test is what caught the missing-x264 problem. Current bundle: ~495 MB.
- Every ffmpeg/ffprobe call passes `**_no_window()` (`CREATE_NO_WINDOW` on nt) — without it a console window flashes on screen for each invocation.
- `console=False` in the spec means `sys.stdout`/`sys.stderr` are `None` at runtime. `__main__.py::_redirect_output()` points them at a real log file (`%LOCALAPPDATA%\auto_sub\auto_sub.log`), preserving the stderr breadcrumbs described under "Logging for translation regressions" — they are the only support channel once this is on someone else's machine. It leaves a real terminal alone (`isatty`).
- The spec **excludes torch/ultralytics**. `ui/burn_options_dialog.py` hides the whole-body YOLO aspect option unless `ultralytics` is importable, so the packaged build never offers an option that would error out.
- `collect_data_files("faster_whisper")` is required — the Silero VAD ONNX model ships as package data and `vad_filter=True` fails without it. Likewise `collect_dynamic_libs` for ctranslate2 / onnxruntime / av, whose native libs aren't found by import-following.

### Subtitle format
- Internally **everything is `.ass`** (Advanced SubStation Alpha). `.srt` cannot carry styling (font, size, color, background, position) and has poor Arabic handling.
- `core/ass_writer.py` writes UTF-8, `Encoding: 1`, RTL is handled by libass + HarfBuzz at render time — **do not** pre-reverse Arabic strings.
- Color conversion: `_hex_to_ass_color(hex, visibility=0..255)`. Visibility is user-facing (255 = fully visible). Internally inverted to ASS's transparency byte. There was a bug where primary text was alpha=255 (fully transparent); the fix is to pass `visibility=255` for text fill and `visibility=back_alpha` only for the background box.

### PySide6 / Qt
- `QDialog.Accepted` is a class-level enum. **`dlg.Accepted` raises `AttributeError`** in PySide6 6.11. Always use `QDialog.Accepted`. This bug silently broke the translate dialog (exception swallowed by Qt's signal dispatch, dialog appeared cancelled, English was burned).
- `QSizePolicy.Expanding` is on the class, not on the instance returned by `widget.sizePolicy()`. Import `QSizePolicy` and reference `QSizePolicy.Expanding`.
- **`QVideoWidget` on macOS does not reliably composite child widget overlays** — child `QLabel`s can hide the video underneath. We use `QGraphicsView + QGraphicsVideoItem` instead, with subtitle text as a `QGraphicsSimpleTextItem` and the background as a `QGraphicsRectItem`. Cross-platform reliable.
- After `QMediaPlayer.setSource(...)`, call `play()` then immediately `pause()` then `setPosition(0)` to flush the first frame so the user sees a poster image instead of black.

### Translation flow
- Translation is **deliberately manual**. We export a prompt the user pastes into Claude/ChatGPT, then they paste Arabic back. LLMs are better than any free machine-translation engine for this use case.
- `ui/translate_dialog.py` is a **side-by-side EN/AR table**. Earlier paste-and-parse approaches kept failing for the user because of line-count drift. The table:
  - Lets bulk-paste auto-fill the right column (best effort).
  - Lets you edit any cell directly.
  - On OK, applies whatever Arabic is in the right column; empty rows fall back to English with a confirmation.
- The Arabic-character guard (`_has_arabic`) warns when 0 Arabic chars are detected (catches accidentally re-pasting the prompt).

### Logging for translation regressions
- `ui/timeline.py::replace_texts` prints to stderr what landed in cells.
- `ui/main_window.py::_start_burn` prints to stderr what `dump()` returns.
- These two lines in `/tmp/auto_sub.log` are the source of truth when "burn shows English even though I translated" comes up.

## Pipeline state machine

The toolbar has 4 numbered steps. Each is "idle" / "next" / "done" — driven by `_update_pipeline()` in `main_window.py`:

| Step | "next" when | "done" when |
|------|-------------|-------------|
| 1 Open | no video loaded | video loaded |
| 2 Transcribe | video loaded, no segments | segments exist |
| 3 Translate | segments exist, language == "en" | language == "ar" |
| 4 Burn | segments exist | (never marked done; burns are repeatable) |

When changing state, call `self._update_pipeline()`. The QSS uses `objectName` (`step` / `step-next` / `step-done`) — Qt requires `unpolish`/`polish` after changing `objectName` to re-apply the stylesheet, see `_set_step_state()`.

## File map

```
auto_sub/
├── .github/workflows/windows-build.yml  # builds the Windows release on CI
├── packaging/
│   ├── auto_sub.spec     # PyInstaller onedir spec
│   └── READ_ME_FIRST.txt # plain-language instructions shipped to end users
├── core/         # pure logic, no Qt
│   ├── models.py         # Segment, Style dataclasses
│   ├── transcribe.py     # faster-whisper + word-level silence-trim & gap-split
│   ├── ass_writer.py     # Segments + Style → .ass file
│   ├── burn.py           # ffmpeg invocations (preview frame + final burn)
│   ├── reframe.py        # 9:16 smart crop: face track → time-varying crop chain
│   └── translate_io.py   # prompt building, numbered-line parser
└── ui/
    ├── main_window.py    # toolbar pipeline, splitter, drop overlay, workers
    ├── player.py         # QGraphicsView-based video player + subtitle overlay
    ├── timeline.py       # subtitle grid: editable, click-to-seek, active highlight
    ├── style_panel.py    # grouped font / outline / background / position controls
    ├── burn_options_dialog.py  # per-export aspect ratio chooser (source / 9:16)
    └── translate_dialog.py  # side-by-side EN/AR table
```

## Running

```bash
source .venv/bin/activate
python -m auto_sub
```

The venv is Python 3.12 (3.14 lacks wheels for some deps).

## Common tasks

- **Run headless smoke-test:** `QT_QPA_PLATFORM=offscreen python -c "from PySide6.QtWidgets import QApplication; import sys; from auto_sub.ui.main_window import MainWindow; a=QApplication(sys.argv); w=MainWindow(); w.show()"`
- **Cut a fresh test clip:** see the README — `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg -y -ss 4458 -i SOURCE -t 60 -c:v libx264 -crf 20 -c:a aac OUT.mp4`.
- **Force a specific model without touching settings:** `AUTO_SUB_MODEL=medium python -m auto_sub`.
- **Inspect what was burned:** open `<output>.subbed.ass` next to the burned mp4 — it's the literal `.ass` file ffmpeg used.

## Don't

- Don't add cloud translation. Manual paste is a feature, not a TODO.
- Don't switch off `word_timestamps`. The silence-trim and gap-split depend on it.
- Don't pre-reverse Arabic strings. libass handles RTL shaping.
- Don't use `dlg.Accepted` — always `QDialog.Accepted`.
- Don't add another GUI framework. PySide6 is fine.
- Don't write `.srt` as the internal format.
- Don't re-add the model dropdown, or add torch/ultralytics to the Windows bundle. Both were removed to keep the release simple and small for non-technical users.
- Don't switch the spec to `console=True` or onefile.
