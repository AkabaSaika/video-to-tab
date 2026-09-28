"""Rhythm marks below the tab staff: stems, beams/flags, dots and tuplet numbers.

For every beat position the marks are measured, not interpreted; `solve.py` turns them
into duration candidates. Beams and flags are counted the same way: every column just
beside a stem crosses each beam (horizontal) or each flag (diagonal curve) once.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from app.omr.glyphs import GlyphClassifier, components
from app.region import Staff

MIN_STEM = 0.6  # in s


def stem_positions(
    ink: np.ndarray, staff: Staff, span: tuple[int, int]
) -> list[tuple[float, float]]:
    """(x center, length in s) of all vertical strokes below the staff within span."""
    s = staff.spacing
    y0 = int(staff.lines[-1] + 0.25 * s)
    y1 = min(ink.shape[0], int(staff.lines[-1] + 4.5 * s))
    x0, x1 = max(0, span[0] + 3), min(ink.shape[1], span[1] - 3)
    if y1 - y0 < 3 or x1 <= x0:
        return []
    k = max(5, int(MIN_STEM * s))
    region = ink[y0:y1, x0:x1].astype(np.uint8)
    vert = cv2.morphologyEx(
        region, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, k))
    )
    cols = np.flatnonzero(vert.any(axis=0))
    if cols.size == 0:
        return []
    runs = np.split(cols, np.flatnonzero(np.diff(cols) > 1) + 1)
    out = []
    for r in runs:
        if len(r) > max(3, 0.25 * s):
            continue
        rows = np.flatnonzero(vert[:, r[0] : r[-1] + 1].any(axis=1))
        out.append((float(r.mean()) + x0, (rows[-1] - rows[0] + 1) / s))
    return out


@dataclass
class BeatMarks:
    stem: bool = False
    stem_top: float = 0.0  # in s below the bottom line
    stem_len: float = 0.0  # in s
    beams: int = 0
    beam_conf: float = 0.0  # share of beside-stem columns that agree with `beams`
    dot: bool = False
    tuplet: int | None = None


def _runs(col: np.ndarray) -> int:
    col = col.astype(np.int8)
    return int(np.count_nonzero(np.diff(np.concatenate([[0], col])) == 1))


def _stem_near(vert: np.ndarray, x: float, s: float) -> tuple[int, int] | None:
    """Columns [c0, c1) of the stem run closest to x within +-0.45 s."""
    w = vert.shape[1]
    lo, hi = max(0, int(x - 0.45 * s)), min(w, int(x + 0.45 * s) + 1)
    cols = np.flatnonzero(vert[:, lo:hi].any(axis=0)) + lo
    if cols.size == 0:
        return None
    runs = np.split(cols, np.flatnonzero(np.diff(cols) > 1) + 1)
    run = min(runs, key=lambda r: abs(r.mean() - x))
    if len(run) > max(3, 0.25 * s):  # too thick for a stem
        return None
    return int(run[0]), int(run[-1]) + 1


def _count_beams(ink: np.ndarray, c0: int, c1: int, top: int, bottom: int, s: float):
    """Beams/flags crossing the columns beside the stem, near the stem's end."""
    h, w = ink.shape
    r0, r1 = max(0, int(bottom - 1.1 * s)), min(h, bottom + 2)
    r0 = max(r0, top + 1)
    best = (0, 0.0)
    for a, b in ((c0 - int(0.45 * s), c0 - 2), (c1 + 2, c1 + int(0.45 * s))):
        a, b = max(0, a), min(w, b)
        if b - a < 2:
            continue
        counts = [_runs(ink[r0:r1, c]) for c in range(a, b)]
        vals, freq = np.unique(counts, return_counts=True)
        k = int(vals[np.argmax(freq)])
        conf = float(freq.max() / len(counts))
        if k > best[0] or (k == best[0] and conf > best[1]):
            best = (k, conf)
    return best


def read_rhythm(
    ink: np.ndarray,
    staff: Staff,
    xs: list[float],
    span: tuple[int, int],
    clf: GlyphClassifier,
) -> list[BeatMarks]:
    s = staff.spacing
    base = staff.lines[-1]
    y0 = int(base + 0.25 * s)
    y1 = min(ink.shape[0], int(base + 4.5 * s))
    if y1 - y0 < 3 or not xs:
        return [BeatMarks() for _ in xs]
    region = ink[y0:y1].astype(np.uint8)
    k = max(5, int(0.5 * s))
    vert = cv2.morphologyEx(
        region, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, k))
    )
    blobs = components(region, min_area=3)
    out = []
    stems: list[tuple[int, int, int]] = []
    for x in xs:
        m = BeatMarks()
        stem = _stem_near(vert, x, s)
        if stem is not None:
            c0, c1 = stem
            rows = np.flatnonzero(vert[:, c0:c1].any(axis=1))
            runs = np.split(rows, np.flatnonzero(np.diff(rows) > 1) + 1)
            run = max(runs, key=len)
            top, bottom = int(run[0]), int(run[-1])
            if (bottom - top + 1) < MIN_STEM * s:
                out.append(m)
                continue
            m.stem = True
            m.stem_top = (top + y0 - base) / s
            m.stem_len = (bottom - top + 1) / s
            m.beams, m.beam_conf = _count_beams(region, c0, c1, top, bottom, s)
            m.dot = any(
                c1 + 0.05 * s <= b.x <= c1 + 0.9 * s
                and bottom - 0.7 * s <= b.cy <= bottom + 0.5 * s
                and 0.08 * s <= b.w <= 0.4 * s
                and 0.08 * s <= b.h <= 0.4 * s
                and b.mask.mean() > 0.5
                for b in blobs
            )
            stems.append((c0, c1, bottom))
        out.append(m)
    # tuplet numbers below the stems' ends
    if stems:
        lowest = max(b for _, _, b in stems)
        cand = [
            b
            for b in blobs
            if b.y > lowest + 0.05 * s
            and 0.3 * s <= b.h <= 1.0 * s
            and span[0] <= b.cx <= span[1]  # a tuplet number belongs to its own measure
        ]
        if cand:
            labels = clf.classify(cand, s)
            for b, (lab, conf) in zip(cand, labels, strict=True):
                if lab in ("3", "5", "6", "7") and conf > 0.6:
                    near = sorted(range(len(xs)), key=lambda i: abs(xs[i] - b.cx))[: int(lab)]
                    for i in near:
                        out[i].tuplet = int(lab)
    return out
