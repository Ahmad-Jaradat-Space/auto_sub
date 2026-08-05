from __future__ import annotations

from .models import Segment, Style


def _fmt_time(t: float) -> str:
    if t < 0:
        t = 0.0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def _hex_to_ass_color(hex_color: str, visibility: int = 255) -> str:
    """Convert #RRGGBB to ASS &HAABBGGRR.

    `visibility` is the user-facing 0..255 opacity (255 = fully visible).
    ASS stores transparency, so it's inverted internally.
    """
    h = hex_color.lstrip("#")
    if len(h) != 6:
        h = "FFFFFF"
    r, g, b = h[0:2], h[2:4], h[4:6]
    vis = max(0, min(255, int(visibility)))
    a = 255 - vis
    return f"&H{a:02X}{b}{g}{r}".upper()


def build_ass(
    segments: list[Segment],
    style: Style,
    video_w: int = 1920,
    video_h: int = 1080,
    play_res: tuple[int, int] | None = None,
) -> str:
    """Build the .ass body.

    `play_res` overrides the rendered PlayResX/Y — use it when the burn-time
    output dimensions differ from the source (e.g., 9:16 reframe). MarginV is
    rescaled proportionally so the sub still sits at the same relative offset
    from the bottom.
    """
    primary = _hex_to_ass_color(style.primary_color, visibility=255)
    outline = _hex_to_ass_color(style.outline_color, visibility=255)
    back = _hex_to_ass_color(style.back_color, visibility=style.back_alpha)
    # BorderStyle: 1 = outline + shadow, 3 = opaque box behind text.
    border_style = 3 if style.back_alpha > 0 else 1

    if play_res is not None:
        play_w, play_h = play_res
        margin_v = int(round(style.margin_v * (play_h / max(1, video_h))))
        margin_h = int(round(style.margin_h * (play_w / max(1, video_w))))
    else:
        play_w, play_h = video_w, video_h
        margin_v = style.margin_v
        margin_h = style.margin_h

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_w}
PlayResY: {play_h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Ar,{style.font_name},{style.font_size},{primary},&H000000FF,{outline},{back},{-1 if style.bold else 0},{-1 if style.italic else 0},0,0,100,100,0,0,{border_style},{style.outline_width},0,{style.alignment},{margin_h},{margin_h},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = [header]
    for seg in segments:
        text = seg.text.replace("\n", "\\N")
        lines.append(
            f"Dialogue: 0,{_fmt_time(seg.start)},{_fmt_time(seg.end)},Ar,,0,0,0,,{text}"
        )
    return "\n".join(lines) + "\n"


def write_ass(
    path: str,
    segments: list[Segment],
    style: Style,
    video_w: int = 1920,
    video_h: int = 1080,
    play_res: tuple[int, int] | None = None,
) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(build_ass(segments, style, video_w, video_h, play_res=play_res))
