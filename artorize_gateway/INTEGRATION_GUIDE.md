# Artorize Gateway Integration Guide

Complete guide for integrating with the Artorize protection pipeline and receiving SAC-encoded masks.

## Overview

When you submit an image for protection, the gateway:
1. Applies multiple protection layers (Fawkes, PhotoGuard, Mist, Nightshade, watermarks)
2. Generates poison masks (hi/lo planes) for each layer
3. **Automatically encodes masks to SAC binary format**
4. **NEW**: Uploads directly to backend (backend mode) OR uploads to CDN/storage (legacy mode)
5. Sends callback with backend artwork_id (backend mode) OR URLs (legacy mode)

## Integration Modes

The gateway supports **two integration modes**:

### Mode 1: Backend Upload (Recommended for New Integrations)
- Processor uploads directly to your backend storage
- Callback returns simple `backend_artwork_id`
- Eliminates router temporary storage
- Stateless router operation
- **See: [BACKEND_UPLOAD_GUIDE.md](./BACKEND_UPLOAD_GUIDE.md) for complete documentation**

### Mode 2: CDN/Storage Upload (Legacy Mode)
- Processor uploads to CDN/S3/local storage
- Callback returns URLs for protected image and SAC mask
- Router manages temporary storage
- **This guide documents Mode 2 (legacy workflow)**

## Workflow

### 1. Submit Image for Processing

**POST** `/v1/process/artwork`

```bash
curl -X POST http://localhost:8765/v1/process/artwork \
  -F "file=@artwork.jpg" \
  -F 'metadata={
    "job_id": "unique-job-123",
    "artist_name": "Artist Name",
    "artwork_title": "Artwork Title",
    "callback_url": "https://your-site.com/api/callbacks/artorize",
    "callback_auth_token": "your-secret-token",
    "watermark_strategy": "invisible-watermark",
    "watermark_strength": 0.5
  }'
```

**Response** (202 Accepted):
```json
{
  "job_id": "unique-job-123",
  "status": "processing",
  "estimated_time_seconds": 45,
  "message": "Job queued for processing. Callback will be sent upon completion."
}
```

---

### 2. Receive Callback (Automatic)

Your callback endpoint receives a POST request when processing completes.

**Callback Payload Structure:**

```json
{
  "job_id": "unique-job-123",
  "status": "completed",
  "processing_time_ms": 38420,
  "result": {
    "protected_image_url": "https://cdn.example.com/protected/unique-job-123.jpeg",
    "thumbnail_url": "https://cdn.example.com/thumbnails/unique-job-123_thumb.jpeg",
    "sac_mask_url": "https://cdn.example.com/protected/unique-job-123.jpeg.sac",
    "hashes": {
      "average_hash": "ffc3c3c3c3c3c3c3",
      "perceptual_hash": "8f8f8f8f8f8f8f8f",
      "difference_hash": "a1a1a1a1a1a1a1a1",
      "wavelet_hash": "b2b2b2b2b2b2b2b2"
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

**Key Fields:**
- `protected_image_url`: Final protected image (CDN-hosted, immutable cache)
- `sac_mask_url`: **SAC-encoded mask binary** (append `.sac` to image URL)
- `thumbnail_url`: 300x300 thumbnail for previews
- `hashes`: Perceptual hashes for similarity search

---

### 3. Store and Serve to Frontend

**Backend (Store URLs):**

```python
@app.post("/api/callbacks/artorize")
async def handle_artorize_callback(payload: dict, authorization: str):
    # Validate auth token
    if authorization != f"Bearer {settings.ARTORIZE_SECRET}":
        raise HTTPException(401)

    job_id = payload["job_id"]
    result = payload["result"]

    # Save to database
    await db.artworks.update_one(
        {"job_id": job_id},
        {
            "$set": {
                "protected_image_url": result["protected_image_url"],
                "thumbnail_url": result["thumbnail_url"],
                "sac_mask_url": result["sac_mask_url"],
                "hashes": result["hashes"],
                "processing_status": "completed",
                "completed_at": datetime.utcnow(),
            }
        }
    )

    return {"status": "received"}
