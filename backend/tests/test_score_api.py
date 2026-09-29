import json
import time

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.jobs import INTERRUPTED, JobStore, Status
from app.main import create_app
from tests.test_api import wait_for


def upload(client, synth_video):
    with synth_video.path.open("rb") as f:
        r = client.post("/api/jobs", files={"file": ("my.avi", f, "video/x-msvideo")})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def analyzed(client, synth_video):
    job = wait_for(client, upload(client, synth_video), "ready_for_region")
    r = client.put(f"/api/jobs/{job['id']}/region", json=job["region"]["roi"])
    assert r.status_code == 200, r.text
    return wait_for(client, job["id"], "ready_for_review")


def test_recognize_writes_score_and_moves_to_ready_for_score(tmp_path, synth_video):
    client = TestClient(create_app(tmp_path))
    job = analyzed(client, synth_video)
    assert client.get(f"/api/jobs/{job['id']}/score").status_code == 404

    order = [2, 0]  # page C then page A; each synthetic page is one measure
    r = client.post(f"/api/jobs/{job['id']}/recognize", json={"order": order})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "recognizing"
    assert r.json()["stage"] == "recognize"
    job = wait_for(client, job["id"], "ready_for_score")
    assert job["score_order"] == order
    assert job["progress"] == 1.0

    score = client.get(f"/api/jobs/{job['id']}/score").json()
    assert score["strings"] == 6 and score["title"] == ""
    assert [m["line"] for m in score["measures"]] == [0, 1]
    assert all(m["beats"] for m in score["measures"])
    assert json.loads((tmp_path / job["id"] / "score.json").read_text()) == score

    # recognizing again is allowed from ready_for_score
    r = client.post(f"/api/jobs/{job['id']}/recognize", json={"order": [0]})
    assert r.status_code == 200, r.text
    job = wait_for(client, job["id"], "ready_for_score")
    assert job["score_order"] == [0]


def test_recognize_rejects_bad_order_and_wrong_status(tmp_path, synth_video):
    client = TestClient(create_app(tmp_path))
    job_id = upload(client, synth_video)
    wait_for(client, job_id, "ready_for_region")
    r = client.post(f"/api/jobs/{job_id}/recognize", json={"order": []})
    assert r.status_code == 400

    job = analyzed(client, synth_video)
    r = client.post(f"/api/jobs/{job['id']}/recognize", json={"order": [0, 99]})
    assert r.status_code == 400
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "ready_for_review"

    app = create_app(tmp_path / "other")
    store = app.state.store
    busy = store.create()
    busy.pages = [{"id": 0, "file": "pages/a.png"}]
    store.update(busy, status=Status.ANALYZING)
    r = TestClient(app).post(f"/api/jobs/{busy.id}/recognize", json={"order": [0]})
    assert r.status_code == 409


def blank_job(app, status=Status.READY_FOR_REVIEW):
    store = app.state.store
    job = store.create()
    (job.dir / "pages").mkdir()
    cv2.imwrite(str(job.dir / "pages" / "blank.png"), np.full((120, 400, 3), 255, np.uint8))
    store.update(job, pages=[{"id": 0, "file": "pages/blank.png"}], status=status)
    return job


def test_recognize_without_staff_fails_in_chinese(tmp_path):
    app = create_app(tmp_path)
    client = TestClient(app)
    job = blank_job(app)
    r = client.post(f"/api/jobs/{job.id}/recognize", json={"order": [0]})
    assert r.status_code == 200, r.text
    failed = wait_for_status(client, job.id, "failed")
    assert failed["error"] == "没有识别到谱表"
    assert not (job.dir / "score.json").exists()

    # a failed job can be retried
    r = client.post(f"/api/jobs/{job.id}/recognize", json={"order": [0]})
    assert r.status_code == 200


def wait_for_status(client, job_id, status, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] == status:
            return job
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {status}")


def scored_job(app):
    job = blank_job(app, Status.READY_FOR_SCORE)
    score = {
        "strings": 6,
        "tuning": [40, 45, 50, 55, 59, 64],
        "measures": [{"beats": [{"duration": 1, "notes": [{"string": 0, "fret": 3}]}]}],
    }
    (job.dir / "score.json").write_text(json.dumps(score))
    return job


