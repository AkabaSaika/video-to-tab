"""Per-line recognition: staff, bars, fret numbers, rests, beats and measure numbers.

Everything is measured in units of the staff line spacing `s`, so the same rules apply
at any resolution and to any tab software.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

import cv2
import numpy as np

from app.omr import solve
from app.omr.glyphs import (
    DIGITS,
    Blob,
    GlyphClassifier,
    components,
    default_classifier,
    gray_of,
    merge_pieces,
    otsu_ink,
    staff_ink,
)
from app.omr.model import STANDARD_TUNINGS, Beat, Measure, Note, Score, Song
from app.omr.rhythm import BeatMarks, read_rhythm, stem_positions
from app.omr.solve import BeatEvidence
from app.region import Staff, detect_staves
from app.stitch import BAR_COVERAGE, BAR_MERGE_GAP, INK_LEVEL

MIN_DIGIT_CONF = 0.4
SMALL_DIGIT = 0.72  # digits smaller than this fraction of the typical height are annotations
HIDDEN_STEM = 0.95  # min stem length (in s) for a beat without a number
STRING_TOL = 0.33  # max distance (in s) from a digit's center to its string line


@dataclass
class Glyph:
    blob: Blob
    label: str
    conf: float


@dataclass
class Fret:
    x: float  # center
    y: float
    w: int
    h: int
    string: int
    fret: int
    conf: float
    circled: bool = False
    dead: bool = False


@dataclass
class LineResult:
    staff: Staff
    bars: list[int]
    measures: list[RawMeasure]
    debug: dict = field(default_factory=dict)


def staff_candidates(gray: np.ndarray) -> list[Staff]:
    """Evenly spaced staves found at several line coverages (faded or partly covered
    lines can drop below the default coverage)."""
    found = []
    for ratio in (0.4, 0.3, 0.2):
        for st in detect_staves(gray, ratio):
            gaps = np.diff(st.lines)
            if (
                len(st.lines) >= 4
                and np.std(gaps) <= 0.12 * np.mean(gaps) + 0.5
                and _lines_are_ink(gray, st)
            ):
                found.append(st)
    return found


LINE_RUN = 0.7  # min length (in s) of a horizontal ink run that counts as staff line
MIN_LINE_COVER = 0.15  # min share of a line row covered by such runs


def _lines_are_ink(gray: np.ndarray, staff: Staff) -> bool:
    """Reject 'staves' made of the gaps between real lines: detect_staves also tries the
    inverted image, where the background bands between lines can look like evenly spaced
    lines. A real line row is largely covered by long horizontal runs of ink (the line
    between numbers); the rows halfway between lines are not, even when dense chords put
    many digit strokes there, because digit strokes are short. Ink is found with a local
    threshold, so thin light-grey lines count too."""
    g = 255 - gray if np.median(gray) < 128 else gray  # dark theme: make lines dark
    s = staff.spacing
    y0 = max(0, int(staff.lines[0] - s))
    y1 = min(g.shape[0], int(staff.lines[-1] + s) + 1)
    crop = np.ascontiguousarray(g[y0:y1, staff.x0 : staff.x1 + 1])
    if crop.shape[0] < 3 or crop.shape[1] < 3:
        return False
    ink = cv2.adaptiveThreshold(crop, 1, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 10)
    k = max(9, int(round(LINE_RUN * s)))
    runs = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (k, 1)))
    cover = runs.mean(axis=1)

    def at(y: float) -> float:
        y = int(round(y)) - y0
        rows = cover[max(0, y - 1) : y + 2]
        return float(rows.max()) if rows.size else 0.0

    lines = staff.lines
    mids = [(a + b) / 2 for a, b in zip(lines, lines[1:], strict=False)]
    line_cover = min(at(y) for y in lines)
    return line_cover >= MIN_LINE_COVER and float(np.median([at(y) for y in mids])) < 0.5 * (
        line_cover
    )


def _overlap(a: Staff, b: Staff) -> bool:
    return a.lines[0] <= b.lines[-1] and b.lines[0] <= a.lines[-1]


def find_staves(gray: np.ndarray, strings: int | None = None) -> list[Staff]:
    """All tab staves of a line image, top to bottom: the verified staves with the
    requested number of lines if there are any, else those with the most lines. The
    same staff found at several coverages counts once (the most evenly spaced one)."""
    found = staff_candidates(gray)
    if not found:
        return []
    counts = {len(st.lines) for st in found}
    n = strings if strings in counts else max(counts)
    found = sorted(
        (st for st in found if len(st.lines) == n), key=lambda st: np.std(np.diff(st.lines))
    )
    kept: list[Staff] = []
    for st in found:
        if not any(_overlap(st, k) for k in kept):
            kept.append(st)
    return sorted(kept, key=lambda st: st.lines[0])


def bar_extents(gray: np.ndarray, staff: Staff) -> list[tuple[int, int]]:
    """(first, last) column of each bar line, a double or final bar counting as one
    (Guitar Pro's final bar is a thin line, a gap and a thick line)."""
    dark = gray[staff.lines[0] : staff.lines[-1] + 1] < INK_LEVEL
    cols = np.flatnonzero(dark.mean(axis=0) >= BAR_COVERAGE)
    if cols.size == 0:
        return []
    groups = np.split(cols, np.flatnonzero(np.diff(cols) > BAR_MERGE_GAP) + 1)
    return [(int(g[0]), int(g[-1])) for g in groups]


def find_bar_lines(gray: np.ndarray, staff: Staff) -> list[int]:
    """Like stitch.find_bars, but for a given staff."""
    return [a for a, _ in bar_extents(gray, staff)]


def _is_enclosure(b: Blob, others: list[Blob], s: float) -> bool:
    """A ring (circled note) around at least one other blob."""
    if b.h < 0.8 * s or b.w < 0.5 * s or b.mask.mean() > 0.45:
        return False
    inside = [
        o
        for o in others
        if o is not b
        and o.x >= b.x - 1
        and o.x + o.w <= b.x + b.w + 1
        and o.y >= b.y - 1
        and o.y + o.h <= b.y + b.h + 1
    ]
    if inside:
        return True
    # a digit touching its ring: the ring is taller than any fret number
    return b.h >= 1.1 * s and any(p.h >= 0.5 * s for p in peel_ring(b, s))


def peel_ring(ring: Blob, s: float) -> list[Blob]:
    """Blobs inside a ring once the ring itself (its outer band) is removed."""
    m = ring.mask.astype(np.uint8)
    # rings are convex; the hull is robust to small gaps left by staff-line removal
    pts = cv2.findNonZero(m)
    filled = np.zeros_like(m)
    cv2.fillConvexPoly(filled, cv2.convexHull(pts), 1)
    # erode by the ring's stroke width: leftmost run length in the middle rows
    rows = m[m.shape[0] // 4 : 3 * m.shape[0] // 4]
    runs = [
        int(np.argmin(r[np.argmax(r) :])) for r in rows if r.any() and not r[np.argmax(r) :].all()
    ]
    t = max(2, int(np.median(runs)) + 1) if runs else max(2, int(round(0.1 * s)))
    inner = cv2.erode(filled, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * t + 1, 2 * t + 1)))
    out = components(m & inner, min_area=4)
    for b in out:
        b.x += ring.x
        b.y += ring.y
    return [b for b in out if b.h >= 0.3 * s]


