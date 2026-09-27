import time

from fastapi.testclient import TestClient

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
