# auto_sub
source .venv/bin/activate && python -m auto_sub
Local Mac GUI to put burned-in Arabic subtitles on an English video clip — fully free, no API keys, no cloud.

The hard parts handled for you:
- Whisper segments that linger past actual speech are trimmed to the last spoken word.
- Whisper segments that span a long silence are split where the silence is.
- Translation round-trip is paste-driven (best Arabic quality), with an EN/AR side-by-side table that won't silently lose your work to line-count mismatches.
- Arabic is burned through libass + a bundled font, so output looks identical on any machine.

## Pipeline (UI is numbered to match)

1. **📂 Open video** — drop a file or press `⌘O`.
2. **📝 Transcribe** — faster-whisper runs locally; pick the model from the toolbar.
3. **🌐 Translate** — copy the auto-built prompt, paste into Claude/ChatGPT, paste the Arabic back into the side-by-side table.
4. **🔥 Burn & Export** — ffmpeg burns the styled subtitles. The `.ass` is also written next to the `.mp4` so you can inspect the exact text rendered.

The toolbar lights the **next** recommended step in blue, marks completed steps in green, and the status bar mirrors the same "Next → …" hint.

## Install (development, macOS)

```bash
brew install ffmpeg-full         # default `ffmpeg` no longer bundles libass
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
python -m auto_sub
```

Why `ffmpeg-full`: Homebrew's `ffmpeg` (8.x) ships without libass, so the `ass` filter doesn't exist and any subtitle burn fails. `ffmpeg-full` is keg-only at `/opt/homebrew/opt/ffmpeg-full/bin` — the app finds it automatically.

Why Python 3.12: PySide6 + faster-whisper don't all ship 3.14 wheels yet.

## Windows release (what non-technical users get)

A self-contained folder — unzip, double-click `auto_sub.exe`, nothing to install. ffmpeg is bundled inside it, so there is no Homebrew equivalent to explain.

Build it from the **Actions** tab on GitHub → *Build Windows app* → *Run workflow*, then download the `auto_sub-windows` artifact. PyInstaller cannot cross-compile, so the build has to happen on a Windows runner; you never need a Windows machine yourself. Tagging `v*` builds automatically too.

See `packaging/`:
- `auto_sub.spec` — PyInstaller onedir spec (excludes torch/ultralytics to keep it ~400 MB)
- `READ_ME_FIRST.txt` — plain-language instructions shipped inside the folder

## Model

One model, no dropdown: **`large-v3-turbo`**. Roughly 95 % of `large-v3` quality at ~5× the speed, which matters because these machines transcribe on CPU.

First transcription downloads ~1.6 GB into the HuggingFace cache with a real progress bar (`core/transcribe.py::ensure_model`), then it's local forever.

Override for testing with `AUTO_SUB_MODEL=large-v3 python -m auto_sub`.

## Keyboard shortcuts

| Key | Action |
|---|---|
| `⌘O` | Open video |
| `⌘T` | Transcribe |
| `⌘E` | Translate |
| `⌘B` | Burn & Export |
| `Space` | Play / pause video |

## Layout

```
┌─────────────────────────────────────────────────────────────────┐
│ 1 Open  ›  2 Transcribe  ›  3 Translate  ›  4 Burn   Model: …  │
├─────────────────────────────────────────────────────────────────┤
│                │                            │                  │
│   Timeline     │     Live video player      │   Style panel    │
│   (click a     │   (subtitle overlay        │   (font / color  │
│    row to      │    updates as it plays;    │    / background  │
│    seek)       │    active row highlights)  │    / position)   │
│                │                            │                  │
├─────────────────────────────────────────────────────────────────┤
│ Next → 2 · 📝 Transcribe                                        │
└─────────────────────────────────────────────────────────────────┘
```

## Why .ass and not .srt

`.srt` cannot carry per-line styling. Arabic also needs proper RTL shaping (HarfBuzz via libass). `.ass` (Advanced SubStation Alpha) carries the font, size, color, outline, background box, position, and alignment in-band, and libass renders it pixel-identical on any machine that has the same font.

## Project structure

```
auto_sub/
├── core/
│   ├── transcribe.py     # faster-whisper + silence-trim + gap-split
│   ├── ass_writer.py     # build .ass from segments + style
│   ├── burn.py           # ffmpeg invocations (preview frame + final burn)
│   ├── translate_io.py   # prompt + numbered-line parser
│   └── models.py         # Segment, Style dataclasses
├── ui/
│   ├── main_window.py    # toolbar + splitter + pipeline state
│   ├── player.py         # QGraphicsView + QGraphicsVideoItem + sub overlay
│   ├── timeline.py       # subtitle grid with click-to-seek
│   ├── style_panel.py    # grouped style controls
│   └── translate_dialog.py  # side-by-side EN/AR table
└── assets/
    └── NotoSansArabic-Regular.ttf
```

## Troubleshooting

- **"ffmpeg failed code N"** — on macOS make sure `ffmpeg-full` is installed (`brew install ffmpeg-full`); on Windows the `ffmpeg` folder next to `auto_sub.exe` is missing, so re-unzip the release.
- **Log file** — `/tmp/auto_sub.log` on macOS, `%LOCALAPPDATA%\auto_sub\auto_sub.log` on Windows. Written whenever stderr isn't a terminal, which is always true for the packaged build.
- **Burn shows English instead of Arabic** — check the log; the app prints `replace_texts applied …` and `burning N segments. First texts: [...]` on each step, so you can see exactly what landed in the cells.
- **Subtitles linger after the speaker stops** — tighten `tail_pad` in `core/transcribe.py` (default 0.30 s).
- **One subtitle spans a long pause** — lower `split_gap` in `core/transcribe.py` (default 0.80 s).
- **Preview is black** — check `/tmp/auto_sub.log` for `[auto_sub] player error: …`.

## License

MIT (this repo). Whisper: MIT (OpenAI). Noto Sans Arabic: SIL Open Font License 1.1.
