import xml.etree.ElementTree as ET
from fractions import Fraction as F

import pytest

from app.drums.export import midi, musicxml, place
from app.drums.instruments import Mapping
from app.drums.model import Beat, DrumMeasure, DrumNote, DrumScore
from tests.drum_midi import read

music21 = pytest.importorskip("music21")

HH, SN, BD = DrumNote("G", 5, "x"), DrumNote("C", 5), DrumNote("F", 4)
PEDAL = DrumNote("D", 4, "x")


def groove() -> DrumScore:
    """Two bars: 8th hi-hats, snare on 2 and 4 (accented on 4), kick on 1 and 3, an open
    hi-hat, a ghost note; the pedal voice has no rests (Guitar Pro style)."""
    v1 = []
    for i in range(8):
        notes = [HH if i != 7 else DrumNote("G", 5, "x", open=True)]
        if i in (2, 6):
            notes.append(DrumNote("C", 5, accent=i == 6))
        if i in (0, 4):
            notes.append(BD)
        v1.append(Beat(F(i, 8), 8, notes=notes))
    v2 = [Beat(F(1, 4), 4, notes=[PEDAL]), Beat(F(3, 4), 8, notes=[PEDAL])]
    bar2 = [
        Beat(F(0), 4, notes=[DrumNote("A", 5, "x"), BD]),
        Beat(F(1, 4), 4, rest=True),
        Beat(F(1, 2), 16, notes=[SN]),
        Beat(F(9, 16), 16, notes=[DrumNote("C", 5, ghost=True)]),
        Beat(F(5, 8), 8, notes=[DrumNote("E", 5)]),
        Beat(F(3, 4), 8, tuplet=3, notes=[DrumNote("D", 5)]),
        Beat(F(3, 4) + F(1, 12), 8, tuplet=3, notes=[DrumNote("D", 5)]),
        Beat(F(3, 4) + F(2, 12), 8, tuplet=3, notes=[DrumNote("A", 4)]),
    ]
    return DrumScore("Groove", 96, (4, 4), [DrumMeasure([v1, v2]), DrumMeasure([bar2, []])])


def events(score: DrumScore, mapping: Mapping) -> list[tuple[int, F, int]]:
    """(measure, onset in quarters, GM key) of every note, the way the map reads it."""
    out = []
    for mi, m in enumerate(score.measures):
        for v in m.voices:
            for b in v:
                out += [(mi, b.onset * 4, mapping.resolve(n)) for n in b.notes]
    return sorted(out)


def read_back(xml: str) -> list[tuple[int, F, int]]:
    """music21 gives onsets and positions; it keeps only the part's first instrument, so
    each note's <instrument id> (in document order, like music21's notes) comes from the
    XML itself and its <midi-unpitched> gives the GM key."""
    root = ET.fromstring(xml.split("\n", 2)[2])
    gm = {
        mi.get("id"): int(mi.find("midi-unpitched").text) - 1 for mi in root.iter("midi-instrument")
    }
    for mi in root.iter("midi-instrument"):
        assert mi.find("midi-channel").text == "10"
    ids = [n.find("instrument").get("id") for n in root.iter("note") if n.find("rest") is None]
    parsed = music21.converter.parseData(xml, format="musicxml")
    notes = []
    for mi, m in enumerate(parsed.parts[0].getElementsByClass("Measure")):
        for v in m.voices or [m]:
            for n in v.notes:
                subs = n.notes if isinstance(n, music21.chord.ChordBase) else [n]
                for u in subs:
                    assert isinstance(u, music21.note.Unpitched)
                    notes.append((mi, F(n.getOffsetInHierarchy(m)).limit_denominator(96), u))
    assert len(ids) == len(notes)
    # music21 lists voice by voice, as written; pair them in that order
    return sorted((mi, on, gm[i]) for (mi, on, _), i in zip(notes, ids, strict=True))


def test_musicxml_reads_back_with_the_same_instruments_and_onsets():
    s = groove()
    xml = musicxml(s)
    assert read_back(xml) == events(s, Mapping())
    root = ET.fromstring(xml.split("\n", 2)[2])
    assert root.find("part/measure/attributes/clef/sign").text == "percussion"
    heads = [n.find("notehead") for n in root.iter("note")]
    assert sum(h is not None and h.text == "x" for h in heads) >= 8
    assert any(h is not None and h.get("parentheses") == "yes" for h in heads)
    assert len(root.findall(".//articulations/accent")) == 1
    assert len(root.findall(".//technical/open-string")) == 1
    assert root.find(".//sound").get("tempo") == "96"
    # the pedal voice has no rests: the gaps are invisible <forward>s
    m1 = root.find("part/measure")
    assert all(n.find("rest") is None for n in m1.iter("note"))
    assert m1.find("forward") is not None


