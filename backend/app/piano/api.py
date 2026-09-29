"""/api/piano/*: piano sheet jobs (see docs/superpowers/specs/2026-09-29-piano-design.md)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from app.piano import workflow
from app.piano.jobs import BUSY, PianoJob, PianoStatus, PianoStore
from app.source import VIDEO_EXTS, SourceError, normalize_url, save_upload


def _safe_path(root: Path, name: str) -> Path | None:
    path = (root / name).resolve()
    return path if path.is_relative_to(root.resolve()) and path.is_file() else None


def piano_router(store: PianoStore) -> APIRouter:
    router = APIRouter(prefix="/api/piano")

    def get_job(job_id: str) -> PianoJob:
        job = store.get(job_id)
        if job is None:
            raise HTTPException(404, "任务不存在")
        return job

    def editable(job_id: str, sid: int) -> tuple[PianoJob, dict]:
        job = get_job(job_id)
        if job.status in BUSY:
            raise HTTPException(409, "任务正在处理中，请稍后再试")
        entry = next((s for s in job.systems if s["id"] == sid), None)
        if entry is None:
            raise HTTPException(404, "这一组谱表不存在，请刷新后重试")
        return job, entry

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

    @router.delete("/jobs/{job_id}/systems/{sid}")
    def delete_system(job_id: str, sid: int) -> dict:
        job, entry = editable(job_id, sid)
        store.update(job, systems=[s for s in job.systems if s["id"] != sid])
        for key in ("image", "musicxml"):
            path = _safe_path(job.dir, entry.get(key) or "")
            if path is not None:
                path.unlink()
        return job.to_dict()

    @router.post("/jobs/{job_id}/systems/{sid}/recognize")
    def recognize_system(job_id: str, sid: int) -> dict:
        job, _ = editable(job_id, sid)
        workflow.recognize_system(store, job, sid)
        if job.status == PianoStatus.FAILED and any(s.get("ok") for s in job.systems):
            store.update(job, status=PianoStatus.READY, error=None)
        return job.to_dict()

    @router.get("/jobs/{job_id}/musicxml")
    def musicxml(job_id: str) -> Response:
        job = get_job(job_id)
        text = workflow.merged(job)
        if text is None:
            raise HTTPException(404, "还没有识别出的谱表")
        name = f"piano-{job.id}.musicxml"
        return Response(
            text,
            media_type="application/vnd.recordare.musicxml+xml",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    @router.get("/jobs/{job_id}/files/{name:path}")
    def files(job_id: str, name: str) -> FileResponse:
        job = get_job(job_id)
        path = _safe_path(job.dir, name)
        if path is None:
            raise HTTPException(404, "文件不存在")
        return FileResponse(path)

    return router
