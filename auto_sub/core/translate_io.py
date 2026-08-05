from __future__ import annotations

import re

from .models import Segment

PROMPT_TEMPLATE = """\
Translate the following English subtitle lines to natural, modern Arabic.

Strict rules:
1. Output EXACTLY the same number of lines, in the same order.
2. Keep each line numbered the same way (e.g. "1. ...").
3. Do NOT merge or split lines.
4. Use natural conversational Arabic — for football/coaching content, use clear common terminology.
5. No extra commentary, no explanations, no transliteration. Only the translated lines.
6. Keep shortcuts as is in english

English:
{numbered}
"""


def export_numbered(segments: list[Segment]) -> str:
    return "\n".join(f"{i + 1}. {s.text}" for i, s in enumerate(segments))


def build_prompt(segments: list[Segment]) -> str:
    return PROMPT_TEMPLATE.format(numbered=export_numbered(segments))


_NUM_PREFIX = re.compile(r"^\s*[\(\[]?\d+[\.\)\-:،]\s*")


def _strip_num_prefix(s: str) -> str:
    return _NUM_PREFIX.sub("", s, count=1).strip()


def parse_numbered(text: str, expected_count: int) -> list[str]:
    """Parse the Arabic output back into a list of strings.

    Strategy:
      1. Try strict mode — keep only lines that start with a digit + separator
         (so preambles like "Here is the translation:" are ignored).
      2. If that doesn't match the expected count, fall back to "all non-empty
         lines" mode.
    Raises ValueError only if neither approach yields the right count.
    """
    raw_lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    strict = [_strip_num_prefix(ln) for ln in raw_lines if _NUM_PREFIX.match(ln)]
    if len(strict) == expected_count:
        return strict

    lenient = [_strip_num_prefix(ln) for ln in raw_lines]
    if len(lenient) == expected_count:
        return lenient

    raise ValueError(
        f"Expected {expected_count} translated lines, "
        f"got {len(strict)} numbered / {len(lenient)} total. "
        "Check that the LLM preserved one line per English line "
        "(no preamble, no wrapped lines)."
    )


def apply_translation(segments: list[Segment], translated: list[str]) -> list[Segment]:
    if len(segments) != len(translated):
        raise ValueError("segment / translation length mismatch")
    return [Segment(start=s.start, end=s.end, text=t) for s, t in zip(segments, translated)]
