import socket

from fastapi.testclient import TestClient

from app.launcher import pick_port
from app.main import create_app


def test_pick_port_prefers_requested_port_when_free():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        free = s.getsockname()[1]
    assert pick_port(free) == free


def test_pick_port_falls_back_when_taken():
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        taken = busy.getsockname()[1]
        port = pick_port(taken)
    assert port != taken and port > 0


def test_frontend_dir_can_be_set_by_env(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<p>bundled ui</p>")
    monkeypatch.setenv("VTT_FRONTEND_DIR", str(dist))
    client = TestClient(create_app(tmp_path / "jobs"))
    assert "bundled ui" in client.get("/").text
