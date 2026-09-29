from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, fields
from enum import StrEnum
from pathlib import Path

from app.frames import DecodeError
from app.pipeline import NoPagesFound
from app.source import SourceError

INTERRUPTED = "程序重启，处理被中断，请重试"


def write_atomic(path: Path, text: str) -> None:
    """Write via a temp file in the same folder + rename, so readers never see half a file."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class Status(StrEnum):
    DOWNLOADING = "downloading"
    READY_FOR_REGION = "ready_for_region"
    ANALYZING = "analyzing"
    READY_FOR_REVIEW = "ready_for_review"
    RECOGNIZING = "recognizing"
    READY_FOR_SCORE = "ready_for_score"
    FAILED = "failed"


@dataclass
class Job:
    id: str
    dir: Path
    status: Status = Status.DOWNLOADING
    stage: str = ""  # download | probe | scan | compose | recognize
    progress: float = 0.0
    error: str | None = None
    video: str | None = None  # file name inside dir
    width: int = 0
    height: int = 0
    duration: float = 0.0
    region: dict | None = None  # {"roi": {...}, "confidence": float}
    pages: list[dict] = field(default_factory=list)
    # page dict: {"id", "file", "start", "end", "duplicate_of"}
    created: float = 0.0  # unix time
    source: str = ""  # uploaded file name or URL
    title: str = ""  # score title, mirrored from score.json on save
    score_order: list[int] = field(default_factory=list)
    # page ids given to the last recognition; Measure.line indexes into this list
    score_files: list[str] = field(default_factory=list)
    # their page files at recognition time; re-analysis deletes these, so a stale score
    # never shows a different page's image

    def to_dict(self) -> dict:
        d = asdict(self)
        del d["dir"]  # absolute filesystem path; not for clients or state.json
        return d

    @staticmethod
    def from_dict(d: dict, job_dir: Path) -> Job:
        known = {f.name for f in fields(Job)} - {"dir"}
        job = Job(**{k: v for k, v in d.items() if k in known}, dir=job_dir)
        job.status = Status(job.status)
        return job

    def summary(self) -> dict:
        return {
            "id": self.id,
            "created": self.created,
            "status": self.status,
            "title": self.title,
            "source": self.source,
        }


class JobStore:
    # Keys that only carry incremental progress info; updates touching only these are
    # throttled (see update()) since analysis can emit thousands of them per job.
    _PROGRESS_ONLY_KEYS = frozenset({"progress", "stage"})
    _PROGRESS_SAVE_INTERVAL = 0.5  # seconds

    def __init__(self, root: Path):
        self.root = root
        self._jobs: dict[str, Job] = {}
        self._lock = threading.RLock()
        self._last_save: dict[str, float] = {}
        self._load()

    def _load(self) -> None:
        """Restore jobs from <root>/*/state.json; work cut short by a restart is failed."""
        busy = (Status.DOWNLOADING, Status.ANALYZING, Status.RECOGNIZING)
        for state in self.root.glob("*/state.json"):
            try:
                job = Job.from_dict(json.loads(state.read_text(encoding="utf-8")), state.parent)
            except (OSError, ValueError, TypeError) as exc:
                logging.getLogger(__name__).warning("skipping %s: %s", state, exc)
                continue
            if job.id != state.parent.name:
                continue
            if not job.created:
                job.created = state.stat().st_mtime
            if job.status in busy:
                job.status, job.error, job.stage = Status.FAILED, INTERRUPTED, ""
                self.save(job)
            self._jobs[job.id] = job

    def create(self) -> Job:
        job_id = uuid.uuid4().hex[:12]
        job = Job(id=job_id, dir=self.root / job_id, created=time.time())
        job.dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._jobs[job_id] = job
        self.save(job)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def recent(self, limit: int = 20) -> list[Job]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created, reverse=True)
        return jobs[:limit]

    def save(self, job: Job) -> None:
        text = json.dumps(job.to_dict(), ensure_ascii=False, indent=2)
        write_atomic(job.dir / "state.json", text)

    def update(self, job: Job, **changes) -> None:
        with self._lock:
            for key, value in changes.items():
                setattr(job, key, value)
            if changes.keys() <= self._PROGRESS_ONLY_KEYS:
                now = time.monotonic()
                if now - self._last_save.get(job.id, 0.0) < self._PROGRESS_SAVE_INTERVAL:
                    return
            self._last_save[job.id] = time.monotonic()
            self.save(job)

    def transition(self, job: Job, allowed: tuple[Status, ...], **changes) -> bool:
        """Atomically apply `changes` iff job.status is currently in `allowed`.

        Guards against two concurrent callers both passing a status check and
        launching duplicate work (e.g. two PUT /region requests racing).
        """
        with self._lock:
            if job.status not in allowed:
                return False
            for key, value in changes.items():
                setattr(job, key, value)
            self.save(job)
            return True

    def run(self, job: Job, fn: Callable[[], None]) -> threading.Thread:
        """Run fn in a daemon thread; any exception marks the job failed.

        App-level errors (already Chinese, or yt-dlp errors wrapped in Chinese by
        SourceError) are surfaced verbatim. Anything else is an unexpected bug, so
        it's wrapped in a generic Chinese message and the traceback is logged.
        """

        def target() -> None:
            try:
                fn()
            except (SourceError, DecodeError, NoPagesFound, ValueError) as exc:
                logging.getLogger(__name__).exception("job %s failed", job.id)
                self.update(job, status=Status.FAILED, error=str(exc))
            except Exception as exc:  # noqa: BLE001 - deliberately broad: any bug must fail the job
                logging.getLogger(__name__).exception("job %s failed", job.id)
                self.update(
                    job, status=Status.FAILED, error=f"处理失败（{type(exc).__name__}）：{exc}"
                )

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        return thread
