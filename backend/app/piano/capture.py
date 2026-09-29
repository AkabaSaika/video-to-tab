"""The ordered, de-duplicated grand-staff systems shown in a piano video.

Every sampled frame is searched for whole systems (systems.find_systems). A system is the
same as one seen shortly before if its notation (staff lines removed, scaled to one size)
matches, which tolerates scrolling, a play cursor, highlights and compression noise. The
sharpest clean sighting is kept. Systems are ordered by first sighting, then top to bottom,
which suits both continuously scrolling and page-turning videos.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from app.frames import probe, sample_frames
from app.piano.systems import System, find_systems

SIG_SIZE = (480, 160)  # signature width, height
SAME = 0.35  # notation mismatch below this: the same system
CLEAN = 0.2  # mismatch below this: a clean sighting that may replace the kept image
RECENT = 4.0  # seconds: a system unseen for longer counts as new if it shows up again
MIN_HITS = 2  # sightings needed; drops systems glimpsed in one frame (e.g. a crossfade)


@dataclass
class Captured:
    image: np.ndarray = field(repr=False)  # BGR crop of the whole system
    first: float  # seconds: first and last sighting
    last: float
    y: int  # crop top in the frame of the first sighting
    x0: int  # crop left in the frame
    sharpness: float
    signature: np.ndarray = field(repr=False)
    hits: int = 1


def signature(sys_: System) -> np.ndarray:
    """The notation around the staves, staff lines removed, scaled to SIG_SIZE (0/1)."""
    s = sys_.spacing
    gray = cv2.cvtColor(sys_.image, cv2.COLOR_BGR2GRAY)
    y0 = max(0, int(sys_.top - 2 * s) - sys_.y0)
    y1 = min(gray.shape[0], int(sys_.bottom + 2 * s) - sys_.y0)
    band = gray[y0:y1]
    if np.median(band) < 128:
        band = 255 - band
    ink = cv2.adaptiveThreshold(band, 1, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 10)
    lines = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (int(4 * s) | 1, 1))
    )
    notation = cv2.subtract(ink, lines)
    small = cv2.resize(notation.astype(np.float32), SIG_SIZE, interpolation=cv2.INTER_AREA)
    return (small > 0.2).astype(np.uint8)


def mismatch(a: np.ndarray, b: np.ndarray) -> float:
    """Share of either signature's ink with no ink of the other nearby (0 = same)."""
    kernel = np.ones((5, 5), np.uint8)
    total = int(a.sum()) + int(b.sum())
    if total == 0:
        return 1.0
    miss = int((a & (1 - cv2.dilate(b, kernel))).sum()) + int(
        (b & (1 - cv2.dilate(a, kernel))).sum()
    )
    return miss / total


def sharpness(img: np.ndarray) -> float:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_32F).var())


def capture(
    video: Path, fps: float = 5.0, progress: Callable[[float], None] = lambda f: None
) -> list[Captured]:
    duration = probe(video).duration
    tracks: list[Captured] = []
    for t, frame in sample_frames(video, fps):
        taken: set[int] = set()
        for sys_ in find_systems(frame):
            sig = signature(sys_)
            best, best_score = None, SAME
            for k, tr in enumerate(tracks):
                if k in taken or t - tr.last > RECENT:
                    continue
                score = mismatch(sig, tr.signature)
                if score < best_score:
                    best, best_score = k, score
            if best is None:
                tracks.append(
                    Captured(sys_.image, t, t, sys_.y0, sys_.x0, sharpness(sys_.image), sig)
                )
                taken.add(len(tracks) - 1)
                continue
            tr = tracks[best]
            taken.add(best)
            tr.last, tr.hits = t, tr.hits + 1
            sharp = sharpness(sys_.image)
            if best_score < CLEAN and sharp > tr.sharpness:
                tr.image, tr.sharpness, tr.x0 = sys_.image, sharp, sys_.x0
        if duration > 0:
            progress(min(1.0, t / duration))
    progress(1.0)
    kept = [tr for tr in tracks if tr.hits >= MIN_HITS]
    return sorted(kept, key=lambda tr: (tr.first, tr.y))
