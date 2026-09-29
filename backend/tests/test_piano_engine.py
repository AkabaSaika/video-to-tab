import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest

from app.piano import engine
from tests.piano_data import meta, needs_models, system_crop


def test_model_dir_from_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("VTT_HOMR_MODELS", str(tmp_path))
    assert engine.model_dir() == tmp_path


def test_ensure_models_fetches_only_missing_files(tmp_path):
    first = engine.MODEL_FILES[0]
    (tmp_path / first).write_bytes(b"x")
    fetched = []

    def fetch(name: str, dest: Path) -> None:
        fetched.append(name)
        (dest / name).write_bytes(b"y")

    assert not engine.models_available(tmp_path)
    assert engine.ensure_models(tmp_path, fetch=fetch) == tmp_path
    assert fetched == engine.MODEL_FILES[1:]
    assert engine.models_available(tmp_path)
    engine.ensure_models(tmp_path, fetch=fetch)  # all present: nothing fetched again
    assert len(fetched) == len(engine.MODEL_FILES) - 1


def test_ensure_models_reports_failed_download_in_chinese(tmp_path):
    def fetch(name: str, dest: Path) -> None:
        raise OSError("offline")

    with pytest.raises(engine.EngineError, match="模型"):
        engine.ensure_models(tmp_path, fetch=fetch)


def _pitches(xml: str) -> list[str]:
    root = ET.fromstring(xml)
    out = []
    for p in root.iter("pitch"):
        alter = p.findtext("alter")
        acc = {"1": "#", "-1": "-"}.get(alter or "", "")
        out.append(f"{p.findtext('step')}{acc}{p.findtext('octave')}")
    return out


@needs_models()
def test_recognize_one_grand_staff_system():
    xml = engine.recognize(system_crop(0))
    root = ET.fromstring(xml)
    parts = root.findall("part")
    assert len(parts) == 1
    measures = parts[0].findall("measure")
    assert len(measures) == meta()["systems"][0]["measures"]  # K. 545 m. 1-4
    assert root.find(".//attributes/staves").text == "2"
    first = _pitches(ET.tostring(measures[0], encoding="unicode"))
    assert {"C5", "E5", "G5", "C4", "G4", "E4"} <= set(first)


@needs_models()
def test_recognize_blank_image_fails_cleanly():
    with pytest.raises(engine.EngineError):
        engine.recognize(np.full((300, 1200, 3), 255, np.uint8))
