from __future__ import annotations

import os
import threading
import time
from collections.abc import Iterator
from pathlib import Path

from .models import Segment

# One model, no dropdown. large-v3-turbo is ~5x faster than large-v3 on CPU
# (which is what every Windows machine here will be using) at ~95% of the
# quality. Override for testing with AUTO_SUB_MODEL=...
MODEL_NAME = os.environ.get("AUTO_SUB_MODEL", "large-v3-turbo")

# Approximate download size, used only to give the first-run progress bar a
# scale. Being a little off just makes the bar finish early or hang at 99%.
MODEL_DOWNLOAD_BYTES = 1_620_000_000


def _hf_cache_dir() -> Path:
    from huggingface_hub.constants import HF_HUB_CACHE

    return Path(HF_HUB_CACHE)


def _dir_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def model_is_cached() -> bool:
    """True when the weights are already on disk, so no download is needed."""
    from faster_whisper.utils import download_model

    try:
        download_model(MODEL_NAME, local_files_only=True)
        return True
    except Exception:  # noqa: BLE001 — any failure means "not cached"
        return False


def ensure_model(progress=None) -> None:
    """Download the Whisper weights if missing, reporting bytes as they land.

    huggingface_hub gives no usable byte callback here, so the download runs on
    a helper thread while we watch the cache directory grow. Crude, but it is
    the difference between a visible progress bar and an app that looks frozen
    for ten minutes on first use.

    progress: optional callable(done_bytes: float, total_bytes: float)
    """
    if model_is_cached():
        return

    from faster_whisper.utils import download_model

    cache = _hf_cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    baseline = _dir_size(cache)

    error: list[BaseException] = []

    def _fetch() -> None:
        try:
            download_model(MODEL_NAME)
        except BaseException as e:  # noqa: BLE001 — re-raised on the caller's thread
            error.append(e)

    t = threading.Thread(target=_fetch, daemon=True)
    t.start()
    while t.is_alive():
        if progress:
            grown = max(0, _dir_size(cache) - baseline)
            progress(min(grown, MODEL_DOWNLOAD_BYTES), MODEL_DOWNLOAD_BYTES)
        time.sleep(1.0)
    t.join()
    if error:
        raise error[0]


def transcribe(
    video_path: str,
    model_size: str | None = None,
    progress=None,
    tail_pad: float = 0.30,
    split_gap: float = 0.80,
    max_chars: int = 25,
    max_dur: float = 3.0,
    min_dur: float = 0.70,
    split_punct: bool = True,
    split_comma: bool = True,
) -> Iterator[Segment]:
    """Yield Segment objects as faster-whisper produces them.

    Several well-known Whisper subtitle problems are handled here using
    word-level timestamps:

      1. *Lingering during silence.* Whisper's segment-level `end` often
         extends past the actual final word. We trim end to
         `last_word.end + tail_pad`.

      2. *One segment that spans a long pause.* Whisper sometimes glues a
         sentence before and after several seconds of silence into a single
         segment. We split such a segment wherever the inter-word gap exceeds
         `split_gap` seconds, producing two (or more) shorter subs with the
         silence in between left blank.

      3. *One giant block during continuous speech.* When someone talks
         without long pauses, the whole paragraph stays one segment and
         renders as a large multi-line block. We additionally split into short
         cues at sentence punctuation (`split_punct`) and commas
         (`split_comma`), and cap each cue at `max_chars` characters and
         `max_dur` seconds. Cues shorter than `min_dur` are merged forward
         (when they still fit the caps) to avoid flicker. Every cue boundary
         snaps to a real word start/end, so timing stays accurate.

    progress: optional callable(done_seconds: float, total_seconds: float)
    """
    from faster_whisper import WhisperModel

    size = model_size or MODEL_NAME
    model = WhisperModel(size, device="auto", compute_type="int8")

    raw_segments, info = model.transcribe(
        video_path,
        language="en",
        vad_filter=True,
        # Word timestamps are required for both the silence-trim and the
        # gap-split. VAD parameters are left at defaults so Whisper's natural
        # phrase grouping is preserved.
        word_timestamps=True,
    )
    total = float(info.duration or 0.0)

    for s in raw_segments:
        if not s.text.strip():
            continue
        for seg in _segment_from_words(
            s,
            tail_pad=tail_pad,
            split_gap=split_gap,
            max_chars=max_chars,
            max_dur=max_dur,
            min_dur=min_dur,
            split_punct=split_punct,
            split_comma=split_comma,
        ):
            if progress:
                progress(seg.end, total)
            yield seg


