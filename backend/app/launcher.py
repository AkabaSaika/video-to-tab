"""Entry point of the packaged app: start the local server and open the browser."""

from __future__ import annotations

import os
import socket
import sys
import threading
import webbrowser
from pathlib import Path


def base_dir() -> Path:
    """Folder holding the executable when frozen, else the repository root."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def bundle_dir() -> Path:
    """Where PyInstaller unpacked the bundled files (the repo root when not frozen)."""
    return Path(getattr(sys, "_MEIPASS", base_dir()))


def pick_port(preferred: int = 8000) -> int:
    """`preferred` if it is free on 127.0.0.1, otherwise any free port."""
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", preferred))
        except OSError:
            s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        # a Western-locale Windows console cannot encode Chinese; never crash on output
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    base = base_dir()
    os.environ.setdefault("VTT_DATA_DIR", str(base / "data" / "jobs"))
    frontend = bundle_dir() / "frontend" / "dist"
    if frontend.is_dir():
        os.environ.setdefault("VTT_FRONTEND_DIR", str(frontend))
    cookies = base / "cookies.txt"
    if cookies.is_file():
        os.environ.setdefault("VTT_COOKIES_FILE", str(cookies))

    import uvicorn

    from app.main import app  # imported after the environment is set up

    port = pick_port()
    url = f"http://127.0.0.1:{port}"
    print(f"video-to-tab 已启动：{url}")
    print("浏览器会自动打开；关闭此窗口即退出。")
    threading.Timer(1.5, webbrowser.open, (url,)).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
