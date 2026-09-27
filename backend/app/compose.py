from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np

from app.frames import sample_frames
from app.models import Page, Roi, Segment
from app.segment import frame_change, prep_gray

MAX_MEDIAN_FRAMES = 25
SAME_PAGE_THRESHOLD = 0.05  # frame_change below this means identical content


def median_page(frames: list[np.ndarray]) -> np.ndarray:
    """Per-pixel temporal median: a cursor that keeps moving never wins the vote."""
    stack = np.stack(frames)
    median = np.median(stack, axis=0).astype(np.uint8)
    if len(frames) >= 3:
        return median
    errors = [np.abs(f.astype(np.int16) - median).mean() for f in frames]
    return frames[int(np.argmin(errors))]


def same_content(a: np.ndarray, b: np.ndarray) -> bool:
    if a.shape != b.shape:
        return False
    return frame_change(prep_gray(a), prep_gray(b)) < SAME_PAGE_THRESHOLD


def merge_adjacent(pages: list[Page]) -> list[Page]:
    merged: list[Page] = []
    for page in pages:
        if merged and same_content(merged[-1].image, page.image):
            prev = merged[-1]
            keep = prev.image if prev.end - prev.start >= page.end - page.start else page.image
            merged[-1] = Page(keep, prev.start, page.end)
        else:
            merged.append(page)
    return merged


def mark_repeats(pages: list[Page]) -> list[Page]:
    for i, page in enumerate(pages):
        page.duplicate_of = None
        for j in range(i):
            if pages[j].duplicate_of is None and same_content(pages[j].image, page.image):
                page.duplicate_of = j
                break
    return pages


def build_pages(
    video: Path,
    roi: Roi,
    segments: list[Segment],
    fps: float,
    on_progress: Callable[[int], None] = lambda i: None,
) -> list[Page]:
    """Second decoding pass: gather ROI frames of each segment and median them."""
    wanted: dict[int, int] = {}  # sample index -> segment index
    for s_i, seg in enumerate(segments):
        n = seg.end_idx - seg.start_idx + 1
        picks = np.linspace(seg.start_idx, seg.end_idx, min(n, MAX_MEDIAN_FRAMES))
        for idx in np.unique(picks.round().astype(int)):
            wanted[int(idx)] = s_i
    buckets: list[list[np.ndarray]] = [[] for _ in segments]
    for idx, (_, img) in enumerate(sample_frames(video, fps=fps, roi=roi)):
        on_progress(idx)
        if idx in wanted:
            buckets[wanted[idx]].append(img)
    return [
        Page(median_page(frames), seg.start, seg.end)
        for seg, frames in zip(segments, buckets, strict=True)
        if frames
    ]
