# Artorize Processor Core - API Documentation

## API Base URL
`http://localhost:8000`

## API Endpoints

### 1. Submit Job (File Upload)
```http
POST /v1/jobs
Content-Type: multipart/form-data
```

**Request Parameters:**
- `file` (binary, required): Image file to process
- `include_hash_analysis` (string, optional): Enable analysis processors ("true"/"false", default: "true")
- `include_protection` (string, optional): Enable protection layers ("true"/"false", default: "true")
- `enable_tineye` (string, optional): Enable TinEye analysis ("true"/"false", default: "false")
- `processors` (string, optional): Comma-separated list of specific processors to run

**Response Body:**
```json
{
  "job_id": "abc123def456",
  "status": "queued"
}
```

### 1b. Submit Job (JSON Payload)
```http
POST /v1/jobs
Content-Type: application/json
```

**Request Body:**
```json
{
  "image_url": "https://example.com/image.jpg",
  "local_path": "/path/to/image.jpg",
  "processors": ["imagehash", "stegano"],
  "include_hash_analysis": true,
  "include_protection": true,
  "enable_tineye": false
}
```

**Response Body:**
```json
{
  "job_id": "abc123def456",
  "status": "queued"
}
```

---

### 2. Get Job Status
```http
GET /v1/jobs/{job_id}
```

**Path Parameters:**
- `job_id` (string, required): Job ID

**Response Body (200):**
```json
{
  "job_id": "abc123def456",
  "status": "queued|running|done|error",
  "submitted_at": "2024-01-01T12:00:00Z",
  "updated_at": "2024-01-01T12:03:00Z",
  "error": null
}
```

**Response Body (404):**
```json
{
  "detail": "job not found"
}
```

---

### 3. Get Job Result
```http
GET /v1/jobs/{job_id}/result
```

**Path Parameters:**
- `job_id` (string, required): Job ID

**Response Body (200):**
```json
{
  "job_id": "abc123def456",
  "summary": {
    "image": "/path/to/input/image.jpg",
    "analysis": "/path/to/analysis.json",
    "layers": [
      {
        "stage": "original",
        "description": "Unmodified input image",
        "path": "/path/to/layers/00-original/image.jpg",
        "processing_size": [1920, 1080],
        "mask_path": null
      },
      {
        "stage": "fawkes",
        "description": "Gaussian cloak perturbation",
        "path": "/path/to/layers/01-fawkes/image.jpg",
        "processing_size": [512, 288],
        "mask_path": "/path/to/layers/01-fawkes/image_fawkes_mask.png"
      }
    ],
    "projects": [
      {
        "name": "Fawkes",
        "notes": "Applied synthetic cloaking perturbation.",
        "applied": true,
        "layer_path": "/path/to/layers/01-fawkes/image.jpg"
      }
    ]
  },
  "analysis": {
    "processors": [
      {
        "name": "imagehash",
        "ok": true,
        "results": {
          "average_hash": "0x1234567890abcdef",
          "perceptual_hash": "0xfedcba0987654321"
        }
      }
    ]
  },
  "output_dir": "/path/to/output/directory"
}
```

### 4. Download Layer Image
```http
GET /v1/jobs/{job_id}/layers/{layer}
```

**Path Parameters:**
- `job_id` (string, required): Job ID
- `layer` (string, required): Layer name (`original`, `fawkes`, `photoguard`, `mist`, `nightshade`, `invisible-watermark`, `tree-ring`, `stegano-embed`, `c2pa-manifest`)

**Response Body (200):**
```
Content-Type: image/jpeg|image/png
[Binary image data]
```

**Response Body (404):**
```json
{
  "detail": "layer not found"
}
```

**Response Body (409):**
```json
{
  "detail": "job not complete"
}
```

---

### 5. Delete Job
```http
DELETE /v1/jobs/{job_id}
```

**Path Parameters:**
- `job_id` (string, required): Job ID

**Response Body (200):**
```json
{
  "job_id": "abc123def456",
  "status": "deleted"
}
```

**Response Body (404):**
```json
{
  "detail": "job not found"
}
```

---

## Processor Control

The API provides granular control over which processors run:

### Analysis Processor Control
- `include_hash_analysis`: Enables/disables all analysis processors (imagehash, stegano detection, etc.)
- `processors`: Comma-separated list to run only specific analysis processors (e.g., "imagehash,stegano")
- `enable_tineye`: Enables TinEye reverse image search (requires API key)

### Protection Layer Control
- `include_protection`: Enables/disables all protection layers
- Individual protection layers can be controlled via configuration files (see Configuration section)

### Available Analysis Processors

The following processor names can be used in the `processors` parameter:

- **`metadata`** - EXIF/image metadata extraction (format, size, mode, EXIF data)
- **`imagehash`** - Perceptual hashing (pHash, aHash, dHash, wHash, colorhash)
- **`dhash`** - Alternative dHash implementation with row/column variants
- **`blockhash`** - Block-based hashing (8-bit and 16-bit variants)
- **`stegano`** - LSB steganography detection and message extraction
- **`tineye`** - Reverse image search (requires `TINEYE_API_KEY` environment variable)

**Example processor filtering:**
```bash
# Run only metadata and perceptual hashing
curl -F "file=@image.jpg" -F "processors=metadata,imagehash" http://localhost:8000/v1/jobs

# Run all hash-related processors
curl -F "file=@image.jpg" -F "processors=imagehash,dhash,blockhash" http://localhost:8000/v1/jobs
```

### Available Protection Layers
- `fawkes`: Gaussian noise cloaking
- `photoguard`: Blur + edge blending
- `mist`: Color/contrast enhancement
- `nightshade`: Pixel shifting + noise
- `invisible-watermark`: LSB text watermark
- `tree-ring`: Radial watermark pattern
- `stegano-embed`: Steganographic message embedding
- `c2pa-manifest`: C2PA provenance manifest

---

## Configuration Files

Protection layers can be configured via JSON/TOML files or environment variables:

### JSON Configuration Example
```json
{
  "workflow": {
    "enable_fawkes": true,
    "enable_photoguard": true,
    "enable_mist": true,
    "enable_nightshade": true,
    "watermark_strategy": "invisible-watermark",
    "watermark_text": "artscraper",
    "tree_ring_frequency": 9.0,
    "tree_ring_amplitude": 18.0,
    "enable_stegano_embed": false,
    "stegano_message": "Protected by artscraper",
    "enable_c2pa_manifest": true
  },
  "input_dir": "input",
  "output_root": "outputs",
  "include_hash_analysis": true,
  "include_tineye": false,
  "max_stage_dim": 512
}
```

### Environment Variables
```bash
ARTORIZE_RUNNER_WORKFLOW__ENABLE_FAWKES=true
ARTORIZE_RUNNER_WORKFLOW__ENABLE_PHOTOGUARD=false
ARTORIZE_RUNNER_WORKFLOW__WATERMARK_STRATEGY=tree-ring
ARTORIZE_RUNNER_INCLUDE_HASH_ANALYSIS=true
```

### Configuration Loading
Set `ARTORIZE_RUNNER_CONFIG=/path/to/config.json` or pass config path to load functions.

---

## Error Response Format

Error responses include a `detail` field with the error message:
```json
{
  "detail": "job not found"
}
```

---

## FastAPI Documentation

When running the server, interactive API documentation is available at:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`