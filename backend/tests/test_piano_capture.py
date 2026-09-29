import cv2
import pytest

from app.piano.capture import capture
from tests.piano_data import meta, score
from tests.piano_synth import pages, piano_page_video, piano_scroll_video

GT = meta()["systems"]


def locate(sys_) -> int:
    """Row in the fixture score where this crop was taken from (the videos never shift
    the score sideways, so the crop's columns are the score's)."""
    big = cv2.cvtColor(score(), cv2.COLOR_BGR2GRAY)[:, sys_.x0 : sys_.x0 + sys_.image.shape[1]]
    small = cv2.cvtColor(sys_.image, cv2.COLOR_BGR2GRAY)
    _, val, _, loc = cv2.minMaxLoc(cv2.matchTemplate(big, small, cv2.TM_CCOEFF_NORMED))
    assert val > 0.6, val
    return loc[1]


def check(systems) -> None:
    """Every ground-truth system exactly once, in order, whole."""
    assert len(systems) == len(GT)
    for sys_, g in zip(systems, GT, strict=True):
        y = locate(sys_)
        h = sys_.image.shape[0]
        # the crop holds the whole system (its ink box) and no other system
        assert y <= g["y0"] + 2 and y + h >= g["y1"] - 2, (y, h, g)
    starts = [s.first for s in systems]
    assert starts == sorted(starts)


@pytest.fixture(scope="module")
def scroll(tmp_path_factory):
    return piano_scroll_video(tmp_path_factory.mktemp("piano") / "scroll.avi")


def test_scrolling_video_gives_each_system_once_whole_and_in_order(scroll):
    progress = []
    systems = capture(scroll, progress=progress.append)
    check(systems)
    assert progress and progress[-1] == pytest.approx(1.0)


def test_page_turn_video_gives_each_system_once_whole_and_in_order(tmp_path):
    assert len(pages()) >= 3
    check(capture(piano_page_video(tmp_path / "pages.avi")))


def test_fast_scroll_still_catches_every_system(tmp_path):
    check(capture(piano_scroll_video(tmp_path / "fast.avi", speed=400, quality=40)))
