"""Recognition on synthetic tab lines drawn in the Guitar Pro style (no ground-truth file)."""

import cv2
import numpy as np
import pytest

from app.omr.glyphs import MODEL_PATH
from app.omr.recognize import recognize_images

SPACING = 24  # px between strings
TOP = 60


def draw_line(
    measures, strings=6, stems=True, final_bar="thin", label=None, tuplet_in=None, through=False
):
    """measures: list of measures, each a list of 4 beats, each a list of (string, fret).
    Draws one tab line with quarter-note stems below every beat. Options mimic Guitar Pro:
    a thin+thick final bar, a track label before the first bar, and a tuplet "3" under the
    measure with index `tuplet_in`."""
    return draw_system([measures], strings, stems, final_bar, label, tuplet_in, through)


def draw_system(
    staves,
    strings=6,
    stems=True,
    final_bar="thin",
    label=None,
    tuplet_in=None,
    through=False,
):
    """Several tab staves stacked in one line image (Guitar Pro's multi-track system).
    Each entry of `staves` is a list of measures as in draw_line. A beat may also be:
    - TIE: a stem without a number (a tied continuation, as Guitar Pro draws it);
    - a list holding (string, "(14)")-style frets: a parenthesized note with a tie arc
      coming in from the left (a tied note); "g(14)" draws the parentheses without the
      arc (Guitar Pro's ghost note).
    With through=True the stems start right under the lowest fret number of the beat and
    run down through the staff, touching the digit."""
    beat_w, pad = 90, 30
    lead = 10 if label is None else 140
    width = lead + len(staves[0]) * (4 * beat_w + pad) + 60
    staff_h = (strings - 1) * SPACING + 140
    img = np.full((staff_h * len(staves), width, 3), 255, np.uint8)
    for k, measures in enumerate(staves):
        top = TOP + k * staff_h
        _draw_staff(img, top, measures, strings, stems, final_bar, label, tuplet_in, through)
    return img


TIE = "tie"


