"""Piano job steps; each runs inside PianoStore.run() (or a request, for one system)."""

from __future__ import annotations

import os
from pathlib import Path

import cv2
import numpy as np

from app.frames import probe
from app.jobs import write_atomic
from app.piano import engine
from app.piano.capture import capture
from app.piano.jobs import PianoJob, PianoStatus, PianoStore
from app.piano.merge import merge
from app.source import download_url


def variant_image(image: np.ndarray, variant: int) -> np.ndarray:
    """Another view of a system for another try: homr's result depends on the scale and
    the margins, so a retry that failed or read wrongly gets a different one."""
    if variant % 3 == 1:
        big = cv2.resize(image, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
        return cv2.copyMakeBorder(big, 40, 40, 40, 40, cv2.BORDER_CONSTANT, value=(255,) * 3)
    if variant % 3 == 2:
        small = cv2.resize(image, None, fx=0.8, fy=0.8, interpolation=cv2.INTER_AREA)
        return cv2.copyMakeBorder(small, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=(255,) * 3)
    return image


def recognize_image(image: np.ndarray, variant: int = 0) -> str:
    return engine.recognize(variant_image(image, variant))


def recognize_system(store: PianoStore, job: PianoJob, sid: int) -> dict:
    """(Re)read one system; the result (or the error) is stored with it."""
    entry = next(s for s in job.systems if s["id"] == sid)
    image = cv2.imread(str(job.dir / entry["image"]))
    attempt = entry.get("attempts", 0)
    changes: dict = {"attempts": attempt + 1}
    try:
        if image is None:
            raise engine.EngineError(f"谱表图像缺失：{entry['image']}")
        xml = recognize_image(image, attempt)
    except engine.EngineError as exc:
        changes |= {"ok": False, "error": str(exc), "musicxml": None}
    else:
        name = f"systems/{sid:03d}.musicxml"
        write_atomic(job.dir / name, xml)
        changes |= {"ok": True, "error": None, "musicxml": name}
    systems = [s | changes if s["id"] == sid else s for s in job.systems]
    store.update(job, systems=systems)
    return next(s for s in systems if s["id"] == sid)


def run(store: PianoStore, job: PianoJob, url: str | None = None) -> None:
    """Download (if url), capture the systems, recognize each."""
    if url:
        store.update(job, status=PianoStatus.DOWNLOADING, stage="download", progress=0.0)
        cookies = os.environ.get("VTT_COOKIES_FILE")
        path = download_url(
            url,
            job.dir,
            Path(cookies) if cookies else None,
            lambda f: store.update(job, progress=f),
        )
        store.update(job, video=path.name)
    video = job.dir / job.video
    info = probe(video)
    store.update(
        job,
        width=info.width,
        height=info.height,
        duration=info.duration,
        status=PianoStatus.CAPTURING,
        stage="capture",
        progress=0.0,
    )
    found = capture(video, progress=lambda f: store.update(job, progress=f))
    if not found:
        raise ValueError("视频中没有找到完整的大谱表（钢琴的高音谱表 + 低音谱表）")
    (job.dir / "systems").mkdir(exist_ok=True)
    systems = []
    for i, sys_ in enumerate(found):
        name = f"systems/{i:03d}.png"
        cv2.imwrite(str(job.dir / name), sys_.image)
        systems.append(
            {
                "id": i,
                "image": name,
                "musicxml": None,
                "ok": None,
                "error": None,
                "start": round(sys_.first, 2),
                "end": round(sys_.last, 2),
                "attempts": 0,
            }
        )
    store.update(
        job, systems=systems, status=PianoStatus.RECOGNIZING, stage="recognize", progress=0.0
    )
    for k, entry in enumerate(systems):
        recognize_system(store, job, entry["id"])
        store.update(job, progress=(k + 1) / len(systems))
    store.update(job, status=PianoStatus.READY, stage="", progress=1.0)


def merged(job: PianoJob) -> str | None:
    """The whole piece from the recognized systems, in order; None if there are none."""
    parts = [
        (job.dir / s["musicxml"]).read_text(encoding="utf-8")
        for s in job.systems
        if s.get("ok") and s.get("musicxml") and (job.dir / s["musicxml"]).is_file()
    ]
    return merge(parts, job.title) if parts else None
