# Artorize Processor Core - API Documentation

## API Base URL
`http://localhost:8765`

**Note:** The default port is 8765 (configurable via `--port` flag when starting the gateway)

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

### 6. Process Artwork with Callback (Async)
```http
POST /v1/process/artwork
Content-Type: multipart/form-data
```

**Purpose:** Submit artwork for processing with async callback support. This endpoint eliminates double image transfer by uploading results to storage and sending a callback with URLs instead of returning the image data.

**Request Parameters:**
- `file` (binary, required): Image file to process
- `metadata` (string, required): JSON string containing job metadata and callback configuration

**Metadata JSON Schema:**
```json
{
  "job_id": "uuid-generated-by-client",
  "artist_name": "Artist Name",
  "artwork_title": "Artwork Title",
  "callback_url": "http://router.example.com/api/callbacks/process-complete",
  "callback_auth_token": "Bearer secret-token-for-callback",
  "processors": ["metadata", "imagehash", "stegano"],
  "watermark_strategy": "invisible-watermark",
  "watermark_strength": 0.5,
  "tags": ["digital-art", "portrait"]
}
```

**Metadata Fields:**
- `job_id` (string, required): Unique job identifier (UUID recommended)
- `artist_name` (string, optional): Artist name for metadata
- `artwork_title` (string, optional): Artwork title for metadata
- `callback_url` (string, required): URL to send completion callback to
- `callback_auth_token` (string, required): Authorization token for callback (e.g., "Bearer token")
- `processors` (array, optional): List of specific processors to run
- `watermark_strategy` (string, optional): Watermark strategy to use
- `watermark_strength` (float, optional): Watermark strength (0.0-1.0)
- `tags` (array, optional): Tags for the artwork

**Response Body (202 Accepted):**
```json
{
  "job_id": "uuid-generated-by-client",
  "status": "processing",
  "estimated_time_seconds": 45,
  "message": "Job queued for processing. Callback will be sent upon completion."
}
```

**Callback Payload (Success):**

When processing completes successfully, a POST request is sent to `callback_url` with the following payload:

```json
{
  "job_id": "uuid-generated-by-client",
  "status": "completed",
  "processing_time_ms": 42350,
  "result": {
    "protected_image_url": "http://localhost:8765/v1/storage/protected/uuid.jpeg",
    "thumbnail_url": "http://localhost:8765/v1/storage/thumbnails/uuid_thumb.jpeg",
    "sac_mask_url": "http://localhost:8765/v1/storage/protected/uuid.jpeg.sac",
    "hashes": {
      "perceptual_hash": "0xfedcba0987654321",
      "average_hash": "0x1234567890abcdef",
      "difference_hash": "0xabcdef1234567890"
    },
    "metadata": {
      "artist_name": "Artist Name",
      "artwork_title": "Artwork Title"
    },
    "watermark": {
      "strategy": "invisible-watermark",
      "strength": 0.5
    }
  }
}
```

**Callback Payload Fields:**
- `protected_image_url` (string): Final protected image URL (CDN/S3/local)
- `thumbnail_url` (string): 300x300 thumbnail URL
- `sac_mask_url` (string): **SAC-encoded poison mask URL** (NEW - CDN-ready binary format)
- `hashes` (object): Perceptual hashes for similarity search
- `metadata` (object): Artist/artwork information
- `watermark` (object): Watermark strategy and settings

**Callback Payload (Error):**

If processing fails, the callback payload will contain an error:

```json
{
  "job_id": "uuid-generated-by-client",
  "status": "failed",
  "processing_time_ms": 5200,
  "error": {
    "code": "PROCESSING_FAILED",
    "message": "Error details here"
  }
}
```

**Error Response Codes:**
- `400` - Invalid metadata, missing required fields, or unsupported image format
- `413` - Image file too large
- `503` - Processor queue full or service unavailable

**Storage Configuration:**

The endpoint supports multiple storage backends configured via `GatewayConfig`:

- **Local Storage (default)**: Images stored in `outputs/protected/` and `outputs/thumbnails/`
  - URLs: `http://localhost:8000/v1/storage/protected/{job_id}.jpeg`
- **S3 Storage**: Images uploaded to S3 bucket (requires `boto3` package)
  - Configure: `storage_type="s3"`, `s3_bucket_name`, `s3_region`
  - URLs: CDN or S3 direct URLs
