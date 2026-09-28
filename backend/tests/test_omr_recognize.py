"""Recognition on synthetic tab lines drawn in the Guitar Pro style (no ground-truth file)."""

import cv2
import numpy as np
import pytest

from app.omr.glyphs import MODEL_PATH
from app.omr.recognize import recognize_images

SPACING = 24  # px between strings
TOP = 60


def draw_line(measures, strings=6, stems=True):
    """measures: list of measures, each a list of 4 beats, each a list of (string, fret).
    Draws one tab line with quarter-note stems below every beat."""
    beat_w, pad = 90, 30
    width = pad + len(measures) * (4 * beat_w + pad) + 20
    height = TOP + (strings - 1) * SPACING + 140
    img = np.full((height, width, 3), 255, np.uint8)
    ys = [TOP + (strings - 1 - s) * SPACING for s in range(strings)]  # string 0 at the bottom
    for y in ys:
        cv2.line(img, (0, y), (width - 1, y), (0, 0, 0), 1)
    x = 10
    for measure in measures:
        cv2.line(img, (x, ys[-1]), (x, ys[0]), (0, 0, 0), 2)
        for k, beat in enumerate(measure):
            bx = x + pad + k * beat_w
            for string, fret in beat:
                text = str(fret)
                (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
                y = ys[string]
                cv2.rectangle(
                    img,
                    (bx - 2, y - th // 2 - 3),
                    (bx + tw + 2, y + th // 2 + 3),
                    (255, 255, 255),
                    -1,
                )
                cv2.putText(
                    img,
                    text,
                    (bx, y + th // 2),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 0, 0),
                    1,
                    cv2.LINE_AA,
                )
            if stems and beat:
                cx = bx + 6
                cv2.line(img, (cx, ys[0] + 14), (cx, ys[0] + 60), (0, 0, 0), 2)
        x += 4 * beat_w + pad
    cv2.line(img, (x, ys[-1]), (x, ys[0]), (0, 0, 0), 2)
    return img


MEASURES = [
    [[(0, 3)], [(1, 5), (2, 7)], [(3, 12)], [(5, 0)]],
    [[(4, 10)], [(2, 2)], [(0, 15), (1, 17)], [(5, 8)]],
]


def notes_of(score):
    return [[sorted((n.string, n.fret) for n in b.notes) for b in m.beats] for m in score.measures]


@pytest.mark.skipif(not MODEL_PATH.exists(), reason="model not trained")
def test_six_string_line_with_two_digit_frets_and_chords():
    score = recognize_images([draw_line(MEASURES)])
    assert score.strings == 6
    assert score.tuning == [40, 45, 50, 55, 59, 64]
    assert notes_of(score) == [[sorted(b) for b in m] for m in MEASURES]
    assert all(b.duration == 4 for m in score.measures for b in m.beats)
    assert all(b.confidence >= 0.7 for m in score.measures for b in m.beats)


@pytest.mark.skipif(not MODEL_PATH.exists(), reason="model not trained")
def test_line_without_rhythm_marks_still_fills_each_measure():
    score = recognize_images([draw_line(MEASURES, stems=False)])
    assert notes_of(score) == [[sorted(b) for b in m] for m in MEASURES]
    for m in score.measures:
        assert sum(b.length() for b in m.beats) == m.capacity()
        assert all(b.confidence < 0.7 for b in m.beats)  # guessed rhythm is flagged


@pytest.mark.skipif(not MODEL_PATH.exists(), reason="model not trained")
def test_image_without_tab_gives_empty_score():
    blank = np.full((300, 800, 3), 255, np.uint8)
    score = recognize_images([blank])
    assert score.measures == []
