import re
from pathlib import Path

import pytest

from app.omr.model import Beat, Measure, Note, Score

GP = Path(__file__).parents[2] / "data" / "tabs" / "[7弦]AveMujica+KiLLKiSS.gp"


def test_score_round_trips_through_dict():
    score = Score(7, [35], 120, [Measure(5, (4, 4), [Beat(8, 0, None, False, [Note(0, 3)])])])
    assert Score.from_dict(score.to_dict()) == score


@pytest.mark.skipif(not GP.exists(), reason="ground-truth file not available")
def test_gpif_reads_known_measures():
    from app.omr.gpif import read_track

    score = read_track(GP, "Guitar Mutsumi")
    assert score.strings == 7 and score.tuning[0] == 33
    m14 = score.measures[13]
    assert [b.duration for b in m14.beats] == [4, 8, 4, 8, 4]
    assert {(n.string, n.fret) for n in m14.beats[0].notes} == {(0, 7), (1, 7)}
    assert all(sum(b.length() for b in m.beats) in (0, 1) for m in score.measures)


def test_unknown_track_name_is_a_clear_error(tmp_path):
    import zipfile

    from app.omr.gpif import read_track

    gp = tmp_path / "t.gp"
    with zipfile.ZipFile(gp, "w") as z:
        z.writestr(
            "Content/score.gpif",
            "<GPIF><Tracks><Track id='0'><Name>Lead</Name></Track>"
            "</Tracks><MasterBars/><Bars/><Voices/><Beats/><Notes/><Rhythms/></GPIF>",
        )
    with pytest.raises(ValueError, match="Lead"):
        read_track(gp, "Bass")


def test_score_title_round_trips_and_defaults():
    assert Score.from_dict({}).title == ""
    assert Score.from_dict({}) == Score()
    score = Score(6, [40, 45, 50, 55, 59, 64], None, [], "My Song")
    assert Score.from_dict(score.to_dict()) == score


def test_from_dict_fills_missing_fields_with_defaults():
    score = Score.from_dict({"measures": [{"beats": [{"notes": [{"string": 2, "fret": 5}]}]}]})
    beat = score.measures[0].beats[0]
    assert beat.duration == 4 and beat.confidence == 1.0 and not beat.rest
    assert beat.notes == [Note(2, 5)]
    assert score.measures[0].time == (4, 4)


@pytest.mark.parametrize(
    ("data", "where"),
    [
        ([], "乐谱"),
        ({"strings": "7"}, "strings"),
        ({"strings": True}, "strings"),
        ({"tuning": [40, "A"]}, "tuning"),
        ({"title": 3}, "title"),
        ({"measures": {}}, "measures"),
        ({"measures": [{"time": [4]}]}, "measures[0].time"),
        ({"measures": [{"beats": [{"duration": 4.5}]}]}, "measures[0].beats[0].duration"),
        ({"measures": [{"beats": [{"rest": 1}]}]}, "measures[0].beats[0].rest"),
        ({"measures": [{"beats": [{"notes": [{"fret": None}]}]}]}, "notes[0].fret"),
        ({"measures": [{"beats": [{"notes": [{"confidence": "x"}]}]}]}, "confidence"),
    ],
)
def test_from_dict_rejects_wrong_types(data, where):
    with pytest.raises(ValueError, match=re.escape(where)):
        Score.from_dict(data)


def _numbered(*numbers):
    return Score(
        7, [], None, [Measure(n, (4, 4), [Beat(4, notes=[Note(0, n)])], line=0) for n in numbers]
    )


def test_pad_numbers_adds_unflagged_leading_rests():
    from app.omr.model import pad_numbers

    score = _numbered(3, 4)
    padded = pad_numbers(score)
    assert [m.number for m in padded.measures] == [1, 2, 3, 4]
    for m in padded.measures[:2]:
        assert m.line == -1 and m.confidence == 1.0
        assert [(b.duration, b.rest, b.notes) for b in m.beats] == [(1, True, [])]
    assert padded.measures[2:] == score.measures
    assert [m.number for m in score.measures] == [3, 4]  # input untouched


def test_pad_numbers_fills_gaps_with_flagged_rests():
    from app.omr.model import pad_numbers

    padded = pad_numbers(_numbered(1, 2, 5))
    assert [m.number for m in padded.measures] == [1, 2, 3, 4, 5]
    assert [(m.line, m.confidence) for m in padded.measures[2:4]] == [(-1, 0.0), (-1, 0.0)]
    assert padded.measures[4].beats[0].notes == [Note(0, 5)]


def test_pad_numbers_leaves_non_increasing_numbers_alone():
    from app.omr.model import pad_numbers

    for numbers in [(3, 3, 4), (5, 4), (2, None, 4), (0, 1)]:
        score = _numbered(*numbers)
        assert pad_numbers(score) == score


def test_pad_numbers_on_empty_score():
    from app.omr.model import pad_numbers

    assert pad_numbers(Score()) == Score()


