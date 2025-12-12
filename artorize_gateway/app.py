
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
from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from artorize_runner.cli import build_processors
from artorize_runner.core import BaseProcessor, run_pipeline, dumps_json
from artorize_runner.protection_pipeline import (
    ProtectionWorkflowConfig,
    _build_project_status,
)
from artorize_runner.protection_pipeline_gpu import _apply_layers_batched
from artorize_runner.utils import extend_sys_path
from .input_utils import download_to_path, resolve_local_path, parse_comma_separated, boolean_from_form
from .similarity_routes import router as similarity_router
from .sac_routes import router as sac_router
from .callback_client import CallbackClient
from .image_storage import StorageUploader
from .backend_upload import BackendUploadClient, BackendAuthError



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
    # Callback settings
    callback_timeout: float = 10.0
    callback_retry_attempts: int = 3
    callback_retry_delay: float = 2.0
    # Storage settings
    storage_type: str = "local"  # "local", "s3", or "cdn"
    s3_bucket_name: str = "artorizer-protected-images"
    s3_region: str = "us-east-1"
    cdn_base_url: str = "https://cdn.artorizer.com"
    local_storage_base_url: str = "http://localhost:8000/v1/storage"
    # Backend upload settings
    backend_url: Optional[str] = None
    backend_timeout: float = 30.0
    backend_auth_token: Optional[str] = None
    backend_upload_max_retries: int = 3
    backend_upload_retry_delay: float = 2.0

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
    # Callback support
    callback_url: Optional[str] = None
    callback_auth_token: Optional[str] = None
    artist_name: Optional[str] = None
    artwork_title: Optional[str] = None
    watermark_strategy: Optional[str] = None
    watermark_strength: Optional[float] = None
    # Backend upload support
    backend_url: Optional[str] = None
    backend_auth_token: Optional[str] = None
    artwork_description: Optional[str] = None
    artwork_tags: Optional[Sequence[str]] = None
    artwork_creation_time: Optional[str] = None

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
    callback_client: Optional[CallbackClient] = None
    progress_callback_client: Optional[CallbackClient] = None
    storage_uploader: Optional[StorageUploader] = None
    backend_upload_client: Optional[BackendUploadClient] = None


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


class ArtworkMetadata(BaseModel):
    """Metadata for artwork processing with callback support."""
    job_id: str
    artist_name: Optional[str] = None
    artwork_title: Optional[str] = None
    callback_url: str
    callback_auth_token: str
    processors: Optional[Sequence[str]] = None
    watermark_strategy: Optional[str] = None
    watermark_strength: Optional[float] = None
    tags: Optional[Sequence[str]] = None
    # Backend upload support
    backend_url: Optional[str] = None
    backend_auth_token: Optional[str] = None
    artwork_description: Optional[str] = None
    artwork_creation_time: Optional[str] = None


class ProcessArtworkResponse(BaseModel):
    """Response for artwork processing submission."""
    job_id: str
    status: str
    estimated_time_seconds: Optional[int] = None
    message: str


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
        # Use GPU pipeline by default for better performance
        workflow_config = ProtectionWorkflowConfig()
        stage_records: List[Dict[str, object]] = _apply_layers_batched(
            image_path, target_dir, workflow_config, use_gpu=True
        )
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