_SENTENCE_END = (".", "!", "?")
_CLAUSE_END = (",",)


def _emit(cluster, tail_pad: float):
    """Build one Segment from a list of words; None if it has no text."""
    text = "".join(w.word for w in cluster).strip()
    if not text:
        return None
    start = float(cluster[0].start)
    end = float(cluster[-1].end) + tail_pad
    if end <= start:
        end = start + 0.2
    return Segment(start=start, end=end, text=text)


def _segment_from_words(
    s,
    tail_pad: float,
    split_gap: float,
    max_chars: int,
    max_dur: float,
    min_dur: float,
    split_punct: bool,
    split_comma: bool,
):
    """Convert a faster-whisper Segment into one or more short, timed cues.

    - Hard-splits after a word ending in sentence punctuation / a comma.
    - Otherwise closes the cue before the next word would exceed the
      inter-word gap, the duration cap, or the character cap.
    - Trims end to last_word.end + tail_pad.
    - Merges cues shorter than min_dur into the following cue when the result
      still fits the caps (anti-flicker).
    - Falls back to the raw segment if there are no word timestamps.
    """
    words = list(getattr(s, "words", None) or [])
    if not words:
        yield Segment(start=float(s.start), end=float(s.end), text=s.text.strip())
        return

    # Build word clusters using a one-word lookahead so cues stay within caps.
    clusters: list[list] = []
    cur: list = []
    for i, w in enumerate(words):
        cur.append(w)
        token = w.word.strip()
        if (split_punct and token.endswith(_SENTENCE_END)) or (
            split_comma and token.endswith(_CLAUSE_END)
        ):
            clusters.append(cur)
            cur = []
            continue
        if i + 1 < len(words):
            nxt = words[i + 1]
            gap = float(nxt.start) - float(w.end)
            dur_if_add = float(nxt.end) - float(cur[0].start)
            text_if_add = "".join(x.word for x in cur).strip() + nxt.word
            if (
                gap > split_gap
                or dur_if_add > max_dur
                or len(text_if_add.strip()) > max_chars
            ):
                clusters.append(cur)
                cur = []
    if cur:
        clusters.append(cur)

    segs = [seg for c in clusters if (seg := _emit(c, tail_pad)) is not None]

    # Anti-flicker: merge a too-short cue into the next when caps still hold.
    merged: list[Segment] = []
    for seg in segs:
        if merged:
            prev = merged[-1]
            combined_dur = seg.end - prev.start
            combined_text = f"{prev.text} {seg.text}"
            if (prev.end - prev.start) < min_dur and (
                combined_dur <= max_dur and len(combined_text) <= max_chars
            ):
                merged[-1] = Segment(
                    start=prev.start, end=seg.end, text=combined_text
                )
                continue
        merged.append(seg)

    # Prevent overlapping cues: a cue's padded end must not cross the next
    # cue's start, or libass renders both at once and stacks them vertically.
    # When there is a real pause the pad stays well clear of the next start,
    # so this only trims back-to-back cues produced by continuous speech.
    for i in range(len(merged) - 1):
        cur = merged[i]
        nxt_start = merged[i + 1].start
        if cur.end > nxt_start > cur.start:
            merged[i] = Segment(start=cur.start, end=nxt_start, text=cur.text)

    yield from merged
