# Artscraper Gateway

`artscraper_gateway` exposes the Artscraper pipelines over a lightweight FastAPI service. Any web UI, router firmware, or automation script can upload an image, let the existing processors run, and download the resulting JSON and layer images without touching Python internals.

## Features
- Async job queue backed by the same processors used by `artscraper_runner`.
- Accepts direct uploads, URLs, or local file references.
- Stores every run under `outputs/<job-id>/` with consistent naming.
- Optional hashing/stegano analysis and protection stages per request.
- Minimal dependencies (`fastapi`, `uvicorn`, `httpx`, `aiofiles`, `python-multipart`).

## Installation
From the repository root:
```
python -m pip install fastapi uvicorn aiofiles httpx python-multipart
```
You can manage these in a virtual environment if preferred.

## Running the Service
```
python -m artscraper_gateway --host 0.0.0.0 --port 8765
```
Environment / CLI configuration is derived from `GatewayConfig`:
- `base_dir` (default `gateway_jobs/`): where uploads are staged per job.
- `output_parent` (default `outputs/`): parent directory for job artefacts.
- `worker_concurrency` (default `1`): number of background workers.
- `request_timeout` (default `30` seconds): timeout for URL downloads.

You can create a custom launcher that tweaks these values:

```python
from artorize_gateway import GatewayConfig, create_app

config = GatewayConfig(worker_concurrency=2)
app = create_app(config)
```
Then point uvicorn/gunicorn at the `app` object.

## API Summary
| Method | Path | Notes |
| --- | --- | --- |
| POST | `/v1/jobs` | Multipart (`file`) or JSON (`image_url`/`local_path`). Optional fields: `processors`, `include_hash_analysis`, `include_protection`, `enable_tineye`. |
| GET | `/v1/jobs/{job_id}` | Returns job status (`queued`, `running`, `done`, `error`) and timestamps. |
| GET | `/v1/jobs/{job_id}/result` | Returns the aggregated summary, optional analysis payload, and the absolute output directory. |
| GET | `/v1/jobs/{job_id}/layers/{stage}` | Streams a processed image (`original`, `fawkes`, etc.). |
| DELETE | `/v1/jobs/{job_id}` | Removes intake/output directories after retrieval. |

A complete walkthrough with `curl` examples lives in [`ARTSCRAPER_WEB_INTEGRATION.md`](../ARTSCRAPER_WEB_INTEGRATION.md).

## Output Layout
Every successful job produces:
```
outputs/
  <job-id>/
    summary.json
    analysis.json         # present when include_hash_analysis=true
    layers/
      00-original/<image>
      01-fawkes/<image>
      02-photoguard/<image>
      03-mist/<image>
      04-nightshade/<image>
      05-invisible-watermark/<image>
```
Uploads are kept in `gateway_jobs/<job-id>/input/` until the job is deleted.

## Testing
```
pytest -q artscraper_gateway/tests
```
The tests submit the Mona Lisa sample from `input/`, verify job status transitions, ensure artefacts land under `outputs/`, and exercise the deletion endpoint.

## Integration Tips
- Set `TINEYE_API_KEY` before launch if you want TinEye lookups.
- Scale `worker_concurrency` cautiously; the heavy lifting happens in Pillow/NumPy and runs in threads via `asyncio.to_thread`.
- Pair the service with a reverse proxy if you need HTTPS or authentication.
- Monitor disk usage in `outputs/` and consider scheduling `DELETE` calls once clients collect their files.
