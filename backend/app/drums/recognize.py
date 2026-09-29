"""One image of drum notation (one or more 5-line percussion staves) → measures.

Classical CV, per staff:
- staff lines: app.piano.systems.find_staves, retried with a global (Otsu) threshold
  when dense noteheads break a line, else 5 evenly spaced dark rows of the row profile;
- x noteheads by template matching (a cross, plain and with a line through it) on the
  ink, filled and hollow heads as blobs left by a disk opening (small holes filled);
- stems and bar lines are the vertical strokes; stem direction splits the voices;
- beams/flags per stem with app.omr.rhythm._count_beams (up stems: the image flipped),
  dots, rests (shape rules), "o" rings above the staff (open hi-hat), parentheses
  (ghost notes), accents;
- per voice and measure app.omr.solve.solve_measure fits durations to the time
  signature. A voice without rests (Guitar Pro writes the pedal voice that way) takes
  its onsets from where its notes line up with the other voice instead.
- the time signature is read from the digits after the clef (app.omr.glyphs classifier).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from fractions import Fraction
from itertools import product

import cv2
import numpy as np

from app.drums.model import Beat, DrumMeasure, DrumNote, position
from app.omr import solve as omr_solve
from app.omr.glyphs import CLASSES, components, default_classifier, features, merge_pieces
from app.omr.rhythm import BeatMarks, _count_beams
from app.omr.solve import BeatEvidence, Option
from app.piano.systems import find_staves
from app.region import Staff

X_THRESHOLD = 0.75  # template match score of an x notehead
X_INK = 0.12  # ... and the share of ink around it (NCC also fires on faint noise)
TIMES = {(n, d) for n in (2, 3, 4, 5, 6, 7, 9, 12) for d in (2, 4, 8, 16)}


@dataclass
class Head:
    x: float
    y: float
    w: int
    h: int
    kind: str  # x | filled | hollow
    step: int = 0
    stem: int | None = None
    open: bool = False
    ghost: bool = False
    accent: bool = False
    circled: bool = False


@dataclass
class Stem:
    x: float
    c0: int
    c1: int
    top: int
    bottom: int
    heads: list[int] = field(default_factory=list)
    up: bool = True


@dataclass
class Rest:
    x: float
    y: float
    kind: str  # rest_1 (whole) | rest_2 (half) | rest_4 | rest_8 | rest_16
    dot: bool = False


@dataclass
class Page:
    measures: list[DrumMeasure]
    time: tuple[int, int] | None  # the time signature printed at the start, if any
    staves: int = 0
    staff_x0: float = 0.0  # where the first staff starts (px)
    header_end: float = 0.0  # where its clef / time signature end (px)


# ------------------------------------------------------------------------ helpers


def _gray(img: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    return 255 - gray if np.median(gray) < 128 else gray


def _comps(mask: np.ndarray, min_area: int = 2):
    n, lab, st, cen = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    return [(st[i], cen[i], lab == i) for i in range(1, n) if st[i][4] >= min_area]


def _disk(d: float) -> np.ndarray:
    d = max(3, int(round(d)))
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (d, d))


def _profile_staves(gray: np.ndarray) -> list[Staff]:
    """Fallback: 5 equally spaced dark rows in the row-darkness profile."""
    dark = (255 - gray.astype(np.float32)).mean(axis=1)
    dark = np.convolve(dark, [0.25, 0.5, 0.25], mode="same")
    floor = np.median(dark) + 25
    peaks = [
        y
        for y in range(1, len(dark) - 1)
        if dark[y] >= dark[y - 1] and dark[y] > dark[y + 1] and dark[y] > floor
    ]
    cands = []
    for y0 in peaks:
        for sp in np.arange(6, 31, 0.25):
            ys = [min(peaks, key=lambda p: abs(p - (y0 + k * sp))) for k in range(5)]
            if len(set(ys)) == 5 and all(abs(ys[k] - (y0 + k * sp)) <= 1.5 for k in range(5)):
                cands.append((sum(dark[y] for y in ys), ys))
    used: set[int] = set()
    out = []
    for _, ys in sorted(cands, reverse=True):
        if any(y in used for y in range(ys[0] - 3, ys[-1] + 4)):
            continue
        used.update(range(ys[0] - 3, ys[-1] + 4))
        cols = np.flatnonzero(gray[ys[2]] < 160)
        if cols.size < 0.2 * gray.shape[1]:
            continue
        out.append(Staff([int(y) for y in ys], int(cols[0]), int(cols[-1])))
    return sorted(out, key=lambda st: st.lines[0])


def find_lines(gray: np.ndarray, ink: np.ndarray) -> list[Staff]:
    """5-line staves: the piano finder, then with Otsu ink forced dark (dense heads on a
    line break the adaptive threshold's runs), then the row profile."""
    staves = [st for st in find_staves(gray) if len(st.lines) == 5]
    if not staves:
        staves = [st for st in find_staves(np.where(ink > 0, 0, gray).astype(np.uint8))]
        staves = [st for st in staves if len(st.lines) == 5]
    if not staves:
        staves = _profile_staves(gray)
    return staves


# ------------------------------------------------------------------------ one staff


@dataclass
class StaffReading:
    heads: list[Head]  # kept heads
    stems: list[Stem]
    marks: list[tuple[int, float]]  # beams, confidence per stem
    stem_dot: list[bool]
    rests: list[Rest]
    bars: list[float]
    x_start: float  # where the notation starts (after the clef / time signature)
    header_end: float
    time: tuple[int, int] | None
    header: float | None = None  # end of a clef / time signature, None if there is none


def _header_end(noline: np.ndarray, L: list[float], x0: int, s: float) -> float:
    """Clef + time signature: ink chained from the staff start with gaps < 1.6 s."""
    band = noline[max(0, int(L[0] - 0.3 * s)) : int(L[4] + 0.3 * s)]
    cols = band.any(axis=0)
    x, end, gap = int(x0), int(x0), 0
    while x < min(len(cols), x0 + 12 * s):
        if cols[x]:
            end, gap = x, 0
        else:
            gap += 1
            if gap > 1.6 * s and end > x0 + 0.5 * s:
                break
        x += 1
    return end + 0.3 * s


def _clef_end(noline: np.ndarray, L: list[float], x0: float, s: float) -> float | None:
    """Right edge of a percussion clef (two thick bars around the middle line) at the
    staff start, or None."""
    lo, hi = max(0, int(x0)), min(noline.shape[1], int(x0 + 4 * s))
    top, bottom = int(L[0]), int(L[4]) + 1
    if hi - lo < 3:
        return None
    bars = [
        b
        for b in components(np.ascontiguousarray(noline[top:bottom, lo:hi]), min_area=4)
        if 1.4 * s <= b.h <= 2.6 * s
        and 0.2 * s <= b.w <= 0.8 * s
        and abs(b.cy + top - L[2]) < 0.5 * s
        and b.mask.mean() > 0.7
    ]
    bars.sort(key=lambda b: b.x)
    for a_, b_ in zip(bars, bars[1:], strict=False):
        if b_.x - (a_.x + a_.w) < 0.8 * s:
            return lo + b_.x + b_.w
    # blurred: both bars in one blob
    for b in components(np.ascontiguousarray(noline[top:bottom, lo:hi]), min_area=4):
        if (
            b.x < 2 * s
            and 1.4 * s <= b.h <= 2.6 * s
            and 0.8 * s <= b.w <= 2.2 * s
            and abs(b.cy + top - L[2]) < 0.5 * s
            and b.mask.mean() > 0.5
        ):
            return lo + b.x + b.w
    return None


def _common_time(noline: np.ndarray, L: list[float], x0: float, s: float) -> float | None:
    """Right edge of a "C" (common time) right after x0, or None."""
    lo, hi = max(0, int(x0)), min(noline.shape[1], int(x0 + 3.5 * s))
    top, bottom = max(0, int(L[0] - 0.5 * s)), int(L[4] + 0.5 * s) + 1
    if hi - lo < 3:
        return None
    for b in components(np.ascontiguousarray(noline[top:bottom, lo:hi]), min_area=4):
        if not (1.6 * s <= b.h <= 2.5 * s and 0.9 * s <= b.w <= 1.9 * s):
            continue
        if abs(b.cy + top - L[2]) > 0.4 * s:
            continue
        m = b.mask
        rows = slice(m.shape[0] // 3, m.shape[0] - m.shape[0] // 3)
        opening = m[rows, int(0.55 * m.shape[1]) :].mean()
        back = m[rows, : max(1, int(0.3 * m.shape[1]))].mean()
        if opening < 0.12 and back > 0.3:
            return lo + b.x + b.w
    return None


def _read_time(
    noline: np.ndarray, L: list[float], x0: float, x1: float, s: float
) -> tuple[tuple[int, int] | None, float]:
    """Digits stacked on the staff starting within 2.5 s after x0 (and before x1):
    ((numerator, denominator), right edge) or (None, x0). The two numbers touch at the
    middle line, so each half of the staff is read alone."""
    lo, hi = max(0, int(x0)), min(noline.shape[1], max(int(x0) + 1, int(x1)))
    mid = int(round(L[2]))
    cut = max(1, int(round(0.08 * s)))
    halves = (
        noline[max(0, int(L[0] - 0.4 * s)) : mid - cut, lo:hi],
        noline[mid + cut + 1 : int(L[4] + 0.4 * s) + 1, lo:hi],
    )
    if hi - lo < 3 or min(h.shape[0] for h in halves) < 3:
        return None, x0
    clf = default_classifier()
    options, centers, right = [], [], x0
    for half in halves:
        blobs = [
            b
            for b in components(np.ascontiguousarray(half), min_area=4)
            if 0.3 * s <= b.w <= 2.2 * s and 1.2 * s <= b.h <= 2.6 * s
        ]
        blobs = sorted(merge_pieces(blobs, 2.6 * s), key=lambda b: b.x)
        if not blobs or blobs[0].x > 2.5 * s:
            return None, x0
        group = [blobs[0]]  # the leftmost number: one digit, or two side by side
        for b in blobs[1:]:
            if b.x - (group[-1].x + group[-1].w) < 0.5 * s and len(group) < 2:
                group.append(b)
        # every reading of the number with its probability (digits only)
        # the classifier knows tab digits, about 0.7 staff spaces tall: scale to match
        like_tab = max(b.h for b in group) / 0.7
        proba = clf.proba(features(group, [like_tab] * len(group)))
        digit = [{c: float(p[CLASSES.index(c)]) for c in "0123456789"} for p in proba]
        numbers: dict[int, float] = {}
        for combo in product("0123456789", repeat=len(group)):
            p = float(np.prod([d[c] for d, c in zip(digit, combo, strict=True)]))
            numbers[int("".join(combo))] = max(numbers.get(int("".join(combo)), 0.0), p)
        options.append(numbers)
        centers.append((group[0].x + group[-1].x + group[-1].w) / 2)
        right = max(right, lo + group[-1].x + group[-1].w)
    if abs(centers[0] - centers[1]) > 0.8 * s:
        return None, x0
    best = max(TIMES, key=lambda t: options[0].get(t[0], 0.0) * options[1].get(t[1], 0.0))
    if options[0].get(best[0], 0.0) * options[1].get(best[1], 0.0) < 0.005:
        return None, x0
    return best, right


def read_header(
    noline: np.ndarray, L: list[float], x0: float, s: float
) -> tuple[tuple[int, int] | None, float | None]:
    """(time signature, where the clef / time signature end) at the staff start; the
    end is None when there is neither (a later line of a Guitar Pro strip)."""
    clef = _clef_end(noline, L, x0, s)
    if clef is None:  # a time signature comes after a clef (notes can look like digits)
        return None, None
    start = clef
    time, right = _read_time(noline, L, start, start + 6 * s, s)
    if time is not None:
        return time, right + 0.3 * s
    c = _common_time(noline, L, start, s)
    if c is not None:
        return (4, 4), c + 0.3 * s
    return None, clef + 0.3 * s


def _templates(s: float) -> list[tuple[np.ndarray, bool, int]]:
    """(template, only near a staff line, shape): 0 a cross (three sizes, plain and with
    a staff line through it), 1 a circled cross, 2 a circled slash (Guitar Pro's open
    and half-open hi-hat)."""
    out = []
    blur = 0.08 * s + 0.3
    for size in (0.9, 1.1, 1.3):
        for with_line in (False, True):
            T = int(round(size * s)) | 1
            pad = max(2, int(0.25 * s))
            tpl = np.zeros((T + 2 * pad, T + 2 * pad), np.float32)
            th = max(1, int(round(0.13 * s)))
            cv2.line(tpl, (pad, pad), (pad + T - 1, pad + T - 1), 1.0, th)
            cv2.line(tpl, (pad + T - 1, pad), (pad, pad + T - 1), 1.0, th)
            if with_line:
                c = tpl.shape[0] // 2
                cv2.line(tpl, (0, c), (tpl.shape[1] - 1, c), 1.0, max(1, int(round(0.1 * s))))
            out.append((cv2.GaussianBlur(tpl, (0, 0), blur), with_line, 0))
    for size in (0.85, 1.0, 1.15):
        for shape in (1, 2):
            r = size * s / 2
            pad = max(2, int(0.25 * s))
            n = int(2 * (r + pad)) | 1
            c = n // 2
            tpl = np.zeros((n, n), np.float32)
            th = max(1, int(round(0.12 * s)))
            cv2.circle(tpl, (c, c), int(round(r)), 1.0, th)
            d = int(round(r * 0.7))
            cv2.line(tpl, (c - d, c + d), (c + d, c - d), 1.0, th)
            if shape == 1:
                cv2.line(tpl, (c - d, c - d), (c + d, c + d), 1.0, th)
            out.append((cv2.GaussianBlur(tpl, (0, 0), blur), False, shape))
    return out


def _cross_score(src: np.ndarray, L, s: float) -> tuple[np.ndarray, np.ndarray]:
    """Best normalized cross-correlation with a drawn notehead template at every pixel,
    and which shape it was (see _templates)."""
    score = np.full(src.shape, -1.0, np.float32)
    shape = np.zeros(src.shape, np.uint8)
    near_line = np.zeros(src.shape[0], bool)
    for ly in [*L, L[0] - s, L[4] + s]:
        near_line[max(0, int(ly - 0.2 * s)) : int(ly + 0.2 * s) + 1] = True
    for tpl, line_only, kind in _templates(s):
        if src.shape[0] < tpl.shape[0] or src.shape[1] < tpl.shape[1]:
            continue
        r = cv2.matchTemplate(src, tpl, cv2.TM_CCOEFF_NORMED)
        o = tpl.shape[0] // 2
        full = np.full(src.shape, -1.0, np.float32)
        full[o : o + r.shape[0], o : o + r.shape[1]] = r
        if line_only:
            full[~near_line] = -1.0
        better = full > score
        score[better] = full[better]
        shape[better] = kind
    return score, shape


def _ring(B: np.ndarray, x: int, y: int, s: float) -> bool:
    """A closed ring around (x, y) (ink at 14 of 16 angles) with ink at its centre."""
    h, w = B.shape
    c = max(1, int(round(0.1 * s)))
    if not B[max(0, y - c) : y + c + 1, max(0, x - c) : x + c + 1].any():
        return False
    hits = 0
    for a in np.linspace(0, 2 * np.pi, 16, endpoint=False):
        for r in np.arange(0.35 * s, 0.7 * s, 1.0):
            px, py = int(round(x + r * np.cos(a))), int(round(y + r * np.sin(a)))
            if 0 <= py < h and 0 <= px < w and B[py, px]:
                hits += 1
                break
    return hits >= 14


def _x_heads(B: np.ndarray, vert: np.ndarray, noline: np.ndarray, L, s) -> list[Head]:
    """Crosses by template matching on the ink. A cross touching a filled head (a pedal
    hi-hat right under a kick) is matched again with that head taken out."""
    blur = 0.08 * s + 0.3
    src = cv2.GaussianBlur((B & (1 - vert)).astype(np.float32), (0, 0), blur)
    score, shape = _cross_score(src, L, s)
    solid = cv2.morphologyEx(noline, cv2.MORPH_OPEN, _disk(0.5 * s))
    window = np.zeros_like(solid)
    for (_x, _y, w, h, _), c, _ in _comps(solid, int(0.3 * s * s)):
        if 0.85 * s <= w <= 1.9 * s and 0.55 * s <= h <= 1.4 * s:  # a filled head
            for dy in (-1, 1):
                yc = int(c[1] + dy * s)
                window[
                    max(0, yc - int(0.3 * s)) : yc + int(0.3 * s) + 1,
                    max(0, int(c[0] - 0.4 * s)) : int(c[0] + 0.4 * s) + 1,
                ] = 1
    if window.any():
        clean = B & (1 - vert) & (1 - cv2.dilate(solid, _disk(0.15 * s)))
        again, again_shape = _cross_score(
            cv2.GaussianBlur(clean.astype(np.float32), (0, 0), blur), L, s
        )
        use = (window > 0) & (again > score)
        score[use], shape[use] = again[use], again_shape[use]
    peak = (score == cv2.dilate(score, _disk(0.8 * s))) & (score > X_THRESHOLD)
    heads = []
    r_ = int(0.5 * s)
    for yy, xx in zip(*np.nonzero(peak), strict=True):
        if solid[max(0, yy - 2) : yy + 3, max(0, xx - 2) : xx + 3].any():
            continue  # a filled head / beam / rest, not a cross
        if B[max(0, yy - r_) : yy + r_ + 1, max(0, xx - r_) : xx + r_ + 1].mean() < X_INK:
            continue
        circled = bool(shape[yy, xx] > 0)
        if circled and not _ring(B, xx, yy, s):
            continue  # a curl of a rest, a letter: not a closed ring with a crossing in it
        heads.append(Head(float(xx), float(yy), int(1.1 * s), int(s), "x", circled=circled))
    merged: list[Head] = []
    for hd in sorted(heads, key=lambda h: h.x):
        if any(abs(m.x - hd.x) < 0.6 * s and abs(m.y - hd.y) < 0.5 * s for m in merged[-4:]):
            continue
        merged.append(hd)
    return merged


def remove_lines(B: np.ndarray, s: float) -> np.ndarray:
    """Ink without the staff lines (ledger lines are short and stay); strokes crossing a
    line are kept whole."""
    hl = cv2.morphologyEx(
        B, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (int(3 * s), 1))
    )
    lt = max(2, int(round(0.3 * s)))
    thick = cv2.morphologyEx(
        hl, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, lt + 1))
    )
    lines_m = cv2.subtract(hl, cv2.dilate(thick, np.ones((3, 1), np.uint8)))
    noline = cv2.subtract(B, lines_m)
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 2 * lt + 3))
    return noline | (lines_m & cv2.morphologyEx(noline, cv2.MORPH_CLOSE, k))


