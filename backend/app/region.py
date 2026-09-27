from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from app.models import Roi


@dataclass(frozen=True)
class Staff:
    lines: list[int]  # y of each line, top to bottom
    x0: int
    x1: int

    @property
    def spacing(self) -> float:
        return float(np.mean(np.diff(self.lines)))


@dataclass(frozen=True)
class RegionGuess:
    roi: Roi
    confidence: float  # 0..1; 0 means fallback guess


def _to_gray(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img


def _line_mask(gray: np.ndarray) -> np.ndarray:
    """Pixels that are darker than their surroundings and part of a >=15px horizontal run.

    The 31px adaptive block keeps a thin line from lifting the local mean enough to
    flag the background next to it."""
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 10
    )
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 1))
    return cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel) > 0


def _line_rows(mask: np.ndarray, min_len_ratio: float) -> list[np.ndarray]:
    """Row-index groups of lines covering >= min_len_ratio of the width.

    Coverage is counted over the whole row, so lines broken by fret numbers still count."""
    rows = np.flatnonzero(mask.sum(axis=1) >= mask.shape[1] * min_len_ratio)
    if rows.size == 0:
        return []
    return np.split(rows, np.flatnonzero(np.diff(rows) > 1) + 1)


def _staff_extent(mask: np.ndarray, groups: list[np.ndarray], spacing: float) -> tuple[int, int]:
    """Longest column run where at least half of the staff's lines have ink.

    Other overlays (chord diagrams, logos) rarely line up with most staff lines."""
    coverage = np.mean([mask[g].any(axis=0) for g in groups], axis=0) >= 0.5
    bridge = int(2 * spacing) | 1  # close gaps left by fret numbers
    closed = cv2.morphologyEx(
        coverage.astype(np.uint8)[None, :],
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (bridge, 1)),
    )[0]
    cols = np.flatnonzero(closed)
    if cols.size == 0:
        return 0, mask.shape[1] - 1
    runs = np.split(cols, np.flatnonzero(np.diff(cols) > 1) + 1)
    longest = max(runs, key=len)
    return int(longest[0]), int(longest[-1])


def _make_staff(mask: np.ndarray, groups: list[np.ndarray]) -> Staff:
    lines = [int(round(g.mean())) for g in groups]
    x0, x1 = _staff_extent(mask, groups, float(np.mean(np.diff(lines))))
    return Staff(lines, x0, x1)


def _group_staves(mask: np.ndarray, rows: list[np.ndarray]) -> list[Staff]:
    """Group consecutive lines with (nearly) equal gaps; >=4 lines make a staff."""
    staves: list[Staff] = []
    group: list[np.ndarray] = []
    for line in rows:
        if not group:
            group = [line]
            continue
        gap = line.mean() - group[-1].mean()
        if len(group) == 1:
            ok = gap >= 4
        else:
            prev_gap = group[-1].mean() - group[-2].mean()
            ok = abs(gap - prev_gap) <= 0.2 * prev_gap + 1
        if ok:
            group.append(line)
        elif len(group) >= 4:
            staves.append(_make_staff(mask, group))
            group = [line]
        else:
            # the previous line may still start a new staff with this one
            group = [group[-1], line] if gap >= 4 else [line]
    if len(group) >= 4:
        staves.append(_make_staff(mask, group))
    return staves


def detect_staves(img: np.ndarray, min_len_ratio: float = 0.4) -> list[Staff]:
    """Find staves: groups of >=4 evenly spaced long horizontal lines (tab = 6, bass = 4).

    Both polarities are tried (dark lines on a light panel, light lines on a dark one).
    With the wrong polarity the gaps *between* lines show up instead, which yields one
    line fewer per staff, so the polarity with more lines in total wins."""
    gray = _to_gray(img)
    candidates = []
    for g in (gray, 255 - gray):
        mask = _line_mask(g)
        candidates.append(_group_staves(mask, _line_rows(mask, min_len_ratio)))
    return max(candidates, key=lambda staves: sum(len(st.lines) for st in staves))


def has_staff_lines(img: np.ndarray) -> bool:
    return len(detect_staves(img)) > 0


def _overlaps(a: Staff, b: Staff) -> bool:
    return a.lines[0] <= b.lines[-1] and b.lines[0] <= a.lines[-1]


def staves_bbox(staves: list[Staff], width: int, height: int) -> Roi:
    """Box around all staves, with room for chord names above and note stems below.

    Vertical extent is the union; horizontal extent is the median over detections."""
    s = max(st.spacing for st in staves)
    x0 = np.median([st.x0 for st in staves]) - s
    x1 = np.median([st.x1 for st in staves]) + s
    y0 = min(st.lines[0] for st in staves) - 3 * s
    y1 = max(st.lines[-1] for st in staves) + 3 * s
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = min(width, int(x1)), min(height, int(y1))
    return Roi(x0, y0, x1 - x0, y1 - y0)


def trim_to_panel(gray: np.ndarray, roi: Roi, tolerance: int = 25, min_bg: float = 0.6) -> Roi:
    """Shrink the top/bottom edges until rows look like the tab panel background,
    so the margin reserved for chord names does not swallow part of the video."""
    crop = roi.crop(gray)
    bg = np.median(crop)
    is_panel = (np.abs(crop.astype(np.int16) - bg) < tolerance).mean(axis=1) >= min_bg
    rows = np.flatnonzero(is_panel)
    if rows.size == 0:
        return roi
    top, bottom = int(rows[0]), int(rows[-1])
    return Roi(roi.x, roi.y + top, roi.w, bottom - top + 1)


def detect_region(frames: list[np.ndarray]) -> RegionGuess:
    """Locate the tab area from several frames.

    Each frame is detected on its own (the staff may sit a little higher or lower on
    every page). A staff is trusted only if some staff overlaps it vertically in at
    least half of the frames, and among trusted staves only those with the most lines
    are kept: a guitar neck held level can mimic a partial staff, but tab is 6 lines.
    """
    h, w = frames[0].shape[:2]
    per_frame = [detect_staves(f) for f in frames]

    def support(st: Staff) -> int:
        return sum(any(_overlaps(st, o) for o in found) for found in per_frame)

    stable = [st for found in per_frame for st in found if support(st) * 2 >= len(frames)]
    if not stable:
        return RegionGuess(Roi(0, h * 2 // 3, w, h - h * 2 // 3), 0.0)
    most = max(len(st.lines) for st in stable)
    stable = [st for st in stable if len(st.lines) == most]
    hits = sum(any(_overlaps(st, o) for st in stable for o in found) for found in per_frame)
    median = np.median(np.stack([_to_gray(f) for f in frames]), axis=0).astype(np.uint8)
    roi = trim_to_panel(median, staves_bbox(stable, w, h))
    return RegionGuess(roi, hits / len(frames))
