# Processor Core API Design - Double Transfer Optimization

## Problem Statement
Currently, images are transferred twice:
1. Router → Processor (image upload for processing)
2. Processor → Router (processed image return)

This doubles network bandwidth, increases latency, and creates unnecessary I/O overhead.

## Solution Architecture
Implement an **async callback pattern**:
1. Router uploads image to Processor once
2. Processor processes asynchronously
3. Processor sends callback to Router with **metadata only** (no image)
4. Router stores result metadata in MongoDB

**Image storage**: Processor saves processed images to shared storage (S3/CDN), returns URLs only.

---

## API Specification

### 1. Processor Core: Image Upload & Processing Endpoint

**Endpoint**: `POST /v1/process/artwork`

**Purpose**: Accept image, metadata, and callback URL for async processing

**Request (Multipart Form-Data)**:
```http
POST /v1/process/artwork HTTP/1.1
Host: processor.artorizer.local:8000
Content-Type: multipart/form-data; boundary=----WebKitFormBoundary

------WebKitFormBoundary
Content-Disposition: form-data; name="image"; filename="artwork.jpg"
Content-Type: image/jpeg

[binary image data]
------WebKitFormBoundary
Content-Disposition: form-data; name="metadata"
Content-Type: application/json

{
  "job_id": "uuid-generated-by-router",
  "artist_name": "Artist Name",
  "artwork_title": "Artwork Title",
  "callback_url": "http://router.artorizer.local:3000/api/callbacks/process-complete",
  "callback_auth_token": "Bearer secret-token-for-callback",
  "processors": ["metadata", "imagehash", "stegano"],
  "watermark_strategy": "invisible-watermark",
  "watermark_strength": 0.5,
  "tags": ["digital-art", "portrait"]
}
------WebKitFormBoundary--
```

**Request (JSON Alternative)**:
```http
POST /v1/process/artwork HTTP/1.1
Content-Type: application/json

{
  "job_id": "uuid-generated-by-router",
  "image_url": "https://cdn.example.com/uploads/temp-image.jpg",
  "artist_name": "Artist Name",
  "artwork_title": "Artwork Title",
  "callback_url": "http://router.artorizer.local:3000/api/callbacks/process-complete",
  "callback_auth_token": "Bearer secret-token-for-callback",
  "processors": ["metadata", "imagehash", "stegano"],
  "watermark_strategy": "tree-ring",
  "watermark_strength": 0.7
}
```

**Response (202 Accepted)**:
```json
{
  "job_id": "uuid-generated-by-router",
  "status": "processing",
  "estimated_time_seconds": 45,
  "message": "Job queued for processing. Callback will be sent upon completion."
}
```

**Error Responses**:
- `400` - Invalid metadata, missing required fields, or unsupported image format
- `413` - Image file too large (exceeds MAX_FILE_SIZE)
- `503` - Processor queue full or service unavailable

---

### 2. Router: Process Completion Callback Endpoint

**Endpoint**: `POST /api/callbacks/process-complete`

**Purpose**: Receive processing results from Processor Core

**Security**: Validates `Authorization` header matches token sent in original request

**Request (from Processor)**:
```http
POST /api/callbacks/process-complete HTTP/1.1
Host: router.artorizer.local:3000
Content-Type: application/json
Authorization: Bearer secret-token-for-callback

{
  "job_id": "uuid-generated-by-router",
  "status": "completed",
  "processing_time_ms": 42350,
  "result": {
    "protected_image_url": "https://cdn.artorizer.com/protected/abc123.jpg",
    "thumbnail_url": "https://cdn.artorizer.com/thumbnails/abc123_thumb.jpg",
    "metadata": {
      "width": 1920,
      "height": 1080,
      "format": "JPEG",
      "color_profile": "sRGB",
      "dpi": 300
    },
    "hashes": {
      "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "perceptual_hash": "0xfedcba0987654321",
      "average_hash": "0x1234567890abcdef",
      "difference_hash": "0xabcdef1234567890",
      "blockhash8": "0xaabbccddee112233"
    },
    "watermark": {
      "strategy": "invisible-watermark",
      "strength": 0.5,
      "signature": "artorizer-v1-2024-signature-hash"
    },
    "processors_applied": [
      {
        "name": "metadata",
        "success": true,
        "duration_ms": 120
      },
      {
        "name": "imagehash",
        "success": true,
        "duration_ms": 350
      },
      {
        "name": "stegano",
        "success": true,
        "duration_ms": 41880
      }
    ]
  }
}
```

**Response (200 OK)**:
```json
{
  "status": "received",
  "job_id": "uuid-generated-by-router",
  "message": "Processing result stored successfully"
}
```

**Error Response (Callback Failed)**:
```json
{
  "job_id": "uuid-generated-by-router",
  "status": "failed",
  "processing_time_ms": 5200,
  "error": {
    "code": "WATERMARK_INJECTION_FAILED",
    "message": "Failed to inject invisible watermark: insufficient image entropy",
    "processor": "stegano",
    "details": {
      "attempted_strength": 0.5,
      "min_required_entropy": 6.2,
      "actual_entropy": 4.8
    }
  }
}
```

