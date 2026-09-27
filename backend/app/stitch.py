"""Stitch step-scrolling tab pages into one strip and re-flow it by measure.

Some videos scroll the tab left in jumps, so consecutive pages overlap by about one
measure. Overlapping neighbours are aligned horizontally, joined into one long strip,
cut at bar lines and packed into lines as wide as the original page.
"""

from __future__ import annotations

import cv2
import numpy as np

from app.models import Page
from app.region import detect_staves

INK_LEVEL = 140  # darker than this is ink; white and the yellow highlight are background
MIN_SHIFT = 50
MIN_OVERLAP = 200
OVERLAP_THRESHOLD = 0.35
PEAK_EXCLUSION = 40  # px around the best shift that belong to the same peak
PEAK_MARGIN = 0.15  # best must beat any other peak by this much (real video: >= 0.33)
BAR_COVERAGE = 0.9
BAR_MERGE_GAP = 12  # px; the two strokes of a double bar line become one
BAR_MARGIN = 3  # px kept left of a bar line so each measure starts with its bar


def _gray(img: np.ndarray) -> np.ndarray:
    """Grayscale with dark ink on a light background; a dark theme is inverted."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    return 255 - gray if np.median(gray) < 128 else gray


def ink_mask(img: np.ndarray) -> np.ndarray:
    """Ink pixels without staff lines and bar lines. Staff lines match at every shift;
    bar lines match at every multiple of an even measure width. Either would make any
    two pages of the same layout look like an overlap."""
    ink = (_gray(img) < INK_LEVEL).astype(np.uint8)
    rows = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (41, 1)))
    cols = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 41)))
    return (ink & (1 - rows) & (1 - cols)).astype(bool)


def overlap_shift(a: np.ndarray, b: np.ndarray) -> tuple[int, float]:
    """Best shift s where b's left part repeats a from column s, with its IoU score.

    The score is 0.0 when another peak, more than PEAK_EXCLUSION px away, comes within
    PEAK_MARGIN of the best one: a riff repeated across a page turn matches at several
    shifts and the true one cannot be told, so such pages are not treated as overlapping.
    """
    if a.shape != b.shape:
        return 0, 0.0
    ma, mb = ink_mask(a), ink_mask(b)
    width = ma.shape[1]
    scores = []
    for s in range(MIN_SHIFT, width - MIN_OVERLAP + 1):
        x, y = ma[:, s:], mb[:, : width - s]
        union = np.count_nonzero(x | y)
        scores.append(np.count_nonzero(x & y) / union if union else 0.0)
    if not scores:
        return 0, 0.0
    best = int(np.argmax(scores))
    far = [v for i, v in enumerate(scores) if abs(i - best) > PEAK_EXCLUSION]
    if far and scores[best] - max(far) < PEAK_MARGIN:
        return MIN_SHIFT + best, 0.0
    return MIN_SHIFT + best, float(scores[best])


def find_bars(strip: np.ndarray) -> list[int]:
    """x of bar lines: columns inked over >=90% of the tab staff's height. A double or
    final bar line counts once, at its first (leftmost) column."""
    gray = _gray(strip)  # light theme, so staff detection sees the lines, not the gaps
    staves = detect_staves(gray)
    if not staves:
        return []
    staff = max(staves, key=lambda st: (len(st.lines), st.lines[0]))
    dark = gray[staff.lines[0] : staff.lines[-1] + 1] < INK_LEVEL
    cols = np.flatnonzero(dark.mean(axis=0) >= BAR_COVERAGE)
    if cols.size == 0:
        return []
    groups = np.split(cols, np.flatnonzero(np.diff(cols) > BAR_MERGE_GAP) + 1)
    return [int(g[0]) for g in groups]


def build_strip(group: list[Page], shifts: list[int]) -> tuple[np.ndarray, list[tuple]]:
    """Join a group left to right; spans record (x0, x1, start, end) per source page."""
    parts, spans, x = [], [], 0
    for page, shift in zip(group, [*shifts, None], strict=True):
        part = page.image if shift is None else page.image[:, :shift]
        parts.append(part)
        spans.append((x, x + part.shape[1], page.start, page.end))
        x += part.shape[1]
    return np.hstack(parts), spans


def line_ranges(strip_width: int, bars: list[int], width: int) -> list[tuple[int, int]]:
    """Greedy packing of measures into [x0, x1) lines no wider than `width`
    (a single wider measure gets its own line). Without bars, cut every `width` px.
    Bars within 2 * BAR_MARGIN of either end are ignored so no sliver line is made."""
    if not bars:
        return [(x, min(x + width, strip_width)) for x in range(0, strip_width, width)]
    inner = (b - BAR_MARGIN for b in bars)
    edge = 2 * BAR_MARGIN
    cuts = sorted({0, strip_width, *(c for c in inner if edge <= c <= strip_width - edge)})
    lines: list[tuple[int, int]] = []
    start, end = cuts[0], cuts[0]
    for cut in cuts[1:]:
        if cut - start > width and end > start:
            lines.append((start, end))
            start = end
        end = cut
    lines.append((start, end))
    return lines


def reflow(strip: np.ndarray, spans: list[tuple], width: int) -> list[Page]:
    pages = []
    for x0, x1 in line_ranges(strip.shape[1], find_bars(strip), width):
        covered = [s for s in spans if s[0] < x1 and s[1] > x0]
        image = strip[:, x0:x1].copy()  # narrower last lines are padded at export time
        pages.append(Page(image, min(s[2] for s in covered), max(s[3] for s in covered)))
    return pages


def stitch_pages(pages: list[Page]) -> list[Page]:
    """Replace each run of overlapping pages with measure-aligned lines; pages that do
    not overlap their neighbours (page-switching videos) pass through unchanged."""
    if not pages:
        return []
    result: list[Page] = []
    group, shifts = [pages[0]], []

    def flush() -> None:
        if len(group) == 1:
            result.append(group[0])
        else:
            strip, spans = build_strip(group, shifts)
            result.extend(reflow(strip, spans, group[0].image.shape[1]))

    for prev, cur in zip(pages, pages[1:], strict=False):
        shift, score = overlap_shift(prev.image, cur.image)
        if score >= OVERLAP_THRESHOLD:
            group.append(cur)
            shifts.append(shift)
        else:
            flush()
            group, shifts = [cur], []
    flush()
    return result
