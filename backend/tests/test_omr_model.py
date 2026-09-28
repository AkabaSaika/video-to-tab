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
