import pytest

from app.drums.instruments import (
    INSTRUMENTS,
    PRESETS,
    Mapping,
    head_family,
    note_key,
    used_keys,
)
from app.drums.model import Beat, DrumMeasure, DrumNote, DrumScore


def gm(mapping: Mapping, step: str, octave: int, head: str = "normal", **flags) -> int:
    return mapping.resolve(DrumNote(step, octave, head, **flags))


def test_default_map_follows_the_common_convention():
    m = Mapping()
    assert gm(m, "A", 5, "x") == 49  # crash
    assert gm(m, "G", 5, "x") == 42  # closed hi-hat
    assert gm(m, "G", 5, "x", open=True) == 46  # "o" above: open hi-hat
    assert gm(m, "F", 5, "x") == 51  # ride
    assert gm(m, "E", 5) == 50  # high tom
    assert gm(m, "D", 5) == 47  # mid tom
    assert gm(m, "C", 5) == 38  # snare
    assert gm(m, "C", 5, "hollow") == 38  # a half-note snare is still the snare
    assert gm(m, "C", 5, ghost=True, accent=True) == 38
    assert gm(m, "A", 4) == 43  # floor tom
    assert gm(m, "F", 4) == 36  # kick
    assert gm(m, "D", 4, "x") == 44  # pedal hi-hat
    assert gm(m, "G", 5, "circle-x") == 46


def test_unknown_positions_fall_back_to_the_nearest_of_the_same_kind():
    m = Mapping()
    assert gm(m, "B", 3) in (35, 36)  # far below the staff: the lowest drum (a kick)
    assert gm(m, "B", 5, "x") in (49, 57)  # above the crash line: a crash
    assert gm(m, "E", 5, "x") in (51, 42)  # x on a tom line: a cymbal nearby


def test_presets_and_overrides():
    assert {"default", "gp", "musescore"} <= set(PRESETS)
    gp = Mapping("gp")
    assert gm(gp, "D", 5) == 48
    m = Mapping("default", {"C5:normal": 40, "G5:x": 46})
    assert gm(m, "C", 5) == 40
    assert gm(m, "G", 5, "x") == 46
    assert gm(m, "F", 4) == 36  # untouched
    with pytest.raises(ValueError):
        Mapping("nope")
    with pytest.raises(ValueError):
        Mapping("default", {"C5:normal": 200})
    with pytest.raises(ValueError):
        Mapping("default", {"Q9:zz": 38})
    again = Mapping.from_dict(m.to_dict())
    assert again == m


def test_keys_and_families():
    assert head_family("hollow") == "normal"
    assert head_family("circle-x") == "circle-x"
    assert note_key(DrumNote("G", 5, "x", open=True)) == "G5:x:open"
    assert note_key(DrumNote("C", 5, "hollow")) == "C5:normal"
    for g, inst in INSTRUMENTS.items():
        assert 27 <= g <= 87 and inst.label and inst.name


def test_used_keys_counts_the_notes_of_a_score():
    beats = [
        Beat(0, 8, notes=[DrumNote("G", 5, "x"), DrumNote("F", 4)]),
        Beat(0, 8, notes=[DrumNote("G", 5, "x", open=True)]),
        Beat(0, 8, notes=[DrumNote("G", 5, "x")]),
    ]
    score = DrumScore(measures=[DrumMeasure([beats])])
    assert used_keys(score.measures) == {"G5:x": 2, "F4:normal": 1, "G5:x:open": 1}
