"""Drum job steps; each runs inside DrumStore.run() (or a request, for one page).

Per page the job folder holds the captured image (pages/NNN.png), what was read from it
(pages/NNN.json, a DrumScore of its measures: positions and noteheads only) and the
MusicXML the preview shows (pages/NNN.musicxml, made with the job's instrument map).
Changing the map or the tempo rewrites the MusicXML files; changing the time signature
reads the pages again (the durations depend on it, and reading takes ~0.1 s a page).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import cv2
import numpy as np

from app.drums.capture import capture
from app.drums.export import midi, musicxml
from app.drums.instruments import Mapping
from app.drums.jobs import DrumJob, DrumStatus, DrumStore
from app.drums.model import DrumMeasure, DrumScore
from app.drums.recognize import recognize
from app.frames import probe
from app.jobs import write_atomic
from app.source import download_url


def mapping_of(job: DrumJob) -> Mapping:
    return Mapping.from_dict(job.mapping)


def variant_image(image: np.ndarray, variant: int) -> np.ndarray:
    """Another view of a page for another try: bigger (small staff spaces read better)
    or a little smaller."""
    if variant % 3 == 1:
        return cv2.resize(image, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
    if variant % 3 == 2:
        return cv2.resize(image, None, fx=0.85, fy=0.85, interpolation=cv2.INTER_AREA)
    return image


def solving_time(job: DrumJob, printed: tuple[int, int] | None) -> tuple[int, int] | None:
    """The user's time signature, else what the page itself prints (None: the page's
    own, else the one printed earlier in the video, else 4/4)."""
    if job.time:
        return (job.time[0], job.time[1])
    if printed:
        return None
    return tuple(job.detected_time) if job.detected_time else None  # type: ignore[return-value]


def page_score(job: DrumJob, entry: dict) -> DrumScore | None:
    name = entry.get("score")
    if not name or not (job.dir / name).is_file():
        return None
    return DrumScore.from_dict(json.loads((job.dir / name).read_text(encoding="utf-8")))


def render_page(job: DrumJob, entry: dict) -> None:
    """The page's preview MusicXML, from what was read and the job's current map."""
    score = page_score(job, entry)
    if score is None:
        return
    score.tempo = job.tempo
    name = f"pages/{entry['id']:03d}.musicxml"
    write_atomic(job.dir / name, musicxml(score, mapping_of(job)))
    entry["musicxml"] = name
    entry["rev"] = entry.get("rev", 0) + 1  # the preview changed: clients fetch it again


def recognize_page(store: DrumStore, job: DrumJob, pid: int, variant: int | None = None) -> dict:
    """(Re)read one page; the result (or the error) is stored with it. Without a
    `variant` this is another try (another view of the image than last time)."""
    entry = next(p for p in job.pages if p["id"] == pid)
    image = cv2.imread(str(job.dir / entry["image"]))
    attempt = entry.get("attempts", 0)
    changes: dict = {}
    if variant is None:
        variant = attempt
        changes["attempts"] = attempt + 1
    if image is None:
        changes |= {"ok": False, "error": f"页面图像缺失：{entry['image']}"}
    else:
        first = recognize(variant_image(image, variant))
        printed = first.time
        if printed and not job.detected_time:
            store.update(job, detected_time=list(printed))
        use = solving_time(job, printed)
        page = first if use is None else recognize(variant_image(image, variant), time=use)
        if not page.measures:
            changes |= {"ok": False, "error": "这一页没有识别出小节", "measures": 0}
        else:
            time_sig = page.measures[0].time or (4, 4)
            score = DrumScore(job.title, job.tempo, time_sig, page.measures)
            name = f"pages/{pid:03d}.json"
            text = json.dumps(score.to_dict(), ensure_ascii=False, separators=(",", ":"))
            write_atomic(job.dir / name, text)
            changes |= {
                "ok": True,
                "error": None,
                "score": name,
                "measures": len(page.measures),
                "summed": sum(bool(m.ok) for m in page.measures),
                "time": list(printed) if printed else None,
            }
    merged = entry | changes
    if merged.get("ok"):
        render_page(job, merged)
    pages = [merged if p["id"] == pid else p for p in job.pages]
    store.update(job, pages=pages)
    return merged


def rerender(store: DrumStore, job: DrumJob) -> None:
    pages = [dict(p) for p in job.pages]
    for entry in pages:
        if entry.get("ok"):
            render_page(job, entry)
    store.update(job, pages=pages)


def reread(store: DrumStore, job: DrumJob) -> None:
    """Every page again, the way it was last read (the time signature changed)."""
    for entry in list(job.pages):
        recognize_page(store, job, entry["id"], variant=max(0, entry.get("attempts", 1) - 1))


def run(store: DrumStore, job: DrumJob, url: str | None = None) -> None:
    """Download (if url), capture the pages, read each."""
    if url:
        store.update(job, status=DrumStatus.DOWNLOADING, stage="download", progress=0.0)
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
        status=DrumStatus.CAPTURING,
        stage="capture",
        progress=0.0,
    )
    mode, found = capture(video, progress=lambda f: store.update(job, progress=f))
    if not found:
        raise ValueError("视频中没有找到完整的鼓谱小节")
    (job.dir / "pages").mkdir(exist_ok=True)
    pages = []
    for i, page in enumerate(found):
        name = f"pages/{i:03d}.png"
        cv2.imwrite(str(job.dir / name), page.image)
        pages.append(
            {
                "id": i,
                "image": name,
                "score": None,
                "musicxml": None,
                "ok": None,
                "error": None,
                "start": round(page.start, 2),
                "end": round(page.end, 2),
                "attempts": 0,
                "rev": 0,
                "measures": len(page.measures) or None,
                "summed": None,
                "time": None,
            }
        )
    store.update(
        job,
        mode=mode,
        pages=pages,
        status=DrumStatus.RECOGNIZING,
        stage="recognize",
        progress=0.0,
    )
    for k, entry in enumerate(pages):
        recognize_page(store, job, entry["id"])
        store.update(job, progress=(k + 1) / len(pages))
    store.update(job, status=DrumStatus.READY, stage="", progress=1.0)


def whole(job: DrumJob) -> DrumScore | None:
    """The whole piece from the recognized pages, in order; None if there are none."""
    measures: list[DrumMeasure] = []
    for entry in job.pages:
        if entry.get("ok"):
            score = page_score(job, entry)
            if score is not None:
                measures += score.measures
    if not measures:
        return None
    time_sig = measures[0].time or (4, 4)
    return DrumScore(job.title, job.tempo, time_sig, measures)


def export_musicxml(job: DrumJob) -> str | None:
    score = whole(job)
    return musicxml(score, mapping_of(job)) if score else None


def export_midi(job: DrumJob) -> bytes | None:
    score = whole(job)
    return midi(score, mapping_of(job)) if score else None