def staff_band(staff: Staff) -> tuple[int, int]:
    """Rows searched for fret numbers and rests."""
    s = staff.spacing
    return int(staff.lines[0] - 0.6 * s), int(staff.lines[-1] + 0.5 * s)


def _string_of(cy: float, lines: list[int], s: float) -> int | None:
    d = [abs(cy - y) for y in lines]
    i = int(np.argmin(d))
    if d[i] > STRING_TOL * s:
        return None
    return len(lines) - 1 - i


def staff_glyphs(ink: np.ndarray, staff: Staff, bars: list[tuple[int, int]], clf: GlyphClassifier):
    """Classified glyphs inside the staff band plus the enclosure (circle) blobs.
    `bars` are bar-line extents; glyphs left or right of the staff's lines (a track label
    such as "Gt.1") are not notes, because a fret number always sits on a string."""
    s = staff.spacing
    y0, y1 = staff_band(staff)
    y0, y1 = max(0, y0), min(ink.shape[0], y1)
    band = ink[y0:y1].copy()
    for a, b in bars:  # bar lines are not glyphs; blank the whole (double/final) bar
        band[:, max(0, a - 2) : b + 5] = 0
    blobs = components(band, min_area=4)
    blobs = [b for b in blobs if staff.x0 - 0.5 * s <= b.cx <= staff.x1 + 0.5 * s]
    for b in blobs:
        b.y += y0
    circles = [b for b in blobs if _is_enclosure(b, blobs, s)]
    rest = [b for b in blobs if b not in circles]
    for c in circles:  # digits touching the ring are part of the ring's blob
        rest += peel_ring(c, s)
    # ties/slurs: long and flat; bar-like: tall and thin
    rest = [b for b in rest if not (b.w > 1.3 * s and b.h < 0.6 * s)]
    rest = [b for b in rest if not (b.h > 1.6 * s and b.w < 0.25 * s)]
    rest = merge_pieces(rest, s)
    labels = clf.classify(rest, s)
    return [Glyph(b, lab, c) for b, (lab, c) in zip(rest, labels, strict=True)], circles