```

**Frontend API Response:**

```json
{
  "artwork_id": "12345",
  "image_url": "https://cdn.example.com/protected/unique-job-123.jpeg",
  "thumbnail_url": "https://cdn.example.com/thumbnails/unique-job-123_thumb.jpeg",
  "mask_url": "https://cdn.example.com/protected/unique-job-123.jpeg.sac",
  "artist_name": "Artist Name",
  "title": "Artwork Title"
}
```

---

### 4. Browser: Fetch and Parse SAC Mask

The frontend can fetch the SAC mask to reconstruct the original image or apply visual effects.

**JavaScript Example:**

```javascript
// Fetch SAC mask
async function fetchSACMask(sacUrl) {
  const response = await fetch(sacUrl, { mode: 'cors' });
  if (!response.ok) throw new Error(`SAC fetch failed: ${response.status}`);

  const buffer = await response.arrayBuffer();
  return parseSAC(buffer);
}

// Parse SAC binary format
function parseSAC(buffer) {
  const dv = new DataView(buffer);

  // Validate magic
  const magic = String.fromCharCode(
    dv.getUint8(0), dv.getUint8(1),
    dv.getUint8(2), dv.getUint8(3)
  );
  if (magic !== 'SAC1') throw new Error('Invalid SAC file');

  // Parse header
  const lengthA = dv.getUint32(8, true);
  const lengthB = dv.getUint32(12, true);
  const width = dv.getUint32(16, true);
  const height = dv.getUint32(20, true);

  // Extract int16 arrays
  const a = new Int16Array(buffer, 24, lengthA);
  const b = new Int16Array(buffer, 24 + lengthA * 2, lengthB);

  return { a, b, width, height };
}

// Apply mask to reconstruct original
async function reconstructOriginal(protectedImgEl, sacUrl) {
  const { a, b, width, height } = await fetchSACMask(sacUrl);

  // Create canvas for reconstruction
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d');

  // Draw protected image
  const protectedBitmap = await createImageBitmap(
    await fetch(protectedImgEl.src).then(r => r.blob())
  );
  ctx.drawImage(protectedBitmap, 0, 0, width, height);

  // Apply mask to reconstruct
  const imageData = ctx.getImageData(0, 0, width, height);
  const pixels = imageData.data;

  for (let i = 0; i < a.length; i++) {
    const pixelIdx = i * 4;
    // Apply differential mask (simplified - actual implementation depends on encoding)
    pixels[pixelIdx + 0] = Math.max(0, Math.min(255, pixels[pixelIdx + 0] + a[i]));
    pixels[pixelIdx + 1] = Math.max(0, Math.min(255, pixels[pixelIdx + 1] + b[i]));
    // ... apply to remaining channels
  }

  ctx.putImageData(imageData, 0, 0);
  return canvas;
}
```

**React Component Example:**

```jsx
function ProtectedArtwork({ artwork }) {
  const [showOriginal, setShowOriginal] = useState(false);
  const canvasRef = useRef(null);

  useEffect(() => {
    if (showOriginal && artwork.mask_url) {
      const img = document.createElement('img');
      img.src = artwork.image_url;
      img.onload = async () => {
        const canvas = await reconstructOriginal(img, artwork.mask_url);
        canvasRef.current?.replaceWith(canvas);
      };
    }
  }, [showOriginal, artwork]);

  return (
    <div>
      <img src={artwork.image_url} alt={artwork.title} />
      <button onClick={() => setShowOriginal(!showOriginal)}>
        {showOriginal ? 'Show Protected' : 'Show Original'}
      </button>
      <canvas ref={canvasRef} style={{ display: showOriginal ? 'block' : 'none' }} />
    </div>
  );
}
```

---

## URL Convention

For consistency, SAC masks follow this convention:

```
Image URL:    https://cdn.example.com/i/12345.jpg
SAC Mask URL: https://cdn.example.com/i/12345.jpg.sac
```

Simply append `.sac` to the image URL.

---

## Error Handling

**Callback Error Payload:**

```json
{
  "job_id": "unique-job-123",
  "status": "failed",
  "processing_time_ms": 5200,
  "error": {
    "code": "PROCESSING_FAILED",
    "message": "Image processing error: invalid format"
  }
}
```

**Error Codes:**
- `PROCESSING_FAILED`: Protection pipeline error
- `STORAGE_UPLOAD_FAILED`: CDN/S3 upload error (legacy mode)
- `BACKEND_UPLOAD_FAILED`: Backend upload error (backend mode)
- `UNKNOWN_ERROR`: Unexpected failure

---

## Performance Characteristics

| Stage | Time |
|-------|------|
| Protection pipeline | 20-40s |
| SAC encoding | 2-10ms |
| CDN upload | 100-500ms |
| **Total** | **~25-45s** |

**SAC File Sizes:**
- Raw SAC: ~2MB (512×512 RGBA)
- With Brotli: ~200KB-1MB (50-80% compression)

---

## Security Considerations

1. **Validate callback auth token**: Always check `Authorization` header
2. **Verify job ownership**: Ensure job_id matches your submitted job
3. **HTTPS only**: Never accept callbacks over HTTP
4. **Rate limiting**: Prevent callback spam
5. **SAC integrity**: Optionally compute SHA-256 of SAC for verification

**Example Auth Header:**
```
Authorization: Bearer your-secret-token
```

---

## Testing

### Local Testing

```bash
# Start gateway
py -3.12 -m artorize_gateway --host localhost --port 8765

