"""Capture: every measure (strip videos) or staff line (page videos) exactly once, in
order, whole."""

import cv2
import numpy as np
import pytest

from app.drums.capture import capture, panel_roi
from app.drums.recognize import layout, recognize
from app.frames import grab_frames
from tests.drum_data import gt_measures, predicted, rates, score, strip_meta
from tests.drum_synth import (
    GP_PANEL_Y,
    GP_SIZE,
    PAGE_PANEL_Y,
    gp_strip_video,
    page_groups,
    page_systems,
    page_video,
    strip,
    strip_measures,
)


def _gray(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img


def similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Best normalized correlation of the smaller image anywhere in the larger one."""
    a, b = _gray(a), _gray(b)
    if a.shape[0] * a.shape[1] > b.shape[0] * b.shape[1]:
        a, b = b, a
    pad = cv2.copyMakeBorder(b, 12, 12, 12, 12, cv2.BORDER_REPLICATE)
    if a.shape[0] > pad.shape[0] or a.shape[1] > pad.shape[1]:
        a = a[: pad.shape[0], : pad.shape[1]]
    return float(cv2.matchTemplate(pad, a, cv2.TM_CCOEFF_NORMED).max())


@pytest.fixture(scope="module")
def gp_video(tmp_path_factory):
    return gp_strip_video(tmp_path_factory.mktemp("gp") / "gp.avi")


def test_panel_is_found_below_the_camera(gp_video):
    roi = panel_roi(grab_frames(gp_video, 8))
    assert GP_PANEL_Y - 4 <= roi.y <= GP_PANEL_Y + 30
    assert roi.y + roi.h >= GP_SIZE[1] - 4
    assert roi.w >= GP_SIZE[0] - 8


def test_gp_strip_gives_every_measure_once_in_order(gp_video):
    progress = []
    mode, pages = capture(gp_video, progress=progress.append)
    assert mode == "strip"
    assert progress and progress[-1] == pytest.approx(1.0)
    got = [p.image[:, a:b] for p in pages for a, b in p.measures]
    src = strip()
    want = [src[:, a:b] for a, b in strip_measures()]
    assert len(got) == len(want)
    for i, (g, w) in enumerate(zip(got, want, strict=True)):
        # the measure's own content, not a neighbour's (identical measures repeat, so
        # being as similar as the right one is enough)
        score = similarity(g, w)
        assert score > 0.75, (i, score)
    # the first page starts with the clef and the time signature, later ones do not
    assert layout(pages[0].image).header is not None
    assert all(layout(p.image).header is None for p in pages[1:])
    starts = [p.start for p in pages]
    assert starts == sorted(starts)
    assert all(p.image.shape[1] <= GP_SIZE[0] for p in pages)


def test_page_turns_give_every_staff_line_once_in_order(tmp_path):
    video = page_video(tmp_path / "pages.avi")
    mode, pages = capture(video)
    assert mode == "pages"
    systems = page_systems()
    assert len(page_groups()) >= 3
    assert len(pages) == len(systems)
    for page, (piece, i, img) in zip(pages, systems, strict=True):
        best = max(range(len(systems)), key=lambda k: similarity(page.image, systems[k][2]))
        # identical lines may exist; the right one must be as good as the best
        assert similarity(page.image, img) >= similarity(page.image, systems[best][2]) - 0.02
        assert similarity(page.image, img) > 0.8, (piece, i)
        assert page.image.shape[0] >= img.shape[0] - 70  # whole: staff and notes
    assert [p.start for p in pages] == sorted(p.start for p in pages)
    assert all(p.y >= PAGE_PANEL_Y - 1 for p in pages)


def test_gp_strip_pages_read_back_as_the_score(gp_video):
    """The pages made of captured measures recognize like the score itself: the header
    is read on the first page and its time signature carries over."""
    _, pages = capture(gp_video)
    first = recognize(pages[0].image)
    assert first.time == (4, 4)
    measures = [m for p in pages for m in recognize(p.image, time=first.time).measures]
    gt = gt_measures(strip_meta()["events"], len(strip_measures()))
    result = rates(score(gt, predicted(measures)))
    print("\ngp strip video", result)
    assert result["measures"] == f"{len(gt)}/{len(gt)}"
    assert result["recall"] >= 0.9 and result["precision"] >= 0.9