def _is_stem_piece(g: Glyph, digits: list[Glyph], s: float, band: tuple[int, int]) -> bool:
    """A stem drawn through the staff leaves thin, solid pieces between the lines that
    look like a "1". Such a piece touches a number above or below it, or the band edge."""
    b = g.blob
    if b.w > 0.25 * s:  # a real "1" has a flag or serifs
        return False

    def touches(o: Blob, above: bool) -> bool:
        gap = b.y - (o.y + o.h) if above else o.y - (b.y + b.h)
        return o is not b and abs(o.cx - b.cx) < 0.4 * s and -2 <= gap <= 0.25 * s

    at_edge = (b.y <= band[0] + 1 or b.y + b.h >= band[1] - 1) and b.mask.mean() > 0.8
    return at_edge or any(touches(o.blob, up) for o in digits for up in (True, False))


def frets_from_glyphs(glyphs: list[Glyph], circles: list[Blob], staff: Staff) -> list[Fret]:
    s = staff.spacing
    digits = [g for g in glyphs if g.label in (*DIGITS, "x") and g.conf >= MIN_DIGIT_CONF]
    if digits:  # annotations (harmonic frets...) and specks are smaller than fret numbers
        typical = float(np.median([g.blob.h for g in digits]))
        digits = [g for g in digits if g.blob.h >= SMALL_DIGIT * typical]
    band = staff_band(staff)
    digits = [g for g in digits if not _is_stem_piece(g, digits, s, band)]
    digits.sort(key=lambda g: g.blob.x)
    # join neighbouring digits on the same row into multi-digit numbers
    groups: list[list[Glyph]] = []
    for g in digits:
        for grp in groups:
            last = grp[-1].blob
            gap = g.blob.x - (last.x + last.w)
            if (
                -1 <= gap <= 0.3 * s
                and abs(g.blob.cy - last.cy) <= 0.25 * s
                and "x" not in (g.label, grp[-1].label)
            ):
                grp.append(g)
                break
        else:
            groups.append([g])
    frets = []
    for grp in groups:
        x0 = grp[0].blob.x
        x1 = max(g.blob.x + g.blob.w for g in grp)
        cy = float(np.mean([g.blob.cy for g in grp]))
        h = max(g.blob.h for g in grp)
        string = _string_of(cy, staff.lines, s)
        if string is None:
            continue
        dead = grp[0].label == "x"
        value = 0 if dead else int("".join(g.label for g in grp))
        conf = float(min(g.conf for g in grp))
        circled = any(c.x <= x0 and c.x + c.w >= x1 and c.y <= cy <= c.y + c.h for c in circles)
        frets.append(Fret((x0 + x1) / 2, cy, x1 - x0, h, string, value, conf, circled, dead))
    # one note per string per position: keep the more confident one
    frets.sort(key=lambda f: -f.conf)
    kept: list[Fret] = []
    for f in frets:
        if all(not (k.string == f.string and abs(k.x - f.x) < 0.5 * s) for k in kept):
            kept.append(f)
    return sorted(kept, key=lambda f: f.x)


@dataclass
class RestMark:
    x: float
    kind: str
    conf: float
    blob: Blob


def rests_from_glyphs(glyphs: list[Glyph], frets: list[Fret], staff: Staff) -> list[RestMark]:
    s = staff.spacing
    band = staff_band(staff)
    out = []
    for g in glyphs:
        if not g.label.startswith("rest") or g.conf < 0.5:
            continue
        b = g.blob
        if b.y <= band[0] or b.y + b.h >= band[1] or b.h > 2.5 * s:
            continue  # clipped by the band: part of something bigger (bend arrow, text)
        # parentheses/marks hugging a fret number are not rests
        if any(
            max(b.x - (f.x + f.w / 2), (f.x - f.w / 2) - (b.x + b.w)) < 0.35 * s
            and b.y < f.y + f.h / 2
            and b.y + b.h > f.y - f.h / 2
            for f in frets
        ):
            continue
        out.append(RestMark(g.blob.cx, g.label, g.conf, g.blob))
    return out


