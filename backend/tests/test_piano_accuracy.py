"""End to end on the synthetic scrolling video: capture -> homr -> merge, scored against
the ground-truth MusicXML. Needs the homr models (skipped without them) and music21."""

import json

import pytest

from app.piano import engine
from app.piano.capture import capture
from app.piano.merge import merge
from tests.piano_data import DATA, meta, needs_models, system_crop
from tests.piano_synth import piano_scroll_video

music21 = pytest.importorskip("music21")
from tests.piano_eval import evaluate, measures_of  # noqa: E402


def ground_truth() -> list[dict]:
    out = []
    for piece in meta()["pieces"]:
        out += measures_of(music21.converter.parse(DATA / f"{piece}.musicxml"))
    return out


def score_of(xml: str) -> dict:
    parsed = music21.converter.parseData(xml, format="musicxml")
    return evaluate(ground_truth(), measures_of(parsed))


@needs_models()
def test_scrolling_video_end_to_end_accuracy(tmp_path):
    video = piano_scroll_video(tmp_path / "scroll.avi")
    systems = capture(video)
    assert len(systems) == len(meta()["systems"])
    from_video = score_of(merge([engine.recognize(s.image) for s in systems]))
    # the same systems cut straight from the rendered score: capture must lose nothing
    direct = score_of(
        merge([engine.recognize(system_crop(i)) for i in range(len(meta()["systems"]))])
    )
    print("\npiano accuracy", json.dumps({"video": from_video, "direct": direct}))
    assert from_video["pitch_recall"] >= 0.95
    assert from_video["pitch_precision"] >= 0.95
    assert from_video["duration_of_matched"] >= 0.9
    assert from_video["pitch_recall"] >= direct["pitch_recall"] - 0.02
