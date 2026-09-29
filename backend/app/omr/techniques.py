"""Playing techniques drawn around the tab numbers: marks, never notes.

Everything is geometric and measured in the staff spacing `s`; text ("P.M.", "H", "P",
"full", "1/2", "sl.") is read by its shape (letters, dots, baseline) rather than by
font, and only supports the geometric cue it belongs to.

- palm mute: "P.M." (letter, dot, wider letter, dot) above the staff, centered on the
  first muted beat, optionally followed by dashes and a closing tick at the last one;
- staccato: a lone round dot above the staff over a beat;
- hammer-on / pull-off: a lone "H" or "P" above the staff between two notes of one
  string, or an arc from a note to the next note of its string with another fret (an arc
  to the same fret is a tie);
- bend: a thin stroke rising from beside a number to above the staff (the arrow), with
  its label above: a word ("full") is a whole tone, a stacked fraction a half, a digit
  before the fraction adds whole tones;
- slide: a short diagonal on a string: between two numbers it slides out of the first
  (legato when "sl." is written above, else a shift slide), before a number with none just
  left of it it slides in, after a number with none just right of it it slides out;
- harmonic: a number in angle brackets: the fret itself (natural harmonic) or a smaller
  number right of a fret (artificial harmonic, drawn as fret + harmonic fret);
- vibrato: a wavy line above the staff over a beat.

Fret objects get technique fields in their `tech` dict (named as on model.Note); beat
groups get beat-level marks (palm_mute, staccato) in their `marks` dict.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from app.omr.glyphs import DIGITS, Blob, components, union

# ---------------------------------------------------------------- shapes


def is_dot(b: Blob, s: float) -> bool:
    return (
        0.1 * s <= b.w <= 0.42 * s
        and 0.1 * s <= b.h <= 0.42 * s
        and abs(b.w - b.h) <= 0.15 * s + 1
        and b.mask.mean() >= 0.5
    )


def is_dash(b: Blob, s: float) -> bool:
    return 0.15 * s <= b.w <= 0.8 * s and b.h <= 0.22 * s + 1 and b.w >= 2 * b.h


def is_tick(b: Blob, s: float) -> bool:
    return 0.35 * s <= b.h <= 1.1 * s and b.w <= 0.2 * s + 1 and b.mask.mean() >= 0.7


def is_letter(b: Blob, s: float) -> bool:
    return 0.3 * s <= b.h <= 1.2 * s and 0.2 * s <= b.w <= 1.4 * s and not is_tick(b, s)


def holes(mask: np.ndarray) -> list[tuple[float, float, int]]:
    """(cx, cy, area) of the enclosed background regions of a glyph mask."""
    m = np.pad(mask.astype(np.uint8), 1)
    n, labels, stats, cents = cv2.connectedComponentsWithStats(1 - m, connectivity=4)
    out = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if x == 0 or y == 0 or x + w == m.shape[1] or y + h == m.shape[0]:
            continue  # the outside
        if area >= 2:
            out.append((float(cents[i][0]) - 1, float(cents[i][1]) - 1, int(area)))
    return out


def letter_kind(b: Blob) -> str | None:
    """'H', 'P' or None, by topology: P has one loop in its upper half and a stem on the
    left below it; H has no loop, two full-height sides and a crossbar in the middle."""
    m = b.mask
    h, w = m.shape
    if h < 5 or w < 3:
        return None
    hs = holes(m)
    bottom = m[int(0.7 * h) :]
    left, right = bottom[:, : max(1, w // 2)], bottom[:, w // 2 :]
    if len(hs) == 1:
        cx, cy, _ = hs[0]
        if cy < 0.55 * h and left.any() and right.mean() < 0.25 * max(left.mean(), 1e-6):
            return "P"
        return None
    if hs:
        return None
    side = max(1, int(round(0.3 * w)))
    sides = m[:, :side].any(axis=1).mean() >= 0.85 and m[:, w - side :].any(axis=1).mean() >= 0.85
    # the centre columns hold only the crossbar (serifs stop short of the centre)
    mid = m[:, max(0, w // 2 - 1) : w // 2 + 1]
    rows = np.flatnonzero(mid.any(axis=1))
    if not sides or rows.size == 0:
        return None
    crossbar = rows[0] >= 0.25 * h and rows[-1] <= 0.75 * h and rows[-1] - rows[0] <= 0.35 * h
    return "H" if crossbar else None


def slant(b: Blob) -> float:
    """Correlation of the ink's x and y: > 0 for "\\", < 0 for "/" (y grows downward)."""
    ys, xs = np.nonzero(b.mask)
    if xs.size < 3 or xs.std() == 0 or ys.std() == 0:
        return 0.0
    return float(np.corrcoef(xs, ys)[0, 1])