---

## Implementation Requirements

### Processor Core Changes

#### 1. New Configuration (`config.py`)
```python
# Callback settings
CALLBACK_TIMEOUT_MS = int(os.getenv('CALLBACK_TIMEOUT_MS', '10000'))
CALLBACK_RETRY_ATTEMPTS = int(os.getenv('CALLBACK_RETRY_ATTEMPTS', '3'))
CALLBACK_RETRY_DELAY_MS = int(os.getenv('CALLBACK_RETRY_DELAY_MS', '2000'))

# Storage settings
PROCESSED_IMAGE_STORAGE = os.getenv('PROCESSED_IMAGE_STORAGE', 's3')  # s3, local, cdn
S3_BUCKET_NAME = os.getenv('S3_BUCKET_NAME', 'artorizer-protected-images')
S3_REGION = os.getenv('S3_REGION', 'us-east-1')
CDN_BASE_URL = os.getenv('CDN_BASE_URL', 'https://cdn.artorizer.com')
```

#### 2. New Service: Callback Client (`src/services/callback_client.py`)
```python
import httpx
from typing import Dict, Any

class CallbackClient:
    """HTTP client for sending callbacks to Router"""

    async def send_completion_callback(
        self,
        callback_url: str,
        auth_token: str,
        payload: Dict[str, Any]
    ) -> bool:
        """
        Send processing completion callback with retry logic
        Returns True if callback successful, False otherwise
        """
        headers = {
            'Authorization': auth_token,
            'Content-Type': 'application/json'
        }

        for attempt in range(CALLBACK_RETRY_ATTEMPTS):
            try:
                response = await httpx.post(
                    callback_url,
                    json=payload,
                    headers=headers,
                    timeout=CALLBACK_TIMEOUT_MS / 1000
                )
                if response.status_code == 200:
                    return True

            except (httpx.TimeoutError, httpx.NetworkError) as e:
                if attempt == CALLBACK_RETRY_ATTEMPTS - 1:
                    # Log failure, store in DLQ (dead letter queue)
                    await self._store_failed_callback(payload)
                    return False
                await asyncio.sleep(CALLBACK_RETRY_DELAY_MS / 1000)

        return False
```

#### 3. New Service: Storage Uploader (`src/services/storage_uploader.py`)
```python
import boto3
from pathlib import Path

class StorageUploader:
    """Upload processed images to S3/CDN"""

    def __init__(self):
        self.s3_client = boto3.client('s3', region_name=S3_REGION)

    async def upload_protected_image(
        self,
        image_data: bytes,
        job_id: str,
        format: str = 'jpeg'
    ) -> Dict[str, str]:
        """
        Upload protected image and thumbnail to storage
        Returns URLs for full image and thumbnail
        """
        # Generate S3 keys
        full_key = f"protected/{job_id}.{format}"
        thumb_key = f"thumbnails/{job_id}_thumb.{format}"

        # Upload full image
        self.s3_client.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=full_key,
            Body=image_data,
            ContentType=f'image/{format}',
            CacheControl='public, max-age=31536000'
        )

        # Generate and upload thumbnail
        thumbnail_data = await self._generate_thumbnail(image_data)
        self.s3_client.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=thumb_key,
            Body=thumbnail_data,
            ContentType=f'image/{format}',
            CacheControl='public, max-age=31536000'
        )

        return {
            'protected_image_url': f'{CDN_BASE_URL}/{full_key}',
            'thumbnail_url': f'{CDN_BASE_URL}/{thumb_key}'
        }
```

#### 4. Updated Processing Pipeline (`src/services/job_processor.py`)
```python
async def process_artwork_job(job_data: Dict[str, Any]):
    """
    Main processing pipeline (async, runs in background)
    """
    job_id = job_data['job_id']
    callback_url = job_data['callback_url']
    auth_token = job_data['callback_auth_token']

    try:
        # 1. Load image from temp storage
        image = await load_image(job_data['image_path'])

        # 2. Run processors
        results = await run_processors(image, job_data['processors'])

        # 3. Apply watermark
        protected_image = await apply_watermark(
            image,
            strategy=job_data['watermark_strategy'],
            strength=job_data['watermark_strength']
        )

        # 4. Upload to S3/CDN
        storage_urls = await storage_uploader.upload_protected_image(
            protected_image,
            job_id
        )

        # 5. Build callback payload
        callback_payload = {
            'job_id': job_id,
            'status': 'completed',
            'result': {
                'protected_image_url': storage_urls['protected_image_url'],
                'thumbnail_url': storage_urls['thumbnail_url'],
                'hashes': results['hashes'],
                'metadata': results['metadata'],
                'watermark': results['watermark']
            }
        }

        # 6. Send callback to Router
        await callback_client.send_completion_callback(
            callback_url,
            auth_token,
            callback_payload
        )

        # 7. Cleanup temp files
        await cleanup_temp_files(job_data['image_path'])

    except Exception as e:
        # Send failure callback
        error_payload = {
            'job_id': job_id,
            'status': 'failed',
            'error': {
                'code': type(e).__name__,
                'message': str(e)
            }
        }
        await callback_client.send_completion_callback(
            callback_url,
            auth_token,
            error_payload
        )
```