@dataclass
class BeatGroup:
    x: float
    frets: list[Fret]
    rest: RestMark | None = None
    hidden: bool = False  # a stem without a number: tied continuation of the previous beat


def group_beats(frets: list[Fret], rests: list[RestMark], s: float) -> list[BeatGroup]:
    widths = [f.w / max(1, len(str(f.fret))) for f in frets]
    digit_w = float(np.median(widths)) if widths else 0.5 * s
    tol = max(0.6 * digit_w, 0.25 * s)
    beats: list[BeatGroup] = []
    for f in sorted(frets, key=lambda f: f.x):
        near = beats and abs(f.x - np.median([g.x for g in beats[-1].frets])) <= tol
        if near:
            beats[-1].frets.append(f)
        else:
            beats.append(BeatGroup(f.x, [f]))
    for b in beats:
        b.x = float(np.median([f.x for f in b.frets]))
    beats += [BeatGroup(r.x, [], r) for r in rests]
    return sorted(beats, key=lambda b: b.x)


def measure_spans(bars: list[int], width: int, s: float) -> list[tuple[int, int]]:
    edges = sorted(set(bars))
    spans = []
    if not edges or edges[0] > 2 * s:
        spans.append((0, edges[0] if edges else width))
    for a, b in zip(edges, [*edges[1:], width], strict=False):
        spans.append((a, b))
    return [(a, b) for a, b in spans if b - a >= 1.5 * s]


def read_measure_number(
    gray: np.ndarray, staff: Staff, bar_x: int, clf: GlyphClassifier
) -> tuple[int | None, float]:
    """Small digits just above the top line, around the bar line."""
    s = staff.spacing
    y0 = max(0, int(staff.lines[0] - 1.0 * s))
    y1 = max(0, staff.lines[0] - 2)
    x0 = max(0, int(bar_x - 1.2 * s))
    x1 = min(gray.shape[1], int(bar_x + 1.6 * s))
    if y1 - y0 < 3 or x1 - x0 < 3:
        return None, 0.0
    blobs = components(otsu_ink(gray[y0:y1, x0:x1]), min_area=3)
    blobs = [b for b in blobs if b.h >= 0.25 * s and b.y + b.h >= (y1 - y0) - 0.5 * s]
    if not blobs or (x0 == 0 and any(b.x == 0 for b in blobs)):  # cut by the image edge
        return None, 0.0
    for b in blobs:
        b.x += x0
        b.y += y0
    blobs = merge_pieces(blobs, s)
    labels = clf.classify(blobs, s)
    items = sorted(
        [(b, lab, c) for b, (lab, c) in zip(blobs, labels, strict=True)], key=lambda t: t[0].x
    )
    # chains of adjacent glyphs; the one closest to the bar is the number
    chains: list[list] = [[items[0]]]
    for d in items[1:]:
        prev = chains[-1][-1][0]
        if d[0].x - (prev.x + prev.w) <= 0.35 * s:
            chains[-1].append(d)
        else:
            chains.append([d])

    def dist(ch):
        a = ch[0][0].x
        b = ch[-1][0].x + ch[-1][0].w
        return 0 if a <= bar_x <= b else min(abs(a - bar_x), abs(b - bar_x))

    chain = min(chains, key=dist)
    if any(lab not in DIGITS for _, lab, _ in chain):  # a digit not read: don't guess
        return None, 0.0
    return int("".join(lab for _, lab, _ in chain)), float(min(c for _, _, c in chain))


@dataclass
class RawMeasure:
    line: int
    x0: int
    x1: int
    groups: list[BeatGroup]
    marks: list[BeatMarks]
    number: int | None  # OCR'd measure number
    number_conf: float