async def _send_progress_callback(
    job: JobRecord,
    step: str,
    step_number: int,
    total_steps: int,
    percentage: int,
    state: GatewayState,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Send progress callback to Router during job processing."""
    if not job.callback_url or not job.callback_auth_token or not state.progress_callback_client:
        return

    # Derive progress callback URL by replacing "process-complete" with "process-progress"
    progress_callback_url = job.callback_url.replace("process-complete", "process-progress")

    # Build progress payload
    payload = {
        "job_id": job.job_id,
        "current_step": step,
        "step_number": step_number,
        "total_steps": total_steps,
        "percentage": percentage,
        "details": details or {},
    }

    # Send progress callback
    await state.progress_callback_client.send_progress_callback(
        progress_callback_url,
        job.callback_auth_token,
        payload,
    )


async def _send_callback_on_completion(
    job: JobRecord,
    result: Optional[JobResult],
    error: Optional[str],
    state: GatewayState,
) -> None:
    """Send callback to Router after job completion."""
    if not job.callback_url or not job.callback_auth_token or not state.callback_client:
        return

    start_time = job.submitted_at
    end_time = job.updated_at
    processing_time_ms = int((end_time - start_time).total_seconds() * 1000)

    if error:
        # Send error callback
        payload = {
            "job_id": job.job_id,
            "status": "failed",
            "processing_time_ms": processing_time_ms,
            "error": {
                "code": "PROCESSING_FAILED",
                "message": error,
            },
        }
    elif result and job.backend_url and state.backend_upload_client:
        # NEW MODE: Upload directly to backend
        try:
            # Find the original and final protected images
            original_image_path = job.input_path
            final_layer_path = None
            mask_path = None

            if result.summary.get("layers"):
                layers = result.summary["layers"]
                if layers:
                    # STRATEGY 1: Look for final-comparison layer (preferred - contains mandatory SAC mask)
                    final_comparison_layer = None
                    for layer in reversed(layers):
                        if layer.get("stage") == "final-comparison" and layer.get("has_sac_mask"):
                            final_comparison_layer = layer
                            break

                    if final_comparison_layer:
                        # Final-comparison layer found - extract mask from it
                        if "poison_mask_sac_path" in final_comparison_layer:
                            mask_path = Path(final_comparison_layer["poison_mask_sac_path"])

                        # Find the actual final protected image from the last protection layer
                        for layer in reversed(layers):
                            if layer.get("is_protection_layer") and layer.get("path") and not layer.get("error"):
                                final_layer_path = Path(layer["path"])
                                break
                    else:
                        # STRATEGY 2: Fallback to last protection layer with SAC mask (for backwards compatibility)
                        final_layer = None
                        for layer in reversed(layers):
                            if layer.get("has_sac_mask") and layer.get("path"):
                                final_layer = layer
                                break

                        # STRATEGY 3: Fallback to last protection layer without errors
                        if not final_layer:
                            for layer in reversed(layers):
                                if layer.get("is_protection_layer") and not layer.get("error"):
                                    final_layer = layer
                                    break

                        if not final_layer:
                            raise RuntimeError(
                                f"No valid protection layer found. Checked {len(layers)} layers. "
                                f"Layer stages: {[l.get('stage') for l in layers]}"
                            )

                        final_layer_path = Path(final_layer["path"]) if final_layer.get("path") else None

                        # Look for combined SAC mask in the final layer's poison mask data
                        if "poison_mask_sac_path" in final_layer:
                            mask_path = Path(final_layer["poison_mask_sac_path"])

                    # STRATEGY 4: Pattern-based fallback if mask still not found
                    if not mask_path or not mask_path.exists():
                        # Try to find SAC mask by searching all layer directories
                        search_attempted = False
                        for layer in reversed(layers):
                            if layer.get("path"):
                                layer_path = Path(layer["path"])
                                if layer_path.exists():
                                    search_attempted = True
                                    layer_dir = layer_path.parent
                                    # Look for final-comparison mask first
                                    for mask_file in layer_dir.glob("*final-comparison_mask.sac"):
                                        mask_path = mask_file
                                        break
                                    # If not found, look for any mask.sac file
                                    if not mask_path:
                                        for mask_file in layer_dir.glob("*_mask.sac"):
                                            mask_path = mask_file
                                            break
                                if mask_path:
                                    break

                        if not mask_path and search_attempted:
                            raise RuntimeError(
                                "SAC mask file not found in any layer directory. "
                                "This may indicate the protection pipeline did not complete properly."
                            )

            if not final_layer_path or not final_layer_path.exists():
                raise RuntimeError("Final protected image not found")

            # Extract hashes from analysis
            hashes = {}
            if result.analysis:
                for proc_result in result.analysis.get("results", []):
                    if proc_result.get("processor") == "imagehash":
                        hashes = proc_result.get("data", {}).get("hashes", {})
                        break

            # Prepare metadata for backend
            upload_metadata = {
                "artwork_title": job.artwork_title or "Untitled",
                "artist_name": job.artist_name or "Unknown",
                "artwork_description": job.artwork_description,
                "tags": job.artwork_tags,
                "artwork_creation_time": job.artwork_creation_time,
                "hashes": hashes,
                "watermark": {
                    "strategy": job.watermark_strategy or "invisible-watermark",
                    "strength": job.watermark_strength or 0.5,
                },
                "processing_time_ms": processing_time_ms,
            }

            # Upload to backend
            backend_response = await state.backend_upload_client.upload_artwork(
                backend_url=job.backend_url,
                original_image_path=original_image_path,
                protected_image_path=final_layer_path,
                mask_path=mask_path,
                analysis=result.analysis,
                summary=result.summary,
                metadata=upload_metadata,
                auth_token=job.backend_auth_token,
            )

            artwork_id = backend_response.get("id")
            if not artwork_id:
                raise RuntimeError("Backend did not return artwork_id")

            # Send simplified success callback with artwork_id
            payload = {
                "job_id": job.job_id,
                "status": "completed",
                "backend_artwork_id": artwork_id,
                "processing_time_ms": processing_time_ms,
            }

        except BackendAuthError as e:
            # Backend authentication failed (401 - token invalid/expired/used)
            payload = {
                "job_id": job.job_id,
                "status": "failed",
                "processing_time_ms": processing_time_ms,
                "error": {
                    "code": "BACKEND_AUTH_FAILED",
                    "message": str(e),
                },
            }
        except Exception as e:
            # Backend upload failed (other reasons)
            payload = {
                "job_id": job.job_id,
                "status": "failed",
                "processing_time_ms": processing_time_ms,
                "error": {
                    "code": "BACKEND_UPLOAD_FAILED",
                    "message": str(e),
                },
            }
    elif result and state.storage_uploader:
        # OLD MODE: Upload to storage and send success callback with URLs
        try:
            # Find the final protected image (last layer)
            final_layer_path = None
            sac_mask_path = None

            if result.summary.get("layers"):
                layers = result.summary["layers"]
                if layers:
                    # Find the last protection layer with SAC mask data
                    final_layer = None
                    for layer in reversed(layers):
                        if layer.get("has_sac_mask"):
                            final_layer = layer
                            break

                    # Fallback: find last protection layer without errors
                    if not final_layer:
                        for layer in reversed(layers):
                            if layer.get("is_protection_layer") and not layer.get("error"):
                                final_layer = layer
                                break

                    if not final_layer:
                        raise RuntimeError("No valid protection layer found in processing results")

                    final_layer_path = Path(final_layer["path"])

                    # Look for SAC mask in the final layer's poison mask data
                    if "poison_mask_sac_path" in final_layer:
                        sac_mask_path = Path(final_layer["poison_mask_sac_path"])

            if not final_layer_path or not final_layer_path.exists():
                raise RuntimeError("Final protected image not found")

            # Upload to storage (includes SAC if available)
            storage_urls = await state.storage_uploader.upload_protected_image(
                final_layer_path,
                job.job_id,
                image_format="jpeg",
                sac_path=sac_mask_path,
            )

            # Extract hashes from analysis
            hashes = {}
            if result.analysis:
                for proc_result in result.analysis.get("results", []):
                    if proc_result.get("processor") == "imagehash":
                        hashes = proc_result.get("data", {}).get("hashes", {})
                        break

            # Build success payload
            payload_result = {
                "protected_image_url": storage_urls["protected_image_url"],
                "thumbnail_url": storage_urls["thumbnail_url"],
                "hashes": hashes,
                "metadata": {
                    "artist_name": job.artist_name,
                    "artwork_title": job.artwork_title,
                },
                "watermark": {
                    "strategy": job.watermark_strategy or "invisible-watermark",
                    "strength": job.watermark_strength or 0.5,
                },
            }

            # Add SAC mask URL if available
            if "sac_mask_url" in storage_urls:
                payload_result["sac_mask_url"] = storage_urls["sac_mask_url"]

            payload = {
                "job_id": job.job_id,
                "status": "completed",
                "processing_time_ms": processing_time_ms,
                "result": payload_result,
            }
        except Exception as e:
            # Storage upload failed, send error
            payload = {
                "job_id": job.job_id,
                "status": "failed",
                "processing_time_ms": processing_time_ms,
                "error": {
                    "code": "STORAGE_UPLOAD_FAILED",
                    "message": str(e),
                },
            }
    else:
        # No result, unexpected error
        payload = {
            "job_id": job.job_id,
            "status": "failed",
            "processing_time_ms": processing_time_ms,
            "error": {
                "code": "UNKNOWN_ERROR",
                "message": "Processing completed but no result available",
            },
        }

    # Send callback
    await state.callback_client.send_completion_callback(
        job.callback_url,
        job.callback_auth_token,
        payload,
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

        # Step 1: Starting metadata extraction
        await _send_progress_callback(
            job,
            "Extracting image metadata",
            1,
            4,
            25,
            state,
            {"status": "starting"},
        )

        try:
            # Step 2: Applying protection layers
            await _send_progress_callback(
                job,
                "Applying protection layers",
                2,
                4,
                50,
                state,
                {"status": "processing"},
            )

            result = await asyncio.to_thread(_process_job, job)

            # Step 3: Uploading to backend
            await _send_progress_callback(
                job,
                "Uploading to backend",
                3,
                4,
                75,
                state,
                {"status": "uploading"},
            )

        except Exception as exc:  # noqa: BLE001
            job.touch(status=STATUS_ERROR, error=str(exc))
            # Send callback if enabled
            await _send_callback_on_completion(job, None, str(exc), state)
        else:
            job.result = result
            job.touch(status=STATUS_DONE)
            # Send callback if enabled
            await _send_callback_on_completion(job, result, None, state)
        finally:
            state.queue.task_done()




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

    processor_names = parse_comma_separated(processors)

    record = JobRecord(
        job_id=job_id,
        input_path=stored_path,
        input_dir=input_dir,
        output_root=output_root,
        include_hash_analysis=boolean_from_form(include_hash_analysis, True),
        include_protection=boolean_from_form(include_protection, True),
        enable_tineye=boolean_from_form(enable_tineye, False),
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
        source = resolve_local_path(payload.local_path)
        suffix = source.suffix or ".bin"
        stored_path = input_dir / f"{job_id}{suffix}"
        shutil.copy2(source, stored_path)
    else:
        suffix = Path(payload.image_url).suffix or ".bin"
        stored_path = input_dir / f"{job_id}{suffix}"
        await download_to_path(payload.image_url, stored_path, timeout=config.request_timeout)

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

    # Initialize callback client
    state.callback_client = CallbackClient(
        timeout=cfg.callback_timeout,
        retry_attempts=cfg.callback_retry_attempts,
        retry_delay=cfg.callback_retry_delay,
    )

    # Initialize progress callback client (reuse same instance)
    state.progress_callback_client = state.callback_client

    # Initialize storage uploader
    state.storage_uploader = StorageUploader(
        storage_type=cfg.storage_type,
        s3_bucket_name=cfg.s3_bucket_name,
        s3_region=cfg.s3_region,
        cdn_base_url=cfg.cdn_base_url,
        local_storage_base_url=cfg.local_storage_base_url,
        output_dir=cfg.resolved_output_parent(),
    )

    # Initialize backend upload client
    state.backend_upload_client = BackendUploadClient(
        timeout=cfg.backend_timeout,
        max_retries=cfg.backend_upload_max_retries,
        retry_delay=cfg.backend_upload_retry_delay,
    )

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

    # Include similarity search routes
    app.include_router(similarity_router)

    # Include SAC encoding routes
    app.include_router(sac_router)

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

    @app.post("/v1/process/artwork", response_model=ProcessArtworkResponse, status_code=202)
    async def process_artwork(
        state: GatewayState = Depends(get_state),
        file: UploadFile = File(None),
        metadata: Optional[str] = Form(None),
    ) -> ProcessArtworkResponse:
        """
        Process artwork with callback support.
        Accepts multipart form-data with image file and metadata JSON.
        """
        if not file:
            raise HTTPException(status_code=400, detail="image file required")

        # Parse metadata
        if not metadata:
            raise HTTPException(status_code=400, detail="metadata JSON required")

        try:
            import json as json_lib
            metadata_dict = json_lib.loads(metadata)
            artwork_meta = ArtworkMetadata(**metadata_dict)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid metadata: {e}")

        # Validate backend upload configuration
        if artwork_meta.backend_url and not artwork_meta.backend_auth_token:
            raise HTTPException(
                status_code=400,
                detail="backend_auth_token is required when backend_url is provided"
            )

        # Create job directory
        config = state.config
        base_dir = config.resolved_base()
        output_parent = config.resolved_output_parent()

        job_id = artwork_meta.job_id
        job_dir = base_dir / job_id
        input_dir = job_dir / "input"
        input_dir.mkdir(parents=True, exist_ok=True)
        output_root = output_parent / job_id

        # Save uploaded file
        suffix = Path(file.filename or "image").suffix or ".jpg"
        stored_path = input_dir / f"{job_id}{suffix}"
        async with aiofiles.open(stored_path, "wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                await out.write(chunk)

        # Create job record with callback support
        record = JobRecord(
            job_id=job_id,
            input_path=stored_path,
            input_dir=input_dir,
            output_root=output_root,
            include_hash_analysis=True,
            include_protection=True,
            enable_tineye=False,
            processors=artwork_meta.processors,
            callback_url=artwork_meta.callback_url,
            callback_auth_token=artwork_meta.callback_auth_token,
            artist_name=artwork_meta.artist_name,
            artwork_title=artwork_meta.artwork_title,
            watermark_strategy=artwork_meta.watermark_strategy,
            watermark_strength=artwork_meta.watermark_strength,
            # Backend upload support
            backend_url=artwork_meta.backend_url,
            backend_auth_token=artwork_meta.backend_auth_token,
            artwork_description=artwork_meta.artwork_description,
            artwork_tags=artwork_meta.tags,
            artwork_creation_time=artwork_meta.artwork_creation_time,
        )

        state.jobs[job_id] = record
        await state.queue.put(job_id)

        return ProcessArtworkResponse(
            job_id=job_id,
            status="processing",
            estimated_time_seconds=45,
            message="Job queued for processing. Callback will be sent upon completion.",
        )

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

    @app.get("/health")
    async def health_check(state: GatewayState = Depends(get_state)) -> JSONResponse:
        """
        Comprehensive health check endpoint.

        Returns status of:
        - Gateway service (API server)
        - Storage backend (similarity search service)
        - Backend upload service (artwork storage service)
        - Job queue status
        - Worker status
        """
        from .storage_client import get_storage_client

        # Gateway is healthy if we can respond
        gateway_status = "healthy"

        # Check storage backend (similarity search)
        storage_backend_status = "unknown"
        storage_backend_url = None
        try:
            storage_client = get_storage_client()
            storage_backend_url = storage_client.base_url
            is_healthy = await storage_client.health_check()
            storage_backend_status = "healthy" if is_healthy else "unhealthy"
        except Exception as e:
            storage_backend_status = f"error: {str(e)}"

        # Check backend upload service (artwork storage)
        backend_upload_status = "not_configured"
        backend_upload_url = None
        if state.config.backend_url:
            backend_upload_url = state.config.backend_url
            try:
                is_healthy = await state.backend_upload_client.health_check(state.config.backend_url)
                backend_upload_status = "healthy" if is_healthy else "unhealthy"
            except Exception as e:
                backend_upload_status = f"error: {str(e)}"

        # Job queue status
        queue_size = state.queue.qsize()
        total_jobs = len(state.jobs)
        running_jobs = sum(1 for job in state.jobs.values() if job.status == STATUS_RUNNING)
        queued_jobs = sum(1 for job in state.jobs.values() if job.status == STATUS_QUEUED)
        completed_jobs = sum(1 for job in state.jobs.values() if job.status == STATUS_DONE)
        failed_jobs = sum(1 for job in state.jobs.values() if job.status == STATUS_ERROR)

        # Worker status
        workers_count = len(state.workers)
        workers_alive = sum(1 for worker in state.workers if not worker.done())

        # Overall health status
        overall_status = "healthy"
        if storage_backend_status == "unhealthy" or backend_upload_status == "unhealthy":
            overall_status = "degraded"
        if gateway_status != "healthy":
            overall_status = "unhealthy"

        response = {
            "status": overall_status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "components": {
                "gateway": {
                    "status": gateway_status,
                    "version": "0.1.0",
                },
                "storage_backend": {
                    "status": storage_backend_status,
                    "url": storage_backend_url,
                    "description": "Similarity search and artwork database service",
                },
                "backend_upload": {
                    "status": backend_upload_status,
                    "url": backend_upload_url,
                    "description": "Artwork storage and management service",
                },
                "queue": {
                    "status": "healthy" if workers_alive > 0 else "unhealthy",
                    "size": queue_size,
                    "total_jobs": total_jobs,
                    "running": running_jobs,
                    "queued": queued_jobs,
                    "completed": completed_jobs,
                    "failed": failed_jobs,
                },
                "workers": {
                    "status": "healthy" if workers_alive > 0 else "unhealthy",
                    "total": workers_count,
                    "alive": workers_alive,
                    "configured_concurrency": state.config.worker_concurrency,
                },
            },
        }

        # Return 200 for healthy/degraded, 503 for unhealthy
        status_code = 200 if overall_status in ["healthy", "degraded"] else 503
        return JSONResponse(content=response, status_code=status_code)

    return app
