"""Find whole grand-staff systems (a treble and a bass staff joined by bar lines) in a frame."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from app.region import Staff

PAD = 4.0  # staff spaces kept above and below a system for ledger notes, stems, dynamics
MAX_GAP = 12.0  # staff spaces between the two staves of one system, at most
CONNECT = 0.9  # share of the gap rows a bar line must cover to join two staves
RUN = 0.08  # a staff line is a horizontal ink run at least this share of the frame width
COVER = 0.55  # ... and its row is covered by such runs at least this much, relative to the
# best covered row (the staff lines); beams lying along a line cover less


@dataclass
class System:
    image: np.ndarray  # the crop (BGR)
    y0: int  # crop rows [y0, y1) in the frame
    y1: int
    x0: int  # crop columns [x0, x1)
    x1: int
    top: int  # top line of the treble staff, frame row
    bottom: int  # bottom line of the bass staff, frame row
    spacing: float  # staff space in pixels


def _gray(img: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    return 255 - gray if np.median(gray) < 128 else gray  # dark theme: make ink dark


def _ink(gray: np.ndarray) -> np.ndarray:
    """Pixels darker than their surroundings (thin grey lines of a video frame count)."""
    return cv2.adaptiveThreshold(gray, 1, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 10)


def find_staves(gray: np.ndarray) -> list[Staff]:
    """5-line staves, top to bottom. Staff lines are the only long horizontal ink runs
    (beams and slurs are short or slanted), so lines come from a long morphological open."""
    h, w = gray.shape
    k = max(25, int(RUN * w))
    runs = cv2.morphologyEx(
        _ink(gray), cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (k, 1))
    )
    cover = runs.mean(axis=1)
    rows = np.flatnonzero(cover >= max(0.15, COVER * cover.max()))
    if rows.size == 0:
        return []
    groups = np.split(rows, np.flatnonzero(np.diff(rows) > 1) + 1)
    lines = [float(g.mean()) for g in groups]
    staves = []
    i = 0
    while i + 5 <= len(lines):
        ys = lines[i : i + 5]
        gaps = np.diff(ys)
        if gaps.min() >= 4 and gaps.std() <= 0.15 * gaps.mean() + 0.5:
            band = [runs[g] for g in groups[i : i + 5]]
            on = np.mean([b.any(axis=0) for b in band], axis=0) >= 0.6
            cols = np.flatnonzero(on)
            if cols.size >= 0.2 * w:
                staves.append(Staff([int(round(y)) for y in ys], int(cols[0]), int(cols[-1])))
                i += 5
                continue
        i += 1
    return staves


def _joined(gray: np.ndarray, a: Staff, b: Staff) -> bool:
    """Some bar line (or the system's start line) runs from staff a down into staff b."""
    x0, x1 = max(a.x0, b.x0), min(a.x1, b.x1)
    y0, y1 = a.lines[-1] + 2, b.lines[0] - 1
    if x1 - x0 < 10 or y1 - y0 < 2:
        return False
    crop = np.ascontiguousarray(gray[y0:y1, max(0, x0 - 3) : x1 + 4])
    ink = crop < np.median(crop) - 60  # well below the background level
    return bool((ink.mean(axis=0) >= CONNECT).any())


def _pairs(gray: np.ndarray, staves: list[Staff]) -> list[tuple[Staff, Staff]]:
    """Consecutive staves forming a system: similar size, close, joined by a bar line.
    A staff whose partner is off screen stays unpaired."""
    pairs = []
    i = 0
    while i + 1 < len(staves):
        a, b = staves[i], staves[i + 1]
        s = (a.spacing + b.spacing) / 2
        gap = (b.lines[0] - a.lines[-1]) / s
        similar = abs(a.spacing - b.spacing) <= 0.15 * s + 0.5
        if similar and 1.5 <= gap <= MAX_GAP and _joined(gray, a, b):
            pairs.append((a, b))
            i += 2
        else:
            i += 1
    return pairs


def find_systems(frame: np.ndarray, pad: float = PAD) -> list[System]:
    """Whole systems, top to bottom. A system whose staves plus `pad` staff spaces above
    and below do not fit in the frame is dropped: it may be cut off."""
    gray = _gray(frame)
    h, w = gray.shape
    staves = find_staves(gray)
    pairs = _pairs(gray, staves)
    found = []
    for a, b in pairs:
        s = (a.spacing + b.spacing) / 2
        top, bottom = a.lines[0], b.lines[-1]
        need = int(round(pad * s))
        if top - need < 0 or bottom + need >= h:
            continue
        # stop halfway to a neighbouring staff so its notes stay out of the crop
        above = [st.lines[-1] for st in staves if st.lines[-1] < top]
        below = [st.lines[0] for st in staves if st.lines[0] > bottom]
        y0 = max(top - need, (top + max(above)) // 2 if above else 0)
        y1 = min(bottom + need, (bottom + min(below)) // 2 if below else h)
        x0 = max(0, int(min(a.x0, b.x0) - 3 * s))  # the brace sits left of the staves
        x1 = min(w, int(max(a.x1, b.x1) + s))
        crop = frame[y0:y1, x0:x1]
        if crop.ndim == 2:
            crop = cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR)
        found.append(System(crop.copy(), y0, y1, x0, x1, top, bottom, s))
    return found