- **CDN Storage**: Images uploaded to CDN
  - Configure: `cdn_base_url`

**Example Usage:**
```bash
# Create metadata JSON
METADATA='{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "artist_name": "Jane Doe",
  "artwork_title": "Digital Sunrise",
  "callback_url": "http://localhost:3000/api/callbacks/process-complete",
  "callback_auth_token": "Bearer my-secret-token",
  "watermark_strategy": "invisible-watermark",
  "watermark_strength": 0.7
}'

# Submit job
curl -X POST http://localhost:8000/v1/process/artwork \
  -F "file=@artwork.jpg" \
  -F "metadata=$METADATA"
```

**Callback Security:**

The callback is sent with the `Authorization` header containing the token provided in `callback_auth_token`. The receiving endpoint should validate this token before processing the callback.

**Retry Logic:**

The processor will retry failed callbacks up to 3 times (configurable) with a 2-second delay between attempts. Failed callbacks are logged for manual review.

---

### 7. Extract Image Hashes
```http
POST /v1/images/extract-hashes
Content-Type: multipart/form-data
```

**Purpose:** Extract perceptual hashes from an image for similarity analysis or storage.

**Request Parameters (Multipart):**
- `file` (binary, required): Image file to analyze
- `hash_types` (string, optional): Comma-separated hash types to compute (default: "all")
  - Supported: `phash`, `ahash`, `dhash`, `whash`, `colorhash`, `blockhash`, `blockhash8`, `blockhash16`, `all`

**Alternative JSON Request:**
```http
POST /v1/images/extract-hashes
Content-Type: application/json
```

```json
{
  "image_url": "https://example.com/image.jpg",
  "local_path": "/path/to/image.jpg",
  "hash_types": ["phash", "ahash", "dhash"]
}
```

**Response Body (200):**
```json
{
  "hashes": {
    "perceptual_hash": "0xccb4e7f2988b310e",
    "average_hash": "0xfff753db98003000",
    "difference_hash": "0x0da6b6b33107e141",
    "wavelet_hash": "0xfff7d3db99003000",
    "color_hash": "0x11640008000",
    "blockhash8": "0xaabbccddee112233",
    "blockhash16": "0x1234567890abcdef1234567890abcdef"
  },
  "metadata": {
    "width": 7479,
    "height": 11146,
    "format": "JPEG",
    "mode": "RGB"
  }
}
```

**Response Body (400):**
```json
{
  "detail": "Failed to open image file"
}
```

**Hash Type Descriptions:**
- `perceptual_hash` (phash): Most robust for similarity detection, resistant to scaling/compression
- `average_hash` (ahash): Fast, good for exact or near-duplicate detection
- `difference_hash` (dhash): Edge-based comparison, detects structural changes
- `wavelet_hash` (whash): Texture-based comparison using wavelet transform
- `color_hash`: Color distribution comparison, detects color palette changes
- `blockhash8`: Block-based hash with 8-bit precision (requires Python 3.12.x)
- `blockhash16`: Block-based hash with 16-bit precision (requires Python 3.12.x)

**Example Usage:**
```bash
# Extract all hashes from uploaded file
curl -F "file=@image.jpg" http://localhost:8000/v1/images/extract-hashes

# Extract only perceptual and average hashes
curl -F "file=@image.jpg" -F "hash_types=phash,ahash" http://localhost:8000/v1/images/extract-hashes

# Extract hashes from local file path (JSON)
curl -X POST http://localhost:8000/v1/images/extract-hashes \
  -H "Content-Type: application/json" \
  -d '{"local_path": "input/image.jpg"}'
```

---

### 8. Find Similar Images
```http
POST /v1/images/find-similar
Content-Type: multipart/form-data
```

**Purpose:** Find similar images in the system based on perceptual hash comparison.

**Request Parameters (Multipart):**
- `file` (binary, required): Query image file
- `threshold` (string, optional): Similarity threshold 0.0-1.0 (default: 0.85)
- `limit` (string, optional): Maximum number of results (default: 10, max: 100)
- `hash_types` (string, optional): Comma-separated hash types to use for comparison

**Alternative JSON Request:**
```http
POST /v1/images/find-similar
Content-Type: application/json
```

```json
{
  "image_url": "https://example.com/image.jpg",
  "local_path": "/path/to/image.jpg",
  "threshold": 0.85,
  "limit": 10,
  "hash_types": ["phash", "ahash", "dhash"]
}
```

