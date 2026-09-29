import time
import xml.etree.ElementTree as ET

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.piano import workflow
from app.piano.engine import EngineError
from app.piano.jobs import PianoStore
from tests.piano_synth import piano_page_video
from tests.test_piano_merge import attrs, note, system


def fake_xml(pitch: str = "C") -> str:
    return system(
        attrs() + note(pitch, 5) + "<backup><duration>4</duration></backup>" + note("C", 3, 2)
    )


@pytest.fixture(scope="module")
def video(tmp_path_factory):
    return piano_page_video(tmp_path_factory.mktemp("pv") / "pages.avi", seconds=1.0)


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def recognize(image, variant=0):
        seen.append((image.shape, variant))
        if len(seen) == 3:
            raise EngineError("没有识别出乐谱")
        return fake_xml()

    monkeypatch.setattr(workflow, "recognize_image", recognize)
    return seen


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path / "jobs", piano_dir=tmp_path / "piano"))


def wait(client, job_id, status="ready", timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/piano/jobs/{job_id}").json()
        if job["status"] == status:
            return job
        assert job["status"] != "failed", job["error"]
        time.sleep(0.1)
    raise AssertionError(job)


def upload(client, video):
    with video.open("rb") as f:
        r = client.post("/api/piano/jobs", files={"file": ("elise.avi", f, "video/x-msvideo")})
    assert r.status_code == 200, r.text
    return r.json()


def test_full_flow(client, video, calls, tmp_path):
    job = wait(client, upload(client, video)["id"])
    systems = job["systems"]
    assert len(systems) == 8
    assert [s["id"] for s in systems] == list(range(8))
    assert [s["ok"] for s in systems] == [True, True, False] + [True] * 5
    assert systems[2]["error"] == "没有识别出乐谱" and systems[2]["musicxml"] is None
    assert systems[0]["image"] == "systems/000.png"
    assert systems[0]["musicxml"] == "systems/000.musicxml"
    assert (tmp_path / "piano" / job["id"] / "systems" / "007.png").is_file()
    assert client.get(f"/api/piano/jobs/{job['id']}/files/systems/000.png").status_code == 200
    assert client.get(f"/api/piano/jobs/{job['id']}/files/../state.json").status_code == 404
    assert job["title"] == "elise"

    listed = client.get("/api/piano/jobs").json()
    assert [j["id"] for j in listed] == [job["id"]]
    assert client.get("/api/jobs").json() == []  # guitar jobs are separate

    r = client.get(f"/api/piano/jobs/{job['id']}/musicxml")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    assert len(ET.fromstring(r.content).findall("part/measure")) == 7  # the failed one is out

    # re-recognize the failed system: the engine gets another view of it
    r = client.post(f"/api/piano/jobs/{job['id']}/systems/2/recognize")
    assert r.status_code == 200, r.text
    assert r.json()["systems"][2]["ok"] is True
    assert calls[-1][1] == 1

    r = client.delete(f"/api/piano/jobs/{job['id']}/systems/0")
    assert r.status_code == 200
    assert [s["id"] for s in r.json()["systems"]] == list(range(1, 8))
    assert not (tmp_path / "piano" / job["id"] / "systems" / "000.png").exists()
    r = client.get(f"/api/piano/jobs/{job['id']}/musicxml")
    assert len(ET.fromstring(r.content).findall("part/measure")) == 7

    assert client.delete(f"/api/piano/jobs/{job['id']}/systems/0").status_code == 404
    assert client.post(f"/api/piano/jobs/{job['id']}/systems/99/recognize").status_code == 404

    # restart: the store reloads the job from disk
    again = PianoStore(tmp_path / "piano").get(job["id"])
    assert len(again.systems) == 7 and again.status == "ready"


def test_rejects_bad_input(client):
    assert client.post("/api/piano/jobs").status_code == 400
    r = client.post("/api/piano/jobs", data={"url": "https://example.com/v"})
    assert r.status_code == 400
    assert "bilibili" in r.json()["detail"]
    assert client.get("/api/piano/jobs/nope").status_code == 404
    r = client.post("/api/piano/jobs", files={"file": ("a.txt", b"x", "text/plain")})
    assert r.status_code == 400


def test_video_without_music_fails_with_a_message(client, tmp_path, calls):
    path = tmp_path / "blank.avi"
    out = cv2.VideoWriter(str(path), cv2.VideoWriter.fourcc(*"MJPG"), 5, (320, 240))
    for _ in range(10):
        out.write(np.full((240, 320, 3), 255, np.uint8))
    out.release()
    job = upload(client, path)
    job = wait(client, job["id"], "failed")
    assert "大谱表" in job["error"]


def test_url_jobs_download_first(client, video, calls, monkeypatch):
    import shutil

    def download(url, dest, cookies=None, on_progress=lambda f: None):
        on_progress(0.5)
        return shutil.copy(video, dest / "source.avi") and dest / "source.avi"

    monkeypatch.setattr(workflow, "download_url", download)
    r = client.post("/api/piano/jobs", data={"url": "BV1xx411c7mD"})
    assert r.status_code == 200, r.text
    job = wait(client, r.json()["id"])
    assert job["source"] == "https://www.bilibili.com/video/BV1xx411c7mD"
    assert len(job["systems"]) == 8


def test_busy_jobs_refuse_edits(client, tmp_path):
    store = client.app.state.piano_store
    job = store.create()
    store.update(job, status="recognizing", systems=[{"id": 0, "image": "x.png"}])
    assert client.delete(f"/api/piano/jobs/{job.id}/systems/0").status_code == 409
    assert client.post(f"/api/piano/jobs/{job.id}/systems/0/recognize").status_code == 409
    # a job cut short by a restart is failed on reload
    assert PianoStore(tmp_path / "piano").get(job.id).status == "failed"
