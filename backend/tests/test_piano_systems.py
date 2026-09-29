import numpy as np

from app.piano.systems import find_systems
from tests.piano_data import meta, score

GT = meta()["systems"]


def frame(y0: int, h: int = 720) -> np.ndarray:
    img = score()[y0 : y0 + h]
    return np.ascontiguousarray(img)


def gt_index(sys_, y0: int) -> int:
    """The ground-truth system whose ink box holds this system's staff lines."""
    top, bottom = sys_.top + y0, sys_.bottom + y0
    hits = [i for i, g in enumerate(GT) if g["y0"] <= top and bottom <= g["y1"]]
    assert len(hits) == 1, (top, bottom)
    return hits[0]


def test_pairs_the_two_staves_of_each_whole_system():
    found = find_systems(frame(0))
    assert [gt_index(s, 0) for s in found] == [0, 1]
    for s in found:
        g = GT[gt_index(s, 0)]
        assert 10 <= s.spacing <= 13
        # the crop holds the whole system: staves, ledger notes, stems
        assert s.y0 <= g["y0"] + 2 and s.y1 >= g["y1"] - 2
        assert s.image.shape[0] == s.y1 - s.y0
        assert s.image.shape[1] > 0.8 * score().shape[1]


def test_drops_systems_touching_the_frame_edge():
    # system 1 cut through its treble staff; system 2 whole
    g1 = GT[1]
    y0 = g1["y0"] + 150
    found = find_systems(frame(y0))
    idx = [gt_index(s, y0) for s in found]
    assert 1 not in idx
    assert 2 in idx
    # the frame ends just below system 3's bottom staff line: not enough room for stems
    y0 = GT[3]["y1"] - 720 - 25
    found = find_systems(frame(y0))
    assert 3 not in [gt_index(s, y0) for s in found]


def staff_rows(g: dict) -> tuple[int, int, float]:
    """(top line, bottom line, staff space) of a ground-truth system. Lines on half-pixel
    positions render as two light rows, so only the clearly dark rows are used: the upper
    staff's five lines give the spacing, the last dark row is the bass staff's bottom line."""
    img = score()[g["y0"] : g["y1"] + 1]
    rows = np.flatnonzero((img.min(axis=2) < 128).mean(axis=1) > 0.8)
    groups = np.split(rows, np.flatnonzero(np.diff(rows) > 1) + 1)
    lines = [float(r.mean()) + g["y0"] for r in groups]
    return round(lines[0]), round(lines[-1]), (lines[4] - lines[0]) / 4


def test_lower_staff_left_alone_is_not_paired_with_the_next_system():
    # only the bass staff of system 0 is visible at the top; system 1 is whole. White rows
    # are cut out between them, so they are as close as the staves of one system: only the
    # missing bar lines tell them apart.
    img = score()
    _, bottom0, s = staff_rows(GT[0])
    lower_top = bottom0 - 4 * s
    top = img[int(lower_top - 2 * s) : GT[0]["y1"] + 2]
    start1 = GT[1]["y0"] - 2
    rest = img[start1 : GT[1]["y1"] + 60]
    found = find_systems(np.ascontiguousarray(np.vstack([top, rest])))
    assert len(found) == 1
    top1, _, _ = staff_rows(GT[1])
    assert abs(found[0].top - (top.shape[0] + top1 - start1)) <= 1


def test_nothing_in_a_frame_without_music():
    assert find_systems(np.full((720, 1280, 3), 255, np.uint8)) == []
    assert find_systems(np.zeros((720, 1280, 3), np.uint8)) == []


def test_long_beams_along_the_staff_lines_do_not_hide_a_staff():
    # like repeated 16ths across a whole system: thick beams hugging a staff's lines
    img = frame(0).copy()
    top = 204 + 0  # bass staff of system 0: lines 204..250 in the score
    for y in (top - 5, top + 4, 250 + 3):
        img[y : y + 5, 150:900] = 0
    found = find_systems(img)
    assert [gt_index(s, 0) for s in found] == [0, 1]
