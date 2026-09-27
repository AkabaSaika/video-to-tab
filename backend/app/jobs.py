from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path


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
        d["dir"] = str(self.dir)
        return d


class JobStore:
    def __init__(self, root: Path):
        self.root = root
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

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
        for key, value in changes.items():
            setattr(job, key, value)
        self.save(job)

    def run(self, job: Job, fn: Callable[[], None]) -> threading.Thread:
        """Run fn in a daemon thread; any exception marks the job failed."""

        def target() -> None:
            try:
                fn()
            except Exception as exc:  # noqa: BLE001 - surfaced to the user verbatim
                self.update(job, status=Status.FAILED, error=str(exc))

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        return thread
