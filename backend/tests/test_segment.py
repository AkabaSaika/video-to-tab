import numpy as np

from app.frames import sample_frames
from app.segment import SegmentParams, find_segments, frame_change, prep_gray
from tests.synth import ROI_TRUTH, render_panel


def gray_panel(seed, cursor_x=None):
    panel = render_panel(seed)
    if cursor_x is not None:
        panel[:, cursor_x : cursor_x + 3] = (0, 0, 255)
    return prep_gray(panel)


def test_prep_gray_resizes_to_fixed_width():
    assert prep_gray(render_panel(1)).shape == (144, 480)


def test_cursor_movement_is_small_change_page_turn_is_large():
    cursor = frame_change(gray_panel(1, 100), gray_panel(1, 160))
    turn = frame_change(gray_panel(1, 100), gray_panel(2, 160))
    assert cursor < 0.05
    assert turn > 0.3


def test_find_segments_splits_on_changes_and_drops_short_runs():
    a, b = gray_panel(1), gray_panel(2)
    blank = np.zeros_like(a)
    grays = [a] * 5 + [blank] + [b] * 5  # a 0.2 s flash between two pages
    times = [i * 0.2 for i in range(len(grays))]
    segs = find_segments(times, grays, fps=5, params=SegmentParams(min_duration=0.8))
    assert [(s.start_idx, s.end_idx) for s in segs] == [(0, 4), (6, 10)]
    assert segs[0].start == 0.0 and abs(segs[0].end - 1.0) < 1e-9


def test_segments_on_synth_video(synth_video):
    times, grays = [], []
    for t, img in sample_frames(synth_video.path, fps=5, roi=ROI_TRUTH):
        times.append(t)
        grays.append(prep_gray(img))
    segs = find_segments(times, grays, fps=5)
    # blank intro, A, B, B (after flash), C, A -- fade and flash frames are dropped
    starts = [round(s.start, 1) for s in segs]
    assert starts == [0.0, 1.0, 3.4, 5.6, 7.6, 9.6]
