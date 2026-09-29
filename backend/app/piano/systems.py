"""Find whole grand-staff systems (a treble and a bass staff joined by bar lines) in a frame."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from app.region import Staff

PAD = 4.0  # staff spaces kept above and below a system at least (stems, dynamics)
MARGIN = 2.0  # staff spaces between a system's staves and the frame edge, at least
REACH_GAP = 1.25  # staff spaces: blank rows that end a system's notation above/below
MAX_GAP = 12.0  # staff spaces between the two staves of one system, at most
CONNECT = 0.9  # share of the gap rows a bar line must cover to join two staves
RUN = 0.08  # a staff line is a horizontal ink run at least this share of the frame width
COVER = 0.3  # ... and its row is covered by such runs at least this much, relative to
# the best covered row nearby (the other lines; a beam lying on a line hides part of it)
MIN_COVER = 0.12  # ... and at least this share of the frame width


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
    # beams are long and horizontal too, but thick: drop anything taller than a line
    t = max(4, round(h / 216))
    thick = cv2.morphologyEx(
        runs, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, t))
    )
    runs = cv2.subtract(runs, cv2.dilate(thick, np.ones((3, 1), np.uint8)))
    cover = runs.mean(axis=1)
    size = 2 * max(8, h // 25) + 1
    near = cv2.dilate(
        cover.astype(np.float32)[:, None], cv2.getStructuringElement(cv2.MORPH_RECT, (1, size))
    )[:, 0]
    rows = np.flatnonzero((cover >= COVER * near) & (cover >= MIN_COVER))
    if rows.size == 0:
        return []
    groups = np.split(rows, np.flatnonzero(np.diff(rows) > 1) + 1)
    lines = [float(g.mean()) for g in groups]
    strength = [float(cover[g].max()) for g in groups]

    def comb(i: int, j: int) -> list[int] | None:
        """Lines i, j and three more at the same spacing (stray rows in between skipped)."""
        idx = [i, j]
        for _ in range(3):
            gap = (lines[idx[-1]] - lines[idx[0]]) / (len(idx) - 1)
            target = lines[idx[-1]] + gap
            near = min(
                range(idx[-1] + 1, len(lines)), key=lambda n: abs(lines[n] - target), default=None
            )
            if near is None or abs(lines[near] - target) > max(1.5, 0.12 * gap):
                return None
            idx.append(near)
        gaps = np.diff([lines[n] for n in idx])
        return idx if gaps.std() <= 0.15 * gaps.mean() + 0.5 else None

    candidates = []
    for i in range(len(lines)):
        for j in range(i + 1, len(lines)):
            gap = lines[j] - lines[i]
            if gap < 4:
                continue
            if gap > h / 12:
                break
            idx = comb(i, j)
            if idx is not None:
                candidates.append((min(strength[n] for n in idx), idx))
    staves: list[Staff] = []
    taken: list[tuple[float, float]] = []
    # strongest first: a staff beats a copy shifted onto a beam or ledger line next to it
    for _, idx in sorted(candidates, key=lambda c: -c[0]):
        top, bottom = lines[idx[0]], lines[idx[-1]]
        if any(top <= b and a <= bottom for a, b in taken):
            continue
        on = np.mean([runs[groups[n]].any(axis=0) for n in idx], axis=0) >= 0.6
        cols = np.flatnonzero(on)
        if cols.size < MIN_COVER * w:
            continue
        staves.append(Staff([int(round(lines[n])) for n in idx], int(cols[0]), int(cols[-1])))
        taken.append((top, bottom))
    return sorted(staves, key=lambda st: st.lines[0])


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


def _reach(rows: np.ndarray, start: int, step: int, limit: int, gap: int) -> tuple[int, bool]:
    """Follow notation rows from staff line `start` outwards (step -1 up, +1 down) until
    `gap` blank rows or `limit`. Returns the last notation row and whether the notation
    was still going on at `limit`."""
    last = start
    r = start + step
    while r != limit:
        if rows[r]:
            last = r
        elif abs(r - last) > gap:
            return last, False
        r += step
    return last, True


def find_systems(frame: np.ndarray, pad: float = PAD) -> list[System]:
    """Whole systems, top to bottom, each cropped with its notation above and below (at
    least `pad` staff spaces where there is room). A system whose notation runs into the
    frame edge, or that sits closer than MARGIN staff spaces to it, may be cut off and is
    dropped. A neighbouring system's notation is cut off halfway between the two."""
    gray = _gray(frame)
    h, w = gray.shape
    staves = find_staves(gray)
    pairs = _pairs(gray, staves)
    ink = _ink(gray)
    found = []
    for a, b in pairs:
        s = (a.spacing + b.spacing) / 2
        top, bottom = a.lines[0], b.lines[-1]
        if top - MARGIN * s < 0 or bottom + MARGIN * s >= h:
            continue
        sx0, sx1 = min(a.x0, b.x0), max(a.x1, b.x1)
        rows = (ink[:, sx0 : sx1 + 1].sum(axis=1) >= 3).astype(bool)
        above = [st.lines[-1] for st in staves if st.lines[-1] < top]
        below = [st.lines[0] for st in staves if st.lines[0] > bottom]
        up_limit = (top + max(above)) // 2 if above else -1
        down_limit = (bottom + min(below)) // 2 if below else h
        gap = int(round(REACH_GAP * s))
        first, open_up = _reach(rows, top, -1, up_limit, gap)
        last, open_down = _reach(rows, bottom, 1, down_limit, gap)
        if (open_up and not above) or (open_down and not below):
            continue  # notation runs off the frame
        margin = int(round(s / 2))
        y0 = max(up_limit + 1, min(first - margin, top - int(round(pad * s))))
        y1 = min(down_limit, max(last + margin, bottom + int(round(pad * s))) + 1)
        x0 = max(0, int(sx0 - 3 * s))  # the brace sits left of the staves
        x1 = min(w, int(sx1 + s))
        crop = frame[y0:y1, x0:x1]
        if crop.ndim == 2:
            crop = cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR)
        found.append(System(crop.copy(), y0, y1, x0, x1, top, bottom, s))
    return found