def _draw_staff(img, top, measures, strings, stems, final_bar, label, tuplet_in, through):
    beat_w, pad = 90, 30
    width = img.shape[1]
    lead = 10 if label is None else 140
    ys = [top + (strings - 1 - s) * SPACING for s in range(strings)]  # string 0 at the bottom
    x_start = 0 if label is None else lead - 6  # a track label sits left of the staff
    for y in ys:
        cv2.line(img, (x_start, y), (width - 1, y), (0, 0, 0), 1)
    if label is not None:
        cv2.putText(img, label, (12, ys[2] + 8), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)
    x = lead
    for mi, measure in enumerate(measures):
        if mi == tuplet_in:
            tx = x + pad + beat_w
            cv2.putText(img, "3", (tx, ys[0] + 85), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1)
        cv2.line(img, (x, ys[-1]), (x, ys[0]), (0, 0, 0), 2)
        for k, beat in enumerate(measure):
            bx = x + pad + k * beat_w
            lowest_digit = None
            for string, fret in [] if beat == TIE else beat:
                text = str(fret)
                ghost = text.startswith("g")
                text = text.removeprefix("g")
                (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
                y = ys[string]
                bx_text = bx
                if text.startswith("("):
                    bx_text = bx - cv2.getTextSize("(", cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)[0][0]
                    if not ghost:  # the tie arc from the previous note ends before the "("
                        c = (bx_text - 30, y - 6)
                        cv2.ellipse(img, c, (20, 6), 0, 180, 360, (0, 0, 0), 2, cv2.LINE_AA)
                cv2.rectangle(
                    img,
                    (bx_text - 2, y - th // 2 - 3),
                    (bx_text + tw + 2, y + th // 2 + 3),
                    (255, 255, 255),
                    -1,
                )
                cv2.putText(
                    img,
                    text,
                    (bx_text, y + th // 2),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 0, 0),
                    1,
                    cv2.LINE_AA,
                )
                lowest_digit = max(lowest_digit or 0, y + th // 2 + 1)
            stem_top = lowest_digit if through and lowest_digit else ys[0] + 14
            if stems and beat:
                cx = bx + 6
                cv2.line(img, (cx, stem_top), (cx, ys[0] + 60), (0, 0, 0), 2)
        x += 4 * beat_w + pad
    cv2.line(img, (x, ys[-1]), (x, ys[0]), (0, 0, 0), 2)
    if final_bar == "thick":  # Guitar Pro's final bar: thin line, gap, thick line
        cv2.rectangle(img, (x + 8, ys[-1]), (x + 18, ys[0]), (0, 0, 0), -1)


MEASURES = [
    [[(0, 3)], [(1, 5), (2, 7)], [(3, 12)], [(5, 0)]],
    [[(4, 10)], [(2, 2)], [(0, 15), (1, 17)], [(5, 8)]],
]


def only_track(song):
    assert len(song.tracks) == 1
    return song.tracks[0]


def notes_of(score):
    return [[sorted((n.string, n.fret) for n in b.notes) for b in m.beats] for m in score.measures]


@pytest.mark.skipif(not MODEL_PATH.exists(), reason="model not trained")
def test_six_string_line_with_two_digit_frets_and_chords():
    score = only_track(recognize_images([draw_line(MEASURES)]))
    assert score.strings == 6
    assert score.tuning == [40, 45, 50, 55, 59, 64]
    assert notes_of(score) == [[sorted(b) for b in m] for m in MEASURES]
    assert all(b.duration == 4 for m in score.measures for b in m.beats)
    assert all(b.confidence >= 0.7 for m in score.measures for b in m.beats)


@pytest.mark.skipif(not MODEL_PATH.exists(), reason="model not trained")
def test_line_without_rhythm_marks_still_fills_each_measure():
    score = only_track(recognize_images([draw_line(MEASURES, stems=False)]))
    assert notes_of(score) == [[sorted(b) for b in m] for m in MEASURES]
    for m in score.measures:
        assert sum(b.length() for b in m.beats) == m.capacity()
        assert all(b.confidence < 0.7 for b in m.beats)  # guessed rhythm is flagged


@pytest.mark.skipif(not MODEL_PATH.exists(), reason="model not trained")
def test_image_without_tab_gives_empty_score():
    blank = np.full((300, 800, 3), 255, np.uint8)
    assert recognize_images([blank]).tracks == []


@pytest.mark.skipif(not MODEL_PATH.exists(), reason="model not trained")
def test_thick_final_bar_adds_no_measure():
    score = only_track(recognize_images([draw_line(MEASURES, final_bar="thick")]))
    assert notes_of(score) == [[sorted(b) for b in m] for m in MEASURES]


@pytest.mark.skipif(not MODEL_PATH.exists(), reason="model not trained")
def test_track_label_before_first_bar_is_not_a_measure():
    score = only_track(recognize_images([draw_line(MEASURES, label="Gt.1")]))
    assert notes_of(score) == [[sorted(b) for b in m] for m in MEASURES]


@pytest.mark.skipif(not MODEL_PATH.exists(), reason="model not trained")
def test_tuplet_digit_stays_in_its_measure():
    score = only_track(recognize_images([draw_line(MEASURES, tuplet_in=1)]))
    first = score.measures[0]
    assert [(b.duration, b.tuplet) for b in first.beats] == [(4, None)] * 4


def test_compare_counts_recognized_measures_missing_from_ground_truth():
    from app.omr.evaluate import compare
    from app.omr.model import Beat, Measure, Note, Score

    gt = Score(6, [], None, [Measure(1, (4, 4), [Beat(1, 0, None, False, [Note(0, 3)])])])
    rec = Score(
        6,
        [],
        None,
        [
            Measure(1, (4, 4), [Beat(1, 0, None, False, [Note(0, 3)])]),
            Measure(2, (4, 4), [Beat(1, 0, None, False, [Note(3, 1)])]),  # phantom
        ],
    )
    summary = compare(gt, rec, 1, 1).summary()
    assert summary["extra_measures"] == 1
    assert summary["fret_precision"] == 50.0


def test_compare_reports_tie_accuracy_on_matched_notes():
    from app.omr.evaluate import compare
    from app.omr.model import Beat, Measure, Note, Score

    def song(ties):
        beats = [
            Beat(4, 0, None, False, [Note(0, 3), Note(1, 5)]),
            Beat(4, 0, None, False, [Note(0, 3, tied=ties[0]), Note(1, 5, tied=ties[1])]),
            Beat(2, 0, None, False, [Note(2, 7, tied=ties[2])]),
        ]
        return Score(6, [], None, [Measure(1, (4, 4), beats)])

    s = compare(song([True, True, False]), song([True, False, True]), 1, 1).summary()
    assert s["tie_accuracy"] == round(100 * 3 / 5, 2)  # 5 matched notes, 2 disagree
    assert s["tie_recall"] == 50.0  # 1 of the 2 tied notes found
    assert s["tie_precision"] == 50.0  # 1 of the 2 recognized ties is right
    assert s["counts"]["ties"] == 2


DENSE = [  # six-note chords on every beat: the rows between the lines fill up with digits
    [[(s, f) for s, f in zip(range(6), (1, 3, 3, 2, 1, 1), strict=True)]] * 4,
    [[(s, f) for s, f in zip(range(6), (3, 5, 5, 4, 3, 3), strict=True)]] * 4,
]


@pytest.mark.skipif(not MODEL_PATH.exists(), reason="model not trained")
def test_two_staves_per_line_become_two_tracks():
    song = recognize_images([draw_system([MEASURES, DENSE])] * 2)
    assert len(song.tracks) == 2
    top, bottom = song.tracks
    assert notes_of(top) == [[sorted(b) for b in m] for m in MEASURES] * 2
    assert notes_of(bottom) == [[sorted(b) for b in m] for m in DENSE] * 2
    assert [m.number for m in top.measures] == [m.number for m in bottom.measures]
    assert [m.line for m in bottom.measures] == [0, 0, 1, 1]
    assert top.strings == bottom.strings == 6
    assert top.name and bottom.name and top.name != bottom.name


@pytest.mark.skipif(not MODEL_PATH.exists(), reason="model not trained")
def test_dense_chord_staff_is_a_real_staff():
    from app.omr.glyphs import gray_of
    from app.omr.recognize import find_staves

    staves = find_staves(gray_of(draw_line(DENSE)))
    assert [len(st.lines) for st in staves] == [6]


def test_staff_check_counts_long_runs_not_darkness():
    """Light-grey lines; the rows halfway between them are full of short black strokes
    (dense digits reaching them). Those rows are darker than the lines on average, but
    only the lines are made of long horizontal runs."""
    from app.omr.recognize import _lines_are_ink
    from app.region import Staff

    s, top = 20, 40
    gray = np.full((top + 5 * s + 40, 900), 255, np.uint8)
    lines = [top + i * s for i in range(6)]
    for y in lines:
        gray[y, :] = 185
    for y in lines[:-1]:
        for x in range(0, 900, 10):
            gray[y + s // 2 - 1 : y + s // 2 + 2, x : x + 6] = 0
    assert _lines_are_ink(gray, Staff(lines, 0, 899))
    # the gaps between the lines, as detect_staves' inverted pass can report them
    gaps = [y + s // 2 for y in lines[:-1]]
    assert not _lines_are_ink(gray, Staff(gaps, 0, 899))


THROUGH = [  # stems start right under the (lowest) number and run down through the staff
    [[(4, 1)], [(4, 15)], [(3, 1)], [(4, 13)]],
    [[(2, 11)], [(4, 12), (2, 1)], [(1, 1)], [(4, 14)]],
]  # (not on the top string: a stem from there spans the staff like a bar line)


@pytest.mark.skipif(not MODEL_PATH.exists(), reason="model not trained")
def test_stem_touching_a_one_is_not_part_of_the_number():
    score = only_track(recognize_images([draw_line(THROUGH, through=True)]))
    assert notes_of(score) == [[sorted(b) for b in m] for m in THROUGH]


def test_narrow_digit_read_as_four_is_a_one():
    """Guitar Pro's "1" (a flag and a stroke, no base) can look like a "4" to the
    classifier; a "4" is never much narrower than half its height."""
    from app.omr.glyphs import Blob
    from app.omr.recognize import Glyph, frets_from_glyphs
    from app.region import Staff

    staff = Staff([60, 80, 100, 120, 140, 160], 0, 400)

    def glyph(x, w, label, conf=0.8):
        return Glyph(Blob(x, 72, w, 16, np.ones((16, w), bool)), label, conf)

    glyphs = [glyph(100, 6, "4"), glyph(108, 11, "5"), glyph(200, 11, "4"), glyph(300, 6, "4")]
    glyphs += [glyph(400, 6, "4", 0.39), glyph(408, 11, "2")]  # unsure between 1 and 4
    frets = frets_from_glyphs(glyphs, [], staff)
    assert [(f.string, f.fret) for f in frets] == [(4, 15), (4, 4), (4, 1), (4, 12)]
    assert frets[-1].conf < 0.7  # still flagged for review


def ties_of(score):
    return [
        [sorted((n.string, n.fret, n.tied) for n in b.notes) for b in m.beats]
        for m in score.measures
    ]


@pytest.mark.skipif(not MODEL_PATH.exists(), reason="model not trained")
def test_stem_without_number_is_a_tied_continuation():
    measures = [[[(3, 5), (2, 7)], TIE, [(2, 7)], [(1, 3)]], [[(0, 3)], [(1, 5)], TIE, [(4, 2)]]]
    score = only_track(recognize_images([draw_line(measures)]))
    assert ties_of(score) == [
        [
            [(2, 7, False), (3, 5, False)],
            [(2, 7, True), (3, 5, True)],
            [(2, 7, False)],
            [(1, 3, False)],
        ],
        [[(0, 3, False)], [(1, 5, False)], [(1, 5, True)], [(4, 2, False)]],
    ]
    tied = score.measures[0].beats[1]
    assert not tied.rest and tied.duration == 4
    assert tied.confidence < 0.7  # which notes continue is a guess: flagged for review


@pytest.mark.skipif(not MODEL_PATH.exists(), reason="model not trained")
def test_parenthesized_number_is_a_tied_note():
    measures = [
        [[(3, 5)], [(3, "(5)")], [(2, 12)], [(2, "(12)"), (0, 3)]],
        [[(4, 10)], [(4, "g(10)")], [(0, 15), (1, 17)], [(5, 8)]],  # a ghost note, no arc
    ]
    score = only_track(recognize_images([draw_line(measures)]))
    assert ties_of(score) == [
        [[(3, 5, False)], [(3, 5, True)], [(2, 12, False)], [(0, 3, False), (2, 12, True)]],
        [[(4, 10, False)], [(4, 10, False)], [(0, 15, False), (1, 17, False)], [(5, 8, False)]],
    ]
