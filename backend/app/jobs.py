from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path

from app.frames import DecodeError
from app.pipeline import NoPagesFound
from app.source import SourceError


class Status(StrEnum):
    DOWNLOADING = "downloading"
    READY_FOR_REGION = "ready_for_region"
    ANALYZING = "analyzing"
    READY_FOR_REVIEW = "ready_for_review"
    FAILED = "failed"


@dataclass
class Job:
    id: str
    dir: Path
    status: Status = Status.DOWNLOADING
    stage: str = ""
    progress: float = 0.0
    error: str | None = None
    video: str | None = None  # file name inside dir
    width: int = 0
    height: int = 0
    duration: float = 0.0
    region: dict | None = None  # {"roi": {...}, "confidence": float}
    pages: list[dict] = field(default_factory=list)
    # page dict: {"id", "file", "start", "end", "duplicate_of"}

    def to_dict(self) -> dict:
        d = asdict(self)
        del d["dir"]  # absolute filesystem path; not for clients or state.json
        return d


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

    def create(self) -> Job:
        job_id = uuid.uuid4().hex[:12]
        job = Job(id=job_id, dir=self.root / job_id)
        job.dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._jobs[job_id] = job
        self.save(job)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def save(self, job: Job) -> None:
        (job.dir / "state.json").write_text(json.dumps(job.to_dict(), ensure_ascii=False, indent=2))

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