def analyse_staff(ink: np.ndarray, st: Staff, y_lo: int, y_hi: int) -> StaffReading:
    s = st.spacing
    B = ink[y_lo:y_hi].copy()
    H, W = B.shape
    L = [ln - y_lo for ln in st.lines]
    noline = remove_lines(B, s)
    vert = cv2.morphologyEx(
        noline, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, int(1.5 * s)))
    )
    time, zone = read_header(noline, L, st.x0, s)
    heads = _x_heads(B, vert, noline, L, s)
    # filled / hollow heads: fill small holes, open with a disk
    holes = np.zeros_like(noline)
    for (x, y, w, h, a), _, m in _comps((1 - noline).astype(np.uint8), 1):
        if (
            x > 0
            and y > 0
            and x + w < W
            and y + h < H
            and a < 1.2 * s * s
            and w < 1.3 * s
            and 0.2 * s <= h < 1.1 * s
            and w / max(h, 1) < 2.5
        ):
            holes[m] = 1
    blobs = cv2.morphologyEx(noline | holes, cv2.MORPH_OPEN, _disk(0.62 * s))
    rings: list[tuple[float, float]] = []
    found = _comps(blobs, int(0.3 * s * s))
    extra = []
    for (_x, _y, w, h, _a), _c, m in found:
        if w > 1.9 * s and h <= 2.4 * s:  # a head touching a rest / another head
            sub = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_OPEN, _disk(0.85 * s))
            for (x2, y2, w2, h2, a2), c2, m2 in _comps(sub, int(0.3 * s * s)):
                extra.append(((x2, y2, max(w2, int(1.1 * s)), h2, a2), c2, m2))
    for (x, y, w, h, _), c, _ in found + extra:
        if not (0.85 * s <= w <= 1.9 * s and 0.55 * s <= h <= 2.4 * s):
            continue
        n = max(1, int(round(h / s)))  # heads a second apart touch: split
        for i in range(n):
            cy = y + (i + 0.5) * h / n
            if any(abs(hd.x - c[0]) < 0.7 * s and abs(hd.y - cy) < 0.6 * s for hd in heads):
                continue  # circle-x etc: the cross wins
            share = holes[int(cy - 0.5 * h / n) : int(cy + 0.5 * h / n), x : x + w].mean()
            kind = "hollow" if share > 0.12 else "filled"
            step = int(round((L[4] - cy) / (s / 2)))
            if kind == "filled" and not (-2 <= step <= 8):
                continue  # no drum sits there with a normal head: beam / text
            if kind == "hollow" and (w < 1.05 * s or cy < L[0] - 1.6 * s):
                rings.append((float(c[0]), float(cy)))
                continue  # an "o" (open) mark, not a head
            heads.append(Head(float(c[0]), float(cy), int(w), int(h / n), kind))
    if zone is not None:  # nothing in the clef / time signature is a note
        heads = [hd for hd in heads if hd.x > zone]
    for hd in heads:
        hd.step = int(round((L[4] - hd.y) / (s / 2)))
    # stems and bar lines
    stems: list[Stem] = []
    bars: list[float] = []
    for (x, y, w, h, _), c, _ in _comps(vert, int(1.5 * s)):
        spans = abs(y - L[0]) < 0.4 * s and abs(y + h - 1 - L[4]) < 0.4 * s
        if w > max(4, 0.35 * s):
            if spans and w < 0.9 * s:
                bars.append(float(c[0]))  # thick final bar
            continue
        if spans:
            bars.append(float(c[0]))
            continue
        if zone is None or c[0] > zone:
            stems.append(Stem(float(c[0]), int(x), int(x + w), int(y), int(y + h - 1)))

    # a stem from the first space up to the top line spans the staff like a bar line,
    # but it has a notehead at its end
    def has_head(x: float) -> bool:
        """A head at the bar's lower end on its left (up stem) or upper end on its right."""
        for hd in heads:
            if hd.kind != "filled":
                continue
            left = 0 < x - hd.x and abs(x - hd.x - hd.w / 2) < 0.3 * s
            right = 0 < hd.x - x and abs(hd.x - x - hd.w / 2) < 0.3 * s
            if (left and abs(hd.y - L[4]) < 0.7 * s) or (right and abs(hd.y - L[0]) < 0.7 * s):
                return True
        return False

    for b in [b for b in bars if has_head(b)]:
        bars.remove(b)
        cols = np.flatnonzero(vert[:, int(b)])
        stems.append(Stem(b, int(b), int(b) + 1, int(cols.min()), int(cols.max())))
    # a bar line crossing a staff line looks like a cross to the template
    heads = [hd for hd in heads if hd.kind != "x" or all(abs(hd.x - b) > 0.5 * s for b in bars)]
    merged_bars: list[float] = []
    for b in sorted(bars):
        if merged_bars and b - merged_bars[-1] < 1.2 * s:
            merged_bars[-1] = max(merged_bars[-1], b)
        else:
            merged_bars.append(b)
    bars = merged_bars
    # heads -> stems; a stem without heads is dropped
    for i, hd in enumerate(heads):
        best, bd = None, 1e9
        for j, sm in enumerate(stems):
            dx = min(abs(sm.x - (hd.x + hd.w / 2)), abs(sm.x - (hd.x - hd.w / 2)))
            if dx > 0.45 * s or not (sm.top - 0.7 * s <= hd.y <= sm.bottom + 0.7 * s):
                continue
            if dx < bd:
                best, bd = j, dx
        if best is not None:
            hd.stem = best
            stems[best].heads.append(i)
    stems = [sm for sm in stems if sm.heads]
    for j, sm in enumerate(stems):
        for i in sm.heads:
            heads[i].stem = j
        sm.up = float(np.mean([heads[i].y for i in sm.heads])) > (sm.top + sm.bottom) / 2
    for hd in heads:
        if hd.stem is not None and all(hd is not heads[i] for i in stems[hd.stem].heads):
            hd.stem = None
    # beams per stem (flip for up stems so the far end is at the bottom)
    flipped = noline[::-1].copy()
    marks = []
    for sm in stems:
        if sm.up:
            marks.append(_count_beams(flipped, sm.c0, sm.c1, H - 1 - sm.bottom, H - 1 - sm.top, s))
        else:
            marks.append(_count_beams(noline, sm.c0, sm.c1, sm.top, sm.bottom, s))
    # dots, rings, rests, parentheses, accents from what is left
    used = np.zeros_like(noline)
    for hd in heads:
        p0 = (int(hd.x - 0.8 * s), int(hd.y - 0.65 * s))
        cv2.rectangle(used, p0, (int(hd.x + 0.8 * s), int(hd.y + 0.65 * s)), 1, -1)
    for sm in stems:
        used[sm.top : sm.bottom + 1, max(0, sm.c0 - 1) : sm.c1 + 1] = 1
    for b in bars:
        used[:, max(0, int(b - 0.3 * s)) : int(b + 0.3 * s)] = 1
    beams = cv2.morphologyEx(
        noline,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (int(1.8 * s), max(2, int(0.25 * s)))),
    )
    rest_src = (
        noline
        & (1 - cv2.dilate(used, np.ones((3, 3), np.uint8)))
        & (1 - cv2.dilate(beams, _disk(0.25 * s)))
    )
    rest_src = cv2.morphologyEx(rest_src, cv2.MORPH_CLOSE, _disk(0.15 * s))
    if zone is not None:
        header_end = x_start = zone
    else:
        header_end = x_start = _header_end(noline, L, st.x0, s)
        if stems:
            x_start = min(x_start, min(sm.x for sm in stems) - 1.5 * s)
    rests: list[Rest] = []
    dots: list[tuple[float, float]] = []
    _, own, own_st, _ = cv2.connectedComponentsWithStats(noline.astype(np.uint8), connectivity=8)
    for (x, y, w, h, a), c, m in _comps(rest_src, 3):
        ws, hs = w / s, h / s
        fill = a / max(1, w * h)
        cx, cy = float(c[0]), float(c[1])
        if cx < x_start:
            continue
        if ws <= 0.55 and hs <= 0.55 and fill > 0.5:
            # a dot is a small round blob on its own, not a piece cut off something
            k = own[int(round(cy)), int(round(cx))] if own[int(round(cy)), int(round(cx))] else 0
            alone = k > 0 and max(own_st[k][2], own_st[k][3]) <= 0.6 * s
            if alone and 0.6 <= w / max(h, 1) <= 1.7 and min(ws, hs) >= 0.15:
                dots.append((cx, cy))
            continue
        if 0.3 <= ws <= 1.0 and 0.3 <= hs <= 1.0 and y + h < L[0] - 0.5 * s and fill < 0.75:
            rings.append((cx, cy))  # an "o" above the staff (open hi-hat)
            continue
        near = [hd for hd in heads if abs(hd.x - cx) < 1.3 * s and abs(hd.y - cy) < 0.9 * s]
        if near and ws <= 0.6 and 0.8 <= hs <= 2.2:
            for hd in near:  # a parenthesis next to a head: a ghost note
                if abs(hd.y - cy) < 0.5 * s:
                    hd.ghost = True
            continue
        if not (L[0] - 1.5 * s <= cy <= L[4] + 1.5 * s):
            if 0.6 <= ws <= 1.6 and 0.3 <= hs <= 0.9 and _is_accent(m[y : y + h, x : x + w]):
                owner = min(stems, key=lambda sm: abs(sm.x - cx), default=None)
                if owner is not None and abs(owner.x - cx) < 1.2 * s:
                    for i in owner.heads:
                        heads[i].accent = True
            continue
        if 0.7 <= ws <= 1.6 and 0.3 <= hs <= 0.8 and fill > 0.7:
            # a whole rest hangs from a line, a half rest sits on one
            top_d = min(abs(y - ln) for ln in L)
            bot_d = min(abs(y + h - ln) for ln in L)
            rests.append(Rest(cx, cy, "rest_1" if top_d < bot_d else "rest_2"))
        elif near:
            continue  # other marks around a head
        elif any(abs(x - sm.x) < 0.4 * s and y < sm.bottom and y + h > sm.top for sm in stems):
            continue  # a flag hanging from a stem
        elif 0.5 <= ws <= 1.4 and 2.0 <= hs <= 3.6:
            rests.append(Rest(cx, cy, "rest_4" if fill >= 0.34 else "rest_16"))
        elif 0.5 <= ws <= 1.3 and 1.2 <= hs < 2.0:
            rests.append(Rest(cx, cy, "rest_8"))
    for r in rests:
        r.dot = any(0.3 * s < dx - r.x < 1.6 * s and abs(dy - r.y) < 1.2 * s for dx, dy in dots)
    for hd in heads:
        if hd.kind == "x":
            hd.open = any(abs(rx - hd.x) < 0.8 * s and ry < hd.y for rx, ry in rings)
    stem_dot = []
    for sm in stems:
        hs_ = [heads[i] for i in sm.heads]
        right = max(h_.x + h_.w / 2 for h_ in hs_)
        stem_dot.append(
            any(
                0 < dx - right < 1.3 * s and any(abs(dy - h_.y) < 0.7 * s for h_ in hs_)
                for dx, dy in dots
            )
        )
    keep = [hd for hd in heads if hd.stem is not None or hd.kind == "hollow"]
    # stems refer to heads by index: keep the full list, mark the dropped ones
    for hd in heads:
        if hd not in keep:
            hd.kind = "dropped"
    return StaffReading(heads, stems, marks, stem_dot, rests, bars, x_start, header_end, time, zone)


