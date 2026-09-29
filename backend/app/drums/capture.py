"""The drum notation shown in a video, as page images of whole measures, in order.

1. The score panel: a camera picture usually fills part of the frame, so the brightest
   wide band of the frame (the white panel) is cut out first; every brightness decision
   is made inside it.
2. Mode: one staff in the panel is a Guitar Pro style strip ("strip"); several stacked
   staves are pages or vertical scrolling ("pages").
3. Strip: the guitar pipeline's screen segmentation (app.segment) and median images
   (app.compose) give each stable screen. The measure being played is highlighted
   (yellow); each highlighted stretch is one played measure, cut at its bar lines, so a
   measure is taken once even when the screen jumps and repeated grooves look the same.
   Screens without a highlight fall back to all whole measures between bar lines,
   minus those repeating the end of the previous screen. The measures are then packed
   into pages as wide as the screen.
4. Pages: every staff line is tracked from frame to frame (the piano capture's approach,
   one staff per line): the same line keeps its place or moves with the others; new
   lines are new, even if they look the same as ones before a page turn.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from app.compose import median_page
from app.drums.recognize import find_lines, layout, remove_lines
from app.frames import grab_frames, probe, sample_frames
from app.models import Roi
from app.segment import SegmentParams, find_segments, prep_gray

Progress = Callable[[float], None]

BRIGHT = 170  # grey level of the panel background at least
BRIGHT_ROW = 0.8  # share of bright pixels in a row of the panel
MIN_PANEL = 0.12  # of the frame height
YELLOW_H = (12, 42)  # OpenCV hue range of a highlight
YELLOW_S = 25
YELLOW_COL = 0.3  # share of highlighted pixels in a column
SIG_SIZE = (480, 120)
SAME = 0.35  # signature mismatch below this: the same staff line / measure
RECENT = 1.5  # seconds a staff line may go unseen and still be the same one
MIN_HITS = 2
MEDIAN = 9  # frames per screen for its median image


@dataclass
class Captured:
    image: np.ndarray = field(repr=False)  # BGR
    start: float  # seconds on screen
    end: float
    measures: list[tuple[int, int]] = field(default_factory=list)  # [x0, x1) (strip)
    y: int = 0  # top row in the frame


# ------------------------------------------------------------------ panel and mode


def _longest_run(mask: np.ndarray, gap: int) -> tuple[int, int] | None:
    """[a, b) of the longest run of True, gaps up to `gap` bridged."""
    idx = np.flatnonzero(mask)
    if idx.size == 0:
        return None
    runs = np.split(idx, np.flatnonzero(np.diff(idx) > gap + 1) + 1)
    best = max(runs, key=lambda r: r[-1] - r[0])
    return int(best[0]), int(best[-1]) + 1


def panel_roi(frames: list[np.ndarray]) -> Roi:
    """The score panel: the widest band of bright rows of the median frame (staff lines
    are thin dark rows inside it). The whole frame if there is no such band (a dark
    theme or a full-screen score)."""
    gray = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) if f.ndim == 3 else f for f in frames]
    median = np.median(np.stack(gray), axis=0).astype(np.uint8)
    h, w = median.shape
    rows = (median >= BRIGHT).mean(axis=1) >= BRIGHT_ROW
    band = _longest_run(rows, max(3, h // 100))
    if band is None or band[1] - band[0] < MIN_PANEL * h:
        return Roi(0, 0, w, h)
    y0, y1 = band
    cols = (median[y0:y1] >= BRIGHT).mean(axis=0) >= BRIGHT_ROW
    span = _longest_run(cols, max(3, w // 100)) or (0, w)
    x0, x1 = span if span[1] - span[0] >= 0.3 * w else (0, w)
    return Roi(x0, y0, x1 - x0, y1 - y0)


def _staves(img: np.ndarray) -> list:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    if np.median(gray) < 128:
        gray = 255 - gray
    _, ink = cv2.threshold(gray, 0, 1, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    if ink.mean() > 0.5:
        return []
    return find_lines(gray, ink)


def choose_mode(frames: list[np.ndarray], roi: Roi) -> str | None:
    """ "strip" (one staff line in the panel), "pages" (several) or None (no staff)."""
    counts = [len(_staves(roi.crop(f))) for f in frames]
    seen = [c for c in counts if c]
    if not seen:
        return None
    return "pages" if float(np.median(seen)) >= 2 else "strip"


# ------------------------------------------------------------------ strip


def highlight_span(img: np.ndarray) -> tuple[int, int] | None:
    """[x0, x1) of the yellow highlight in a panel image, if there is one."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    yellow = (
        (hsv[..., 0] >= YELLOW_H[0])
        & (hsv[..., 0] <= YELLOW_H[1])
        & (hsv[..., 1] >= YELLOW_S)
        & (hsv[..., 2] >= BRIGHT)
    )
    cols = yellow.mean(axis=0) >= YELLOW_COL
    span = _longest_run(cols, max(6, img.shape[1] // 80))  # across the cursor
    if span is None or span[1] - span[0] < 0.03 * img.shape[1]:
        return None
    return span


def signature(img: np.ndarray, lines: list[int] | None = None, s: float = 10.0) -> np.ndarray:
    """The notation without staff lines, scaled to SIG_SIZE (0/1)."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    if lines:
        gray = gray[max(0, int(lines[0] - 3 * s)) : int(lines[-1] + 3 * s)]
    _, ink = cv2.threshold(gray, 0, 1, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    notation = remove_lines(ink, s)
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


@dataclass
class Measure:
    screen: int
    x0: int  # in the screen image
    x1: int
    start: float
    end: float
    header: bool = False  # the crop starts at the staff start (clef, time signature)
    lit: bool = False  # found by the highlight
    complete: bool = True  # bar lines found on both sides


def _snap(bars: list[float], x0: int, x1: int, s: float) -> tuple[int, int, bool]:
    """A highlight span widened to the bar lines right at its ends; whether both were
    there (the measure is whole on this screen)."""
    left = [b for b in bars if x0 - 1.0 * s <= b <= x0 + 0.6 * s]
    right = [b for b in bars if x1 - 0.6 * s <= b <= x1 + 1.0 * s and b > x0 + 2 * s]
    a = int(round(max(left))) if left else x0
    b = int(round(min(right))) if right else x1
    return a, b, bool(left and right)


def _periods(spans: list[tuple[float, tuple[int, int] | None]]) -> list:
    """Consecutive frames highlighting the same measure (their spans overlap by most of
    the shorter one): [(x0, x1, start, end)], the span from the widest sightings."""
    groups: list[list] = []
    for t, span in spans:
        if span is None:
            continue
        if groups:
            a, b = groups[-1][0][-1]
            overlap = min(b, span[1]) - max(a, span[0])
            if overlap > 0.6 * min(b - a, span[1] - span[0]):
                groups[-1][0].append(span)
                groups[-1][2] = t
                continue
        groups.append([[span], t, t])
    out = []
    for group, start, end in groups:
        widest = max(b - a for a, b in group)
        wide = [(a, b) for a, b in group if b - a >= 0.9 * widest]
        out.append(
            (int(np.median([a for a, _ in wide])), int(np.median([b for _, b in wide])), start, end)
        )
    return out


def _screen_measures(i: int, img: np.ndarray, spans, start: float, end: float) -> list[Measure]:
    lay = layout(img)
    if lay is None:
        return []
    s = lay.spacing
    periods = _periods(spans)
    if periods:
        out = []
        for x0, x1, a, b in periods:
            left, right, whole = _snap(lay.bars, x0, x1, s)
            if right - left < 2 * s:
                continue
            header = lay.header is not None and left <= lay.header + s
            out.append(Measure(i, left, right, a, b, header, True, whole or header))
        return out
    # no highlight: every whole measure between bar lines
    edges = [float(b) for b in lay.bars]
    out = []
    if lay.header is not None and edges:
        out.append(Measure(i, int(lay.x0), int(round(edges[0])), start, end, True))
    for a, b in zip(edges, edges[1:], strict=False):
        if b - a >= 2 * s:
            out.append(Measure(i, int(round(a)), int(round(b)), start, end))
    return out


def _crop(img: np.ndarray, m: Measure, last: bool) -> np.ndarray:
    x0 = 0 if m.header else max(0, m.x0 - 2)
    x1 = min(img.shape[1], m.x1 + (4 if last else -2))
    return img[:, x0:x1]


def _dedupe(screens: list[np.ndarray], measures: list[Measure], lines: dict) -> list[Measure]:
    """Take a measure seen on both sides of a screen change once.

    Highlighted: Guitar Pro may scroll in the middle of a measure, so its highlight is
    seen at the end of one screen and again (maybe cut off at the left) at the start of
    the next; together the two last about one measure. The more complete sighting is
    kept. Without a highlight: the same picture right after itself (overlapping
    screens)."""
    if not measures:
        return []
    lengths = [m.end - m.start for m in measures if m.lit and m.end > m.start]
    typical = float(np.median(lengths)) if lengths else 0.0
    kept = [measures[0]]
    for m in measures[1:]:
        prev = kept[-1]
        if prev.screen == m.screen:
            kept.append(m)
            continue
        if m.lit and prev.lit:
            same = typical > 0 and m.start - prev.end <= 1.0 and m.end - prev.start <= 1.4 * typical
        else:
            a = _crop(screens[prev.screen], prev, True)
            b = _crop(screens[m.screen], m, True)
            (la, sa), (lb, sb) = lines[prev.screen], lines[m.screen]
            same = mismatch(signature(a, la, sa), signature(b, lb, sb)) < SAME
        if not same:
            kept.append(m)
            continue
        better = (m.complete, m.x1 - m.x0) > (prev.complete, prev.x1 - prev.x0)
        merged = m if better else prev
        kept[-1] = Measure(
            merged.screen,
            merged.x0,
            merged.x1,
            prev.start,
            m.end,
            merged.header,
            merged.lit,
            merged.complete,
        )
    return kept


def _align(crop: np.ndarray, top: int, ref: int, fill) -> np.ndarray:
    """Shift a crop vertically so its top staff line sits at row `ref`."""
    dy = ref - top
    if dy == 0:
        return crop
    out = np.empty_like(crop)
    out[:] = fill
    if dy > 0:
        out[dy:] = crop[: crop.shape[0] - dy]
    else:
        out[:dy] = crop[-dy:]
    return out


def pack(screens, measures: list[Measure], lines: dict, width: int, y: int) -> list[Captured]:
    """Measures side by side, as many as fit in `width`, top staff lines level."""
    if not measures:
        return []
    ref = lines[measures[0].screen][0][0]
    fill = np.median(screens[measures[0].screen].reshape(-1, 3), axis=0).astype(np.uint8)
    pages: list[Captured] = []
    cur: list[Measure] = []

    def flush() -> None:
        parts, spans, x = [], [], 0
        for k, m in enumerate(cur):
            img = screens[m.screen]
            part = _align(_crop(img, m, k == len(cur) - 1), lines[m.screen][0][0], ref, fill)
            x0 = x + (m.x0 if m.header else 2)
            parts.append(part)
            x += part.shape[1]
            spans.append((x0, x - (4 if k == len(cur) - 1 else 0)))
        pages.append(Captured(np.hstack(parts), cur[0].start, cur[-1].end, spans, y))

    used = 0
    for m in measures:
        w = _crop(screens[m.screen], m, True).shape[1]
        if cur and used + w > width:
            flush()
            cur, used = [], 0
        cur.append(m)
        used += w
    flush()
    return pages


def _screen_images(
    video: Path, roi: Roi, segments: list, fps: float, on_progress: Callable[[int], None]
) -> list[np.ndarray | None]:
    """Each segment's median image (the cursor never wins the vote), segment by segment
    so only one segment's frames are held at a time."""
    out: list[np.ndarray | None] = [None] * len(segments)
    wanted: dict[int, int] = {}
    for k, seg in enumerate(segments):
        n = seg.end_idx - seg.start_idx + 1
        for idx in np.unique(np.linspace(seg.start_idx, seg.end_idx, min(n, MEDIAN)).round()):
            wanted[int(idx)] = k
    current, frames = None, []
    for idx, (_, img) in enumerate(sample_frames(video, fps=fps, roi=roi)):
        on_progress(idx)
        k = wanted.get(idx)
        if k is None:
            continue
        if k != current and frames:
            out[current] = median_page(frames)
            frames = []
        current = k
        frames.append(img)
    if frames:
        out[current] = median_page(frames)
    return out


def capture_strip(video: Path, roi: Roi, fps: float, progress: Progress) -> list[Captured]:
    duration = probe(video).duration
    total = max(1.0, duration * fps)
    times, grays, spans = [], [], []
    for t, img in sample_frames(video, fps=fps, roi=roi):
        times.append(t)
        grays.append(prep_gray(img))
        spans.append(highlight_span(img))
        progress(min(0.5, 0.5 * len(times) / total))
    segments = find_segments(times, grays, fps, SegmentParams())
    del grays
    images = _screen_images(
        video, roi, segments, fps, lambda i: progress(0.5 + min(0.4, 0.4 * i / total))
    )
    screens, measures, lines = [], [], {}
    for seg, image in zip(segments, images, strict=True):
        if image is None:
            continue
        i = len(screens)
        screens.append(image)
        seg_spans = [(times[k], spans[k]) for k in range(seg.start_idx, seg.end_idx + 1)]
        found = _screen_measures(i, image, seg_spans, seg.start, seg.end)
        if found:
            lay = layout(image)
            lines[i] = (lay.lines, lay.spacing)
            measures += found
    measures = _dedupe(screens, measures, lines)
    progress(1.0)
    return pack(screens, measures, lines, roi.w, roi.y)


# ------------------------------------------------------------------ pages


@dataclass
class Track:
    image: np.ndarray
    first: float
    last: float
    y: int  # crop top in the frame, last sighting
    y_first: int
    sharpness: float
    signature: np.ndarray
    hits: int = 1


def staff_lines_of(img: np.ndarray) -> list[tuple[np.ndarray, int, list[int], float]]:
    """(crop, crop top, staff lines in the crop, spacing) of every whole staff line,
    top to bottom. A line too close to the top or bottom edge may be cut off: dropped."""
    staves = _staves(img)
    h, w = img.shape[:2]
    out = []
    for k, st in enumerate(staves):
        s = st.spacing
        top, bottom = st.lines[0], st.lines[-1]
        if top - 2.5 * s < 0 or bottom + 2.5 * s >= h:
            continue
        up = (staves[k - 1].lines[-1] + top) // 2 if k else 0
        down = (bottom + staves[k + 1].lines[0]) // 2 if k + 1 < len(staves) else h
        y0 = max(up, int(top - 5 * s))
        y1 = min(down, int(bottom + 5 * s))
        x0, x1 = max(0, int(st.x0 - 3 * s)), min(w, int(st.x1 + s))
        crop = img[y0:y1, x0:x1].copy()
        out.append((crop, y0, [ln - y0 for ln in st.lines], s))
    return out


def _sharpness(img: np.ndarray) -> float:
    return float(cv2.Laplacian(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.CV_32F).var())


def capture_pages(video: Path, roi: Roi, fps: float, progress: Progress) -> list[Captured]:
    duration = probe(video).duration
    tracks: list[Track] = []
    for t, frame in sample_frames(video, fps=fps, roi=roi):
        found = staff_lines_of(frame)
        sigs = [signature(c, lines, s) for c, _, lines, s in found]
        live = [k for k, tr in enumerate(tracks) if t - tr.last <= RECENT]
        # the lines on screen move together (scrolling) or not at all: find the shift
        # most of them agree on, then match each line near its expected place
        shifts = []
        for (_, y, _, _), sig in zip(found, sigs, strict=True):
            for k in live:
                if mismatch(sig, tracks[k].signature) < SAME:
                    shifts.append(y - tracks[k].y)
        dy = int(np.median(shifts)) if shifts else 0
        taken: set[int] = set()
        for (crop, y, _lines, s), sig in zip(found, sigs, strict=True):
            best, best_score = None, SAME
            for k in live:
                if k in taken or abs(y - (tracks[k].y + dy)) > 2 * s:
                    continue
                score = mismatch(sig, tracks[k].signature)
                if score < best_score:
                    best, best_score = k, score
            sharp = _sharpness(crop)
            if best is None:
                tracks.append(Track(crop, t, t, y, y, sharp, sig))
                taken.add(len(tracks) - 1)
                continue
            tr = tracks[best]
            taken.add(best)
            tr.last, tr.y, tr.hits = t, y, tr.hits + 1
            if best_score < SAME / 2 and sharp > tr.sharpness:
                tr.image, tr.sharpness = crop, sharp
        if duration > 0:
            progress(min(1.0, t / duration))
    progress(1.0)
    kept = sorted(
        (tr for tr in tracks if tr.hits >= MIN_HITS), key=lambda tr: (tr.first, tr.y_first)
    )
    return [Captured(tr.image, tr.first, tr.last, [], tr.y_first + roi.y) for tr in kept]


# ------------------------------------------------------------------ both


def capture(
    video: Path, fps: float = 5.0, progress: Progress = lambda f: None
) -> tuple[str, list[Captured]]:
    """("strip" | "pages", the pages in order). Raises ValueError without drum notation."""
    frames = grab_frames(video, 12)
    if not frames:
        raise ValueError("视频中没有可用的画面")
    roi = panel_roi(frames)
    mode = choose_mode(frames, roi)
    if mode is None:
        raise ValueError("视频中没有找到鼓谱（五线谱）")
    if mode == "strip":
        return mode, capture_strip(video, roi, fps, progress)
    return mode, capture_pages(video, roi, fps, progress)