def test_midi_has_gm_keys_on_channel_10_at_the_right_ticks():
    s = groove()
    data = read(midi(s))
    assert data["format"] == 1 and data["ppq"] == 480
    conductor, drums = data["tracks"]
    assert (0, "tempo", 60_000_000 // 96) in conductor
    assert (0, "time", 4, 4) in conductor
    ons = [e for e in drums if e[1] == "on"]
    assert {e[2] for e in ons} == {10}
    got = sorted((t, key) for t, _, _, key, _ in ons)
    want = sorted((mi * 1920 + int(on * 480), key) for mi, on, key in events(s, Mapping()))
    assert got == want
    vel = {(t, key): v for t, _, _, key, v in ons}
    assert vel[(1920 * 0 + 3 * 480, 38)] > vel[(480, 38)]  # the accent
    assert vel[(1920 + int(F(9, 4) * 480), 38)] < vel[(480, 38)]  # the ghost note
    assert (7 * 240, 46) in got  # the open hi-hat
    offs = [e for e in drums if e[1] == "off"]
    assert len(offs) == len(ons)


def test_changing_the_map_changes_both_exports_without_recognizing_again():
    s = groove()
    custom = Mapping("default", {"C5:normal": 40, "F4:normal": 35})
    xml_a, xml_b = musicxml(s), musicxml(s, custom)
    assert xml_a != xml_b
    keys_b = {k for _, _, k in read_back(xml_b)}
    assert 40 in keys_b and 35 in keys_b and 38 not in keys_b and 36 not in keys_b
    ons = [e for e in read(midi(s, custom))["tracks"][1] if e[1] == "on"]
    assert {e[3] for e in ons} >= {40, 35} and not {e[3] for e in ons} & {36, 38}


def test_time_signature_changes_and_empty_measures():
    s = DrumScore(
        "",
        120,
        (4, 4),
        [DrumMeasure([[]]), DrumMeasure([[Beat(F(0), 4, dots=1, notes=[SN])]], time=(6, 8))],
    )
    root = ET.fromstring(musicxml(s).split("\n", 2)[2])
    ms = root.findall("part/measure")
    assert ms[0].find("note/rest").get("measure") == "yes"
    assert ms[1].find("attributes/time/beats").text == "6"
    conductor = read(midi(s))["tracks"][0]
    assert (1920, "time", 6, 8) in conductor


def test_overlapping_or_overlong_beats_are_made_writable():
    voice = [
        Beat(F(0), 2, notes=[SN]),  # a half note ...
        Beat(F(1, 4), 4, notes=[SN]),  # ... cut short by the next beat
        Beat(F(1, 4), 8, notes=[BD]),  # same onset again: moves after the previous
        Beat(F(15, 16), 4, notes=[SN]),  # runs past the bar line
        Beat(F(1), 4, notes=[SN]),  # starts after it: dropped
    ]
    placed = place(voice, F(1))
    assert [p.start for p in placed] == [F(0), F(1, 4), F(1, 2), F(15, 16)]
    assert all(a.start + a.length <= b.start for a, b in zip(placed, placed[1:], strict=False))
    assert placed[-1].start + placed[-1].length <= 1
    assert placed[0].duration == 4


def test_noteheads_follow_the_instrument():
    """A Guitar Pro circled cross on the hi-hat line is an open hi-hat: written as a
    cross with an "o" (what Verovio and MuseScore draw); a remapped position gets the
    new drum's notehead."""
    beats = [
        Beat(F(0), 4, notes=[DrumNote("G", 5, "circle-x")]),
        Beat(F(1, 4), 4, notes=[DrumNote("C", 5)]),
        Beat(F(1, 2), 4, notes=[DrumNote("F", 5, "x")]),
    ]
    s = DrumScore("", 120, (4, 4), [DrumMeasure([beats])])
    notes = ET.fromstring(musicxml(s).split("\n", 2)[2]).findall(".//note")
    heads = [n.findtext("notehead") for n in notes]
    assert heads == ["x", None, "x"]
    assert notes[0].find("notations/technical/open-string") is not None
    moved = Mapping("default", {"C5:normal": 42, "F5:x": 53})
    notes = ET.fromstring(musicxml(s, moved).split("\n", 2)[2]).findall(".//note")
    assert [n.findtext("notehead") for n in notes] == ["x", "x", "diamond"]
