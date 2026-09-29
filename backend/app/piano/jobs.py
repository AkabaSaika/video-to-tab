"""Piano jobs: the guitar JobStore's storage and threading, with the piano job's own
fields and states. They live in their own data folder (data/piano)."""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field, fields
from enum import StrEnum
from pathlib import Path

from app.jobs import INTERRUPTED, JobStore


class PianoStatus(StrEnum):
    DOWNLOADING = "downloading"
    CAPTURING = "capturing"
    RECOGNIZING = "recognizing"
    READY = "ready"
    FAILED = "failed"


BUSY = (PianoStatus.DOWNLOADING, PianoStatus.CAPTURING, PianoStatus.RECOGNIZING)


@dataclass
class PianoJob:
    id: str
    dir: Path
    status: PianoStatus = PianoStatus.DOWNLOADING
    stage: str = ""  # download | capture | recognize
    progress: float = 0.0
    error: str | None = None
    video: str | None = None  # file name inside dir
    width: int = 0
    height: int = 0
    duration: float = 0.0
    systems: list[dict] = field(default_factory=list)
    # {"id", "image", "musicxml" (None until recognized), "ok" (None = not yet),
    #  "error", "start", "end" (seconds the system is on screen), "attempts"}
    created: float = 0.0
    source: str = ""  # uploaded file name or URL
    title: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        del d["dir"]
        return d

    @staticmethod
    def from_dict(d: dict, job_dir: Path) -> PianoJob:
        known = {f.name for f in fields(PianoJob)} - {"dir"}
        job = PianoJob(**{k: v for k, v in d.items() if k in known}, dir=job_dir)
        job.status = PianoStatus(job.status)
        return job

    def summary(self) -> dict:
        return {
            "id": self.id,
            "created": self.created,
            "status": self.status,
            "title": self.title,
            "source": self.source,
            "systems": len(self.systems),
        }


class PianoStore(JobStore):
    def _load(self) -> None:
        for state in self.root.glob("*/state.json"):
            try:
                data = json.loads(state.read_text(encoding="utf-8"))
                job = PianoJob.from_dict(data, state.parent)
            except (OSError, ValueError, TypeError) as exc:
                logging.getLogger(__name__).warning("skipping %s: %s", state, exc)
                continue
            if job.id != state.parent.name:
                continue
            if job.status in BUSY:
                job.status, job.error, job.stage = PianoStatus.FAILED, INTERRUPTED, ""
                self.save(job)
            self._jobs[job.id] = job

    def create(self) -> PianoJob:  # type: ignore[override]
        job_id = uuid.uuid4().hex[:12]
        job = PianoJob(id=job_id, dir=self.root / job_id, created=time.time())
        job.dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._jobs[job.id] = job
        self.save(job)
        return job
