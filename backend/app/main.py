from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import cv2
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import workflow
from app.frames import frame_at
from app.jobs import Job, JobStore, Status
from app.models import Roi
from app.pipeline import AnalyzeParams
from app.source import SourceError, normalize_url, save_upload

REPO_ROOT = Path(__file__).resolve().parents[2]


def safe_path(root: Path, name: str) -> Path | None:
    path = (root / name).resolve()
    return path if path.is_relative_to(root.resolve()) and path.is_file() else None


class RegionIn(BaseModel):
    x: int
    y: int
    w: int
    h: int
    fps: float = 5.0
    diff_threshold: float = 0.15
    min_duration: float = 0.8


class ExportIn(BaseModel):
    order: list[int]
    fmt: Literal["png", "pdf"]


def create_app(data_dir: Path | None = None) -> FastAPI:
    data_dir = data_dir or Path(os.environ.get("VTT_DATA_DIR", REPO_ROOT / "data" / "jobs"))
    store = JobStore(data_dir)
    app = FastAPI(title="video-to-tab")
    app.state.store = store

    def get_job(job_id: str) -> Job:
        job = store.get(job_id)
        if job is None:
            raise HTTPException(404, "任务不存在")
        return job

    @app.post("/api/jobs")
    def create_job(file: UploadFile | None = File(None), url: str | None = Form(None)) -> dict:
        if (file is None) == (not url):
            raise HTTPException(400, "请上传视频文件或填写链接（二选一）")
        try:
            clean_url = normalize_url(url) if url else None
            job = store.create()
            if file is not None:
                path = save_upload(file.file, file.filename or "", job.dir)
                store.update(job, video=path.name)
        except SourceError as exc:
            raise HTTPException(400, str(exc)) from exc
        store.run(job, lambda: workflow.prepare(store, job, clean_url))
        return job.to_dict()

    @app.get("/api/jobs/{job_id}")
    def read_job(job_id: str) -> dict:
        return get_job(job_id).to_dict()

    @app.put("/api/jobs/{job_id}/region")
    def set_region(job_id: str, body: RegionIn) -> dict:
        job = get_job(job_id)
        if not job.video:
            raise HTTPException(409, "视频尚未就绪")
        roi = Roi(body.x, body.y, body.w, body.h)
        params = AnalyzeParams(body.fps, body.diff_threshold, body.min_duration)
        allowed = (Status.READY_FOR_REGION, Status.READY_FOR_REVIEW, Status.FAILED)
        if not store.transition(job, allowed, status=Status.ANALYZING, error=None):
            raise HTTPException(409, f"当前状态不能开始分析：{job.status}")
        store.run(job, lambda: workflow.run_analysis(store, job, roi, params))
        return job.to_dict()

    @app.post("/api/jobs/{job_id}/export")
    def export(job_id: str, body: ExportIn) -> dict:
        job = get_job(job_id)
        try:
            name = workflow.export(job, body.order, body.fmt)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"url": f"/api/jobs/{job_id}/files/{name}"}

    @app.get("/api/jobs/{job_id}/frame")
    def frame(job_id: str, t: float = 0.0) -> Response:
        job = get_job(job_id)
        if not job.video:
            raise HTTPException(409, "视频尚未就绪")
        ok, buf = cv2.imencode(".jpg", frame_at(job.dir / job.video, t))
        if not ok:
            raise HTTPException(500, "帧图像编码失败")
        return Response(buf.tobytes(), media_type="image/jpeg")

    @app.get("/api/jobs/{job_id}/files/{name:path}")
    def files(job_id: str, name: str) -> FileResponse:
        job = get_job(job_id)
        path = safe_path(job.dir, name)
        if path is None:
            raise HTTPException(404, "文件不存在")
        return FileResponse(path)

    dist = REPO_ROOT / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


app = create_app()