def test_note_tied_defaults_false_and_round_trips():
    assert Note(0, 3).tied is False
    score = Score(6, [], None, [Measure(1, (4, 4), [Beat(4, notes=[Note(0, 3, tied=True)])])])
    assert Score.from_dict(score.to_dict()) == score
    with pytest.raises(ValueError, match="tied"):
        Score.from_dict({"measures": [{"beats": [{"notes": [{"tied": 1}]}]}]})


def test_song_round_trips_with_named_tracks():
    from app.omr.model import Song

    gt1 = Score(6, [40, 45, 50, 55, 59, 64], None, [Measure(1, beats=[Beat(4)])], name="Gt.1")
    gt2 = Score(7, [35, 40, 45, 50, 55, 59, 64], None, [], name="Gt.2")
    song = Song("My Song", 180, [gt1, gt2])
    data = song.to_dict()
    assert data["title"] == "My Song" and data["tempo"] == 180
    assert [t["name"] for t in data["tracks"]] == ["Gt.1", "Gt.2"]
    assert Song.from_dict(data) == song


def test_song_from_old_single_score_json_wraps_it():
    from app.omr.model import Song

    old = Score(6, [40, 45, 50, 55, 59, 64], 150, [Measure(1, beats=[Beat(4)])], "Old")
    song = Song.from_dict(old.to_dict())
    assert song.title == "Old" and song.tempo == 150
    assert len(song.tracks) == 1
    assert song.tracks[0].measures == old.measures
    assert song.tracks[0].strings == 6 and song.tracks[0].tuning == old.tuning


@pytest.mark.parametrize(
    ("data", "where"),
    [
        ({"tracks": {}}, "tracks"),
        ({"tracks": [3]}, "tracks[0]"),
        ({"tracks": [{"strings": "6"}]}, "tracks[0].strings"),
        ({"tracks": [{"name": 1}]}, "tracks[0].name"),
        ({"tracks": [], "title": 3}, "title"),
        ({"tracks": [], "tempo": "fast"}, "tempo"),
    ],
)
def test_song_from_dict_rejects_wrong_types(data, where):
    from app.omr.model import Song

    with pytest.raises(ValueError, match=re.escape(where)):
        Song.from_dict(data)


def _note_xml(nid, string, fret, tie=None):
    tie_xml = f"<Tie origin='false' destination='{tie}'/>" if tie else ""
    return (
        f"<Note id='{nid}'>{tie_xml}<Properties>"
        f"<Property name='String'><String>{string}</String></Property>"
        f"<Property name='Fret'><Fret>{fret}</Fret></Property></Properties></Note>"
    )


def test_gpif_reads_tie_destinations(tmp_path):
    import zipfile

    from app.omr.gpif import read_track

    gp = tmp_path / "t.gp"
    with zipfile.ZipFile(gp, "w") as z:
        z.writestr(
            "Content/score.gpif",
            "<GPIF><Tracks><Track id='0'><Name>Lead</Name></Track></Tracks>"
            "<MasterBars><MasterBar><Time>4/4</Time><Bars>0</Bars></MasterBar></MasterBars>"
            "<Bars><Bar id='0'><Voices>0 -1 -1 -1</Voices></Bar></Bars>"
            "<Voices><Voice id='0'><Beats>0 1</Beats></Voice></Voices>"
            "<Beats><Beat id='0'><Rhythm ref='0'/><Notes>0</Notes></Beat>"
            "<Beat id='1'><Rhythm ref='0'/><Notes>1 2</Notes></Beat></Beats>"
            "<Notes>"
            + _note_xml(0, 2, 14)
            + _note_xml(1, 2, 14, tie="true")
            + _note_xml(2, 0, 3, tie="false")
            + "</Notes><Rhythms><Rhythm id='0'><NoteValue>Half</NoteValue></Rhythm></Rhythms>"
            "</GPIF>",
        )
    beats = read_track(gp, "Lead").measures[0].beats
    assert [(n.string, n.fret, n.tied) for n in beats[0].notes] == [(2, 14, False)]
    assert [(n.string, n.fret, n.tied) for n in beats[1].notes] == [(0, 3, False), (2, 14, True)]


# ---------------------------------------------------------------- playing techniques


def test_note_techniques_default_off_and_round_trip():
    n = Note(0, 3)
    assert (n.bend, n.bend_release, n.slide, n.slide_in, n.hopo) == (None, False, None, None, False)
    assert (n.harmonic, n.harmonic_fret, n.vibrato, n.palm_mute, n.staccato) == (
        None,
        None,
        False,
        False,
        False,
    )
    rich = Note(
        3,
        8,
        bend=2.0,
        bend_release=True,
        slide="legato",
        slide_in="below",
        hopo=True,
        harmonic="artificial",
        harmonic_fret=5.0,
        vibrato=True,
        palm_mute=True,
        staccato=True,
    )
    score = Score(7, [], None, [Measure(1, (4, 4), [Beat(4, notes=[rich])])])
    assert Score.from_dict(score.to_dict()) == score


