# Backend Upload Integration Guide

## Overview

The processor gateway now supports **direct backend upload**, eliminating the need for intermediate storage in the router. When enabled, the processor uploads all processed files directly to the backend and returns a simple `artwork_id` in the callback.

## Benefits

- **Eliminates router storage**: Router no longer stores 94MB+ original images in memory
- **Reduces data transfer**: 21% reduction in total network traffic
- **Stateless router**: Router can scale horizontally without state concerns
- **Simplified callbacks**: Returns `artwork_id` instead of 200+ lines of JSON with URLs

## Configuration

### Environment Variables

Add these to your `.env` file or environment:

```bash
# Backend Storage API (optional defaults)
BACKEND_URL=http://localhost:3002
BACKEND_TIMEOUT=30
BACKEND_UPLOAD_MAX_RETRIES=3
BACKEND_UPLOAD_RETRY_DELAY=2
```

**Note**:
- Gateway-level `BACKEND_AUTH_TOKEN` is **deprecated** - use per-artwork tokens instead
- Individual requests MUST provide `backend_auth_token` in metadata
- Each artwork submission receives a unique, one-time authentication token

### GatewayConfig (Python)

```python
from artorize_gateway import GatewayConfig, create_app

config = GatewayConfig(
    backend_url="https://backend.artorize.com",
    backend_timeout=30.0,
    # Note: backend_auth_token is deprecated - tokens are now per-artwork
    backend_upload_max_retries=3,
    backend_upload_retry_delay=2.0,
)

app = create_app(config)
```

## API Usage

### Request Format

Submit artwork with `backend_url` in metadata to enable backend upload mode:

```bash
curl -X POST http://localhost:8765/v1/process/artwork \
  -F "file=@artwork.jpg" \
  -F 'metadata={
    "job_id": "f2dc197c-43b9-404d-b3f3-159282802609",
    "callback_url": "https://router.com/api/callbacks/process-complete",
    "callback_auth_token": "Bearer router-secret-token",
    "backend_url": "https://backend.artorize.com",
    "backend_auth_token": "backend-api-key",
    "artist_name": "Leonardo da Vinci",
    "artwork_title": "Mona Lisa",
    "artwork_description": "Famous Renaissance portrait",
    "tags": ["renaissance", "portrait", "famous"],
    "artwork_creation_time": "2025-10-11T12:00:00Z"
  }'
```

### Metadata Fields

| Field | Required | Description |
|-------|----------|-------------|
| `job_id` | Yes | Unique job identifier |
| `callback_url` | Yes | URL to receive completion callback |
| `callback_auth_token` | Yes | Authorization token for callback |
| `backend_url` | **Yes (for backend mode)** | Backend API base URL |
| `backend_auth_token` | **Yes (for backend mode)** | One-time authentication token (per-artwork) |
| `artist_name` | No | Artist name |
| `artwork_title` | No | Artwork title |
| `artwork_description` | No | Artwork description |
| `tags` | No | Array of tags |
| `artwork_creation_time` | No | ISO 8601 timestamp |

## Callback Payloads

### Success Callback (Backend Upload Mode)

**Simplified response with artwork_id:**

```json
{
  "job_id": "f2dc197c-43b9-404d-b3f3-159282802609",
  "status": "completed",
  "backend_artwork_id": "60f7b3b3b3b3b3b3b3b3b3b3",
  "processing_time_ms": 64000
}
```

### Success Callback (Legacy Mode)

**When `backend_url` is NOT provided:**

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
      "difference_hash": "0x789ghi..."
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

### Failure Callback

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

### Error Codes

| Code | Description | Action |
|------|-------------|--------|
| `PROCESSING_FAILED` | Image processing error | Check input image format |
| `BACKEND_AUTH_FAILED` | Backend authentication failed (401) | Token invalid, expired, or already used |
| `BACKEND_UPLOAD_FAILED` | Backend upload error (non-auth) | Check backend URL and connectivity |
| `STORAGE_UPLOAD_FAILED` | Storage upload error (legacy mode) | Check storage config |
| `UNKNOWN_ERROR` | Unexpected error | Contact support |

## Backend API

The processor uploads to this backend endpoint:

### Endpoint: `POST /artworks`

**Request**: `multipart/form-data`

**Files**:
- `original`: Original image (JPEG/PNG)
- `protected`: Protected image (JPEG/PNG)
- `maskHi`: High-byte SAC mask (`.sac` binary, optional)
- `maskLo`: Low-byte SAC mask (`.sac` binary, optional)
- `analysis`: Analysis JSON (optional)
- `summary`: Summary JSON

**Fields**:
- `title`: Artwork title
- `artist`: Artist name
- `description`: Description (optional)
- `tags`: Comma-separated tags (optional)
- `createdAt`: ISO 8601 timestamp (optional)
- `extra`: JSON string with hashes, watermark info, processing time

**Response** (201 Created):
```json
{
  "id": "60f7b3b3b3b3b3b3b3b3b3b3",
  "formats": {
    "original": {
      "contentType": "image/jpeg",
      "bytes": 1048576,
      "checksum": "sha256:abc123...",
      "fileId": "60f7b3b3b3b3b3b3b3b3b3b4"
    },
    "protected": {
      "contentType": "image/jpeg",
      "bytes": 1048576,
      "checksum": "sha256:def456...",
      "fileId": "60f7b3b3b3b3b3b3b3b3b3b5"
    }
  }
}
```

