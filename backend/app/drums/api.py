"""/api/drums/*: drum sheet jobs (see docs/superpowers/specs/2026-09-30-drums-design.md)."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from app.drums import workflow
from app.drums.instruments import INSTRUMENTS, Mapping, catalog, used_keys
from app.drums.jobs import BUSY, DrumJob, DrumStatus, DrumStore
from app.drums.model import DrumNote
from app.drums.recognize import TIMES
from app.source import VIDEO_EXTS, SourceError, normalize_url, save_upload


class MappingIn(BaseModel):
    preset: str = "default"
    overrides: dict[str, int] = Field(default_factory=dict)


class SettingsIn(BaseModel):
    time: list[int] | None = None
    tempo: int = Field(default=120, ge=20, le=400)


def _safe_path(root: Path, name: str) -> Path | None:
    path = (root / name).resolve()
    return path if path.is_relative_to(root.resolve()) and path.is_file() else None


def mapping_view(job: DrumJob) -> dict:
    """The job's map, the choices, and every (position, notehead) the pages use with
    the drum it currently means."""
    mapping = workflow.mapping_of(job)
    measures = []
    for entry in job.pages:
        if entry.get("ok"):
            score = workflow.page_score(job, entry)
            if score is not None:
                measures += score.measures
    table = mapping.table()
    used = []
    for key, count in sorted(used_keys(measures).items(), key=lambda kv: -kv[1]):
        pos, head, *rest = key.split(":")
        note = DrumNote(pos[0], int(pos[1:]), head, open=bool(rest))
        gm = mapping.resolve(note)
        used.append(
            {
                "key": key,
                "count": count,
                "gm": gm,
                "label": INSTRUMENTS[gm].label if gm in INSTRUMENTS else str(gm),
                "overridden": key in mapping.overrides,
            }
        )
    return mapping.to_dict() | {"table": table, "used": used} | catalog()


def drums_router(store: DrumStore) -> APIRouter:
    router = APIRouter(prefix="/api/drums")

    def get_job(job_id: str) -> DrumJob:
        job = store.get(job_id)
        if job is None:
            raise HTTPException(404, "任务不存在")
        return job

    def idle(job_id: str) -> DrumJob:
        job = get_job(job_id)
        if job.status in BUSY:
            raise HTTPException(409, "任务正在处理中，请稍后再试")
        return job

    def page_of(job: DrumJob, pid: int) -> dict:
        entry = next((p for p in job.pages if p["id"] == pid), None)
        if entry is None:
            raise HTTPException(404, "这一页不存在，请刷新后重试")
        return entry

    @router.post("/jobs")
    def create_job(file: UploadFile | None = File(None), url: str | None = Form(None)) -> dict:
        if (file is None) == (not url):
            raise HTTPException(400, "请上传视频文件或填写链接（二选一）")
        try:
            clean_url = normalize_url(url) if url else None
            if file is not None:
                ext = Path(file.filename or "").suffix.lower()
                if ext not in VIDEO_EXTS:
                    raise SourceError(f"不支持的文件类型：{ext or '无扩展名'}")
            job = store.create()
            if file is not None:
                name = file.filename or ""
                path = save_upload(file.file, name, job.dir)
                store.update(job, video=path.name, source=name, title=Path(name).stem)
            else:
                store.update(job, source=clean_url)
        except SourceError as exc:
            raise HTTPException(400, str(exc)) from exc
        store.run(job, lambda: workflow.run(store, job, clean_url))
        return job.to_dict()

    @router.get("/jobs")
    def list_jobs() -> list[dict]:
        return [job.summary() for job in store.recent()]

    @router.get("/jobs/{job_id}")
    def read_job(job_id: str) -> dict:
        return get_job(job_id).to_dict()

    @router.delete("/jobs/{job_id}/pages/{pid}")
    def delete_page(job_id: str, pid: int) -> dict:
        job = idle(job_id)
        entry = page_of(job, pid)
        store.update(job, pages=[p for p in job.pages if p["id"] != pid])
        for key in ("image", "score", "musicxml"):
            path = _safe_path(job.dir, entry.get(key) or "")
            if path is not None:
                path.unlink()
        return job.to_dict()

    @router.post("/jobs/{job_id}/pages/{pid}/recognize")
    def recognize_page(job_id: str, pid: int) -> dict:
        job = idle(job_id)
        page_of(job, pid)
        workflow.recognize_page(store, job, pid)
        if job.status == DrumStatus.FAILED and any(p.get("ok") for p in job.pages):
            store.update(job, status=DrumStatus.READY, error=None)
        return job.to_dict()

    @router.get("/jobs/{job_id}/mapping")
    def read_mapping(job_id: str) -> dict:
        return mapping_view(get_job(job_id))

    @router.put("/jobs/{job_id}/mapping")
    def write_mapping(job_id: str, body: MappingIn) -> dict:
        job = idle(job_id)
        try:
            mapping = Mapping(body.preset, dict(body.overrides))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        store.update(job, mapping=mapping.to_dict())
        workflow.rerender(store, job)
        return {"job": job.to_dict(), "mapping": mapping_view(job)}

    @router.put("/jobs/{job_id}/settings")
    def write_settings(job_id: str, body: SettingsIn) -> dict:
        job = idle(job_id)
        time_sig = list(body.time) if body.time else None
        if time_sig is not None and (len(time_sig) != 2 or tuple(time_sig) not in TIMES):
            raise HTTPException(400, f"不支持的拍号：{'/'.join(map(str, time_sig))}")
        time_changed = time_sig != job.time
        store.update(job, time=time_sig, tempo=body.tempo)
        if time_changed:
            workflow.reread(store, job)
        else:
            workflow.rerender(store, job)
        return job.to_dict()

    def download(job_id: str, kind: str) -> Response:
        job = get_job(job_id)
        data = workflow.export_musicxml(job) if kind == "musicxml" else workflow.export_midi(job)
        if data is None:
            raise HTTPException(404, "还没有识别出的小节")
        stem = job.title or f"drums-{job.id}"
        ext, media = (
            ("musicxml", "application/vnd.recordare.musicxml+xml")
            if kind == "musicxml"
            else ("mid", "audio/midi")
        )
        ascii_name = f"drums-{job.id}.{ext}"
        disposition = (
            f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(f'{stem}.{ext}')}"
        )
        return Response(data, media_type=media, headers={"Content-Disposition": disposition})

    @router.get("/jobs/{job_id}/musicxml")
    def export_musicxml(job_id: str) -> Response:
        return download(job_id, "musicxml")

    @router.get("/jobs/{job_id}/midi")
    def export_midi(job_id: str) -> Response:
        return download(job_id, "midi")

    @router.get("/jobs/{job_id}/files/{name:path}")
    def files(job_id: str, name: str) -> FileResponse:
        job = get_job(job_id)
        path = _safe_path(job.dir, name)
        if path is None:
            raise HTTPException(404, "文件不存在")
        return FileResponse(path)

    return router
