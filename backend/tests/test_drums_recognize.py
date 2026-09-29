"""Recognition accuracy on the spike's 8 ground-truth pieces, and the special cases."""

import json
from collections import Counter
from fractions import Fraction

import cv2
import pytest

from app.drums.recognize import recognize
from tests.drum_data import gt_measures, image, meta, predicted, rates, score

GATES = {"clean": 0.90, "deg": 0.80}  # recall and precision; 1280 and lily are reported only


def run(variant: str) -> dict:
    total: Counter = Counter()
    per = {}
    for piece in meta()["accuracy"]:
        m = meta()["pieces"][piece]
        if variant == "lily" and not m.get("lily"):
            continue
        page = recognize(image(piece, variant))
        c = score(gt_measures(m["events"], m["measures"]), predicted(page.measures))
        total += c
        per[piece] = round(c["inst"] / max(c["gt"], 1), 2)
    return rates(total) | {"per_piece": per}


@pytest.mark.parametrize("variant", ["clean", "deg", "1280", "lily"])
def test_instrument_and_onset_accuracy(variant):
    result = run(variant)
    print(f"\ndrum accuracy {variant}", json.dumps(result, ensure_ascii=False))
    if variant in GATES:
        assert result["recall"] >= GATES[variant]
        assert result["precision"] >= GATES[variant]


def test_reads_the_printed_time_signature_and_otherwise_knows_it_did_not():
    assert recognize(image("shuffle")).time == (12, 8)
    assert recognize(image("rock8")).time == (4, 4)
    assert recognize(image("hh16", "deg")).time == (4, 4)
    # no time signature printed (a later line of a strip): None, the caller decides
    img = image("hh16")
    page = recognize(img)
    assert page.staff_x0 < page.header_end
    blank = img.copy()
    blank[:, : int(page.header_end)] = 255
    assert recognize(blank).time is None
    # a time given by the caller wins, and the measures are solved with it
    forced = recognize(image("shuffle"), time=(4, 4))
    assert forced.time == (12, 8)  # what is printed is still reported
    assert all(m.time == (4, 4) for m in forced.measures)


def test_12_8_measures_are_solved_in_12_8():
    page = recognize(image("shuffle"))
    assert [m.time for m in page.measures] == [(12, 8)] * 4
    assert sum(bool(m.ok) for m in page.measures) >= 3


def test_single_voice_layout_takes_the_pedal_onsets_from_the_hands():
    """Guitar Pro: kick on the hands' up stems, the pedal voice without rests. Its
    onsets cannot come from adding up durations, only from lining up with voice 1."""
    m = meta()["pieces"]["gpsingle"]
    page = recognize(image("gpsingle"))
    gt = gt_measures(m["events"], m["measures"])
    pr = predicted(page.measures)
    assert len(pr) == len(gt)
    for i, (g, p) in enumerate(zip(gt, pr, strict=True)):
        want = sorted(e[1] for e in g if e[3] == "ph")
        got = sorted(e[1] for e in p if e[3] == "ph")
        assert got == want, i
    # the last measure: the hands start on beat 2 without a rest and the kicks of beat 1
    # are on down stems, so neither voice adds up alone; together they do
    want = sorted((e[1], e[3]) for e in gt[-1] if e[3] != "rest")
    assert sorted((e[1], e[3]) for e in pr[-1] if e[3] != "rest") == want
    assert page.measures[-1].ok
    assert rates(score(gt, pr))["recall"] >= 0.95


def test_measures_carry_raw_positions_and_noteheads():
    page = recognize(image("openhh"))
    notes = [n for mm in page.measures for v in mm.voices for b in v for n in b.notes]
    assert {n.notehead for n in notes} >= {"x", "normal"}
    assert sum(n.open for n in notes) >= 6  # 8 open hi-hats in the piece
    assert {(n.step, n.octave) for n in notes} >= {("G", 5), ("C", 5), ("F", 4), ("D", 4)}
    first = page.measures[0].voices[0]
    assert first[0].onset == Fraction(0)


def test_blank_or_noise_gives_no_measures():
    assert recognize(cv2.cvtColor(image("rock8")[:40, :400], cv2.COLOR_BGR2GRAY)).measures == []