**Response Body (200):**
```json
{
  "query_hashes": {
    "perceptual_hash": "0xccb4e7f2988b310e",
    "average_hash": "0xfff753db98003000",
    "difference_hash": "0x0da6b6b33107e141"
  },
  "similar_images": [
    {
      "artwork_id": "60f7b3b3b3b3b3b3b3b3b3b3",
      "title": "Similar Artwork 1",
      "artist": "Artist Name",
      "similarity_score": 0.95,
      "matching_hashes": {
        "perceptual_hash": 0.98,
        "average_hash": 0.92,
        "difference_hash": 0.94
      },
      "thumbnail_url": "/artworks/60f7b3b3b3b3b3b3b3b3b3b3?variant=protected",
      "uploaded_at": "2023-07-21T09:15:00Z"
    }
  ],
  "total_matches": 5,
  "search_time_ms": 142
}
```

**Response Body (400):**
```json
{
  "detail": "threshold must be between 0.0 and 1.0"
}
```

**Response Body (503):**
```json
{
  "detail": {
    "error": "Backend storage service not configured",
    "message": "Set STORAGE_BACKEND_URL environment variable...",
    "query_hashes": { "perceptual_hash": "0x..." },
    "similar_images": [],
    "total_matches": 0
  }
}
```

**Configuration:**

This endpoint requires an external backend storage service. Configure via environment variables:

```bash
STORAGE_BACKEND_URL=http://localhost:3000
STORAGE_BACKEND_TIMEOUT=30  # seconds
```

The backend service must implement the `/v1/similarity/search` endpoint accepting:
```json
{
  "hashes": { "perceptual_hash": "0x...", "average_hash": "0x..." },
  "threshold": 0.85,
  "limit": 10
}
```

**Example Usage:**
```bash
# Find similar images with default settings
curl -F "file=@query_image.jpg" http://localhost:8000/v1/images/find-similar

# Custom threshold and limit
curl -F "file=@query_image.jpg" \
  -F "threshold=0.9" \
  -F "limit=20" \
  http://localhost:8000/v1/images/find-similar

# JSON payload with local path
curl -X POST http://localhost:8000/v1/images/find-similar \
  -H "Content-Type: application/json" \
  -d '{"local_path": "input/image.jpg", "threshold": 0.9, "limit": 5}'
```

**Note:** If the backend storage service is not configured, the endpoint will return a 503 error with the computed hashes but no similarity results.

---

## SAC Encoding Endpoints (Mask Transmission)

SAC (Simple Array Container) is a compact binary format for transmitting poison mask data to CDN/browsers. These endpoints provide fast, efficient encoding of dual int16 arrays.

### 9. Encode Mask Pair (Images)
```http
POST /v1/sac/encode
Content-Type: multipart/form-data
```

**Purpose:** Encode hi/lo mask image pair into SAC v1 binary format.

**Request Parameters:**
- `mask_hi` (binary, required): High-byte mask image (PNG/JPEG)
- `mask_lo` (binary, required): Low-byte mask image (PNG/JPEG)

**Response (200):**
```
Content-Type: application/octet-stream
Cache-Control: public, max-age=31536000, immutable
X-SAC-Width: 512
X-SAC-Height: 512
X-SAC-Length-A: 262144
X-SAC-Length-B: 262144

[Binary SAC data]
```

**Performance:** ~5-10ms for 512×512 masks

**Example:**
```bash
curl -X POST http://localhost:8765/v1/sac/encode \
  -F "mask_hi=@mask_hi.png" \
  -F "mask_lo=@mask_lo.png" \
  --output output.sac
```

---

### 10. Encode Mask from NPZ
```http
POST /v1/sac/encode/npz
Content-Type: multipart/form-data
```

**Purpose:** Encode SAC from pre-computed NumPy arrays (faster for programmatic use).

**Request Parameters:**
- `npz_file` (binary, required): NPZ file containing 'hi' and 'lo' uint8 arrays

**Response (200):**
```
Content-Type: application/octet-stream
[Binary SAC data with same headers as /encode]
```

**Performance:** ~2-5ms for 512×512 masks

**Example:**
```bash
curl -X POST http://localhost:8765/v1/sac/encode/npz \
  -F "npz_file=@mask.npz" \
  --output output.sac
```

