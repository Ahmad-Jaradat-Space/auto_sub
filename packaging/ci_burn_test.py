"""Burn a real subtitle through the app's own code path, on a nasty path.

Run by .github/workflows/windows-build.yml against the bundled ffmpeg.

The point is the *path*, not the burn. An earlier version of this test called
ffmpeg directly with `t.ass` and `auto_sub/assets`: relative, ASCII, no spaces,
forward slashes only. It passed happily while every real Windows export was
failing, because `C:\\Users\\...` needs double escaping in an ffmpeg filter
value and `_escape_filter_value` only escaped once. So this test uses an
absolute path containing a drive letter, a space, and Arabic characters, and it
goes through burn.render_preview_frame rather than hand-writing the filter.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auto_sub.core import burn  # noqa: E402
from auto_sub.core.ass_writer import write_ass  # noqa: E402
from auto_sub.core.models import Segment, Style  # noqa: E402


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="auto_sub ci "))
    work = root / "مجلد اختبار"  # space in the parent, Arabic here
    work.mkdir(parents=True)

    ass = work / "clip test.ass"
    video = work / "clip test.mp4"
    out_png = work / "frame out.png"

    write_ass(str(ass), [Segment(start=0.0, end=2.0, text="مرحبا بالعالم")], Style(), 640, 480)

    ffmpeg = burn._ffmpeg()
    print(f"ffmpeg: {ffmpeg}")
    print(f"work dir: {work}")
    print(f"filter: {burn._build_ass_filter(str(ass), str(work))}")

    import subprocess

    subprocess.run(
        [ffmpeg, "-y", "-f", "lavfi", "-i", "testsrc=size=640x480:duration=3",
         "-c:v", "libx264", str(video)],
        check=True, capture_output=True,
    )

    fonts = Path(__file__).resolve().parent.parent / "auto_sub" / "assets"
    burn.render_preview_frame(str(video), str(ass), 1.0, str(out_png), fonts_dir=str(fonts))

    if not out_png.exists() or out_png.stat().st_size < 1000:
        print("FAIL: no usable preview frame produced", file=sys.stderr)
        return 1

    burned = work / "burned out.mp4"
    burn.burn(str(video), str(ass), str(burned), fonts_dir=str(fonts))
    if not burned.exists() or burned.stat().st_size < 1000:
        print("FAIL: no usable burned video produced", file=sys.stderr)
        return 1

    print(f"preview frame: {out_png.stat().st_size} bytes")
    print(f"burned video:  {burned.stat().st_size} bytes")
    print("OK: preview and burn both worked on an absolute path with a space and Arabic characters")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
