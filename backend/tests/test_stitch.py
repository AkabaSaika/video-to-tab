import cv2
import numpy as np
import pytest

from app.models import Page, Roi
from app.pipeline import analyze
from app.stitch import (
    BAR_MARGIN,
    OVERLAP_THRESHOLD,
    find_bars,
    ink_mask,
    line_ranges,
    overlap_shift,
    stitch_pages,
)
from tests.synth import (
    LINE_YS,
    ROI_TRUTH,
    SCROLL_MEASURES,
    SCROLL_STEP,
    render_panel,
    render_scroll_strip,
    render_tab_page,
    scroll_bar_xs,
    scroll_pages,
)


def as_pages(images, seconds=1.0):
    return [Page(img, i * seconds, (i + 1) * seconds) for i, img in enumerate(images)]


def test_ink_mask_drops_staff_lines_keeps_digits():
    panel = render_panel(1)
    mask = ink_mask(panel)
    for y in LINE_YS:
        assert mask[y - ROI_TRUTH.y].mean() < 0.3  # only digit strokes remain on the row
    assert mask.sum() > 200  # fret numbers are still there


def test_ink_mask_drops_bar_lines():
    page = render_tab_page([1, 2, 3, 4])
    mask = ink_mask(page)
    for x in scroll_bar_xs()[:5]:
        assert mask[:, x - 2 : x + 3].sum() < 20  # at most bits of digits near the bar


def test_overlap_shift_finds_scroll_step_despite_highlight():
    pages = scroll_pages(render_scroll_strip())
    for a, b in zip(pages, pages[1:], strict=False):
        shift, score = overlap_shift(a, b)
        assert abs(shift - SCROLL_STEP) <= 3
        assert score >= OVERLAP_THRESHOLD


def test_page_switch_panels_do_not_overlap():
    panels = [render_panel(seed) for seed in (1, 2, 3)]
    for a, b in zip(panels, panels[1:], strict=False):
        assert overlap_shift(a, b)[1] < OVERLAP_THRESHOLD
    assert overlap_shift(panels[0], panels[0][:, :300])[1] == 0.0  # size mismatch


@pytest.mark.parametrize("notes", [5, 2])  # 2: sparse, whole-note style measures
def test_page_switch_pages_with_aligned_bar_lines_pass_through(notes):
    images = [render_tab_page(p, notes) for p in ([1, 2, 3, 4], [5, 6, 7, 8], [9, 10, 11, 12])]
    for a, b in zip(images, images[1:], strict=False):
        assert overlap_shift(a, b)[1] < OVERLAP_THRESHOLD
    pages = as_pages(images)
    assert all(a is b for a, b in zip(stitch_pages(pages), pages, strict=True))


@pytest.mark.parametrize("notes", [5, 2])
def test_riff_repeated_across_page_turn_is_ambiguous_not_an_overlap(notes):
    # A page turn inside a repeated riff A: shifts of one and of two measures match
    # almost equally well, so the true alignment cannot be told and nothing is joined.
    images = [render_tab_page([5, 6, 1, 1], notes), render_tab_page([1, 1, 7, 8], notes)]
    assert overlap_shift(*images)[1] < OVERLAP_THRESHOLD
    pages = as_pages(images)
    assert all(a is b for a, b in zip(stitch_pages(pages), pages, strict=True))


def test_find_bars_on_strip():
    bars = find_bars(render_scroll_strip())
    assert len(bars) == len(scroll_bar_xs())
    assert all(abs(b - x) <= 2 for b, x in zip(bars, scroll_bar_xs(), strict=True))


def test_find_bars_double_bar_is_cut_left_of_both_strokes():
    strip = render_scroll_strip()
    x, oy = scroll_bar_xs()[6], ROI_TRUTH.y
    cv2.line(strip, (x + 6, LINE_YS[0] - oy), (x + 6, LINE_YS[-1] - oy), (0, 0, 0), 2)
    gap_row = strip[LINE_YS[2] - oy + 8, x - 5 : x + 12, 0]
    first = int(np.flatnonzero(gap_row < 128)[0]) + x - 5  # leftmost column of stroke 1
    bars = find_bars(strip)
    assert len(bars) == len(scroll_bar_xs())
    assert bars[6] == first
    starts = [x0 for x0, _ in line_ranges(strip.shape[1], bars, ROI_TRUTH.w)]
    assert first - BAR_MARGIN in starts


def test_line_ranges_packs_whole_measures():
    assert line_ranges(1000, [100, 300, 500, 900], 450) == [
        (0, 297),
        (297, 497),
        (497, 897),
        (897, 1000),
    ]
    assert line_ranges(1000, [], 450) == [(0, 450), (450, 900), (900, 1000)]
    assert line_ranges(1000, [100], 50) == [(0, 97), (97, 1000)]  # oversized measure
    assert line_ranges(1000, [100, 998], 450) == [(0, 97), (97, 1000)]  # no end sliver
    assert line_ranges(1000, [4, 500], 450) == [(0, 497), (497, 1000)]  # no start sliver


def test_stitch_pages_rebuilds_every_measure_once():
    pages = as_pages(scroll_pages(render_scroll_strip()))
    lines = stitch_pages(pages)
    assert len(lines) < len(pages)
    assert all(line.image.shape[1] <= ROI_TRUTH.w for line in lines)
    bars = sum(len(find_bars(line.image)) for line in lines)
    assert bars == SCROLL_MEASURES + 1  # every bar line exactly once
    assert lines[0].start == pages[0].start and lines[-1].end == pages[-1].end


def test_stitch_pages_dark_theme():
    images = [255 - page for page in scroll_pages(render_scroll_strip())]
    for a, b in zip(images, images[1:], strict=False):
        shift, score = overlap_shift(a, b)
        assert abs(shift - SCROLL_STEP) <= 3
        assert score >= OVERLAP_THRESHOLD
    lines = stitch_pages(as_pages(images))
    assert len(lines) < len(images)
    assert sum(len(find_bars(line.image)) for line in lines) == SCROLL_MEASURES + 1


def test_stitch_pages_passes_page_switch_through():
    pages = as_pages([render_panel(seed) for seed in (1, 2, 3)])
    assert all(a is b for a, b in zip(stitch_pages(pages), pages, strict=True))
    assert stitch_pages([]) == []


def test_analyze_scroll_video(scroll_video):
    lines = analyze(scroll_video, Roi(ROI_TRUTH.x, ROI_TRUTH.y, ROI_TRUTH.w, ROI_TRUTH.h))
    bars = sum(len(find_bars(line.image)) for line in lines)
    assert bars == SCROLL_MEASURES + 1
    assert all(line.duplicate_of is None for line in lines)
    assert all(line.start < line.end for line in lines)
