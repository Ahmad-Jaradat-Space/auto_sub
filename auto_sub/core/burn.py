from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import sys
from collections import deque
from functools import cache
from pathlib import Path

# Homebrew's default `ffmpeg` (as of 8.x) drops libass — we need `ffmpeg-full`
# which is keg-only. Prefer it when available so the `ass` filter exists.
_BREW_BIN_DIRS = ("/opt/homebrew/opt/ffmpeg-full/bin", "/usr/local/opt/ffmpeg-full/bin")

_EXE = ".exe" if os.name == "nt" else ""

# Not a Homebrew problem on Windows — the shipped copy is meant to be there.
_INSTALL_HINT = (
    "Reinstall auto_sub — the bundled ffmpeg folder is missing."
    if os.name == "nt"
    else "Install a build with libass: `brew install ffmpeg-full`."
)


def _bundle_dirs() -> list[Path]:
    """Directories that may hold a shipped ffmpeg, most specific first.

    The Windows release bundles ffmpeg in an `ffmpeg/` folder so users never
    have to install anything; a source checkout can drop one there too.
    """
    dirs: list[Path] = []
    if getattr(sys, "frozen", False):  # PyInstaller
        exe_dir = Path(sys.executable).resolve().parent
        dirs += [exe_dir / "ffmpeg", exe_dir / "_internal" / "ffmpeg", exe_dir]
    repo_root = Path(__file__).resolve().parent.parent.parent
    dirs.append(repo_root / "ffmpeg")
    return dirs


@cache
def _has_ass_filter(binary: str) -> bool:
    try:
        out = subprocess.run(
            [binary, "-hide_banner", "-filters"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            check=True, **_no_window(),
        )
    except Exception:
        return False
    return "ass " in out.stdout or " ass " in out.stdout


def _no_window() -> dict:
    """Keep ffmpeg from flashing a console window on Windows."""
    if os.name != "nt":
        return {}
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}


def _find(tool: str) -> str:
    for d in _bundle_dirs():
        p = d / (tool + _EXE)
        if p.exists():
            return str(p)
    for d in _BREW_BIN_DIRS:
        p = os.path.join(d, tool)
        if os.path.exists(p):
            return p
    p = shutil.which(tool)
    if not p:
        raise RuntimeError(f"{tool} not found. {_INSTALL_HINT}")
    return p


def _ffmpeg() -> str:
    bin_ = _find("ffmpeg")
    if not _has_ass_filter(bin_):
        raise RuntimeError(
            f"ffmpeg at {bin_} was built without libass — the `ass` subtitle filter is missing. "
            + _INSTALL_HINT
        )
    return bin_


def _ffprobe() -> str:
    return _find("ffprobe")


def probe_video(video_path: str) -> dict:
    """Return {'width', 'height', 'duration'} for the given video."""
    out = subprocess.run(
        [
            _ffprobe(),
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height:format=duration",
            "-of", "json",
            video_path,
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        **_no_window(),
    )
    data = json.loads(out.stdout)
    stream = data["streams"][0]
    duration = float(data.get("format", {}).get("duration", 0.0))
    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "duration": duration,
    }


# Audio codecs the mp4 muxer accepts. Anything else has to be re-encoded.
_MP4_AUDIO = {"aac", "mp3", "ac3", "eac3", "alac", "mp2", "dts"}


def probe_audio_codec(video_path: str) -> str | None:
    """Return the first audio stream's codec name, or None if there is none."""
    out = subprocess.run(
        [
            _ffprobe(),
            "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=codec_name",
            "-of", "json",
            video_path,
        ],
        check=True, capture_output=True, text=True,
        encoding="utf-8", errors="replace", **_no_window(),
    )
    streams = json.loads(out.stdout).get("streams", [])
    return streams[0].get("codec_name") if streams else None


def _escape_filter_value(path: str) -> str:
    r"""Escape a path for use inside an ffmpeg filter option value.

    ffmpeg unescapes in two passes and each metacharacter belongs to a
    different one, so a single uniform escape cannot work:

      \   survives both passes, so it needs four
      :    separates options in the second pass, so it needs \\:
      '    opens a quoted section in the first pass, and needs \\\'
      , ; [ ] separate filters and pads in the first pass, so one \ is enough

    Getting this wrong is invisible on macOS, where paths carry none of these
    characters, and breaks every export on Windows, where C:\Users\... is the
    normal case and "Match, final.mp4" or "Ahmad's clips" are ordinary names.
    Verified against ffmpeg 8 with libass for each shape above.
    """
    out: list[str] = []
    for ch in path:
        if ch == "\\":
            out.append("\\" * 4)
        elif ch == ":":
            out.append("\\\\:")
        elif ch == "'":
            out.append("\\\\\\'")
        elif ch in ",;[]":
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def _build_ass_filter(ass_path: str, fonts_dir: str | None) -> str:
    parts = [f"f={_escape_filter_value(ass_path)}"]
    if fonts_dir:
        parts.append(f"fontsdir={_escape_filter_value(fonts_dir)}")
    return "ass=" + ":".join(parts)


