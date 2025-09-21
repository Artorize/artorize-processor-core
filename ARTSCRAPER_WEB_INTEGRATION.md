# Artscraper Web/Router Integration Guide

This document explains how the new `artscraper_gateway` service lets web or router frontends drive the Artscraper pipeline with a single HTTP call. It reflects the current implementation and is intended to be copy-pastable for operators.

## Goals
- Keep UI/firmware changes tiny: submit an image, poll for completion, fetch results.
- Reuse the existing `artscraper_runner` processors and protection stages without re-implementing them.
- Stay lightweight (FastAPI + asyncio) so routers and small servers can host the service.
- Store every job under `outputs/<job-id>/` for easy inspection and cleanup.

## Service Overview
```
[Browser/Router UI]
      |
      |  POST image or JSON payload
      v
[artscraper_gateway (FastAPI)]
      |
      |  enqueue job in asyncio.Queue
      v
[Worker thread] --calls--> artscraper_runner (hashes, protections)
      |
      |  writes outputs/<job-id>/layers/... + summary.json
      v
[Result registry] --served via--> GET /v1/jobs/* endpoints
```

- **App lifecycle**: Managed with FastAPI's lifespan hooks. Worker tasks start on boot and shut down gracefully on exit.
- **Persistence**: Each job uses two directories:
  - Intake: `<base_dir>/<job-id>/input/` for the uploaded file (configurable via `GatewayConfig.base_dir`).
  - Outputs: `outputs/<job-id>/` for the final `summary.json`, optional `analysis.json`, and the `layers/` images.
- **State**: In-memory registry keyed by `job_id` (UUID) tracks status, timestamps, and job result metadata.

## Installation
From the repo root:
```
python -m pip install fastapi uvicorn aiofiles httpx python-multipart
```
(Packages live in the system/site environment; create a virtualenv if preferred.)

## Running the Gateway
```
python -m artscraper_gateway --host 0.0.0.0 --port 8765
```
Defaults:
- Base job working dir: `gateway_jobs/`
- Output root: `outputs/`
- Worker concurrency: `1`
- Request timeout for remote downloads: `30s`

Override these via environment variables or by instantiating `GatewayConfig` and passing it to `create_app()` in your own launcher.

## REST API
| Method & Path | Description |
| --- | --- |
| `POST /v1/jobs` | Submit work. Accepts either multipart form data (`file`) or JSON payload. Optional fields: `processors`, `include_hash_analysis`, `include_protection`, `enable_tineye`. |
| `GET /v1/jobs/{job_id}` | Poll status. Returns `queued`, `running`, `done`, or `error`. Includes timestamps and error message if any. |
| `GET /v1/jobs/{job_id}/result` | On success, returns aggregated `summary` (layers + projects) plus `analysis` (hash/stegano data) and the absolute `output_dir`. |
| `GET /v1/jobs/{job_id}/layers/{stage}` | Streams the specific processed image (e.g., `original`, `fawkes`, `mist`). |
| `DELETE /v1/jobs/{job_id}` | Removes intake/output folders once the client finishes downloading artefacts. |

### Request Examples
**Multipart upload (skip protection)**
```
curl -F "file=@path/to/image.jpg" \
     -F "include_protection=false" \
     -F "include_hash_analysis=false" \
     http://localhost:8765/v1/jobs
```

**JSON by URL (full pipeline)**
```
curl -X POST http://localhost:8765/v1/jobs \
     -H "Content-Type: application/json" \
     -d '{
           "image_url": "https://example.com/sample.jpg",
           "include_protection": true,
           "include_hash_analysis": true,
           "processors": ["metadata", "imagehash"],
           "enable_tineye": false
         }'
```

### Responses
- Submission returns `{ "job_id": "...", "status": "queued" }`.
- Polling returns:
```
{
  "job_id": "...",
  "status": "done",
  "submitted_at": "2025-09-17T19:45:12.927428+00:00",
  "updated_at": "2025-09-17T19:45:32.107214+00:00",
  "error": null
}
```
- Result payload (shortened):
```
{
  "job_id": "...",
  "output_dir": "C:/repo/outputs/ab12cd34",
  "summary": {
    "image": "C:/repo/gateway_jobs/ab12cd34/input/ab12cd34.jpg",
    "layers": [
      {"stage": "original", "path": ".../outputs/ab12cd34/layers/00-original/..."},
      {"stage": "fawkes", "path": ".../layers/01-fawkes/..."}
    ],
    "projects": [...]
  },
  "analysis": {
    "processors": [
      {"name": "metadata", "ok": true, ...},
      {"name": "imagehash", "ok": true, ...}
    ]
  }
}
```
If analysis was disabled, `analysis` is `null`.

## Directory Layout
```
outputs/
  <job-id>/
    summary.json
    analysis.json        # present when hashing/stegano step runs
    layers/
      00-original/<image>
      01-fawkes/<image>
      ...
```
`gateway_jobs/<job-id>/input/<job-id>.<ext>` keeps the original upload for traceability until you `DELETE` the job.

## Testing
The automated pytest suite (`pytest -q artscraper_gateway/tests`) uploads both the provided Mona Lisa sample and a synthetic PNG, exercising:
- Lifecycle (submission -> polling -> result fetch)
- Output placement within `outputs/`
- Layer streaming endpoints
- Cleanup endpoint

## Operational Tips
- TinEye searches require `TINEYE_API_KEY` in the environment; set that before launching if needed.
- Adjust `worker_concurrency` when serving multiple simultaneous uploads.
- Jobs are currently held in memory; schedule periodic `DELETE` calls or add a cron to prune finished directories.
- For HTTPS termination, run the app behind a lightweight proxy (nginx, Caddy) and keep uvicorn bound to localhost.

This guide should give router/web teams all the context needed to integrate with the Artscraper gateway.