---

### 11. Encode SAC from Job
```http
GET /v1/sac/encode/job/{job_id}
```

**Purpose:** Generate SAC mask from a completed job's mask files.

**Path Parameters:**
- `job_id` (string, required): Job UUID

**Query Parameters:**
- `output_parent` (string, optional): Base output directory (default: "outputs/")

**Response (200):**
```
Content-Type: application/octet-stream
Content-Disposition: attachment; filename="{job_id}.sac"
Cache-Control: public, max-age=31536000, immutable
[Binary SAC data]
```

**Response (404):**
```json
{
  "detail": "Job not found" | "No mask files found for job"
}
```

**Example:**
```bash
curl http://localhost:8765/v1/sac/encode/job/abc123 --output abc123.sac
```

---

### 12. Batch SAC Encoding (Parallel)
```http
POST /v1/sac/encode/batch
Content-Type: application/json
```

**Purpose:** Encode multiple jobs in parallel with CPU parallelization.

**Request Body:**
```json
{
  "job_ids": ["job1", "job2", "job3"],
  "output_dir": "outputs"
}
```

**Response (200):**
```json
{
  "encoded_count": 3,
  "failed_count": 0,
  "total_bytes": 1572864,
  "results": {
    "job1": {
      "sac_path": "/path/to/job1.sac",
      "width": 512,
      "height": 512,
      "size_bytes": 524288
    },
    "job2": { ... },
    "job3": { ... }
  }
}
```

**Performance:**
- 1 job: ~5ms
- 10 jobs: ~50ms (parallelized)
- 100 jobs: ~500ms (parallelized)

**Example:**
```bash
curl -X POST http://localhost:8765/v1/sac/encode/batch \
  -H "Content-Type: application/json" \
  -d '{"job_ids": ["job1", "job2", "job3"]}'
```

---

### SAC Format Specification

**Binary Layout (24-byte header + payload):**
```
Offset  Size  Field           Type      Value
------  ----  --------------  --------  -----------
0       4     magic           char[4]   "SAC1"
4       1     flags           uint8     0
5       1     dtype_code      uint8     1 (int16)
6       1     arrays_count    uint8     2
7       1     reserved        uint8     0
8       4     length_a        uint32    N elements
12      4     length_b        uint32    N elements
16      4     width           uint32    Image width
20      4     height          uint32    Image height
24      2*N   payload_a       int16[]   Array A data
24+2N   2*N   payload_b       int16[]   Array B data
```

**Key Properties:**
- **Endianness:** Little-endian throughout
- **Size:** ~2MB uncompressed (512×512), ~200KB-1MB with CDN Brotli
- **MIME type:** `application/octet-stream`
- **Caching:** `public, max-age=31536000, immutable`

**Browser Parsing Example:**
```javascript
async function parseSAC(buffer) {
  const dv = new DataView(buffer);
  const magic = String.fromCharCode(
    dv.getUint8(0), dv.getUint8(1),
    dv.getUint8(2), dv.getUint8(3)
  );
  if (magic !== 'SAC1') throw new Error('Invalid SAC');

  const lengthA = dv.getUint32(8, true);
  const lengthB = dv.getUint32(12, true);
  const width = dv.getUint32(16, true);
  const height = dv.getUint32(20, true);

  const a = new Int16Array(buffer, 24, lengthA);
  const b = new Int16Array(buffer, 24 + lengthA * 2, lengthB);

  return { a, b, width, height };
}
```

**Documentation:**
- Full specification: `sac_v_1_cdn_mask_transfer_protocol.md`
- Integration guide: `artorize_gateway/INTEGRATION_GUIDE.md`
- API reference: `artorize_gateway/SAC_API_GUIDE.md`

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
- Swagger UI: `http://localhost:8765/docs`
- ReDoc: `http://localhost:8765/redoc`

## Additional Resources

- **Integration Guide:** `artorize_gateway/INTEGRATION_GUIDE.md` - Complete workflow for receiving SAC-encoded masks
- **SAC API Guide:** `artorize_gateway/SAC_API_GUIDE.md` - Detailed SAC endpoint documentation
- **SAC Protocol Spec:** `sac_v_1_cdn_mask_transfer_protocol.md` - Binary format specification
- **Gateway README:** `artorize_gateway/README.md` - Gateway overview and setup