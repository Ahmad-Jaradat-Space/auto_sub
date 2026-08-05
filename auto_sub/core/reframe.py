"""Smart vertical (9:16) reframing using face or whole-body detection.

Produces a time-varying ffmpeg `crop` expression that follows the speaker so
the output keeps them in frame after cropping a wide source to a tall aspect.

Two detection methods:
- `face` (default): OpenCV's bundled Haar cascade. No extra deps. Good for
  centered front-facing talking-head clips; drops most samples on profiles or
  full-body shots.
- `person`: YOLOv8n via the `ultralytics` package (optional install). Tracks
  the largest person box per frame. Handles non-frontal / full-body subjects.

Both detectors return `list[tuple[float, Optional[float]]]` of
(time_seconds, center_x_normalized) and feed the same downstream smoothing
(`smooth_track`) and ffmpeg expression builder (`build_crop_expr`).
"""
from __future__ import annotations

import os
import sys
from typing import Callable, Literal, Optional

from .burn import probe_video


Method = Literal["face", "person"]


def _import_cv2():
    try:
        import cv2
    except ImportError as e:
        raise RuntimeError(
            "Vertical reframing needs opencv-python. Install with:\n"
            "  pip install opencv-python"
        ) from e
    return cv2


def detect_face_track(
    video_path: str,
    sample_fps: float = 5.0,
    progress: Optional[Callable[[float], None]] = None,
) -> list[tuple[float, Optional[float]]]:
    """Sample the video at `sample_fps` and locate the dominant face per sample.

    Returns list of (time_seconds, face_center_x_normalized) — x is in [0,1]
    relative to source width. None when no face was detected on that sample.
    """
    cv2 = _import_cv2()
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"OpenCV could not open {video_path}")
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = frame_count / src_fps if src_fps else 0.0
    step = max(1, int(round(src_fps / sample_fps)))

    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    detector = cv2.CascadeClassifier(cascade_path)
    if detector.empty():
        raise RuntimeError(f"OpenCV could not load face cascade at {cascade_path}")

    # Detect on a downscaled frame for speed; coordinates scale back.
    detect_w = 480
    scale = detect_w / src_w if src_w else 1.0

    samples: list[tuple[float, Optional[float]]] = []
    idx = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if idx % step == 0:
                t = idx / src_fps if src_fps else 0.0
                small = cv2.resize(frame, None, fx=scale, fy=scale,
                                   interpolation=cv2.INTER_AREA)
                gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
                faces = detector.detectMultiScale(
                    gray, scaleFactor=1.2, minNeighbors=5, minSize=(30, 30)
                )
                cx_norm: Optional[float] = None
                if len(faces) > 0:
                    # Pick the largest detection (most likely the main speaker).
                    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
                    cx_px = (x + w / 2.0) / scale
                    cx_norm = max(0.0, min(1.0, cx_px / src_w)) if src_w else None
                samples.append((t, cx_norm))
                if progress and duration:
                    progress(min(1.0, t / duration))
            idx += 1
    finally:
        cap.release()
    return samples


def detect_person_track(
    video_path: str,
    sample_fps: float = 5.0,
    progress: Optional[Callable[[float], None]] = None,
) -> list[tuple[float, Optional[float]]]:
    """Sample the video at `sample_fps` and locate the dominant person per sample.

    Uses YOLOv8n via the `ultralytics` package (optional dep). Returns the same
    shape as `detect_face_track`: list of (time, normalized_center_x). None when
    no person is detected on that sample.
    """
    os.environ.setdefault("YOLO_VERBOSE", "False")
    try:
        from ultralytics import YOLO
    except ImportError as e:
        raise RuntimeError(
            "Whole-body reframe needs ultralytics. Install with:\n"
            "  pip install ultralytics"
        ) from e

    cv2 = _import_cv2()
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"OpenCV could not open {video_path}")
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = frame_count / src_fps if src_fps else 0.0
    step = max(1, int(round(src_fps / sample_fps)))

    model = YOLO("yolov8n.pt")  # auto-downloads on first run

    samples: list[tuple[float, Optional[float]]] = []
    idx = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if idx % step == 0:
                t = idx / src_fps if src_fps else 0.0
                results = model.predict(
                    frame, classes=[0], imgsz=640, verbose=False
                )
                cx_norm: Optional[float] = None
                if results and len(results[0].boxes) > 0:
                    boxes = results[0].boxes.xyxy.cpu().numpy()  # (N, 4) in pixels of input frame
                    # Pick the largest-area box (most likely the subject).
                    areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
                    best = boxes[int(areas.argmax())]
                    cx_px = (best[0] + best[2]) / 2.0
                    if src_w:
                        cx_norm = max(0.0, min(1.0, float(cx_px) / src_w))
                samples.append((t, cx_norm))
                if progress and duration:
                    progress(min(1.0, t / duration))
            idx += 1
    finally:
        cap.release()
    return samples


