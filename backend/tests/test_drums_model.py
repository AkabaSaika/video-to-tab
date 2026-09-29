from fractions import Fraction

import pytest

from app.drums.model import Beat, DrumMeasure, DrumNote, DrumScore, position, staff_step


def score() -> DrumScore:
    hh = DrumNote("G", 5, "x")
    sn = DrumNote("C", 5, "normal", accent=True)
    bd = DrumNote("F", 4, "normal")
    v1 = [
        Beat(Fraction(0), 8, notes=[hh, bd]),
        Beat(Fraction(1, 8), 8, notes=[DrumNote("G", 5, "x", open=True)]),
        Beat(Fraction(1, 4), 4, dots=1, notes=[sn]),
        Beat(Fraction(5, 8), 8, rest=True),
        Beat(Fraction(3, 4), 16, tuplet=3, notes=[DrumNote("C", 5, "normal", ghost=True)]),
    ]
    v2 = [Beat(Fraction(1, 4), 4, notes=[DrumNote("D", 4, "x")])]
    return DrumScore("Groove", 120, (4, 4), [DrumMeasure([v1, v2], ok=False, time=(4, 4))])


def test_json_round_trip():
    s = score()
    again = DrumScore.from_dict(s.to_dict())
    assert again == s
    assert again.measures[0].voices[0][0].onset == Fraction(0)
    assert again.measures[0].voices[0][3].rest


def test_beat_length_and_end():
    b = Beat(Fraction(1, 4), 4, dots=1)
    assert b.length() == Fraction(3, 8)
    assert b.end() == Fraction(5, 8)
    assert Beat(Fraction(0), 8, tuplet=3).length() == Fraction(1, 12)


def test_reads_older_or_partial_data():
    # an older / hand-written file: no version, no flags, onset as a float in quarters
    data = {
        "title": "x",
        "measures": [
            {"voices": [[{"onset": 1.0, "duration": 4, "notes": [{"step": "C", "octave": 5}]}]]}
        ],
    }
    s = DrumScore.from_dict(data)
    assert s.time == (4, 4) and s.tempo == 120
    beat = s.measures[0].voices[0][0]
    assert beat.onset == Fraction(1, 4)
    assert beat.notes[0].notehead == "normal" and not beat.notes[0].accent
    assert s.measures[0].ok is None


def test_rejects_garbage():
    with pytest.raises(ValueError):
        DrumScore.from_dict({"measures": [{"voices": [[{"duration": "x"}]]}]})


def test_positions():
    assert staff_step("E", 4) == 0  # bottom line of the 5-line staff
    assert staff_step("A", 5) == 10
    assert position(-1) == ("D", 4)
    assert position(9) == ("G", 5)
    assert DrumNote("G", 5, "x").key() == "G5"
