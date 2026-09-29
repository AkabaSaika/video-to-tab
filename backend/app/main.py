from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, Any, Literal

import cv2
from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import workflow
from app.frames import DecodeError, frame_at
from app.jobs import Job, JobStore, Status
from app.models import Roi
from app.omr.model import Song
from app.pipeline import AnalyzeParams
from app.source import VIDEO_EXTS, SourceError, normalize_url, save_upload

REPO_ROOT = Path(__file__).resolve().parents[2]


def safe_path(root: Path, name: str) -> Path | None:
    path = (root / name).resolve()
    return path if path.is_relative_to(root.resolve()) and path.is_file() else None


class RegionIn(BaseModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    w: int = Field(gt=0)
    h: int = Field(gt=0)
    fps: float = Field(default=5.0, gt=0, le=60)
    diff_threshold: float = Field(default=0.15, gt=0, lt=1)
    min_duration: float = Field(default=0.8, ge=0)


class RecognizeIn(BaseModel):
    order: list[int]


class ExportIn(BaseModel):
    order: list[int]
    fmt: Literal["png", "pdf"]


def create_app(data_dir: Path | None = None) -> FastAPI:
    data_dir = data_dir or Path(os.environ.get("VTT_DATA_DIR", REPO_ROOT / "data" / "jobs"))
    store = JobStore(data_dir)
    app = FastAPI(title="video-to-tab")
    app.state.store = store

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        detail = "参数不合法：" + "; ".join(
            f"{'.'.join(str(p) for p in e['loc'][1:])} {e['msg']}" for e in exc.errors()
        )
        return JSONResponse(status_code=422, content={"detail": detail})

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
            if file is not None:
                ext = Path(file.filename or "").suffix.lower()
                if ext not in VIDEO_EXTS:
                    raise SourceError(f"不支持的文件类型：{ext or '无扩展名'}")
            job = store.create()
            if file is not None:
                path = save_upload(file.file, file.filename or "", job.dir)
                store.update(job, video=path.name, source=file.filename or "")
            else:
                store.update(job, source=clean_url)
        except SourceError as exc:
            raise HTTPException(400, str(exc)) from exc
        store.run(job, lambda: workflow.prepare(store, job, clean_url))
        return job.to_dict()

    @app.get("/api/jobs")
    def list_jobs() -> list[dict]:
        return [job.summary() for job in store.recent()]

    @app.get("/api/jobs/{job_id}")
    def read_job(job_id: str) -> dict:
        return get_job(job_id).to_dict()

    @app.put("/api/jobs/{job_id}/region")
    def set_region(job_id: str, body: RegionIn) -> dict:
        job = get_job(job_id)
        if not job.region:
            raise HTTPException(409, "视频尚未就绪")
        roi = Roi(body.x, body.y, body.w, body.h)
        params = AnalyzeParams(body.fps, body.diff_threshold, body.min_duration)
        allowed = (
            Status.READY_FOR_REGION,
            Status.READY_FOR_REVIEW,
            Status.READY_FOR_SCORE,
            Status.FAILED,
        )
        if not store.transition(job, allowed, status=Status.ANALYZING, error=None):
            raise HTTPException(409, f"当前状态不能开始分析：{job.status}")
        store.run(job, lambda: workflow.run_analysis(store, job, roi, params))
        return job.to_dict()

    @app.post("/api/jobs/{job_id}/recognize")
    def recognize(job_id: str, body: RecognizeIn) -> dict:
        job = get_job(job_id)
        known = {p["id"] for p in job.pages}
        if not body.order:
            raise HTTPException(400, "没有选中任何页面")
        if not set(body.order) <= known:
            raise HTTPException(400, "页面不存在，请刷新后重试")
        allowed = (Status.READY_FOR_REVIEW, Status.READY_FOR_SCORE, Status.FAILED)
        changes = {"status": Status.RECOGNIZING, "stage": "recognize", "progress": 0.0}
        if not store.transition(job, allowed, **changes, error=None):
            raise HTTPException(409, f"当前状态不能开始识谱：{job.status}")
        store.run(job, lambda: workflow.recognize(store, job, body.order))
        return job.to_dict()

    @app.get("/api/jobs/{job_id}/score")
    def read_score(job_id: str) -> dict:
        job = get_job(job_id)
        path = job.dir / "score.json"
        if not path.is_file():
            raise HTTPException(404, "还没有识谱结果")
        data = json.loads(path.read_text(encoding="utf-8"))
        try:  # score.json from before multi-track support holds a single Score
            return Song.from_dict(data).to_dict()
        except ValueError:
            return data

    @app.put("/api/jobs/{job_id}/score")
    def write_score(job_id: str, body: Annotated[Any, Body()]) -> dict:
        job = get_job(job_id)
        if job.status == Status.RECOGNIZING:
            raise HTTPException(409, "正在识谱，请稍后再保存")
        if not (job.dir / "score.json").is_file():
            raise HTTPException(404, "还没有识谱结果")
        try:
            song = Song.from_dict(body)
        except ValueError as exc:
            raise HTTPException(422, f"乐谱数据不合法：{exc}") from exc
        workflow.save_score(job, song)
        if song.title != job.title:
            store.update(job, title=song.title)
        return {"ok": True}

    @app.post("/api/jobs/{job_id}/export")
    def export(job_id: str, body: ExportIn) -> dict:
        job = get_job(job_id)
        try:
            name = workflow.export(job, body.order, body.fmt)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(500, str(exc)) from exc
        return {"url": f"/api/jobs/{job_id}/files/{name}"}

    @app.get("/api/jobs/{job_id}/frame")
    def frame(job_id: str, t: float = 0.0) -> Response:
        job = get_job(job_id)
        if not job.video:
            raise HTTPException(409, "视频尚未就绪")
        try:
            img = frame_at(job.dir / job.video, t)
        except DecodeError as exc:
            raise HTTPException(400, str(exc)) from exc
        ok, buf = cv2.imencode(".jpg", img)
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

    dist = Path(os.environ.get("VTT_FRONTEND_DIR", REPO_ROOT / "frontend" / "dist"))
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


app = create_app()
