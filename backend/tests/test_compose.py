import numpy as np

from app.compose import build_pages, mark_repeats, median_page, merge_adjacent, same_content
from app.models import Page, Segment
from tests.synth import ROI_TRUTH, render_panel


def with_cursor(panel, x):
    out = panel.copy()
    out[:, x : x + 3] = (0, 0, 255)
    return out


def test_median_page_removes_moving_cursor():
    panel = render_panel(1)
    frames = [with_cursor(panel, x) for x in range(0, 600, 60)]
    assert np.array_equal(median_page(frames), panel)


def test_median_page_with_two_frames_picks_a_real_frame():
    a, b = render_panel(1), render_panel(2)
    result = median_page([a, b])
    assert np.array_equal(result, a) or np.array_equal(result, b)


def test_same_content_ignores_cursor_but_not_different_notes():
    panel = render_panel(1)
    assert same_content(panel, with_cursor(panel, 300))
    assert not same_content(panel, render_panel(2))
    assert not same_content(panel, panel[:, :100])


def page(seed, start, end):
    return Page(render_panel(seed), start, end)


def test_merge_adjacent_joins_identical_neighbours():
    pages = merge_adjacent([page(1, 0, 2), page(2, 2, 4), page(2, 4, 7), page(1, 7, 9)])
    assert [(p.start, p.end) for p in pages] == [(0, 2), (2, 7), (7, 9)]


def test_mark_repeats_points_to_first_occurrence():
    pages = mark_repeats([page(1, 0, 2), page(2, 2, 4), page(1, 4, 6), page(1, 6, 8)])
    assert [p.duplicate_of for p in pages] == [None, None, 0, 0]


def test_build_pages_from_video(synth_video):
    segs = [Segment(5, 14, 1.0, 3.0), Segment(38, 47, 7.6, 9.6)]  # page A and page C
    pages = build_pages(synth_video.path, ROI_TRUTH, segs, fps=5)
    assert [(p.start, p.end) for p in pages] == [(1.0, 3.0), (7.6, 9.6)]
    assert same_content(pages[0].image, synth_video.panels["A"])
    assert same_content(pages[1].image, synth_video.panels["C"])
