import io

import pytest

from app import source
from app.source import SourceError, download_url, normalize_url, save_upload


@pytest.mark.parametrize(
    "text, expected",
    [
        ("BV1xx411c7mD", "https://www.bilibili.com/video/BV1xx411c7mD"),
        (
            "https://www.bilibili.com/video/BV1xx411c7mD?p=2",
            "https://www.bilibili.com/video/BV1xx411c7mD?p=2",
        ),
        ("b23.tv/abc123", "https://b23.tv/abc123"),
        ("https://youtu.be/dQw4w9WgXcQ", "https://youtu.be/dQw4w9WgXcQ"),
        (
            "  https://m.youtube.com/watch?v=dQw4w9WgXcQ ",
            "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
        ),
    ],
)
def test_normalize_url_accepts(text, expected):
    assert normalize_url(text) == expected


@pytest.mark.parametrize("text", ["https://example.com/v", "https://notyoutube.com/x", "hello"])
def test_normalize_url_rejects(text):
    with pytest.raises(SourceError):
        normalize_url(text)


def test_save_upload(tmp_path):
    path = save_upload(io.BytesIO(b"data"), "My Video.MKV", tmp_path)
    assert path == tmp_path / "source.mkv" and path.read_bytes() == b"data"
    with pytest.raises(SourceError):
        save_upload(io.BytesIO(b"x"), "notes.txt", tmp_path)


class FakeYDL:
    last_opts: dict = {}

    def __init__(self, opts):
        FakeYDL.last_opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download):
        for hook in self.last_opts["progress_hooks"]:
            hook({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100})
        out = self.last_opts["outtmpl"].replace("%(ext)s", "mp4")
        open(out, "wb").write(b"video")
        return {"ext": "mp4"}

    def prepare_filename(self, info):
        return self.last_opts["outtmpl"].replace("%(ext)s", info["ext"])


def test_download_url_uses_video_only_format(tmp_path, monkeypatch):
    monkeypatch.setattr(source.yt_dlp, "YoutubeDL", FakeYDL)
    seen = []
    path = download_url("https://youtu.be/x", tmp_path, tmp_path / "c.txt", seen.append)
    assert path == tmp_path / "source.mp4"
    assert seen == [0.5]
    assert FakeYDL.last_opts["noplaylist"] is True
    assert FakeYDL.last_opts["cookiefile"] == str(tmp_path / "c.txt")
    assert FakeYDL.last_opts["format"].startswith("bv*[height<=1080]")


def test_download_url_wraps_errors(tmp_path, monkeypatch):
    class Boom(FakeYDL):
        def extract_info(self, url, download):
            raise source.yt_dlp.utils.DownloadError("geo blocked")

    monkeypatch.setattr(source.yt_dlp, "YoutubeDL", Boom)
    with pytest.raises(SourceError, match="geo blocked"):
        download_url("https://youtu.be/x", tmp_path)


@pytest.mark.network
def test_download_real_youtube(tmp_path):
    # "Me at the zoo", 19 seconds; run with: pytest -m network
    path = download_url("https://www.youtube.com/watch?v=jNQXAC9IVRw", tmp_path)
    assert path.stat().st_size > 0