@pytest.mark.parametrize(
    ("note", "where"),
    [
        ({"bend": "full"}, "bend"),
        ({"bend_release": 1}, "bend_release"),
        ({"slide": "sideways"}, "slide"),
        ({"slide_in": 3}, "slide_in"),
        ({"hopo": "yes"}, "hopo"),
        ({"harmonic": "loud"}, "harmonic"),
        ({"harmonic_fret": "12"}, "harmonic_fret"),
        ({"vibrato": None}, "vibrato"),
        ({"palm_mute": 0}, "palm_mute"),
        ({"staccato": "no"}, "staccato"),
    ],
)
def test_from_dict_rejects_bad_techniques(note, where):
    with pytest.raises(ValueError, match=re.escape(f"notes[0].{where}")):
        Score.from_dict({"measures": [{"beats": [{"notes": [note]}]}]})


def _prop(name, inner=""):
    return f"<Property name='{name}'>{inner}</Property>"


def test_gpif_reads_techniques(tmp_path):
    """Property shapes as Guitar Pro 8 and alphaTab's Gp7Exporter write them."""
    import zipfile

    from app.omr.gpif import read_track

    def note(nid, fret, props="", elems=""):
        return (
            f"<Note id='{nid}'>{elems}<Properties>"
            f"<Property name='String'><String>3</String></Property>"
            f"<Property name='Fret'><Fret>{fret}</Fret></Property>{props}</Properties></Note>"
        )

    f = "<Float>{}</Float>"
    bend = (
        _prop("Bended", "<Enable/>")
        + _prop("BendOriginValue", f.format(0))
        + _prop("BendMiddleValue", f.format(25))
        + _prop("BendDestinationValue", f.format(50))
    )
    release = (
        _prop("Bended", "<Enable/>")
        + _prop("BendOriginValue", f.format(0))
        + _prop("BendMiddleValue", f.format(100))
        + _prop("BendDestinationValue", f.format(0))
    )
    notes = [
        note(
            0,
            8,
            bend
            + _prop("HarmonicType", "<HType>Semi</HType>")
            + _prop("HarmonicFret", "<HFret>5.000000</HFret>"),
        ),
        note(1, 5, release),
        note(2, 5, _prop("Slide", "<Flags>18</Flags>")),  # legato out + in from below
        note(3, 7, _prop("HopoOrigin", "<Enable/>")),
        note(4, 5, _prop("HopoDestination", "<Enable/>")),
        note(5, 7, _prop("PalmMuted", "<Enable/>")),
        note(6, 7, "", "<Accent>1</Accent>"),
        note(7, 4, "", "<Vibrato>Slight</Vibrato>"),
        note(
            8,
            12,
            _prop("Harmonic", "<Enable/>")
            + _prop("HarmonicType", "<HType>Natural</HType>")
            + _prop("HarmonicFret", "<HFret>12</HFret>"),
        ),
        note(9, 4, _prop("Slide", "<Flags>4</Flags>"), "<Accent>8</Accent>"),
    ]
    k = len(notes)
    ids = range(k)
    gp = tmp_path / "t.gp"
    with zipfile.ZipFile(gp, "w") as z:
        z.writestr(
            "Content/score.gpif",
            "<GPIF><Tracks><Track id='0'><Name>Lead</Name></Track></Tracks>"
            "<MasterBars><MasterBar><Time>4/4</Time><Bars>0</Bars></MasterBar></MasterBars>"
            "<Bars><Bar id='0'><Voices>0 -1 -1 -1</Voices></Bar></Bars>"
            f"<Voices><Voice id='0'><Beats>{' '.join(map(str, range(k)))}</Beats></Voice></Voices>"
            "<Beats>"
            + "".join(f"<Beat id='{i}'><Rhythm ref='0'/><Notes>{i}</Notes></Beat>" for i in ids)
            + "</Beats><Notes>"
            + "".join(notes)
            + "</Notes><Rhythms><Rhythm id='0'><NoteValue>16th</NoteValue></Rhythm></Rhythms>"
            "</GPIF>",
        )
    got = [b.notes[0] for b in read_track(gp, "Lead").measures[0].beats]
    assert (got[0].bend, got[0].bend_release, got[0].harmonic, got[0].harmonic_fret) == (
        1.0,
        False,
        "semi",
        5.0,
    )
    assert (got[1].bend, got[1].bend_release) == (2.0, True)
    assert (got[2].slide, got[2].slide_in) == ("legato", "below")
    assert got[3].hopo and not got[4].hopo
    assert got[5].palm_mute and not got[4].palm_mute
    assert got[6].staccato and not got[9].staccato  # 8 is an accent, not staccato
    assert got[7].vibrato and not got[6].vibrato
    assert (got[8].harmonic, got[8].harmonic_fret) == ("natural", 12.0)
    assert (got[9].slide, got[9].slide_in) == ("out_down", None)
    assert got[5].bend is None and got[5].slide is None and got[5].harmonic is None
