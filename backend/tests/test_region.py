import cv2
import numpy as np

from app.frames import grab_frames
from app.models import Roi
from app.region import detect_region, detect_staves, has_staff_lines, trim_to_panel
from tests.synth import LINE_YS, ROI_TRUTH, H, W, render_panel


def test_detect_staves_light_and_dark():
    for dark in (False, True):
        staves = detect_staves(render_panel(1, dark=dark))
        assert len(staves) == 1
        assert [y + ROI_TRUTH.y for y in staves[0].lines] == LINE_YS


def test_has_staff_lines():
    assert has_staff_lines(render_panel(2))
    assert not has_staff_lines(render_panel(None))


def test_trim_to_panel_cuts_rows_that_are_not_panel():
    gray = np.full((100, 50), 255, np.uint8)
    gray[:20] = 60  # video above the panel
    assert trim_to_panel(gray, Roi(0, 0, 50, 100)) == Roi(0, 20, 50, 80)


def test_detect_region_on_videos(synth_video, synth_video_dark):
    for video in (synth_video, synth_video_dark):
        guess = detect_region(grab_frames(video.path, 20))
        assert guess.roi.iou(ROI_TRUTH) > 0.9
        assert guess.confidence > 0.7


def frame_with_panel(seed, distractor=False):
    frame = np.full((H, W, 3), 120, np.uint8)
    r = ROI_TRUTH
    frame[r.y : r.y + r.h, r.x : r.x + r.w] = render_panel(seed)
    if distractor:  # four "guitar strings" that happen to be level in this frame
        for i in range(4):
            cv2.line(frame, (40, 60 + 10 * i), (600, 60 + 10 * i), (20, 20, 20), 1)
    return frame


def test_ignores_staff_like_lines_seen_in_few_frames():
    frames = [frame_with_panel(i % 3 + 1, distractor=(i < 3)) for i in range(10)]
    guess = detect_region(frames)
    assert guess.roi.iou(ROI_TRUTH) > 0.9
    assert guess.confidence == 1.0


def test_falls_back_to_bottom_third_without_tab():
    guess = detect_region([np.full((H, W, 3), 200, np.uint8) for _ in range(5)])
    assert guess.confidence == 0.0
    assert guess.roi == Roi(0, H * 2 // 3, W, H - H * 2 // 3)