def smooth_track(
    samples: list[tuple[float, Optional[float]]],
    src_w: int,
    src_h: int,
    target_aspect: float = 9.0 / 16.0,
    alpha: float = 0.15,
) -> tuple[int, int, list[tuple[float, int]]]:
    """Convert face samples to a smoothed list of (time, crop_x_px).

    Returns (crop_w, crop_h, keypoints). crop_h == src_h (we crop horizontally).
    """
    crop_h = src_h
    crop_w = int(round(src_h * target_aspect))
    crop_w = max(2, min(crop_w, src_w))
    max_x = src_w - crop_w
    default_x = max_x // 2

    last_known: Optional[float] = None
    raw: list[tuple[float, float]] = []
    for t, cx_norm in samples:
        if cx_norm is None:
            cx = last_known if last_known is not None else 0.5
        else:
            cx = cx_norm
            last_known = cx_norm
        target_x = cx * src_w - crop_w / 2.0
        target_x = max(0.0, min(float(max_x), target_x))
        raw.append((t, target_x))

    smoothed: list[tuple[float, int]] = []
    ema: Optional[float] = None
    for t, x in raw:
        ema = x if ema is None else (alpha * x + (1.0 - alpha) * ema)
        smoothed.append((t, int(round(max(0.0, min(float(max_x), ema))))))

    if not smoothed:
        smoothed = [(0.0, default_x)]
    return crop_w, crop_h, smoothed


def _downsample(track: list[tuple[float, int]], min_dt: float = 1.0) -> list[tuple[float, int]]:
    """Keep first point + any point at least `min_dt` after the previous kept one."""
    if not track:
        return track
    out = [track[0]]
    for t, x in track[1:]:
        if t - out[-1][0] >= min_dt:
            out.append((t, x))
    return out


def build_crop_expr(track: list[tuple[float, int]], crop_w: int, crop_h: int) -> str:
    """Build an ffmpeg `crop` filter with a stepwise time-varying x.

    Uses nested `if(lt(t,T),X,...)` so each keypoint holds until the next one.
    """
    points = _downsample(track, min_dt=1.0)
    if len(points) == 1:
        x_expr = str(points[0][1])
    else:
        # Build from the tail: final value, then wrap each prior keypoint.
        x_expr = str(points[-1][1])
        for t, x in reversed(points[:-1]):
            x_expr = f"if(lt(t,{t:.3f}),{x},{x_expr})"
    # Note: in ffmpeg filter values, ':' separates options and ',' separates
    # filters. The crop x-expression contains both, so wrap the whole filter
    # value with single quotes? No — ffmpeg 8 misreads quoted blocks (see
    # CLAUDE.md). Instead, escape the commas and colons inside the expression.
    x_expr_escaped = x_expr.replace("\\", "\\\\").replace(",", "\\,").replace(":", "\\:")
    y_expr = f"(ih-{crop_h})/2"
    y_expr_escaped = y_expr.replace(",", "\\,").replace(":", "\\:")
    return f"crop=w={crop_w}:h={crop_h}:x={x_expr_escaped}:y={y_expr_escaped}"


def reframe_filter_chain(
    video_path: str,
    target_w: int = 1080,
    target_h: int = 1920,
    progress: Optional[Callable[[float], None]] = None,
    method: Method = "face",
) -> tuple[str, tuple[int, int]]:
    """Full pipeline: probe → detect → smooth → ffmpeg filter chain.

    `method` selects the detector: "face" (Haar via cv2) or "person" (YOLOv8n
    via ultralytics). Returns (filter_chain_string, (output_w, output_h)). The
    filter chain ends with `scale,setsar` — callers should chain `ass=...` after.
    """
    info = probe_video(video_path)
    src_w, src_h = info["width"], info["height"]

    target_aspect = target_w / target_h
    src_aspect = src_w / src_h

    if abs(src_aspect - target_aspect) < 0.01:
        # Already the right shape — just scale.
        return f"scale={target_w}:{target_h}:flags=lanczos,setsar=1", (target_w, target_h)

    if src_aspect < target_aspect:
        # Source is already taller than target — pad sides rather than cropping
        # vertically (we'd lose the speaker's head). Use a centered pad.
        chain = (
            f"scale={target_w}:-2:flags=lanczos,"
            f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1"
        )
        return chain, (target_w, target_h)

    print(f"[auto_sub] reframe: method={method} probing {src_w}x{src_h}…",
          file=sys.stderr, flush=True)
    if method == "person":
        samples = detect_person_track(video_path, sample_fps=5.0, progress=progress)
        label = "persons"
    else:
        samples = detect_face_track(video_path, sample_fps=5.0, progress=progress)
        label = "faces"
    n_hits = sum(1 for _, x in samples if x is not None)
    print(f"[auto_sub] reframe: method={method}, {len(samples)} samples, {n_hits} with {label}",
          file=sys.stderr, flush=True)

    crop_w, crop_h, track = smooth_track(samples, src_w, src_h, target_aspect=target_aspect)
    crop_filter = build_crop_expr(track, crop_w, crop_h)
    chain = f"{crop_filter},scale={target_w}:{target_h}:flags=lanczos,setsar=1"
    return chain, (target_w, target_h)
