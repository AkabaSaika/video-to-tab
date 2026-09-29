"""Build the self-contained release folder and zip for the current OS.

Usage (from the repository root, after `cd frontend && npm ci && npm run build`):
    cd backend && uv run --group build python ../packaging/build.py v0.01
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND_DIST = ROOT / "frontend" / "dist"
OUT = ROOT / "build-release"
NAME = "video-to-tab"


def os_tag() -> str:
    system = {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}[platform.system()]
    machine = platform.machine().lower()
    arches = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}
    arch = arches.get(machine, machine)
    return f"{system}-{arch}"


def homr_models() -> Path:
    """The piano recognition models, downloaded once if missing (see app.piano.engine)."""
    sys.path.insert(0, str(BACKEND))
    from app.piano import engine

    return engine.ensure_models()


def main() -> None:
    version = sys.argv[1] if len(sys.argv) > 1 else "dev"
    if not (FRONTEND_DIST / "index.html").is_file():
        sys.exit("frontend/dist is missing: run `npm ci && npm run build` in frontend/ first")
    models = homr_models()
    shutil.rmtree(OUT, ignore_errors=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onedir",
            "--name",
            NAME,
            "--paths",
            str(BACKEND),
            "--distpath",
            str(OUT / "dist"),
            "--workpath",
            str(OUT / "work"),
            "--specpath",
            str(OUT),
            "--add-data",
            f"{FRONTEND_DIST}{os.pathsep}frontend/dist",
            "--add-data",  # the glyph classifier; the training fonts are not needed at runtime
            f"{BACKEND / 'app' / 'omr' / 'models'}{os.pathsep}app/omr/models",
            "--add-data",  # piano recognition works offline: homr's ONNX models ship with the app
            f"{models}{os.pathsep}homr_models",
            "--collect-submodules",
            "uvicorn",
            "--collect-submodules",
            "homr",
            "--collect-data",
            "homr",  # tokenizer files
            "--collect-data",
            "musicxml",  # the MusicXML schema homr writes against
            "--collect-binaries",
            "onnxruntime",
            # homr's title OCR is stubbed out (app.piano.engine); never bundle it
            "--exclude-module",
            "rapidocr",
            "--exclude-module",
            "homr.title_detection",
            "--collect-submodules",
            "app",
            "--collect-all",
            "av",
            "--collect-all",
            "yt_dlp",
            str(BACKEND / "app" / "launcher.py"),
        ],
        check=True,
    )
    folder = OUT / "dist" / NAME
    shutil.copy(ROOT / "packaging" / "README-release.txt", folder / "README.txt")
    shutil.copy(ROOT / "LICENSE", folder / "LICENSE.txt")
    archive = shutil.make_archive(
        str(OUT / f"{NAME}-{version}-{os_tag()}"), "zip", OUT / "dist", NAME
    )
    print(f"built {archive}")


if __name__ == "__main__":
    main()