def test_put_score_validates_and_writes_atomically(tmp_path):
    app = create_app(tmp_path)
    client = TestClient(app)
    job = scored_job(app)
    url = f"/api/jobs/{job.id}/score"

    score = client.get(url).json()
    score["title"] = "我的谱"
    score["tempo"] = 180
    score["measures"][0]["beats"][0]["notes"][0]["fret"] = 5
    r = client.put(url, json=score)
    assert r.status_code == 200, r.text
    saved = client.get(url).json()
    assert saved["title"] == "我的谱" and saved["tempo"] == 180
    assert saved["measures"][0]["beats"][0]["notes"][0]["fret"] == 5
    assert saved["measures"][0]["beats"][0]["confidence"] == 1.0  # normalized with defaults
    assert client.get(f"/api/jobs/{job.id}").json()["title"] == "我的谱"
    assert sorted(p.name for p in job.dir.iterdir()) == ["pages", "score.json", "state.json"]

    bad = {**score, "measures": [{"beats": [{"duration": "4"}]}]}
    r = client.put(url, json=bad)
    assert r.status_code == 422
    assert r.json()["detail"].startswith("乐谱数据不合法")
    assert "duration" in r.json()["detail"]
    assert client.get(url).json() == saved  # a rejected PUT leaves the file alone

    assert client.put(url, json=[1, 2]).status_code == 422


def test_put_score_refused_while_recognizing_or_before_recognition(tmp_path):
    app = create_app(tmp_path)
    client = TestClient(app)
    fresh = blank_job(app)
    assert client.put(f"/api/jobs/{fresh.id}/score", json={}).status_code == 404
    job = scored_job(app)
    app.state.store.update(job, status=Status.RECOGNIZING)
    assert client.put(f"/api/jobs/{job.id}/score", json={}).status_code == 409


def test_failed_atomic_write_keeps_old_score(tmp_path, monkeypatch):
    app = create_app(tmp_path)
    client = TestClient(app)
    job = scored_job(app)
    before = (job.dir / "score.json").read_text()

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr("app.jobs.os.replace", boom)
    with pytest.raises(OSError):
        client.put(f"/api/jobs/{job.id}/score", json={"title": "x"})
    assert (job.dir / "score.json").read_text() == before
    assert sorted(p.name for p in job.dir.iterdir()) == ["pages", "score.json", "state.json"]


def test_list_jobs_newest_first(tmp_path, synth_video):
    app = create_app(tmp_path)
    client = TestClient(app)
    first = upload(client, synth_video)
    second = app.state.store.create()
    app.state.store.update(second, source="https://www.bilibili.com/video/BV1yBcEeXEVn")
    jobs = client.get("/api/jobs").json()
    assert [j["id"] for j in jobs] == [second.id, first]
    assert jobs[1]["source"] == "my.avi"
    assert jobs[0]["source"].endswith("BV1yBcEeXEVn")
    assert set(jobs[0]) == {"id", "created", "status", "title", "source"}


def test_restart_restores_jobs_and_fails_interrupted_ones(tmp_path):
    store = JobStore(tmp_path)
    done = store.create()
    store.update(done, status=Status.READY_FOR_SCORE, title="t", score_order=[1, 0])
    busy = {}
    for status in (Status.DOWNLOADING, Status.ANALYZING, Status.RECOGNIZING):
        busy[status] = store.create()
        store.update(busy[status], status=status, stage="scan")
    # re-recognizing over an edited score when the program stopped: the score must survive
    rerun = busy[Status.RECOGNIZING]
    (rerun.dir / "score.json").write_text('{"title": "edited"}')
    store.update(rerun, score_order=[0, 1], score_files=["pages/a_000.png", "pages/a_001.png"])
    (tmp_path / "junk").mkdir()
    (tmp_path / "junk" / "state.json").write_text("{not json")

    reloaded = JobStore(tmp_path)
    again = reloaded.get(done.id)
    assert again.status == Status.READY_FOR_SCORE
    assert again.title == "t" and again.score_order == [1, 0]
    assert again.dir == done.dir and again.created == done.created
    for job in busy.values():
        restored = reloaded.get(job.id)
        assert restored.status == Status.FAILED
        assert restored.error == INTERRUPTED == "程序重启，处理被中断，请重试"
        on_disk = json.loads((job.dir / "state.json").read_text())
        assert on_disk["status"] == "failed"
    kept = reloaded.get(rerun.id)
    assert (rerun.dir / "score.json").read_text() == '{"title": "edited"}'
    assert kept.score_order == [0, 1]
    assert kept.score_files == ["pages/a_000.png", "pages/a_001.png"]
    assert reloaded.get("junk") is None
    assert len(reloaded.recent()) == 4