---

### Router Changes

#### 1. New Route: Callback Endpoint (`src/routes/callback.ts`)
```typescript
import { FastifyInstance } from 'fastify';
import { ProcessingResult } from '../types/schemas';
import { DuplicateService } from '../services/duplicate.service';

export async function callbackRoutes(fastify: FastifyInstance) {
  // POST /api/callbacks/process-complete
  fastify.post('/api/callbacks/process-complete', async (request, reply) => {
    // Validate auth token
    const authHeader = request.headers.authorization;
    if (!authHeader || authHeader !== `Bearer ${process.env.CALLBACK_AUTH_TOKEN}`) {
      return reply.code(401).send({ error: 'Unauthorized callback' });
    }

    const result: ProcessingResult = request.body;

    // Store result in MongoDB
    await DuplicateService.getInstance().storeProcessedArtwork({
      job_id: result.job_id,
      status: result.status,
      protected_image_url: result.result?.protected_image_url,
      thumbnail_url: result.result?.thumbnail_url,
      metadata: result.result?.metadata,
      hashes: result.result?.hashes,
      watermark: result.result?.watermark,
      processing_time_ms: result.processing_time_ms,
      completed_at: new Date()
    });

    return { status: 'received', job_id: result.job_id };
  });
}
```

#### 2. Updated Processor Service (`src/services/processor.service.ts`)
```typescript
export class ProcessorService {
  async submitJob(imageBuffer: Buffer, metadata: ProtectRequest): Promise<string> {
    const jobId = randomUUID();
    const form = new FormData();

    // Attach image
    form.append('image', new Blob([imageBuffer]), metadata.artwork_title);

    // Attach metadata with callback URL
    form.append('metadata', JSON.stringify({
      job_id: jobId,
      artist_name: metadata.artist_name,
      artwork_title: metadata.artwork_title,
      callback_url: `${process.env.ROUTER_BASE_URL}/api/callbacks/process-complete`,
      callback_auth_token: `Bearer ${process.env.CALLBACK_AUTH_TOKEN}`,
      processors: metadata.processors,
      watermark_strategy: metadata.watermark_strategy,
      watermark_strength: metadata.watermark_strength
    }));

    // Submit to processor (fire and forget)
    const response = await fetch(`${this.processorUrl}/v1/process/artwork`, {
      method: 'POST',
      body: form,
      signal: AbortSignal.timeout(this.timeout)
    });

    if (!response.ok) {
      throw new Error(`Processor submission failed: ${response.statusText}`);
    }

    return jobId;
  }
}
```

#### 3. New Environment Variables (`.env.example`)
```env
# Router callback configuration
ROUTER_BASE_URL=http://router.artorizer.local:3000
CALLBACK_AUTH_TOKEN=generate-secure-random-token-here

# Processor URL
PROCESSOR_URL=http://processor.artorizer.local:8000
PROCESSOR_TIMEOUT=30000
```

---

## Benefits of This Design

1. **50% reduction in network bandwidth**: Image transferred once (Router → Processor)
2. **Async processing**: Router returns `202 Accepted` immediately, doesn't block
3. **Scalability**: Processor can queue jobs, Router doesn't wait for completion
4. **CDN integration**: Processed images served from S3/CDN, not via Router/Processor
5. **Failure resilience**: Callback retry logic prevents lost results
6. **Secure**: Callback auth token prevents unauthorized result injection

---

## Migration Path

### Phase 1: Implement callback endpoint on Router
- Add `/api/callbacks/process-complete` route
- Add `CALLBACK_AUTH_TOKEN` to environment
- Update MongoDB schema for storing processing results

### Phase 2: Update Processor to use callbacks
- Implement `CallbackClient` service
- Integrate S3/CDN storage uploader
- Update job processing pipeline to send callbacks instead of returning results

### Phase 3: Switch Router to async submission
- Update `/protect` endpoint to return `202` with `job_id`
- Remove synchronous response waiting logic
- Add job status query endpoint (optional, for frontend polling)

### Phase 4: Cleanup
- Remove old synchronous endpoints
- Update documentation
- Monitor callback success rates

---

## Optional: Job Status Query

If frontend needs to poll job status before callback completion:

**Endpoint**: `GET /api/jobs/:job_id/status`

**Response**:
```json
{
  "job_id": "uuid",
  "status": "processing" | "completed" | "failed",
  "created_at": "2024-10-01T12:00:00Z",
  "completed_at": "2024-10-01T12:00:45Z",
  "result": { /* same as callback payload */ }
}
```

This allows frontend to show progress without waiting for callback.
