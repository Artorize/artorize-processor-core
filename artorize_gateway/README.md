# Artorize Gateway

FastAPI HTTP server that exposes the Artorize protection pipeline as a web service. Allows web UIs, router firmware, or automation scripts to submit images and retrieve protected results.

## Features

- **Async job queue** - Non-blocking image processing with status polling
- **Multiple input methods** - File uploads, URLs, or local file paths
- **Processor control** - Selectively enable/disable analysis and protection layers
- **Organized outputs** - Results stored under `outputs/<job-id>/` with consistent naming
- **Lightweight dependencies** - FastAPI, uvicorn, httpx, aiofiles

## Installation

```powershell
py -3 -m pip install fastapi uvicorn aiofiles httpx python-multipart
```

## Usage

### Start Server
```powershell
py -3 -m artorize_gateway --host 0.0.0.0 --port 8000
```

### Configuration
Set via environment variables or custom `GatewayConfig`:

- `base_dir` (default: `gateway_jobs/`) - Temporary upload storage
- `output_parent` (default: `outputs/`) - Final output directory
- `worker_concurrency` (default: `1`) - Background worker threads
- `request_timeout` (default: `30s`) - URL download timeout

### Custom Configuration
```python
from artorize_gateway import GatewayConfig, create_app

config = GatewayConfig(worker_concurrency=4)
app = create_app(config)
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/jobs` | Submit image (multipart or JSON) |
| `GET` | `/v1/jobs/{job_id}` | Check job status |
| `GET` | `/v1/jobs/{job_id}/result` | Get complete results |
| `GET` | `/v1/jobs/{job_id}/layers/{stage}` | Download layer image |
| `DELETE` | `/v1/jobs/{job_id}` | Clean up job files |

### Example Usage

```bash
# Submit image file
curl -F "file=@image.jpg" -F "include_protection=true" http://localhost:8000/v1/jobs

# Submit by URL
curl -X POST http://localhost:8000/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{"image_url": "https://example.com/image.jpg"}'

# Check status
curl http://localhost:8000/v1/jobs/{job_id}

# Download protected image
curl http://localhost:8000/v1/jobs/{job_id}/layers/nightshade -o protected.jpg
```

## API Documentation

When running, interactive documentation is available at:
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

For complete API reference, see `../documentation-processor.md`.

## Output Structure

```
outputs/<job-id>/
├── summary.json          # Processing manifest
├── analysis.json         # Hash analysis (optional)
├── layers/
│   ├── 00-original/      # Unmodified input
│   ├── 01-fawkes/        # Protection layers
│   ├── 02-photoguard/
│   ├── 03-mist/
│   ├── 04-nightshade/
│   └── 05-invisible-watermark/
└── c2pa/                 # C2PA manifest files
```

## Testing

```powershell
pytest -q artorize_gateway/tests
```

## Production Notes

- Set `TINEYE_API_KEY` environment variable for reverse image search
- Use reverse proxy (nginx/Caddy) for HTTPS and authentication
- Monitor disk usage in `outputs/` directory
- Scale `worker_concurrency` based on available CPU cores
