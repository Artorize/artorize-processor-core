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

### Job Processing

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/jobs` | Submit image (multipart or JSON) |
| `GET` | `/v1/jobs/{job_id}` | Check job status |
| `GET` | `/v1/jobs/{job_id}/result` | Get complete results |
| `GET` | `/v1/jobs/{job_id}/layers/{stage}` | Download layer image |
| `DELETE` | `/v1/jobs/{job_id}` | Clean up job files |

### SAC Encoding (Mask Transmission)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/sac/encode` | Encode hi/lo mask images to SAC binary |
| `POST` | `/v1/sac/encode/npz` | Encode from NPZ arrays to SAC binary |
| `GET` | `/v1/sac/encode/job/{job_id}` | Generate SAC from job masks |
| `POST` | `/v1/sac/encode/batch` | Parallel batch SAC encoding |

**SAC Encoding Features:**
- **Fast**: 2-10ms per mask pair, CPU-parallelized batches
- **Compact**: 30-1000% smaller than JSON/Base64
- **CDN-optimized**: Immutable caching headers, Brotli-friendly
- **Full precision**: Lossless int16 encoding

See `SAC_API_GUIDE.md` for detailed usage and `sac_v_1_cdn_mask_transfer_protocol.md` for format specification.

### Example Usage

**Process Artwork with Callback (Recommended):**
```bash
curl -X POST http://localhost:8765/v1/process/artwork \
  -F "file=@artwork.jpg" \
  -F 'metadata={
    "job_id": "unique-123",
    "callback_url": "https://your-site.com/api/callbacks",
    "callback_auth_token": "secret",
    "artist_name": "Artist Name",
    "artwork_title": "Artwork Title"
  }'
```

**Process Artwork with Backend Upload (NEW):**
```bash
curl -X POST http://localhost:8765/v1/process/artwork \
  -F "file=@artwork.jpg" \
  -F 'metadata={
    "job_id": "unique-123",
    "callback_url": "https://router.com/api/callbacks",
    "callback_auth_token": "router-secret",
    "backend_url": "https://backend.com",
    "backend_auth_token": "backend-secret",
    "artist_name": "Artist Name",
    "artwork_title": "Artwork Title",
    "artwork_description": "Description of the artwork",
    "tags": ["abstract", "modern"],
    "artwork_creation_time": "2025-10-11T12:00:00Z"
  }'
```

**Backend Upload Mode:**
- When `backend_url` is provided, the processor uploads directly to backend storage
- Callback payload includes `backend_artwork_id` instead of URLs
- Supports optional fields: `backend_auth_token`, `artwork_description`, `tags`, `artwork_creation_time`
- Backward compatible: omit `backend_url` to use legacy storage mode

**Legacy Job Submission:**
```bash
# Submit image file
curl -F "file=@image.jpg" -F "include_protection=true" http://localhost:8765/v1/jobs

# Submit by URL
curl -X POST http://localhost:8765/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{"image_url": "https://example.com/image.jpg"}'

# Check status
curl http://localhost:8765/v1/jobs/{job_id}

# Download protected image
curl http://localhost:8765/v1/jobs/{job_id}/layers/nightshade -o protected.jpg
```

**SAC Mask Encoding:**
```bash
# Encode from job
curl http://localhost:8765/v1/sac/encode/job/{job_id} --output mask.sac

# Batch encode multiple jobs
curl -X POST http://localhost:8765/v1/sac/encode/batch \
  -H "Content-Type: application/json" \
  -d '{"job_ids": ["job1", "job2"]}'
```

## API Documentation

**Complete API Reference:**
- **[API_REFERENCE.md](./API_REFERENCE.md)** - Complete API endpoint documentation

**Integration Guides:**
- **[BACKEND_UPLOAD_GUIDE.md](./BACKEND_UPLOAD_GUIDE.md)** - Direct backend upload integration (NEW)
- **[INTEGRATION_GUIDE.md](./INTEGRATION_GUIDE.md)** - Complete workflow for receiving SAC-encoded masks
- **[SAC_API_GUIDE.md](./SAC_API_GUIDE.md)** - SAC encoding endpoint reference
- **[sac_v_1_cdn_mask_transfer_protocol.md](../sac_v_1_cdn_mask_transfer_protocol.md)** - Binary format specification

**Interactive API Docs:**
- **Swagger UI**: `http://localhost:8765/docs`
- **ReDoc**: `http://localhost:8765/redoc`

For complete processor reference, see `../documentation-processor.md`.

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
│   ├── 05-invisible-watermark/
│   └── XX-final-comparison/  # Final comparison (MANDATORY)
│       ├── *_mask_hi.png
│       ├── *_mask_lo.png
│       ├── *_mask_hi.sac
│       ├── *_mask_lo.sac
│       └── *_mask.sac    # Primary final comparison SAC
├── poison_mask/          # Poison mask files (if enabled)
│   ├── *_mask_hi.png     # High-byte mask planes
│   ├── *_mask_lo.png     # Low-byte mask planes
│   ├── *_mask_planes.npz # Compressed NumPy arrays
│   ├── *_mask.sac        # SAC-encoded binary (CDN-ready)
│   └── *_poison_metadata.json
└── c2pa/                 # C2PA manifest files
```

**Key Files:**
- `XX-final-comparison/*_mask.sac` - **MANDATORY final comparison SAC mask** (always generated)
  - Compares final protected image to original for complete provenance tracking
  - Cannot be disabled via configuration
- `*_mask.sac` - SAC-encoded per-stage masks (optional, controlled by `enable_poison_mask`)
- `*_mask_hi.png`, `*_mask_lo.png` - Dual-plane poison masks
- `*_mask_planes.npz` - Efficient compressed storage

## Testing

```powershell
pytest -q artorize_gateway/tests
```

## Production Notes

- Set `TINEYE_API_KEY` environment variable for reverse image search
- Use reverse proxy (nginx/Caddy) for HTTPS and authentication
- Monitor disk usage in `outputs/` directory
- Scale `worker_concurrency` based on available CPU cores