def render_preview_frame(
    video_path: str,
    ass_path: str,
    timestamp: float,
    output_png: str,
    fonts_dir: str | None = None,
    width: int = 640,
) -> None:
    """Render a single frame at `timestamp` with subtitles burned in."""
    filt = _build_ass_filter(ass_path, fonts_dir) + f",scale={width}:-2"
    proc = subprocess.run(
        [
            _ffmpeg(),
            "-y",
            "-ss", f"{timestamp:.3f}",
            "-i", video_path,
            "-vf", filt,
            "-frames:v", "1",
            output_png,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        **_no_window(),
    )
    if proc.returncode != 0:
        # Surface the actual ffmpeg complaint, not the bare "exit status N".
        tail = "\n".join(proc.stderr.strip().splitlines()[-3:])
        raise RuntimeError(tail)


def burn(
    video_path: str,
    ass_path: str,
    output_path: str,
    fonts_dir: str | None = None,
    progress=None,
    extra_pre_filter: str | None = None,
) -> None:
    """Hardcode subtitles into the video. Audio is copied without re-encoding.

    `extra_pre_filter` is a raw ffmpeg filter chain prepended before the ass
    filter (e.g., `crop=...,scale=1080:1920:flags=lanczos,setsar=1` for 9:16).
    """
    ass_filter = _build_ass_filter(ass_path, fonts_dir)
    filt = f"{extra_pre_filter},{ass_filter}" if extra_pre_filter else ass_filter

    # The 9:16 crop expression carries one keypoint per second, so a 24 minute
    # video produces ~36 kB of filter. Windows CreateProcess caps a command line
    # at 32767 characters and Popen fails with WinError 206 before ffmpeg starts.
    # -filter_script keeps the chain off the command line entirely.
    tail: deque[str] = deque(maxlen=20)
    script: str | None = None
    if len(filt) > 8000:
        fd, script = tempfile.mkstemp(suffix=".ffilter", text=True)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(filt)
        vf_args = ["-filter_script:v", script]
    else:
        vf_args = ["-vf", filt]

    # The open dialog accepts webm and mkv, which normally carry Vorbis or Opus.
    # ffmpeg 8 will happily mux either into mp4, so `-c:a copy` does not fail --
    # but QuickTime, Windows Media Player and most phones will not decode them,
    # so the user gets an export that plays silently everywhere they send it.
    # Re-encode to AAC unless the source codec is one mp4 players expect.
    try:
        acodec = probe_audio_codec(video_path)
    except Exception:  # noqa: BLE001
        acodec = None
    audio_args = (
        ["-c:a", "copy"] if acodec in _MP4_AUDIO else ["-c:a", "aac", "-b:a", "192k"]
    )

    cmd = [
        _ffmpeg(),
        "-y",
        "-i", video_path,
        *vf_args,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        *audio_args,
        "-movflags", "+faststart",
        output_path,
    ]
    try:
        try:
            proc = subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                encoding="utf-8", errors="replace", **_no_window(),
            )
        except OSError as e:
            # Windows refuses the launch outright when the command line or a
            # path is too long. Without this the finally-block below reads an
            # unbound `proc` and the user sees UnboundLocalError instead.
            raise RuntimeError(f"Could not start ffmpeg: {e}") from e
        assert proc.stderr is not None
        for line in proc.stderr:
            tail.append(line.rstrip())
            if progress:
                progress(line)
        proc.wait()
    finally:
        if script:
            try:
                os.unlink(script)
            except OSError:
                pass
    if proc.returncode != 0:
        # Without the tail every Windows failure mode -- path over 260 chars,
        # read-only or OneDrive-locked folder, disk full, an audio codec that
        # `-c:a copy` cannot put in an mp4 -- reads as the same bare exit code.
        raise RuntimeError(
            f"ffmpeg failed with code {proc.returncode}\n\n" + "\n".join(tail)
        )


def assets_dir() -> str:
    return str(Path(__file__).resolve().parent.parent / "assets")
