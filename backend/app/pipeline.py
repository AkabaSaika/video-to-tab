from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.compose import build_pages, mark_repeats, merge_adjacent
from app.frames import probe, sample_frames
from app.models import Page, Roi
from app.region import has_staff_lines
from app.segment import SegmentParams, find_segments, prep_gray

Progress = Callable[[str, float], None]


@dataclass(frozen=True)
class AnalyzeParams:
    fps: float = 5.0
    diff_threshold: float = 0.15
    min_duration: float = 0.8


class NoPagesFound(Exception):
    pass


def analyze(
    video: Path,
    roi: Roi,
    params: AnalyzeParams | None = None,
    progress: Progress = lambda stage, frac: None,
) -> list[Page]:
    params = params or AnalyzeParams()
    total = max(1, int(probe(video).duration * params.fps))
    times, grays = [], []
    for t, img in sample_frames(video, fps=params.fps, roi=roi):
        times.append(t)
        grays.append(prep_gray(img))
        progress("scan", min(1.0, len(times) / total))
    segments = find_segments(
        times,
        grays,
        params.fps,
        SegmentParams(diff_threshold=params.diff_threshold, min_duration=params.min_duration),
    )
    pages = build_pages(
        video, roi, segments, params.fps, lambda i: progress("compose", min(1.0, i / total))
    )
    pages = [p for p in pages if has_staff_lines(p.image)]
    pages = mark_repeats(merge_adjacent(pages))
    if not pages:
        raise NoPagesFound("没有找到稳定的谱面，请检查框选区域或降低变化阈值")
    return pages
