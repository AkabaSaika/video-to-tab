import time
import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from app.drums.jobs import DrumStore
from app.main import create_app
from tests.drum_midi import read
from tests.drum_synth import gp_strip_video, strip_measures


@pytest.fixture(scope="module")
def video(tmp_path_factory):
    return gp_strip_video(tmp_path_factory.mktemp("dv") / "groove.avi", measure_seconds=0.8)


@pytest.fixture
def client(tmp_path):
    return TestClient(
        create_app(tmp_path / "jobs", piano_dir=tmp_path / "piano", drums_dir=tmp_path / "drums")
    )


def wait(client, job_id, status="ready", timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/drums/jobs/{job_id}").json()
        if job["status"] == status:
            return job
        assert job["status"] != "failed", job["error"]
        time.sleep(0.1)
    raise AssertionError(job)


def upload(client, video, name="groove.avi"):
    with video.open("rb") as f:
        r = client.post("/api/drums/jobs", files={"file": (name, f, "video/x-msvideo")})
    assert r.status_code == 200, r.text
    return r.json()


def root_of(xml: bytes) -> ET.Element:
    return ET.fromstring(xml.decode("utf-8").split("\n", 2)[2])


def measures_of(client, job_id) -> list[ET.Element]:
    r = client.get(f"/api/drums/jobs/{job_id}/musicxml")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    return root_of(r.content).findall("part/measure")


@pytest.fixture
def ready(client, video):
    return wait(client, upload(client, video)["id"])


def test_full_flow(client, ready, tmp_path):
    job = ready
    assert job["mode"] == "strip"
    assert job["title"] == "groove"
    pages = job["pages"]
    assert len(pages) >= 2
    assert [p["id"] for p in pages] == list(range(len(pages)))
    assert all(p["ok"] for p in pages)
    assert sum(p["measures"] for p in pages) == len(strip_measures())
    assert job["detected_time"] == [4, 4] and job["time"] is None and job["tempo"] == 120
    first = pages[0]
    assert first["image"] == "pages/000.png" and first["musicxml"] == "pages/000.musicxml"
    for name in (first["image"], first["musicxml"], first["score"]):
        assert client.get(f"/api/drums/jobs/{job['id']}/files/{name}").status_code == 200
    assert client.get(f"/api/drums/jobs/{job['id']}/files/../state.json").status_code == 404

    assert [j["id"] for j in client.get("/api/drums/jobs").json()] == [job["id"]]
    assert client.get("/api/drums/jobs").json()[0]["pages"] == len(pages)
    assert client.get("/api/jobs").json() == []  # guitar and piano jobs are separate
    assert client.get("/api/piano/jobs").json() == []

    assert len(measures_of(client, job["id"])) == len(strip_measures())
    r = client.get(f"/api/drums/jobs/{job['id']}/midi")
    assert r.status_code == 200 and r.headers["content-type"] == "audio/midi"
    midi = read(r.content)
    assert {e[2] for e in midi["tracks"][1] if e[1] == "on"} == {10}

    # delete a page: its measures leave the export, its files go
    n0 = pages[0]["measures"]
    r = client.delete(f"/api/drums/jobs/{job['id']}/pages/0")
    assert r.status_code == 200
    assert [p["id"] for p in r.json()["pages"]] == list(range(1, len(pages)))
    assert not (tmp_path / "drums" / job["id"] / "pages" / "000.png").exists()
    assert len(measures_of(client, job["id"])) == len(strip_measures()) - n0
    assert client.delete(f"/api/drums/jobs/{job['id']}/pages/0").status_code == 404

    # re-recognize a page: another try, same page
    r = client.post(f"/api/drums/jobs/{job['id']}/pages/1/recognize")
    assert r.status_code == 200, r.text
    again = next(p for p in r.json()["pages"] if p["id"] == 1)
    assert again["attempts"] == 2 and again["ok"]
    assert client.post(f"/api/drums/jobs/{job['id']}/pages/99/recognize").status_code == 404

    # restart: the store reloads the job from disk
    reloaded = DrumStore(tmp_path / "drums").get(job["id"])
    assert len(reloaded.pages) == len(pages) - 1 and reloaded.status == "ready"


def test_mapping_changes_the_exports_without_recognizing_again(client, ready, tmp_path):
    jid = ready["id"]
    m = client.get(f"/api/drums/jobs/{jid}/mapping").json()
    assert m["preset"] == "default" and m["overrides"] == {}
    used = {u["key"]: u for u in m["used"]}
    assert {"G5:x", "C5:normal", "F4:normal"} <= set(used)
    assert used["C5:normal"]["gm"] == 38 and used["C5:normal"]["count"] > 0
    assert {p["id"] for p in m["presets"]} >= {"default", "gp", "musescore"}
    assert any(i["gm"] == 40 and i["label"] for i in m["instruments"])

    page_xml = (tmp_path / "drums" / jid / "pages" / "000.musicxml").read_text()
    r = client.put(
        f"/api/drums/jobs/{jid}/mapping", json={"preset": "gp", "overrides": {"C5:normal": 40}}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mapping"]["used"][0]["gm"] > 0
    assert all(p["attempts"] == 1 for p in body["job"]["pages"])  # no new recognition
    assert (tmp_path / "drums" / jid / "pages" / "000.musicxml").read_text() != page_xml

    xml = client.get(f"/api/drums/jobs/{jid}/musicxml").content.decode()
    assert 'id="P1-I40"' in xml and 'id="P1-I38"' not in xml
    keys = {
        e[3]
        for e in read(client.get(f"/api/drums/jobs/{jid}/midi").content)["tracks"][1]
        if e[1] == "on"
    }
    assert 40 in keys and 38 not in keys
    assert client.get(f"/api/drums/jobs/{jid}/mapping").json()["overrides"] == {"C5:normal": 40}

    bad = client.put(f"/api/drums/jobs/{jid}/mapping", json={"preset": "x", "overrides": {}})
    assert bad.status_code == 400 and "预设" in bad.json()["detail"]
    bad = client.put(
        f"/api/drums/jobs/{jid}/mapping", json={"preset": "gp", "overrides": {"C5:normal": 7}}
    )
    assert bad.status_code == 400


def test_settings_override_the_time_signature_and_set_the_tempo(client, ready):
    jid = ready["id"]
    r = client.put(f"/api/drums/jobs/{jid}/settings", json={"time": [3, 4], "tempo": 90})
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["time"] == [3, 4] and job["tempo"] == 90
    root = root_of(client.get(f"/api/drums/jobs/{jid}/musicxml").content)
    assert root.find("part/measure/attributes/time/beats").text == "3"
    assert root.find(".//sound").get("tempo") == "90"
    conductor = read(client.get(f"/api/drums/jobs/{jid}/midi").content)["tracks"][0]
    assert (0, "time", 3, 4) in conductor and (0, "tempo", 60_000_000 // 90) in conductor
    # back to what the video shows
    job = client.put(f"/api/drums/jobs/{jid}/settings", json={"time": None, "tempo": 90}).json()
    assert job["time"] is None
    root = root_of(client.get(f"/api/drums/jobs/{jid}/musicxml").content)
    assert root.find("part/measure/attributes/time/beats").text == "4"
    for bad in ({"time": [5, 3], "tempo": 90}, {"time": None, "tempo": 5}):
        r = client.put(f"/api/drums/jobs/{jid}/settings", json=bad)
        assert r.status_code in (400, 422)


def test_rejects_bad_input(client):
    assert client.post("/api/drums/jobs").status_code == 400
    r = client.post("/api/drums/jobs", data={"url": "https://example.com/v"})
    assert r.status_code == 400 and "bilibili" in r.json()["detail"]
    assert client.get("/api/drums/jobs/nope").status_code == 404
    assert client.get("/api/drums/jobs/nope/musicxml").status_code == 404
    r = client.post("/api/drums/jobs", files={"file": ("a.txt", b"x", "text/plain")})
    assert r.status_code == 400


def test_video_without_drum_notation_fails_with_a_message(client, tmp_path):
    import cv2
    import numpy as np

    path = tmp_path / "blank.avi"
    out = cv2.VideoWriter(str(path), cv2.VideoWriter.fourcc(*"MJPG"), 10, (320, 240))
    for _ in range(20):
        out.write(np.full((240, 320, 3), 30, np.uint8))
    out.release()
    job = upload(client, path, "blank.avi")
    deadline = time.time() + 30
    while time.time() < deadline:
        job = client.get(f"/api/drums/jobs/{job['id']}").json()
        if job["status"] == "failed":
            break
        time.sleep(0.1)
    assert job["status"] == "failed" and "鼓谱" in job["error"]
    assert client.get(f"/api/drums/jobs/{job['id']}/musicxml").status_code == 404