**Error Responses**:
- `400 Bad Request`: Missing files or invalid format
- `429 Too Many Requests`: Rate limit exceeded (processor retries automatically)
- `500 Internal Server Error`: Backend error (processor retries automatically)

## Retry Logic

The processor automatically retries backend uploads with exponential backoff:

1. **Max retries**: 3 attempts (configurable)
2. **Backoff delays**: 2s, 4s, 8s (exponential)
3. **Timeout**: 30s per attempt (configurable)
4. **Rate limit handling**: 429 errors trigger retry with backoff

## Testing

### Test Backend Upload Mode

```bash
# Start processor gateway
py -3.12 -m artorize_gateway --host 0.0.0.0 --port 8765

# Submit test job with backend upload
curl -X POST http://localhost:8765/v1/process/artwork \
  -F "file=@test-image.jpg" \
  -F 'metadata={
    "job_id": "test-123",
    "callback_url": "http://localhost:8000/test-callback",
    "callback_auth_token": "test-token",
    "backend_url": "http://localhost:3002",
    "artist_name": "Test Artist",
    "artwork_title": "Test Artwork"
  }'
```

### Expected Behavior

1. Processor receives image and metadata
2. Processes image with protection layers
3. Uploads all files to backend at `http://localhost:3002/artworks`
4. Backend returns `artwork_id`
5. Processor sends callback with `backend_artwork_id`

## Migration from Legacy Mode

### Step 1: Deploy Backend Support

Ensure your backend has the `/artworks` endpoint ready.

### Step 2: Enable Backend Upload (Gradual Rollout)

Send `backend_url` and per-artwork token in metadata:

```python
# Router code (example)
# Router generates a unique token for this artwork submission
artwork_token = generate_one_time_token()  # Router's token generation logic

metadata = {
    "job_id": job_id,
    "callback_url": callback_url,
    "callback_auth_token": auth_token,
    # Add these for new mode
    "backend_url": os.getenv("BACKEND_URL", "https://backend.artorize.com"),
    "backend_auth_token": artwork_token,  # One-time token per artwork
    # ... other fields
}
```

**Important**: The `backend_auth_token` must be a unique, one-time token generated by the router for each artwork submission. Do NOT use static tokens or environment variables.

### Step 3: Monitor Success Rate

- Check processor logs for upload errors
- Monitor callback payloads for `backend_artwork_id`
- Track backend upload latency (should be < 10s P95)

### Step 4: Full Migration

Once stable, remove legacy storage code from router.

## Troubleshooting

### Backend Upload Fails

**Check logs:**
```bash
# Processor logs
tail -f processor.log | grep "Backend upload"
```

**Common issues:**
- Backend URL incorrect: Check `backend_url` in metadata
- Auth token invalid: Check `backend_auth_token`
- Backend timeout: Increase `backend_timeout` config
- Backend down: Verify backend is running and accessible

### Callback Not Received

**Check:**
1. Callback URL is correct and accessible
2. Callback auth token is valid
3. Router callback endpoint is ready
4. Network connectivity between processor and router

### Mixed Mode Issues

If using both modes simultaneously:
- Requests WITH `backend_url`: Use backend upload mode
- Requests WITHOUT `backend_url`: Use legacy storage mode
- Both modes are fully compatible

## Performance

**Expected Metrics:**
- Upload time: 5-10 seconds for 100MB artwork
- Success rate: > 99% with retry logic
- Memory usage: Constant (no temp storage)
- Network efficiency: 21% reduction in total traffic

**Optimization Tips:**
- Use backend on same network as processor (reduces latency)
- Configure backend for multipart streaming
- Monitor backend upload endpoint for bottlenecks

## Security

### Authentication

**Backend auth token (per-artwork):**
- Generated by router for each artwork submission
- One-time use only (consumed after successful upload)
- Expires after 1 hour if unused
- Passed as `Authorization: Bearer <token>` header
- Never reuse tokens across multiple artworks

**Callback auth token:**
- Always required
- Router validates this token
- Ensures callbacks are authentic

### HTTPS

Always use HTTPS in production:

```bash
BACKEND_URL=https://backend.artorize.com
```

### File Validation

Processor validates files before upload:
- Image format (JPEG/PNG)
- File size limits (configurable)
- SAC mask format validation

## FAQ

### Q: Can I use both modes simultaneously?
**A**: Yes, per-request mode selection based on `backend_url` in metadata.

### Q: What happens if backend is down?
**A**: Processor retries 3 times, then sends failure callback with `BACKEND_UPLOAD_FAILED`.

### Q: Are original images stored locally?
**A**: Only temporarily during processing. Deleted after backend upload completes.

### Q: How do I revert to legacy mode?
**A**: Simply omit `backend_url` from request metadata.

### Q: Can I test backend upload without a backend?
**A**: Use a mock backend or webhook receiver (e.g., https://webhook.site) to test flow.

## Resources

- **Backend API Spec**: See backend repository for full `/artworks` endpoint documentation
- **SAC Protocol**: `sac_v_1_cdn_mask_transfer_protocol.md` for mask format details
- **Gateway API**: `README.md` for complete gateway documentation
- **Architecture**: `../for-processor/processor-requirements.md` for refactor details