# Submit test job
curl -X POST http://localhost:8765/v1/process/artwork \
  -F "file=@test.jpg" \
  -F 'metadata={"job_id":"test123","callback_url":"http://localhost:3000/test","callback_auth_token":"test-token"}'

# Check job status
curl http://localhost:8765/v1/jobs/test123

# Manually fetch SAC mask
curl http://localhost:8765/v1/sac/encode/job/test123 --output test.sac
```

---

## Advanced: Direct SAC Encoding

If you want to encode SAC masks separately (not through the pipeline):

**From Images:**
```bash
curl -X POST http://localhost:8765/v1/sac/encode \
  -F "mask_hi=@mask_hi.png" \
  -F "mask_lo=@mask_lo.png" \
  --output output.sac
```

**From Job:**
```bash
curl http://localhost:8765/v1/sac/encode/job/{job_id} --output {job_id}.sac
```

**Batch Encoding:**
```bash
curl -X POST http://localhost:8765/v1/sac/encode/batch \
  -H "Content-Type: application/json" \
  -d '{"job_ids": ["job1", "job2", "job3"]}'
```

---

## Summary

### Legacy Mode (This Guide)

1. **Submit** artwork via `/v1/process/artwork` (without `backend_url`)
2. **Receive** callback with `protected_image_url` and `sac_mask_url`
3. **Store** URLs in your database
4. **Serve** to frontend via your API
5. **Fetch** SAC mask in browser for interactivity

### Backend Upload Mode (Recommended)

1. **Submit** artwork via `/v1/process/artwork` (with `backend_url`)
2. **Receive** callback with `backend_artwork_id`
3. **Fetch** artwork from backend using artwork_id
4. **Serve** to frontend via your API
5. **Fetch** SAC mask from backend for interactivity

SAC masks are **automatically generated** during processing—no extra steps needed!

## Related Documentation

**Integration Modes:**
- **[BACKEND_UPLOAD_GUIDE.md](./BACKEND_UPLOAD_GUIDE.md)** - Backend upload mode (recommended for new integrations)
- This guide - Legacy CDN/storage mode

**Technical References:**
- **[SAC_API_GUIDE.md](./SAC_API_GUIDE.md)** - SAC encoding API reference
- **[sac_v_1_cdn_mask_transfer_protocol.md](../sac_v_1_cdn_mask_transfer_protocol.md)** - SAC binary format spec
- **[README.md](./README.md)** - Gateway API documentation

**Migration:**
- New integrations should use backend upload mode
- Existing integrations can migrate gradually
- Both modes are fully supported and backward compatible