def recognize_staff(
    gray: np.ndarray,
    staff: Staff,
    line: int = 0,
    clf: GlyphClassifier | None = None,
    numbers: bool = True,
) -> LineResult:
    """One tab staff of a line image. Measure numbers are read above the staff only when
    `numbers` is set (Guitar Pro prints them above the top staff of a system)."""
    clf = clf or default_classifier()
    s = staff.spacing
    extents = bar_extents(gray, staff)
    bars = [a for a, _ in extents]
    ink = staff_ink(gray, s, staff.lines)
    glyphs, circles = staff_glyphs(ink, staff, extents, clf)
    frets = frets_from_glyphs(glyphs, circles, staff)
    rests = rests_from_glyphs(glyphs, frets, staff)
    raw_ink = (gray < INK_LEVEL).astype(np.uint8)

    measures = []
    spans = measure_spans(bars, gray.shape[1], s)
    for i, (x0, x1) in enumerate(spans):
        mf = [f for f in frets if x0 < f.x < x1]
        mr = [r for r in rests if x0 < r.x < x1]
        if (
            i in (0, len(spans) - 1)
            and not mf
            and not mr
            and not any(x0 < g.blob.cx < x1 for g in glyphs)
        ):
            continue  # blank margin before the first or after the final bar line
        groups = group_beats(mf, mr, s)
        stems = stem_positions(raw_ink, staff, (x0, x1))
        for x, length in stems:
            # a flag's straight part is shorter than the stem it hangs from
            flag = any(abs(x - o) <= 0.8 * s and ol > length for o, ol in stems)
            real = length >= HIDDEN_STEM and not flag
            if real and all(abs(x - g.x) > 0.6 * s for g in groups):
                groups.append(BeatGroup(x, [], None, hidden=True))
        groups.sort(key=lambda g: g.x)
        marks = read_rhythm(raw_ink, staff, [g.x for g in groups], (x0, x1), clf)
        num, conf = (None, 0.0)
        if numbers and x0 in bars:
            num, conf = read_measure_number(gray, staff, x0, clf)
        measures.append(RawMeasure(line, int(x0), int(x1), groups, marks, num, conf))
    debug = {"glyphs": glyphs, "circles": circles, "frets": frets, "rests": rests}
    return LineResult(staff, bars, measures, debug)


def recognize_line(
    img: np.ndarray,
    line: int = 0,
    clf: GlyphClassifier | None = None,
    strings: int | None = None,
) -> list[LineResult]:
    """Every tab staff of one line image, top to bottom (staff k = track k)."""
    clf = clf or default_classifier()
    gray = gray_of(img)
    staves = find_staves(gray, strings)
    return [recognize_staff(gray, st, line, clf, numbers=k == 0) for k, st in enumerate(staves)]


NUMBER_JUMP = 2.5  # cost of a numbering discontinuity (missing or repeated measures)


def number_measures(raw: list[RawMeasure], min_conf: float = 0.5) -> list[int]:
    """Measure numbers in reading order, as index + offset with a piecewise-constant
    offset chosen by Viterbi: every OCR'd number votes for its offset (weighted by
    confidence), and changing the offset costs NUMBER_JUMP. A single misread, or two
    consistent misreads in a row, cannot outvote the counting of the measures around it."""
    ocr = [
        (m.number, m.number_conf)
        if m.number is not None and m.number_conf >= min_conf
        else (None, 0.0)
        for m in raw
    ]
    offsets = sorted({n - i for i, (n, _) in enumerate(ocr) if n is not None} or {1})
    if not raw:
        return []

    def emit(i: int, o: int) -> float:
        n, c = ocr[i]
        if n is None:
            return 0.0
        return c if n == i + o else -0.5 * c

    score = {o: emit(0, o) for o in offsets}
    back: list[dict[int, int]] = []
    for i in range(1, len(raw)):
        best_prev = max(score, key=score.get)
        new, ptr = {}, {}
        for o in offsets:
            stay = score[o]
            jump = score[best_prev] - NUMBER_JUMP
            new[o], ptr[o] = (stay, o) if stay >= jump else (jump, best_prev)
            new[o] += emit(i, o)
        score = new
        back.append(ptr)
    o = max(score, key=score.get)
    path = [o]
    for ptr in reversed(back):
        o = ptr[o]
        path.append(o)
    path.reverse()
    return [i + o for i, o in enumerate(path)]


def _evidence(g: BeatGroup, m: BeatMarks, typical_stem: float) -> BeatEvidence:
    short = m.stem and typical_stem > 0 and m.stem_len < 0.75 * typical_stem
    return BeatEvidence(
        m, any(f.circled for f in g.frets), g.rest.kind if g.rest else None, bool(short)
    )


