from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from app.models import Segment

SEG_WIDTH = 480


@dataclass(frozen=True)
class SegmentParams:
    diff_threshold: float = 0.15  # fraction of changed columns that counts as a page change
    min_duration: float = 0.8  # seconds; shorter stable runs are dropped
    pixel_delta: int = 40  # grey-level change that counts as "changed"


def prep_gray(img: np.ndarray, width: int = SEG_WIDTH) -> np.ndarray:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    h, w = gray.shape
    if w == width:
        return gray
    return cv2.resize(gray, (width, max(1, round(h * width / w))), interpolation=cv2.INTER_AREA)


def frame_change(a: np.ndarray, b: np.ndarray, pixel_delta: int = 40) -> float:
    """Fraction of columns containing a real change between two grey images.

    A moving cursor or note highlight touches only a few narrow columns, while a page
    turn changes digits spread across the whole width, so this separates the two.
    """
    changed = cv2.absdiff(a, b) > pixel_delta
    return float((changed.sum(axis=0) >= 2).mean())


def find_segments(
    times: list[float], grays: list[np.ndarray], fps: float, params: SegmentParams | None = None
) -> list[Segment]:
    params = params or SegmentParams()
    if not grays:
        return []
    breaks = [0]
    for i in range(1, len(grays)):
        if frame_change(grays[i - 1], grays[i], params.pixel_delta) >= params.diff_threshold:
            breaks.append(i)
    breaks.append(len(grays))
    segments = []
    for start, stop in zip(breaks, breaks[1:], strict=False):
        end_idx = stop - 1
        end_t = times[end_idx] + 1.0 / fps
        if end_t - times[start] >= params.min_duration:
            segments.append(Segment(start, end_idx, times[start], end_t))
    return segments
