
from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import aiofiles
import httpx
from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from artscraper_runner.cli import build_processors
from artscraper_runner.core import BaseProcessor, run_pipeline, dumps_json
from artscraper_runner.protection_pipeline import (
    _apply_layers,
    _build_project_status,
)
from artscraper_runner.utils import extend_sys_path


STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_ERROR = "error"


@dataclass
class GatewayConfig:
    base_dir: Path = Path("gateway_jobs")
    output_parent: Path = Path("outputs")
    worker_concurrency: int = 1
    request_timeout: float = 30.0

    def resolved_base(self) -> Path:
        path = self.base_dir.resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    def resolved_output_parent(self) -> Path:
        path = self.output_parent.resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path


@dataclass
class JobResult:
    output_dir: Path
    summary_path: Path
    analysis_path: Optional[Path]
    summary: Dict[str, object]
    analysis: Optional[Dict[str, object]]


@dataclass
class JobRecord:
    job_id: str
    input_path: Path
    input_dir: Path
    output_root: Path
    include_hash_analysis: bool
    include_protection: bool
    enable_tineye: bool
    processors: Optional[Sequence[str]]
    status: str = STATUS_QUEUED
    error: Optional[str] = None
    submitted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    result: Optional[JobResult] = None

    def touch(self, status: Optional[str] = None, error: Optional[str] = None) -> None:
        if status:
            self.status = status
        if error is not None:
            self.error = error
        self.updated_at = datetime.now(timezone.utc)


@dataclass
class GatewayState:
    config: GatewayConfig
    queue: asyncio.Queue[str]
    jobs: Dict[str, JobRecord]
    workers: List[asyncio.Task]


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    submitted_at: datetime
    updated_at: datetime
    error: Optional[str] = None


class JobCreateResponse(BaseModel):
    job_id: str
    status: str


class JobResultResponse(BaseModel):
    job_id: str
    summary: Dict[str, object]
    analysis: Optional[Dict[str, object]]
    output_dir: str


class JobPayload(BaseModel):
    image_url: Optional[str] = None
    local_path: Optional[str] = None
    processors: Optional[Sequence[str]] = None
    include_hash_analysis: Optional[bool] = None
    include_protection: Optional[bool] = None
    enable_tineye: Optional[bool] = None


async def _download_to_path(url: str, dest: Path, timeout: float) -> None:
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(dest, "wb") as out:
                async for chunk in response.aiter_bytes():
                    await out.write(chunk)


def _resolve_local_path(raw: str) -> Path:
    path = Path(raw).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"local file not found: {path}")
    return path


def _filter_processors(processors: List[BaseProcessor], allowed: Optional[Sequence[str]]) -> List[BaseProcessor]:
    if not allowed:
        return processors
    allowed_set = {name.lower() for name in allowed}
    filtered = [proc for proc in processors if proc.name.lower() in allowed_set]
    if not filtered:
        raise ValueError("no processors matched requested names")
    return filtered


def _ensure_original_layer(image_path: Path, target_dir: Path) -> Dict[str, object]:
    from PIL import Image

    layers_dir = target_dir / "layers" / "00-original"
    layers_dir.mkdir(parents=True, exist_ok=True)
    destination = layers_dir / image_path.name
    shutil.copy2(image_path, destination)
    with Image.open(image_path) as im:
        size = list(im.size)
    return {
        "stage": "original",
        "description": "Unmodified input image",
        "path": str(destination.resolve()),
        "processing_size": size,
    }


