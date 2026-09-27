import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import workflow
from app.jobs import JobStore, Status
from app.main import create_app, safe_path


def wait_for(client, job_id, status, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] == status:
            return job
        assert job["status"] != "failed", job["error"]
        time.sleep(0.2)
    raise AssertionError(f"timed out waiting for {status}: {job}")


def test_full_flow(tmp_path, synth_video):
    client = TestClient(create_app(tmp_path))
    with synth_video.path.open("rb") as f:
        r = client.post("/api/jobs", files={"file": ("x.avi", f, "video/x-msvideo")})
    assert r.status_code == 200, r.text
    job = wait_for(client, r.json()["id"], "ready_for_region")
    assert job["region"]["confidence"] > 0.7
    assert client.get(f"/api/jobs/{job['id']}/files/frame.jpg").status_code == 200

    r = client.put(f"/api/jobs/{job['id']}/region", json=job["region"]["roi"])
    assert r.status_code == 200, r.text
    job = wait_for(client, job["id"], "ready_for_review")
    assert [p["duplicate_of"] for p in job["pages"]] == [None, None, None, 0]

    r = client.post(f"/api/jobs/{job['id']}/export", json={"order": [2, 0], "fmt": "pdf"})
    assert r.status_code == 200, r.text
    pdf = client.get(r.json()["url"])
    assert pdf.content.startswith(b"%PDF")


def test_region_rejects_invalid_params(tmp_path, synth_video):
    client = TestClient(create_app(tmp_path))
    with synth_video.path.open("rb") as f:
        r = client.post("/api/jobs", files={"file": ("x.avi", f, "video/x-msvideo")})
    job = wait_for(client, r.json()["id"], "ready_for_region")
    base = job["region"]["roi"]

    r = client.put(f"/api/jobs/{job['id']}/region", json={**base, "fps": 0})
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], str)
    assert r.json()["detail"].startswith("参数不合法")

    r = client.put(f"/api/jobs/{job['id']}/region", json={**base, "fps": -1})
    assert r.status_code == 422


def test_run_analysis_uses_fresh_file_names_and_cleans_up(tmp_path, synth_video):
    client = TestClient(create_app(tmp_path))
    with synth_video.path.open("rb") as f:
        r = client.post("/api/jobs", files={"file": ("x.avi", f, "video/x-msvideo")})
    job = wait_for(client, r.json()["id"], "ready_for_region")
    roi = job["region"]["roi"]
    job_dir = Path(tmp_path) / job["id"]

    r = client.put(f"/api/jobs/{job['id']}/region", json=roi)
    assert r.status_code == 200, r.text
    job = wait_for(client, job["id"], "ready_for_review")
    first_files = [p["file"] for p in job["pages"]]
    assert first_files
    for f in first_files:
        assert (job_dir / f).exists()

    r = client.put(f"/api/jobs/{job['id']}/region", json=roi)
    assert r.status_code == 200, r.text
    job = wait_for(client, job["id"], "ready_for_review")
    second_files = [p["file"] for p in job["pages"]]
    assert second_files
    assert set(first_files).isdisjoint(second_files)

    for f in first_files:
        assert not (job_dir / f).exists()
    for f in second_files:
        assert (job_dir / f).exists()

    order = [p["id"] for p in job["pages"]]
    r = client.post(f"/api/jobs/{job['id']}/export", json={"order": order, "fmt": "png"})
    assert r.status_code == 200, r.text


def test_rejects_bad_input(tmp_path):
    client = TestClient(create_app(tmp_path))
    assert client.post("/api/jobs").status_code == 400
    r = client.post("/api/jobs", data={"url": "https://example.com/v"})
    assert r.status_code == 400
    r = client.post("/api/jobs", files={"file": ("a.txt", b"hi", "text/plain")})
    assert r.status_code == 400
    assert client.get("/api/jobs/nope").status_code == 404


def test_safe_path(tmp_path):
    (tmp_path / "job").mkdir()
    (tmp_path / "job" / "a.png").write_bytes(b"x")
    (tmp_path / "secret").write_bytes(b"x")
    assert safe_path(tmp_path / "job", "a.png") == (tmp_path / "job" / "a.png").resolve()
    assert safe_path(tmp_path / "job", "../secret") is None
    assert safe_path(tmp_path / "job", "missing.png") is None


def test_transition_is_atomic(tmp_path):
    store = JobStore(tmp_path)
    job = store.create()
    store.update(job, status=Status.READY_FOR_REGION)
    allowed = (Status.READY_FOR_REGION, Status.READY_FOR_REVIEW, Status.FAILED)

    assert store.transition(job, allowed, status=Status.ANALYZING, error=None) is True
    assert job.status == Status.ANALYZING

    # Second call finds the job already ANALYZING (not in `allowed`) and must be refused,
    # proving two concurrent callers can't both win the transition.
    assert store.transition(job, allowed, status=Status.ANALYZING, error=None) is False
    assert job.status == Status.ANALYZING


def test_region_conflict_while_busy(tmp_path):
    app = create_app(tmp_path)
    client = TestClient(app)
    store = app.state.store
    job = store.create()
    store.update(job, status=Status.ANALYZING, video="source.avi")

    r = client.put(f"/api/jobs/{job.id}/region", json={"x": 0, "y": 0, "w": 10, "h": 10})
    assert r.status_code == 409


def test_run_wraps_unexpected_exceptions_in_chinese(tmp_path):
    store = JobStore(tmp_path)
    job = store.create()

    def boom():
        raise RuntimeError("boom")

    store.run(job, boom).join()
    assert job.status == Status.FAILED
    assert job.error.startswith("处理失败（RuntimeError）")


def test_run_keeps_known_app_errors_verbatim(tmp_path):
    store = JobStore(tmp_path)
    job = store.create()

    def boom():
        raise ValueError("没有选中任何页面")

    store.run(job, boom).join()
    assert job.status == Status.FAILED
    assert job.error == "没有选中任何页面"


def test_export_raises_on_missing_page_file(tmp_path):
    store = JobStore(tmp_path)
    job = store.create()
    job.pages = [{"id": 0, "file": "pages/000.png", "start": 0.0, "end": 1.0, "duplicate_of": None}]

    with pytest.raises(ValueError, match="页面文件缺失"):
        workflow.export(job, [0], "png")


def test_frame_encode_failure_returns_500(tmp_path, synth_video, monkeypatch):
    app = create_app(tmp_path)
    client = TestClient(app)
    store = app.state.store
    job = store.create()
    shutil.copy(synth_video.path, job.dir / "source.avi")
    store.update(job, video="source.avi")

    monkeypatch.setattr("app.main.cv2.imencode", lambda *a, **k: (False, None))
    r = client.get(f"/api/jobs/{job.id}/frame", params={"t": 0.0})
    assert r.status_code == 500
    assert r.json()["detail"] == "帧图像编码失败"