def bow(b: Blob) -> float:
    """Largest distance of the stroke's centre line from a straight line, over its height
    (a slide is straight; a piece of a tie arc is bent)."""
    m = b.mask
    cols = [c for c in range(m.shape[1]) if m[:, c].any()]
    if len(cols) < 3:
        return 0.0
    xs = np.array(cols, float)
    ys = np.array([np.flatnonzero(m[:, c]).mean() for c in cols])
    fit = np.polyval(np.polyfit(xs, ys, 1), xs)
    return float(np.abs(ys - fit).max() / max(1, b.h))


def is_diagonal(b: Blob, s: float) -> bool:
    """A slide line: a short straight stroke at about 45 degrees (the ends of tie arcs cut
    by a bar line or the image edge are flatter and bent)."""
    return (
        0.3 * s <= b.w <= 1.4 * s
        and 0.3 * s <= b.h <= 1.0 * s
        and 0.5 <= b.w / b.h <= 1.7
        and b.mask.mean() <= 0.5
        and abs(slant(b)) >= 0.9
        and bow(b) <= 0.1
    )


def chevron(b: Blob, s: float) -> str | None:
    """'<' or '>': a thin V lying on its side (its tip at mid-height on one side)."""
    if not (0.2 * s <= b.h <= 1.0 * s and 0.12 * s <= b.w <= 0.7 * s and b.mask.mean() <= 0.6):
        return None
    m = b.mask
    h, w = m.shape
    rows = [r for r in range(h) if m[r].any()]
    if len(rows) < 4:
        return None
    first = np.array([np.argmax(m[r]) for r in rows]) / max(1, w - 1)
    last = np.array([w - 1 - np.argmax(m[r][::-1]) for r in rows]) / max(1, w - 1)
    k = max(1, len(rows) // 5)
    ends, middle = slice(None, k), slice(len(rows) // 2 - k // 2, len(rows) // 2 + k // 2 + 1)
    tip_left = first[middle].min() <= 0.25 and min(first[ends].min(), first[-k:].min()) >= 0.5
    tip_right = last[middle].max() >= 0.75 and max(last[ends].max(), last[-k:].max()) <= 0.5
    if tip_left and not tip_right:
        return "<"
    if tip_right and not tip_left:
        return ">"
    return None


def is_wave(b: Blob, s: float) -> bool:
    """A vibrato line: long, low, and its centre line goes up and down several times."""
    if not (b.w >= 1.0 * s and 0.12 * s <= b.h <= 0.8 * s and b.w >= 2.5 * b.h):
        return False
    m = b.mask
    cols = [c for c in range(m.shape[1]) if m[:, c].any()]
    ys = np.array([np.flatnonzero(m[:, c]).mean() for c in cols])
    k = max(1, int(0.08 * s))
    ys = np.convolve(ys, np.ones(k) / k, mode="valid") if ys.size > k else ys
    d = np.sign(np.diff(ys))
    d = d[d != 0]
    turns = int(np.count_nonzero(np.diff(d) != 0)) if d.size else 0
    return turns >= 4 and np.ptp(ys) >= 0.08 * s


# ---------------------------------------------------------------- above the staff


@dataclass
class Run:
    """Neighbouring blobs on one text row."""

    blobs: list[Blob]

    @property
    def x0(self) -> int:
        return min(b.x for b in self.blobs)

    @property
    def x1(self) -> int:
        return max(b.x + b.w for b in self.blobs)

    @property
    def y0(self) -> int:
        return min(b.y for b in self.blobs)

    @property
    def y1(self) -> int:
        return max(b.y + b.h for b in self.blobs)

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


def text_runs(blobs: list[Blob], s: float) -> list[Run]:
    runs: list[Run] = []
    for b in sorted(blobs, key=lambda b: b.x):
        for r in runs:
            last = max(r.blobs, key=lambda o: o.x + o.w)
            gap = b.x - (last.x + last.w)
            overlap = min(r.y1, b.y + b.h) - max(r.y0, b.y)
            if gap <= 0.35 * s and overlap >= 0.3 * min(b.h, r.y1 - r.y0):
                r.blobs.append(b)
                break
        else:
            runs.append(Run([b]))
    return runs


def is_palm_mute(r: Run, s: float) -> bool:
    """ "P.M.": letter, dot, wider letter, dot, the dots on the letters' baseline. A letter
    may come in pieces (cut by a faint seam of the stitched image); specks are ignored."""
    bl = sorted((b for b in r.blobs if max(b.w, b.h) >= 0.12 * s), key=lambda b: b.x)
    if len(bl) < 4 or not is_dot(bl[-1], s):
        return False
    dots = [i for i, b in enumerate(bl) if is_dot(b, s)]
    if len(dots) != 2 or dots[1] != len(bl) - 1 or dots[0] == 0:
        return False
    first, second = bl[: dots[0]], bl[dots[0] + 1 : -1]
    if not second or not all(b.h >= 0.3 * s for b in first + second):
        return False
    p, m = Run(first), Run(second)
    if not (0.3 * s <= p.y1 - p.y0 <= 1.2 * s and 0.2 * s <= p.x1 - p.x0 <= 1.4 * s):
        return False
    base = max(p.y1, m.y1)
    on_base = all(abs(bl[i].y + bl[i].h - base) <= 0.2 * s + 1 for i in dots)
    same = abs((p.y1 - p.y0) - (m.y1 - m.y0)) <= 0.2 * s + 1
    return on_base and same and (m.x1 - m.x0) >= 1.1 * (p.x1 - p.x0)


def bend_amount(label: Run | None, s: float, digit_of) -> float:
    """Semitones from a bend label: a word ("full") = 2; a stacked fraction = 1 (½), plus 2
    per whole tone written before it ("1½" = 3); a lone digit n = 2n. No label: full."""
    if label is None:
        return 2.0
    bl = sorted(label.blobs, key=lambda b: b.x)
    bottoms = [b.y + b.h for b in bl]
    height = label.y1 - label.y0
    if max(bottoms) - min(bottoms) <= max(2, 0.15 * height):  # one baseline: a word/digit
        if len(bl) == 1:
            d = digit_of(bl[0])
            return 2.0 * d if d else 2.0
        return 2.0
    big = [b for b in bl if b.h >= 0.8 * height]
    if big and big[0].x == bl[0].x:
        d = digit_of(big[0])
        if d:
            return 2.0 * d + 1
    return 1.0


# ---------------------------------------------------------------- annotate


def _blank_frets(ink: np.ndarray, frets, s: float) -> np.ndarray:
    out = ink.copy()
    for f in frets:
        x0, x1 = int(f.x - f.w / 2 - 1), int(f.x + f.w / 2 + 2)
        y0, y1 = int(f.y - f.h / 2 - 1), int(f.y + f.h / 2 + 2)
        out[max(0, y0) : max(0, y1), max(0, x0) : max(0, x1)] = 0
    return out


def above_blobs(ink, gray, staff, frets, bars, top_limit: int) -> list[Blob]:
    """Blobs above the staff's top line, without the fret numbers on the top string and
    without the measure numbers (grey digits right beside a bar line)."""
    s = staff.spacing
    top = staff.lines[0]
    y0 = max(0, int(top_limit), int(top - 4.5 * s))
    y1 = int(top - 0.12 * s)
    if y1 - y0 < 3:
        return []
    x0, x1 = max(0, int(staff.x0 - 0.5 * s)), min(ink.shape[1], int(staff.x1 + 0.5 * s))
    region = _blank_frets(ink, frets, s)[y0:y1, x0:x1]
    out = []
    for b in components(region, min_area=2):
        b.x += x0
        b.y += y0
        near_bar = any(a - 1.2 * s <= b.cx <= a + 1.6 * s for a, _ in bars)
        pale = float(gray[b.y : b.y + b.h, b.x : b.x + b.w][b.mask].mean()) > 95
        if near_bar and b.y + b.h >= top - 1.3 * s and (pale or not is_dot(b, s)):
            continue  # a measure number
        out.append(b)
    return out


def _notes_of(groups):
    return [g for g in groups if g.frets]


def _nearest(groups, x: float, tol: float):
    cand = [g for g in groups if abs(g.x - x) <= tol]
    return min(cand, key=lambda g: abs(g.x - x)) if cand else None


def _string_frets(frets) -> dict[int, list]:
    out: dict[int, list] = {}
    for f in sorted(frets, key=lambda f: f.x):
        out.setdefault(f.string, []).append(f)
    return out


def _extent(marks: list[Blob], x: float, cy: float, s: float) -> tuple[float, list[Blob]]:
    """Right end of the dashes (and closing tick) that start near x on row cy."""
    edge, end, used = x, x, []
    for m in sorted((m for m in marks if m.x >= x - 0.2 * s), key=lambda m: m.x):
        if abs(m.cy - cy) > 0.45 * s or m.x - edge > 1.5 * s:
            break
        edge = m.x + m.w
        end = max(end, edge)
        used.append(m)
        if is_tick(m, s):
            break
    return end, used


def palm_mutes(blobs, runs, groups, staff, s) -> list[tuple[float, float]]:
    """(first beat x, last x) of every P.M. extent. An extent continued from the line
    before starts with dashes at the left end of the staff, without the text."""
    out = []
    marks = [b for b in blobs if is_dash(b, s) or is_tick(b, s)]
    taken: set[int] = set()
    for r in runs:
        if not is_palm_mute(r, s):
            continue
        start = _nearest(_notes_of(groups), r.cx, 1.2 * s)
        if start is None:
            continue
        end, used = _extent(marks, r.x1, r.cy, s)
        taken |= {id(m) for m in used}
        out.append((start.x, max(start.x, end)))
    dashes = sorted((m for m in marks if is_dash(m, s) and id(m) not in taken), key=lambda m: m.x)
    if dashes and dashes[0].x <= staff.x0 + 2.5 * s:
        end, used = _extent(marks, dashes[0].x, dashes[0].cy, s)
        if len(used) >= 2:
            out.append((staff.x0 - s, end))
    for g in groups:
        if any(a - 0.3 * s <= g.x <= b + 0.5 * s for a, b in out):
            g.marks["palm_mute"] = True
    return out


def staccato(blobs, groups, s) -> list[Blob]:
    found = []
    others = [b for b in blobs if not is_dot(b, s)]
    for d in blobs:
        if not is_dot(d, s):
            continue
        # a dot of a word ("P.M.", "sl.") sits on its letters' baseline
        if any(
            abs(o.cx - d.cx) <= 0.9 * s + o.w / 2 and o.y <= d.cy <= o.y + o.h + 0.2 * s
            for o in others
        ):
            continue
        g = _nearest(_notes_of(groups), d.cx, 0.45 * s)
        if g is not None:
            g.marks["staccato"] = True
            found.append(d)
    return found


def _pair_around(by_string, x: float, s: float, top_first: bool = True):
    """The closest pair of consecutive notes on one string with x between them."""
    best = None
    for string, fs in by_string.items():
        for a, b in zip(fs, fs[1:], strict=False):
            if a.x < x < b.x and b.x - a.x <= 12 * s:
                key = (b.x - a.x, -string if top_first else string)
                if best is None or key < best[0]:
                    best = (key, a, b)
    return (best[1], best[2]) if best else None


def _one_letter(r: Run, s: float) -> Blob | None:
    """The run as a single letter: one blob, or pieces of one (cut by a faint seam of
    the stitched image) that touch and share their top and bottom."""
    bl = sorted(r.blobs, key=lambda b: b.x)
    if len(bl) > 3:
        return None
    for a, b in zip(bl, bl[1:], strict=False):
        if b.x - (a.x + a.w) > max(1, 0.1 * s) or abs(a.y - b.y) > 1 or abs(a.h - b.h) > 2:
            return None
    u = union(bl)
    return u if is_letter(u, s) else None


def hopo_letters(runs, frets, s) -> list[tuple[str, object]]:
    by_string = _string_frets(frets)
    out = []
    for r in runs:
        letter = _one_letter(r, s)
        if letter is None:
            continue
        kind = letter_kind(letter)
        if kind is None:
            continue
        pair = _pair_around(by_string, r.cx, s)
        if pair is None:
            continue
        a, _ = pair
        a.tech["hopo"] = True
        out.append((kind, a))
    return out


def hopo_arcs(arcs, frets, s) -> list:
    """An arc from a note to the next note of its string with another fret."""
    by_string = _string_frets(frets)
    out = []
    for arc in arcs:
        if arc.h < max(3, 0.15 * s) or arc.w < 0.8 * s or bow(arc) < 0.2:
            continue  # a bit of staff line left between numbers, not a curve
        for fs in by_string.values():
            for a, b in zip(fs, fs[1:], strict=False):
                if a.fret == b.fret or b.tied or a.dead or b.dead:
                    continue
                starts = abs(arc.x - a.x) <= 0.8 * s
                ends = abs(arc.x + arc.w - b.x) <= 0.8 * s
                level = min(abs(arc.cy - a.y), abs(arc.cy - b.y)) <= 1.1 * s
                if starts and ends and level:
                    a.tech["hopo"] = True
                    out.append(a)
    return out


def slides(glyphs, used: set[int], frets, texts: list[Run], staff, s) -> list:
    """Diagonals on a string; `texts` are the word runs above the staff ("sl.")."""
    lines = staff.lines
    by_string = _string_frets(frets)
    out = []
    for g in glyphs:
        b = g.blob
        if id(g) in used or not is_diagonal(b, s):
            continue
        i = int(np.argmin([abs(b.cy - y) for y in lines]))
        if abs(b.cy - lines[i]) > 0.5 * s:
            continue
        string = len(lines) - 1 - i
        fs = by_string.get(string, [])
        left = [f for f in fs if -0.2 * s <= b.x - (f.x + f.w / 2) <= 0.6 * s]
        right = [f for f in fs if -0.2 * s <= (f.x - f.w / 2) - (b.x + b.w) <= 0.6 * s]
        down = slant(b) > 0  # "\"
        if left and right:
            a, z = left[-1], right[0]
            legato = any(t.x1 >= a.x - 0.8 * s and t.x0 <= z.x + 0.8 * s for t in texts)
            a.tech["slide"] = "legato" if legato else "shift"
            out.append(a)
        elif right:
            right[0].tech["slide_in"] = "above" if down else "below"
            out.append(right[0])
        elif left:
            left[-1].tech["slide"] = "out_down" if down else "out_up"
            out.append(left[-1])
    return out


def bends(ink, staff, frets, bars, runs, s, digit_of) -> list:
    """Arrows rising from beside a number to above the staff, with their labels."""
    top, bottom = staff.lines[0], staff.lines[-1]
    y0 = max(0, int(top - 4.5 * s))
    y1 = min(ink.shape[0], int(bottom + 0.5 * s))
    region = _blank_frets(ink, frets, s)[y0:y1].copy()
    for a, b in bars:
        region[:, max(0, a - 2) : b + 3] = 0
    joined = cv2.dilate(region, np.ones((3, 3), np.uint8))
    out = []
    for c in components(joined, min_area=8):
        c.y += y0
        if c.h < 1.0 * s or c.y > top - 0.3 * s or c.y + c.h < top - 0.5 * s:
            continue  # must rise from a string (the top one too) to above the staff
        if c.mask.mean() > 0.45 or c.w > 4.0 * s:
            continue
        ys, xs = np.nonzero(c.mask)
        low = ys.max()
        bx = float(xs[ys >= low - 1].mean()) + c.x
        by = float(low) + c.y
        cand = [
            f
            for f in frets
            if -0.3 * s <= bx - (f.x + f.w / 2) <= 3.0 * s and f.y - 1.1 * s <= by <= f.y + 0.6 * s
        ]
        if not cand:
            continue
        f = min(cand, key=lambda f: abs(by - f.y) + 0.3 * abs(bx - f.x))
        tip_x = float(xs[ys <= ys.min() + 1].mean()) + c.x
        tip_y = c.y + ys.min()
        labels = [
            r
            for r in runs
            if r.y1 <= tip_y + 0.4 * s
            and r.y1 >= tip_y - 2.0 * s
            and r.x0 - 1.0 * s <= tip_x <= r.x1 + 1.0 * s
            and not is_palm_mute(r, s)
        ]
        label = min(labels, key=lambda r: abs(r.cx - tip_x), default=None)
        f.tech["bend"] = bend_amount(label, s, digit_of)
        # a release goes back down right of the peak; a plain bend's arrow comes up from
        # the left and ends at its tip
        after = xs + c.x > tip_x + 0.35 * s
        if after.any() and ys[after].max() + c.y >= tip_y + 0.4 * c.h:
            f.tech["bend_release"] = True
        out.append((f, c, label))
    return out


def vibratos(blobs, groups, s) -> list:
    out = []
    for b in blobs:
        if not is_wave(b, s):
            continue
        g = _nearest(_notes_of(groups), b.x, 0.9 * s)
        if g is None:
            continue
        for f in g.frets:
            f.tech["vibrato"] = True
        out.append(b)
    return out


def harmonics(glyphs, frets, staff, typical_h: float):
    """Numbers in angle brackets. The bracketed number is a natural harmonic when it is
    itself the fret; a smaller one right of a fret is that fret's artificial harmonic (and
    never a note). Returns the frets without bracket contents."""
    s = staff.spacing
    marks = [(g, chevron(g.blob, s)) for g in glyphs]
    opens = [g for g, k in marks if k == "<"]
    closes = [g for g, k in marks if k == ">"]
    drop: set[int] = set()
    for o in opens:
        ob = o.blob
        cands = [
            c
            for c in closes
            if 0 < c.blob.x - (ob.x + ob.w) <= 3.0 * s and abs(c.blob.cy - ob.cy) <= 0.25 * s
        ]
        if not cands:
            continue
        cb = min(cands, key=lambda c: c.blob.x).blob
        inside = [f for f in frets if ob.x < f.x < cb.x and abs(f.y - ob.cy) <= 0.4 * s]
        full = [f for f in inside if f.h >= 0.85 * typical_h]
        if full:
            for f in full:
                f.tech["harmonic"] = "natural"
                f.tech["harmonic_fret"] = float(f.fret)
            continue
        digits = sorted(
            (
                g
                for g in glyphs
                if g.label in DIGITS
                and ob.x + ob.w <= g.blob.cx <= cb.x
                and abs(g.blob.cy - ob.cy) <= 0.4 * s
            ),
            key=lambda g: g.blob.x,
        )
        drop |= {id(f) for f in inside}
        base = [
            f
            for f in frets
            if id(f) not in drop
            and 0 <= ob.x - (f.x + f.w / 2) <= 1.5 * s
            and abs(f.y - ob.cy) <= 0.5 * s
        ]
        if not base or not digits:
            continue
        f = max(base, key=lambda f: f.x)
        shown = int("".join(g.label for g in digits))
        f.tech["harmonic"] = "artificial"
        f.tech["harmonic_fret"] = float(shown - f.fret if shown > f.fret else shown)
    return [f for f in frets if id(f) not in drop]


def annotate(ink, gray, staff, frets, groups, glyphs, used, arcs, bars, top_limit, clf) -> dict:
    """Mark the techniques of one staff on its frets and beat groups (all measures)."""
    s = staff.spacing
    blobs = above_blobs(ink, gray, staff, frets, bars, top_limit)
    runs = text_runs([b for b in blobs if b.h <= 1.3 * s and not is_wave(b, s)], s)

    def digit_of(b: Blob) -> int | None:
        lab, conf = clf.classify([b], s)[0]
        return int(lab) if lab in DIGITS and conf >= 0.5 else None

    pm = palm_mutes(blobs, runs, groups, staff, s)
    dots = staccato(blobs, groups, s)
    letters = hopo_letters(runs, frets, s)
    flat_above = [b for b in blobs if b.w >= 0.8 * s and b.h <= 0.7 * s and b.w >= 1.8 * b.h]
    flat_above = [b for b in flat_above if not is_wave(b, s) and not is_dash(b, s)]
    arced = hopo_arcs(list(arcs) + flat_above, frets, s)
    words = [r for r in runs if len(r.blobs) >= 2 and not is_palm_mute(r, s)]
    slid = slides(glyphs, used, frets, words, staff, s)
    bent = bends(ink, staff, frets, bars, runs, s, digit_of)
    vib = vibratos(blobs, groups, s)
    return {
        "palm_mute": pm,
        "staccato": dots,
        "hopo_letters": letters,
        "hopo_arcs": arced,
        "slides": slid,
        "bends": bent,
        "vibrato": vib,
    }