def _is_accent(mask: np.ndarray) -> bool:
    """A ">": ink along both diagonals meeting at the right, open at the left middle."""
    h, w = mask.shape
    if h < 3 or w < 4:
        return False
    left_mid = mask[h // 3 : h - h // 3, : max(1, w // 3)].mean()
    right_mid = mask[h // 3 : h - h // 3, w - max(1, w // 3) :].mean()
    corners = (
        mask[: max(1, h // 3), : max(1, w // 3)].mean()
        + mask[h - max(1, h // 3) :, : max(1, w // 3)].mean()
    )
    return right_mid > 0.2 and corners > 0.3 and left_mid < right_mid


# ------------------------------------------------------------------------ durations


def _candidates(ev: BeatEvidence) -> list[Option]:
    """omr.solve's candidates, but a dot next to a rest makes the dotted value likely."""
    opts = omr_solve.candidates(ev)
    if ev.rest_kind and ev.marks.dot:
        opts = [Option(o.duration, o.dots, o.tuplet, o.p * (12.0 if o.dots else 0.1)) for o in opts]
    return opts


def _solve(evidence: list[BeatEvidence], cap: Fraction) -> tuple[list[Option], bool]:
    original = omr_solve.candidates
    if not any(ev.rest_kind and ev.marks.dot for ev in evidence):
        return omr_solve.solve_measure(evidence, cap)
    # the dotted-rest preference: same DP, other candidate list
    cands = [sorted(_candidates(ev), key=lambda o: -o.p) for ev in evidence]
    states: list[dict] = [dict() for _ in range(len(cands) + 1)]
    states[0][Fraction(0)] = (0.0, [])
    for i, opts in enumerate(cands):
        for total, (lp, chosen) in states[i].items():
            for o in opts:
                t = total + o.length()
                if t <= cap:
                    v = lp + math.log(o.p)
                    if t not in states[i + 1] or states[i + 1][t][0] < v:
                        states[i + 1][t] = (v, [*chosen, o])
    del original
    if cap in states[-1]:
        return states[-1][cap][1], True
    return [opts[0] for opts in cands], False


@dataclass
class Event:
    x: float
    notes: list[DrumNote]
    evidence: BeatEvidence
    rest: bool = False


def _grid(onsets: list[Fraction]) -> Fraction:
    """The finest grid the other voice uses (16ths at least)."""
    g = Fraction(1, 16)
    for o in onsets:
        if o.denominator > g.denominator:
            g = Fraction(1, o.denominator)
    return g


def _aligned(
    events: list[Event], anchors: list[tuple[float, Fraction]], cap: Fraction, s: float
) -> tuple[list[Fraction], bool]:
    """Onsets from lining up with the other voice: the onset of its beat at (nearly) the
    same x, else interpolated between its neighbours and snapped to its grid. Also
    whether every event sat right on one of its beats."""
    grid = _grid([o for _, o in anchors])
    out, exact = [], True
    for e in events:
        near = min(anchors, key=lambda a: abs(a[0] - e.x))
        if abs(near[0] - e.x) <= 0.9 * s:
            out.append(near[1])
            continue
        exact = False
        left = max((a for a in anchors if a[0] < e.x), key=lambda a: a[0], default=None)
        right = min((a for a in anchors if a[0] > e.x), key=lambda a: a[0], default=None)
        if left is None or right is None:
            out.append(near[1])
            continue
        f = (e.x - left[0]) / max(1e-6, right[0] - left[0])
        t = left[1] + (right[1] - left[1]) * Fraction(f).limit_denominator(64)
        out.append(min(cap - grid, max(Fraction(0), round(t / grid) * grid)))
    return out, exact


def _beats(events: list[Event], chosen: list[Option], onsets: list[Fraction]) -> list[Beat]:
    return [
        Beat(on, o.duration, o.dots, o.tuplet, e.rest, e.notes)
        for e, o, on in zip(events, chosen, onsets, strict=True)
    ]


def _sequential(chosen: list[Option]) -> list[Fraction]:
    t, out = Fraction(0), []
    for o in chosen:
        out.append(t)
        t += o.length()
    return out


def build_measure(
    voices: dict[int, list[Event]], cap: Fraction, bar_x: float, s: float, time
) -> DrumMeasure:
    solved = {}
    for v, evs in voices.items():
        evs.sort(key=lambda e: e.x)
        if evs:
            chosen, ok = _solve([e.evidence for e in evs], cap)
            solved[v] = (chosen, ok, _sequential(chosen))
    out_voices: list[list[Beat]] = [[], []]
    ok_all = True
    for v in (1, 2):
        if v not in solved:
            continue
        evs = voices[v]
        chosen, ok, onsets = solved[v]
        other = solved.get(3 - v)
        no_rests = not any(e.rest for e in evs)
        if other is not None and other[1] and (no_rests or not ok):
            # Guitar Pro leaves the rests out of the pedal voice, so adding up its
            # durations cannot place it; where it lines up with the other voice, use that
            anchors = [(e.x, on) for e, on in zip(voices[3 - v], other[2], strict=True)]
            anchors.append((bar_x, cap))
            aligned, exact = _aligned(evs, anchors, cap, s)
            if (exact or not ok) and aligned != onsets:
                onsets = aligned
                ok = exact and all(a < b for a, b in zip(aligned, aligned[1:], strict=False))
        ok_all &= ok
        out_voices[v - 1] = _beats(evs, chosen, onsets)
    return DrumMeasure(out_voices, ok_all, time)


# ------------------------------------------------------------------------ the page


def _note(hd: Head) -> DrumNote:
    step, octave = position(hd.step)
    head = {"x": "circle-x" if hd.circled else "x", "filled": "normal", "hollow": "hollow"}
    return DrumNote(step, octave, head[hd.kind], hd.accent, hd.ghost, hd.open)


@dataclass
class Layout:
    """Where things are on one staff line: for the capture step."""

    lines: list[int]  # the 5 staff line rows
    spacing: float
    x0: int  # staff start / end
    x1: int
    bars: list[float]
    header: float | None  # end of the clef / time signature, None if there is none


def layout(img: np.ndarray) -> Layout | None:
    """The widest staff of an image, its bar lines and its header."""
    gray = _gray(img)
    _, ink = cv2.threshold(gray, 0, 1, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    if ink.mean() > 0.5:
        return None
    staves = find_lines(gray, ink)
    if not staves:
        return None
    st = max(staves, key=lambda st: st.x1 - st.x0)
    s = st.spacing
    y_lo, y_hi = max(0, int(st.lines[0] - 5 * s)), min(ink.shape[0], int(st.lines[-1] + 5 * s))
    r = analyse_staff(ink, st, y_lo, y_hi)
    return Layout(list(st.lines), s, st.x0, st.x1, r.bars, r.header)


def recognize(img: np.ndarray, time: tuple[int, int] | None = None) -> Page:
    """All measures of all staves, top to bottom. `time` (if given) is used to solve the
    durations; otherwise the printed time signature, else 4/4."""
    gray = _gray(img)
    _, ink = cv2.threshold(gray, 0, 1, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    if ink.mean() > 0.5:  # nothing but noise
        return Page([], None)
    staves = find_lines(gray, ink)
    if not staves:
        return Page([], None)
    measures: list[DrumMeasure] = []
    printed = None
    first_header = (float(staves[0].x0), float(staves[0].x0))
    for si, st in enumerate(staves):
        s = st.spacing
        y_lo = (
            max(0, int(st.lines[0] - 5 * s))
            if si == 0
            else int((staves[si - 1].lines[-1] + st.lines[0]) / 2)
        )
        y_hi = (
            min(ink.shape[0], int(st.lines[-1] + 5 * s))
            if si == len(staves) - 1
            else int((st.lines[-1] + staves[si + 1].lines[0]) / 2)
        )
        r = analyse_staff(ink, st, y_lo, y_hi)
        if si == 0:
            printed = r.time
            first_header = (float(st.x0), r.header_end)
        use = time or r.time or printed or (4, 4)
        cap = Fraction(use[0], use[1])
        edges = [r.x_start] + [b for b in r.bars if b > r.x_start + s]
        if st.x1 - edges[-1] > 3 * s:
            edges.append(st.x1 + 1)
        mid = st.lines[2] - y_lo
        for a, b in zip(edges[:-1], edges[1:], strict=True):
            voices: dict[int, list[Event]] = {1: [], 2: []}
            for j, sm in enumerate(r.stems):
                if not a <= sm.x < b:
                    continue
                hs_ = [r.heads[i] for i in sm.heads if r.heads[i].kind != "dropped"]
                if not hs_:
                    continue
                k_, conf = r.marks[j]
                ev = BeatEvidence(
                    BeatMarks(stem=True, beams=k_, beam_conf=conf, dot=r.stem_dot[j]),
                    circled=any(h_.kind == "hollow" for h_ in hs_),
                )
                x = float(np.mean([h_.x for h_ in hs_]))
                notes = [_note(h_) for h_ in sorted(hs_, key=lambda h_: -h_.step)]
                voices[1 if sm.up else 2].append(Event(x, notes, ev))
            for hd in r.heads:
                if hd.stem is None and hd.kind == "hollow" and a <= hd.x < b:  # whole note
                    v = 2 if hd.step <= 1 else 1
                    voices[v].append(
                        Event(hd.x, [_note(hd)], BeatEvidence(BeatMarks(), circled=True))
                    )
            for rs in r.rests:
                if a <= rs.x < b:
                    v = 1 if rs.y < mid else 2
                    kind = "rest_block" if rs.kind in ("rest_1", "rest_2") else rs.kind
                    dot = rs.dot and rs.kind != "rest_1"
                    ev = BeatEvidence(BeatMarks(dot=dot), rest_kind=kind)
                    voices[v].append(Event(rs.x, [], ev, rest=True))
            if not voices[1] and not voices[2]:
                continue
            measures.append(build_measure(voices, cap, b, s, use))
    return Page(measures, printed, len(staves), first_header[0], first_header[1])
