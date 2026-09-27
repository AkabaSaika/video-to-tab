from __future__ import annotations

import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO
from urllib.parse import urlsplit

import yt_dlp

VIDEO_EXTS = {
    ".mp4",
    ".mkv",
    ".webm",
    ".mov",
    ".avi",
    ".flv",
    ".m4v",
    ".ts",
    ".wmv",
    ".mpg",
    ".mpeg",
}
ALLOWED_HOSTS = ("bilibili.com", "b23.tv", "youtube.com", "youtu.be")
BV_RE = re.compile(r"^(BV[0-9A-Za-z]{10})$")
# Video-only stream: no merge step, so no system ffmpeg is needed. Prefer H.264.
FORMAT = "bv*[height<=1080][vcodec^=avc]/bv*[height<=1080]/b[height<=1080]/bv*/b"


class SourceError(Exception):
    pass


def save_upload(fileobj: BinaryIO, filename: str, dest_dir: Path) -> Path:
    ext = Path(filename).suffix.lower()
    if ext not in VIDEO_EXTS:
        raise SourceError(f"不支持的文件类型：{ext or '无扩展名'}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"source{ext}"
    with dest.open("wb") as out:
        shutil.copyfileobj(fileobj, out)
    return dest


def normalize_url(text: str) -> str:
    text = text.strip()
    if m := BV_RE.match(text):
        return f"https://www.bilibili.com/video/{m.group(1)}"
    if not re.match(r"^https?://", text):
        text = "https://" + text
    host = (urlsplit(text).hostname or "").lower()
    if not host or not any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS):
        raise SourceError("只支持 bilibili / YouTube 链接或 BV 号")
    return text


def download_url(
    url: str,
    dest_dir: Path,
    cookies_file: Path | None = None,
    on_progress: Callable[[float], None] = lambda f: None,
) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)

    def hook(d: dict) -> None:
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                on_progress(min(1.0, d.get("downloaded_bytes", 0) / total))

    opts = {
        "format": FORMAT,
        "outtmpl": str(dest_dir / "source.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "progress_hooks": [hook],
    }
    if cookies_file:
        opts["cookiefile"] = str(cookies_file)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            path = Path(ydl.prepare_filename(info))
    except yt_dlp.utils.DownloadError as exc:
        raise SourceError(f"下载失败：{exc}（可尝试配置 cookies 或直接上传视频文件）") from exc
    if not path.exists():
        raise SourceError("下载完成但找不到视频文件")
    return path