def _process_job(job: JobRecord) -> JobResult:
    extend_sys_path()
    output_root = job.output_root
    image_path = job.input_path
    image_stem = image_path.stem

    target_dir = output_root / image_stem
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    analysis_summary: Optional[Dict[str, object]] = None
    analysis_path: Optional[Path] = None
    if job.include_hash_analysis:
        processors = build_processors(include_tineye=job.enable_tineye)
        processors = _filter_processors(processors, job.processors)
        analysis_summary = run_pipeline(str(image_path), processors)
        analysis_path = target_dir / "analysis.json"
        analysis_path.write_text(dumps_json(analysis_summary), encoding="ascii")

    if job.include_protection:
        stage_records: List[Dict[str, object]] = _apply_layers(image_path, target_dir)
    else:
        stage_records = [_ensure_original_layer(image_path, target_dir)]

    project_status = _build_project_status(stage_records, analysis_summary)
    summary: Dict[str, object] = {
        "image": str(image_path.resolve()),
        "analysis": str(analysis_path.resolve()) if analysis_path else None,
        "layers": stage_records,
        "projects": project_status,
    }
    summary_path = target_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="ascii")

    return JobResult(
        output_dir=target_dir,
        summary_path=summary_path,
        analysis_path=analysis_path,
        summary=summary,
        analysis=analysis_summary,
    )


async def _worker_loop(state: GatewayState) -> None:
    while True:
        try:
            job_id = await state.queue.get()
        except asyncio.CancelledError:
            break
        job = state.jobs.get(job_id)
        if job is None:
            state.queue.task_done()
            continue
        job.touch(status=STATUS_RUNNING)
        try:
            result = await asyncio.to_thread(_process_job, job)
        except Exception as exc:  # noqa: BLE001
            job.touch(status=STATUS_ERROR, error=str(exc))
        else:
            job.result = result
            job.touch(status=STATUS_DONE)
        finally:
            state.queue.task_done()


def _boolean_from_form(value: Optional[str], default: bool) -> bool:
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


