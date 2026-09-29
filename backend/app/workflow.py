"""Job-level steps glued to the pipeline; each runs inside JobStore.run()."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import cv2

from app.export import export_pdf, export_png
from app.frames import grab_frames, probe
from app.jobs import Job, JobStore, Status, write_atomic
from app.models import Roi
from app.omr.model import Song, pad_numbers
from app.omr.recognize import recognize_images
from app.pipeline import AnalyzeParams, analyze
from app.region import detect_region
from app.source import download_url


def prepare(store: JobStore, job: Job, url: str | None = None) -> None:
    """Download (if url) then probe the video and guess the tab region."""
    if url:
        store.update(job, status=Status.DOWNLOADING, stage="download")
        cookies = os.environ.get("VTT_COOKIES_FILE")
        path = download_url(
            url,
            job.dir,
            Path(cookies) if cookies else None,
            lambda f: store.update(job, progress=f),
        )
        store.update(job, video=path.name)
    video = job.dir / job.video
    store.update(job, stage="probe", progress=0.0)
    info = probe(video)
    frames = grab_frames(video, 20)
    guess = detect_region(frames)
    cv2.imwrite(str(job.dir / "frame.jpg"), frames[len(frames) // 2])
    store.update(
        job,
        width=info.width,
        height=info.height,
        duration=info.duration,
        region={"roi": guess.roi.to_dict(), "confidence": guess.confidence},
        status=Status.READY_FOR_REGION,
        stage="",
        progress=1.0,
    )


def run_analysis(store: JobStore, job: Job, roi: Roi, params: AnalyzeParams) -> None:
    store.update(job, status=Status.ANALYZING, stage="scan", progress=0.0, error=None)
    pages = analyze(
        job.dir / job.video,
        roi.clamp(job.width, job.height),
        params,
        lambda stage, frac: store.update(job, stage=stage, progress=frac),
    )
    pages_dir = job.dir / "pages"
    pages_dir.mkdir(exist_ok=True)
    for old in job.pages:
        old_path = (job.dir / old["file"]).resolve()
        if old_path.is_relative_to(pages_dir.resolve()) and old_path.is_file():
            old_path.unlink()
    run = uuid.uuid4().hex[:8]
    meta = []
    for i, page in enumerate(pages):
        name = f"pages/{run}_{i:03d}.png"
        cv2.imwrite(str(job.dir / name), page.image)
        meta.append(
            {
                "id": i,
                "file": name,
                "start": page.start,
                "end": page.end,
                "duplicate_of": page.duplicate_of,
            }
        )
    store.update(job, pages=meta, status=Status.READY_FOR_REVIEW, stage="", progress=1.0)


def page_images(job: Job, order: list[int]) -> list:
    """The page images for page ids `order` (unknown ids are skipped), in that order."""
    by_id = {p["id"]: p for p in job.pages}
    images = []
    for i in order:
        if i not in by_id:
            continue
        file = by_id[i]["file"]
        image = cv2.imread(str(job.dir / file))
        if image is None:
            raise ValueError(f"页面文件缺失：{file}")
        images.append(image)
    if not images:
        raise ValueError("没有选中任何页面")
    return images


def save_score(job: Job, song: Song) -> None:
    text = json.dumps(song.to_dict(), ensure_ascii=False)
    write_atomic(job.dir / "score.json", text)


def recognize(store: JobStore, job: Job, order: list[int]) -> None:
    """Read the tab from the pages in `order`; Measure.line indexes into `order`."""
    store.update(job, status=Status.RECOGNIZING, stage="recognize", progress=0.0, error=None)
    images = page_images(job, order)
    song = recognize_images(images, progress=lambda f: store.update(job, progress=f))
    if not any(t.measures for t in song.tracks):
        raise ValueError("没有识别到谱表")
    # bar k of the editor and the export is measure k; every track is padded alike
    song.tracks = [pad_numbers(t) for t in song.tracks]
    song.title = job.title  # keep a title the user already typed
    save_score(job, song)
    by_id = {p["id"]: p["file"] for p in job.pages}
    store.update(
        job,
        score_order=list(order),
        score_files=[by_id[i] for i in order],
        status=Status.READY_FOR_SCORE,
        stage="",
        progress=1.0,
    )


def export(job: Job, order: list[int], fmt: str) -> str:
    images = page_images(job, order)
    name = f"tab.{fmt}"
    (export_png if fmt == "png" else export_pdf)(images, job.dir / name)
    return name
