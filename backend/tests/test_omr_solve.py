from fractions import Fraction

from app.omr.rhythm import BeatMarks
from app.omr.solve import BeatEvidence, solve_measure


def stem(beams=0, dot=False, short=False):
    marks = BeatMarks(True, 0.7, 1.0 if short else 1.8, beams, 1.0, dot)
    return BeatEvidence(marks, short_stem=short)


def durations(opts):
    return [(o.duration, o.dots, o.tuplet) for o in opts]


def test_solver_keeps_a_consistent_reading():
    ev = [stem(1)] * 8
    opts, ok = solve_measure(ev, Fraction(1))
    assert ok and durations(opts) == [(8, 0, None)] * 8


def test_solver_fixes_one_misread_beam():
    ev = [stem(1)] * 7 + [stem(2)]  # last beat misread as a 16th
    opts, ok = solve_measure(ev, Fraction(1))
    assert ok and durations(opts)[-1] == (8, 0, None)


def test_solver_dotted_and_short_stem_half():
    opts, ok = solve_measure([stem(0, dot=True, short=True), stem(1), stem(1)], Fraction(1))
    assert ok and durations(opts) == [(2, 1, None), (8, 0, None), (8, 0, None)]


def test_solver_infers_triplet_group_without_visible_number():
    ev = [stem(0, short=True), stem(0), stem(0), stem(0)]
    opts, ok = solve_measure(ev, Fraction(1))
    assert ok and durations(opts) == [(2, 0, None)] + [(4, 0, 3)] * 3