async def _create_job_from_multipart(
    state: GatewayState,
    file: UploadFile,
    include_hash_analysis: Optional[str],
    include_protection: Optional[str],
    enable_tineye: Optional[str],
    processors: Optional[str] = None,
) -> JobCreateResponse:
    config = state.config
    base_dir = config.resolved_base()
    output_parent = config.resolved_output_parent()

    job_id = uuid.uuid4().hex
    job_dir = base_dir / job_id
    input_dir = job_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_root = output_parent / job_id

    suffix = Path(file.filename or "image").suffix or ".bin"
    stored_path = input_dir / f"{job_id}{suffix}"
    async with aiofiles.open(stored_path, "wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            await out.write(chunk)

    processor_names: Optional[List[str]] = None
    if processors:
        processor_names = [part.strip() for part in processors.split(",") if part.strip()]

    record = JobRecord(
        job_id=job_id,
        input_path=stored_path,
        input_dir=input_dir,
        output_root=output_root,
        include_hash_analysis=_boolean_from_form(include_hash_analysis, True),
        include_protection=_boolean_from_form(include_protection, True),
        enable_tineye=_boolean_from_form(enable_tineye, False),
        processors=processor_names,
    )
    state.jobs[job_id] = record
    await state.queue.put(job_id)
    return JobCreateResponse(job_id=job_id, status=record.status)


async def _create_job_from_payload(payload: JobPayload, state: GatewayState) -> JobCreateResponse:
    if not payload.image_url and not payload.local_path:
        raise HTTPException(status_code=400, detail="image_url or local_path required")

    config = state.config
    base_dir = config.resolved_base()
    output_parent = config.resolved_output_parent()

    job_id = uuid.uuid4().hex
    job_dir = base_dir / job_id
    input_dir = job_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_root = output_parent / job_id

    if payload.local_path:
        source = _resolve_local_path(payload.local_path)
        suffix = source.suffix or ".bin"
        stored_path = input_dir / f"{job_id}{suffix}"
        shutil.copy2(source, stored_path)
    else:
        suffix = Path(payload.image_url).suffix or ".bin"
        stored_path = input_dir / f"{job_id}{suffix}"
        await _download_to_path(payload.image_url, stored_path, timeout=config.request_timeout)

    record = JobRecord(
        job_id=job_id,
        input_path=stored_path,
        input_dir=input_dir,
        output_root=output_root,
        include_hash_analysis=payload.include_hash_analysis if payload.include_hash_analysis is not None else True,
        include_protection=payload.include_protection if payload.include_protection is not None else True,
        enable_tineye=payload.enable_tineye if payload.enable_tineye is not None else False,
        processors=payload.processors,
    )
    state.jobs[job_id] = record
    await state.queue.put(job_id)
    return JobCreateResponse(job_id=job_id, status=record.status)


def create_app(config: Optional[GatewayConfig] = None) -> FastAPI:
    cfg = config or GatewayConfig()
    state = GatewayState(config=cfg, queue=asyncio.Queue(), jobs={}, workers=[])

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # noqa: ANN001
        cfg.resolved_base()
        cfg.resolved_output_parent()
        for _ in range(max(1, cfg.worker_concurrency)):
            task = asyncio.create_task(_worker_loop(state))
            state.workers.append(task)
        try:
            yield
        finally:
            for task in state.workers:
                task.cancel()
            for task in state.workers:
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            state.workers.clear()

    app = FastAPI(title="Artscraper Gateway", version="0.1.0", lifespan=lifespan)

    def get_state() -> GatewayState:
        return state

    @app.post("/v1/jobs", response_model=JobCreateResponse)
    async def submit_job(
        state: GatewayState = Depends(get_state),
        file: UploadFile = File(None),
        include_hash_analysis: Optional[str] = Form(None),
        include_protection: Optional[str] = Form(None),
        enable_tineye: Optional[str] = Form(None),
        processors: Optional[str] = Form(None),
        payload: Optional[JobPayload] = Body(None),
    ) -> JobCreateResponse:
        if file is not None:
            return await _create_job_from_multipart(
                state,
                file,
                include_hash_analysis,
                include_protection,
                enable_tineye,
                processors,
            )
        if payload is not None:
            return await _create_job_from_payload(payload, state)
        raise HTTPException(status_code=400, detail="file upload or JSON payload required")

    @app.get("/v1/jobs/{job_id}", response_model=JobStatusResponse)
    async def get_status(job_id: str, state: GatewayState = Depends(get_state)) -> JobStatusResponse:
        record = state.jobs.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="job not found")
        return JobStatusResponse(
            job_id=job_id,
            status=record.status,
            submitted_at=record.submitted_at,
            updated_at=record.updated_at,
            error=record.error,
        )

    @app.get("/v1/jobs/{job_id}/result", response_model=JobResultResponse)
    async def get_result(job_id: str, state: GatewayState = Depends(get_state)) -> JobResultResponse:
        record = state.jobs.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="job not found")
        if record.status != STATUS_DONE or record.result is None:
            raise HTTPException(status_code=409, detail="job not complete")
        result = record.result
        return JobResultResponse(
            job_id=job_id,
            summary=result.summary,
            analysis=result.analysis,
            output_dir=str(result.output_dir.resolve()),
        )

    @app.get("/v1/jobs/{job_id}/layers/{layer}")
    async def get_layer(job_id: str, layer: str, state: GatewayState = Depends(get_state)) -> FileResponse:
        record = state.jobs.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="job not found")
        if record.status != STATUS_DONE or record.result is None:
            raise HTTPException(status_code=409, detail="job not complete")
        for entry in record.result.summary.get("layers", []):
            if entry.get("stage") == layer:
                path = Path(entry.get("path", ""))
                if not path.is_file():
                    raise HTTPException(status_code=404, detail="layer file missing")
                return FileResponse(path)
        raise HTTPException(status_code=404, detail="layer not found")

    @app.delete("/v1/jobs/{job_id}")
    async def delete_job(job_id: str, state: GatewayState = Depends(get_state)) -> JSONResponse:
        record = state.jobs.pop(job_id, None)
        if record is None:
            raise HTTPException(status_code=404, detail="job not found")
        try:
            shutil.rmtree(record.input_dir.parent)
        except FileNotFoundError:
            pass
        try:
            shutil.rmtree(record.output_root)
        except FileNotFoundError:
            pass
        return JSONResponse({"job_id": job_id, "status": "deleted"})

    return app