def _build_track(raw: list[RawMeasure], numbers: list[int | None], strings: int) -> Score:
    stems = [k.stem_len for m in raw for k in m.marks if k.stem]
    typical = float(np.median(stems)) if stems else 0.0
    measures = []
    previous: list[Note] = []
    for m, number in zip(raw, numbers, strict=True):
        beats, evidence = [], []
        for g, mk in zip(m.groups, m.marks, strict=True):
            notes = [
                Note(f.string, f.fret, round(f.conf, 3), f.dead)
                for f in sorted(g.frets, key=lambda f: f.string)
            ]
            if g.hidden:  # tied continuation: same notes as the beat before, low confidence
                notes = [Note(n.string, n.fret, 0.3, n.dead) for n in previous]
            if notes:
                previous = notes
            beats.append(Beat(4, 0, None, g.rest is not None or not notes, notes, int(g.x)))
            evidence.append(_evidence(g, mk, typical))
        measure = Measure(number, (4, 4), beats, m.line, m.x0, m.x1)
        if not beats:  # an empty measure is a whole-measure rest
            measure.beats = [Beat(1, 0, None, True, [], (m.x0 + m.x1) // 2, 0.5)]
        else:
            ok = solve.apply(beats, evidence, measure.capacity())
            measure.confidence = 1.0 if ok else 0.3
        measures.append(measure)
    return Score(strings, STANDARD_TUNINGS.get(strings, []), None, measures)


def _shared_numbers(top: list[RawMeasure], top_numbers: list[int], other: list[RawMeasure]):
    """Numbers for another staff's measures of the same line image: its bar lines are the
    top staff's, so each measure takes the number of the top-staff measure it overlaps
    most (None when it overlaps none)."""
    out: list[int | None] = []
    for m in other:
        best, number = 0, None
        for t, n in zip(top, top_numbers, strict=True):
            ov = min(m.x1, t.x1) - max(m.x0, t.x0)
            if ov > best:
                best, number = ov, n
        out.append(number)
    return out


def track_name(k: int, count: int) -> str:
    return "Guitar" if count == 1 else f"Guitar {k + 1}"


def build_song(pages: list[list[LineResult]], strings: int) -> Song:
    """One track per staff position; `pages` holds each line image's staves top to
    bottom, all with the same number of staves. Measure numbers come from the top staff."""
    count = len(pages[0]) if pages else 0
    top = [m for page in pages for m in page[0].measures]
    top_numbers = number_measures(top)
    by_page: list[list[int]] = []
    i = 0
    for page in pages:
        by_page.append(top_numbers[i : i + len(page[0].measures)])
        i += len(page[0].measures)
    tracks = []
    for k in range(count):
        raw, numbers = [], []
        for page, nums in zip(pages, by_page, strict=True):
            raw += page[k].measures
            numbers += nums if k == 0 else _shared_numbers(page[0].measures, nums, page[k].measures)
        track = _build_track(raw, numbers, strings)
        track.name = track_name(k, count)
        tracks.append(track)
    return Song("", None, tracks)


def common_strings(images: list[np.ndarray]) -> int | None:
    """Most common line count of the staves found per image (the tab's string count)."""
    counts = Counter(
        len(staves[0].lines) for img in images if (staves := find_staves(gray_of(img)))
    )
    return counts.most_common(1)[0][0] if counts else None


def recognize_lines(
    images: list[np.ndarray],
    clf: GlyphClassifier | None = None,
    progress: Callable[[float], None] | None = None,
) -> tuple[list[list[LineResult]], int]:
    """Per line image, its staves top to bottom; plus the string count."""
    clf = clf or default_classifier()
    strings = common_strings(images)
    pages = []
    for i, img in enumerate(images):
        if staves := recognize_line(img, i, clf, strings):
            pages.append(staves)
        if progress:
            progress((i + 1) / len(images))
    return consistent_lines(pages)


def recognize_images(
    images: list[np.ndarray],
    clf: GlyphClassifier | None = None,
    progress: Callable[[float], None] | None = None,
) -> Song:
    """`progress(fraction)` is called after each image."""
    return build_song(*recognize_lines(images, clf, progress))


def consistent_lines(pages: list[list[LineResult]]) -> tuple[list[list[LineResult]], int]:
    """Keep the line images whose staves have the most common number of strings and
    whose staff count is the most common one (a line with a staff missed or extra would
    shift every track below it)."""
    counts = Counter(len(r.staff.lines) for page in pages for r in page)
    strings = counts.most_common(1)[0][0] if counts else 6
    pages = [p for p in pages if all(len(r.staff.lines) == strings for r in p)]
    sizes = Counter(len(p) for p in pages)
    size = sizes.most_common(1)[0][0] if sizes else 0
    return [p for p in pages if len(p) == size], strings