def test_restart_through_the_api(tmp_path, synth_video):
    client = TestClient(create_app(tmp_path))
    job = analyzed(client, synth_video)
    client.post(f"/api/jobs/{job['id']}/recognize", json={"order": [0, 1]})
    wait_for(client, job["id"], "ready_for_score")

    client = TestClient(create_app(tmp_path))
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "ready_for_score"
    assert client.get(f"/api/jobs/{job['id']}/score").status_code == 200
    assert [j["id"] for j in client.get("/api/jobs").json()] == [job["id"]]


def test_recognize_pads_measure_numbers(tmp_path, monkeypatch):
    from app.omr.model import Beat, Measure, Score

    def fake(images, progress=None):
        return Score(6, [], None, [Measure(n, beats=[Beat(4)]) for n in (3, 5)])

    monkeypatch.setattr("app.workflow.recognize_images", fake)
    app = create_app(tmp_path)
    client = TestClient(app)
    job = blank_job(app)
    client.post(f"/api/jobs/{job.id}/recognize", json={"order": [0]})
    wait_for_status(client, job.id, "ready_for_score")
    score = client.get(f"/api/jobs/{job.id}/score").json()
    assert [m["number"] for m in score["measures"]] == [1, 2, 3, 4, 5]
    assert [m["line"] for m in score["measures"]] == [-1, -1, 0, -1, 0]
    assert [m["confidence"] for m in score["measures"]] == [1.0, 1.0, 1.0, 0.0, 1.0]


def test_recognize_records_page_files_that_reanalysis_replaces(tmp_path, synth_video):
    client = TestClient(create_app(tmp_path))
    job = analyzed(client, synth_video)
    order = [2, 0]
    client.post(f"/api/jobs/{job['id']}/recognize", json={"order": order})
    job = wait_for(client, job["id"], "ready_for_score")
    by_id = {p["id"]: p["file"] for p in job["pages"]}
    assert job["score_files"] == [by_id[2], by_id[0]]
    job_dir = tmp_path / job["id"]
    assert all((job_dir / f).is_file() for f in job["score_files"])

    r = client.put(f"/api/jobs/{job['id']}/region", json=job["region"]["roi"])
    assert r.status_code == 200, r.text
    after = wait_for(client, job["id"], "ready_for_review")
    assert after["score_files"] == job["score_files"]  # still what was recognized
    assert not any((job_dir / f).exists() for f in after["score_files"])
    assert set(after["score_files"]).isdisjoint(p["file"] for p in after["pages"])


def test_atomic_write_retries_a_briefly_locked_file(tmp_path, monkeypatch):
    # Windows: antivirus or the search indexer can hold the file for a moment
    from app import jobs

    real = jobs.os.replace
    calls = []

    def flaky(src, dst):
        calls.append(dst)
        if len(calls) == 1:
            raise PermissionError(32, "The process cannot access the file")
        return real(src, dst)

    monkeypatch.setattr("app.jobs.os.replace", flaky)
    monkeypatch.setattr("app.jobs.REPLACE_BACKOFF", 0.0)
    target = tmp_path / "score.json"
    jobs.write_atomic(target, '{"ok": 1}')
    assert target.read_text() == '{"ok": 1}' and len(calls) == 2
    assert [p.name for p in tmp_path.iterdir()] == ["score.json"]


def test_atomic_write_gives_up_on_a_file_that_stays_locked(tmp_path, monkeypatch):
    from app import jobs

    def locked(src, dst):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr("app.jobs.os.replace", locked)
    monkeypatch.setattr("app.jobs.REPLACE_BACKOFF", 0.0)
    with pytest.raises(PermissionError):
        jobs.write_atomic(tmp_path / "score.json", "{}")
    assert list(tmp_path.iterdir()) == []
