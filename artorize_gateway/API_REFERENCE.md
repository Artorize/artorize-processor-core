# Artorize Gateway API Reference

Complete API reference for all gateway endpoints.

**Base URL**: `http://localhost:8765` (default)

---

## Table of Contents

1. [Artwork Processing](#artwork-processing)
2. [Job Management](#job-management)
3. [SAC Encoding](#sac-encoding)
4. [Image Similarity](#image-similarity)
5. [Error Codes](#error-codes)

---

## Artwork Processing

### Process Artwork

Process an image with protection layers and optionally upload to backend.

**Endpoint**: `POST /v1/process/artwork`

**Content-Type**: `multipart/form-data`

**Request Parameters**:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | File | Yes | Image file (JPEG/PNG) |
| `metadata` | JSON | Yes | Processing metadata (see below) |

**Metadata Structure**:

```json
{
  "job_id": "string (required)",
  "callback_url": "string (required)",
  "callback_auth_token": "string (required)",
  "artist_name": "string (optional)",
  "artwork_title": "string (optional)",
  "processors": ["array of strings (optional)"],
  "watermark_strategy": "string (optional, default: invisible-watermark)",
  "watermark_strength": "float (optional, default: 0.5)",
  "tags": ["array of strings (optional)"],

  // Backend Upload Mode (NEW)
  "backend_url": "string (optional, e.g., https://backend.com)",
  "backend_auth_token": "string (optional)",
  "artwork_description": "string (optional)",
  "artwork_creation_time": "ISO 8601 timestamp (optional)"
}
```

**Example Request (Backend Upload Mode)**:

```bash
curl -X POST http://localhost:8765/v1/process/artwork \
  -F "file=@artwork.jpg" \
  -F 'metadata={
    "job_id": "f2dc197c-43b9-404d-b3f3-159282802609",
    "callback_url": "https://router.com/api/callbacks",
    "callback_auth_token": "Bearer router-secret",
    "backend_url": "https://backend.artorize.com",
    "backend_auth_token": "backend-api-key",
    "artist_name": "Leonardo da Vinci",
    "artwork_title": "Mona Lisa",
    "artwork_description": "Famous Renaissance portrait",
    "tags": ["renaissance", "portrait", "famous"],
    "artwork_creation_time": "2025-10-11T12:00:00Z"
  }'
```

**Example Request (Legacy Mode)**:

```bash
curl -X POST http://localhost:8765/v1/process/artwork \
  -F "file=@artwork.jpg" \
  -F 'metadata={
    "job_id": "f2dc197c-43b9-404d-b3f3-159282802609",
    "callback_url": "https://router.com/api/callbacks",
    "callback_auth_token": "Bearer router-secret",
    "artist_name": "Leonardo da Vinci",
    "artwork_title": "Mona Lisa"
  }'
```

**Response** (202 Accepted):

```json
{
  "job_id": "f2dc197c-43b9-404d-b3f3-159282802609",
  "status": "processing",
  "estimated_time_seconds": 45,
  "message": "Job queued for processing. Callback will be sent upon completion."
}
```

**Callback Payload (Backend Upload Mode)**:

```json
{
  "job_id": "f2dc197c-43b9-404d-b3f3-159282802609",
  "status": "completed",
  "backend_artwork_id": "60f7b3b3b3b3b3b3b3b3b3b3",
  "processing_time_ms": 64000
}
```

**Callback Payload (Legacy Mode)**:

```json
{
  "job_id": "f2dc197c-43b9-404d-b3f3-159282802609",
  "status": "completed",
  "processing_time_ms": 64000,
  "result": {
    "protected_image_url": "https://cdn.artorize.com/protected/uuid.jpg",
    "thumbnail_url": "https://cdn.artorize.com/thumbnails/uuid.jpg",
    "sac_mask_url": "https://cdn.artorize.com/masks/uuid.sac",
    "hashes": {
      "perceptual_hash": "0x123abc...",
      "average_hash": "0x456def...",
      "difference_hash": "0x789ghi...",
      "wavelet_hash": "0xabc123..."
    },
    "metadata": {
      "artist_name": "Leonardo da Vinci",
      "artwork_title": "Mona Lisa"
    },
    "watermark": {
      "strategy": "invisible-watermark",
      "strength": 0.5
    }
  }
}
```

**Callback Payload (Error)**:

```json
{
  "job_id": "f2dc197c-43b9-404d-b3f3-159282802609",
  "status": "failed",
  "processing_time_ms": 12000,
  "error": {
    "code": "BACKEND_UPLOAD_FAILED",
    "message": "Backend returned 500: Internal Server Error"
  }
}
```

---

## Job Management

### Submit Job (Legacy)

Submit an image for processing using legacy job API.

**Endpoint**: `POST /v1/jobs`

**Content-Type**: `multipart/form-data` or `application/json`

**Request (Multipart)**:

```bash
curl -X POST http://localhost:8765/v1/jobs \
  -F "file=@image.jpg" \
  -F "include_hash_analysis=true" \
  -F "include_protection=true" \
  -F "enable_tineye=false" \
  -F "processors=imagehash,blockhash"
```

**Request (JSON)**:

```bash
curl -X POST http://localhost:8765/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "image_url": "https://example.com/image.jpg",
    "include_hash_analysis": true,
    "include_protection": true,
    "enable_tineye": false,
    "processors": ["imagehash", "blockhash"]
  }'
```

**Response**:

```json
{
  "job_id": "abc123def456",
  "status": "queued"
}
```

---

### Get Job Status

Check the status of a processing job.

**Endpoint**: `GET /v1/jobs/{job_id}`

**Example**:

```bash
curl http://localhost:8765/v1/jobs/abc123def456
```

**Response**:

```json
{
  "job_id": "abc123def456",
  "status": "running",
  "submitted_at": "2025-10-11T12:00:00Z",
  "updated_at": "2025-10-11T12:01:00Z",
  "error": null
}
```

**Status Values**:
- `queued`: Job is waiting to be processed
- `running`: Job is currently being processed
- `done`: Job completed successfully
- `error`: Job failed with error

---

### Get Job Result

Retrieve the complete result of a finished job.

**Endpoint**: `GET /v1/jobs/{job_id}/result`

**Example**:

```bash
curl http://localhost:8765/v1/jobs/abc123def456/result
```

**Response**:

```json
{
  "job_id": "abc123def456",
  "summary": {
    "image": "/path/to/image.jpg",
    "analysis": "/path/to/analysis.json",
    "layers": [
      {
        "stage": "original",
        "path": "/path/to/layers/00-original/image.jpg"
      },
      {
        "stage": "nightshade",
        "path": "/path/to/layers/04-nightshade/image.jpg"
      }
    ],
    "projects": []
  },
  "analysis": {
    "results": [...]
  },
  "output_dir": "/path/to/outputs/abc123def456"
}
```

---

### Get Layer Image

Download a specific protection layer image.

**Endpoint**: `GET /v1/jobs/{job_id}/layers/{layer_name}`

**Example**:

```bash
curl http://localhost:8765/v1/jobs/abc123def456/layers/nightshade -o protected.jpg
```

**Layer Names**:
- `original`: Original unmodified image
- `fawkes`: After Fawkes protection
- `photoguard`: After PhotoGuard protection
- `mist`: After Mist protection
- `nightshade`: After Nightshade protection
- `invisible-watermark`: After invisible watermark

**Response**: Image file (JPEG/PNG)

---

### Delete Job

Clean up job files and remove from queue.

**Endpoint**: `DELETE /v1/jobs/{job_id}`

**Example**:

```bash
curl -X DELETE http://localhost:8765/v1/jobs/abc123def456
```

**Response**:

```json
{
  "job_id": "abc123def456",
  "status": "deleted"
}
```

---

## SAC Encoding

### Encode SAC from Images

Encode hi/lo mask images to SAC binary format.

**Endpoint**: `POST /v1/sac/encode`

**Content-Type**: `multipart/form-data`

**Request**:

```bash
curl -X POST http://localhost:8765/v1/sac/encode \
  -F "mask_hi=@mask_hi.png" \
  -F "mask_lo=@mask_lo.png" \
  --output output.sac
```

**Response**: SAC binary file

---

### Encode SAC from NPZ

Encode from NumPy compressed arrays.

**Endpoint**: `POST /v1/sac/encode/npz`

**Content-Type**: `multipart/form-data`

**Request**:

```bash
curl -X POST http://localhost:8765/v1/sac/encode/npz \
  -F "mask_npz=@mask_planes.npz" \
  --output output.sac
```

**Response**: SAC binary file

---

### Get SAC from Job

Generate SAC mask from a completed job.

**Endpoint**: `GET /v1/sac/encode/job/{job_id}`

**Example**:

```bash
curl http://localhost:8765/v1/sac/encode/job/abc123def456 --output mask.sac
```

**Response**: SAC binary file

---

### Batch SAC Encoding

Encode multiple jobs in parallel.

**Endpoint**: `POST /v1/sac/encode/batch`

**Content-Type**: `application/json`

**Request**:

```bash
curl -X POST http://localhost:8765/v1/sac/encode/batch \
  -H "Content-Type: application/json" \
  -d '{"job_ids": ["job1", "job2", "job3"]}'
```

**Response**:

```json
{
  "results": [
    {
      "job_id": "job1",
      "status": "success",
      "sac_data": "base64-encoded-sac-data"
    },
    {
      "job_id": "job2",
      "status": "success",
      "sac_data": "base64-encoded-sac-data"
    },
    {
      "job_id": "job3",
      "status": "error",
      "error": "Mask files not found"
    }
  ]
}
```

---

## Image Similarity

### Extract Image Hashes

Extract perceptual hashes from an image.

**Endpoint**: `POST /v1/images/extract-hashes`

**Content-Type**: `multipart/form-data`

**Request**:

```bash
curl -X POST http://localhost:8765/v1/images/extract-hashes \
  -F "file=@image.jpg"
```

**Response**:

```json
{
  "hashes": {
    "perceptual_hash": "8f8f8f8f8f8f8f8f",
    "average_hash": "ffc3c3c3c3c3c3c3",
    "difference_hash": "a1a1a1a1a1a1a1a1",
    "wavelet_hash": "b2b2b2b2b2b2b2b2"
  }
}
```

---

## Error Codes

### Callback Error Codes

| Code | Description | Action |
|------|-------------|--------|
| `PROCESSING_FAILED` | Image processing error | Check input image format/size |
| `BACKEND_UPLOAD_FAILED` | Backend upload error | Check backend URL and auth token |
| `STORAGE_UPLOAD_FAILED` | Storage upload error (legacy) | Check storage configuration |
| `UNKNOWN_ERROR` | Unexpected error | Contact support |

### HTTP Status Codes

| Status | Description |
|--------|-------------|
| `200 OK` | Request successful |
| `201 Created` | Resource created (backend response) |
| `202 Accepted` | Job queued for processing |
| `400 Bad Request` | Invalid request parameters |
| `401 Unauthorized` | Invalid authentication token |
| `404 Not Found` | Job or resource not found |
| `409 Conflict` | Job not yet complete |
| `429 Too Many Requests` | Rate limit exceeded |
| `500 Internal Server Error` | Server error |

---

## Configuration

### Environment Variables

```bash
# Gateway Settings
GATEWAY_BASE_DIR=gateway_jobs
GATEWAY_OUTPUT_DIR=outputs
GATEWAY_WORKER_CONCURRENCY=1
GATEWAY_REQUEST_TIMEOUT=30

# Callback Settings
CALLBACK_TIMEOUT=10
CALLBACK_RETRY_ATTEMPTS=3
CALLBACK_RETRY_DELAY=2

# Storage Settings (Legacy Mode)
STORAGE_TYPE=local  # local, s3, or cdn
S3_BUCKET_NAME=artorizer-protected-images
S3_REGION=us-east-1
CDN_BASE_URL=https://cdn.artorizer.com

# Backend Upload Settings (NEW)
BACKEND_URL=http://localhost:3002
BACKEND_TIMEOUT=30
BACKEND_AUTH_TOKEN=your-backend-token
BACKEND_UPLOAD_MAX_RETRIES=3
BACKEND_UPLOAD_RETRY_DELAY=2
```

---

## Rate Limits

- **Processing**: No hard limit (controlled by worker_concurrency)
- **Callbacks**: 3 retry attempts with exponential backoff
- **Backend Upload**: 3 retry attempts on timeout/network errors

---

## Interactive Documentation

- **Swagger UI**: `http://localhost:8765/docs`
- **ReDoc**: `http://localhost:8765/redoc`

---

## Related Documentation

- **[BACKEND_UPLOAD_GUIDE.md](./BACKEND_UPLOAD_GUIDE.md)** - Backend upload integration guide
- **[INTEGRATION_GUIDE.md](./INTEGRATION_GUIDE.md)** - Legacy CDN/storage integration
- **[SAC_API_GUIDE.md](./SAC_API_GUIDE.md)** - SAC encoding API reference
- **[README.md](./README.md)** - Gateway overview and setup

---

## Support

For issues or questions:
- GitHub Issues: https://github.com/Artorize/artorize-processor-core/issues
- Documentation: https://docs.artorize.com
