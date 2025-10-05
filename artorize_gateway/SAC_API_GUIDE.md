# SAC Encoding API Guide

Fast, efficient binary encoding of poison mask tuples for CDN delivery using the SAC v1 protocol.

## Overview

The SAC (Simple Array Container) encoding endpoints provide high-performance encoding of dual-mask protection data into a compact binary format optimized for CDN distribution. The SAC format reduces bandwidth by 30-1000% compared to JSON/Base64 approaches while maintaining full fidelity.

## Key Features

- **Fast encoding**: 2-10ms per mask pair
- **Parallel batch processing**: CPU-parallelized encoding for multiple jobs
- **CDN-optimized**: Immutable caching headers, minimal overhead
- **Multiple input methods**: Images, NPZ arrays, or job IDs
- **Zero data loss**: Full int16 precision preservation

## Endpoints

### 1. Single Mask Encoding (Images)

**POST** `/v1/sac/encode`

Encode a hi/lo mask pair from uploaded images.

**Request**: `multipart/form-data`
- `mask_hi`: High-byte mask image (PNG/JPEG)
- `mask_lo`: Low-byte mask image (PNG/JPEG)

**Response**: Binary SAC data (`application/octet-stream`)

**Headers**:
- `Cache-Control: public, max-age=31536000, immutable`
- `X-SAC-Width`: Image width
- `X-SAC-Height`: Image height
- `X-SAC-Length-A`: Array A element count
- `X-SAC-Length-B`: Array B element count

**Performance**: ~5-10ms for 512x512 masks

**cURL Example**:
```bash
curl -X POST http://localhost:8765/v1/sac/encode \
  -F "mask_hi=@mask_hi.png" \
  -F "mask_lo=@mask_lo.png" \
  --output output.sac
```

**Python Example**:
```python
import httpx

files = {
    'mask_hi': open('mask_hi.png', 'rb'),
    'mask_lo': open('mask_lo.png', 'rb'),
}

response = httpx.post('http://localhost:8765/v1/sac/encode', files=files)
with open('output.sac', 'wb') as f:
    f.write(response.content)

print(f"Width: {response.headers['X-SAC-Width']}")
print(f"Height: {response.headers['X-SAC-Height']}")
```

---

### 2. NPZ Array Encoding

**POST** `/v1/sac/encode/npz`

Encode from pre-computed NumPy arrays (faster for programmatic use).

**Request**: `multipart/form-data`
- `npz_file`: NPZ file containing `'hi'` and `'lo'` uint8 arrays

**Response**: Binary SAC data

**Performance**: ~2-5ms for 512x512 masks

**Python Example**:
```python
import numpy as np
import httpx

# Create NPZ from arrays
hi_arr = np.random.randint(0, 256, (512, 512, 4), dtype=np.uint8)
lo_arr = np.random.randint(0, 256, (512, 512, 4), dtype=np.uint8)
np.savez_compressed('mask.npz', hi=hi_arr, lo=lo_arr)

# Encode
files = {'npz_file': open('mask.npz', 'rb')}
response = httpx.post('http://localhost:8765/v1/sac/encode/npz', files=files)

with open('output.sac', 'wb') as f:
    f.write(response.content)
```

---

### 3. Job-Based Encoding

**GET** `/v1/sac/encode/job/{job_id}`

Encode mask from a completed processing job.

**Path Parameters**:
- `job_id`: Job UUID

**Query Parameters**:
- `output_parent`: Base output directory (default: `outputs/`)

**Response**: Binary SAC data with `Content-Disposition` header

**Example**:
```bash
curl http://localhost:8765/v1/sac/encode/job/abc123 --output abc123.sac
```

**Use Case**: On-demand SAC generation for individual completed jobs

---

### 4. Batch Parallel Encoding

**POST** `/v1/sac/encode/batch`

Encode multiple jobs in parallel with maximum throughput.

**Request Body** (JSON):
```json
{
  "job_ids": ["job1", "job2", "job3", ...],
  "output_dir": "outputs"  // optional
}
```

**Response** (JSON):
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
    ...
  }
}
```

**Performance**:
- 1 job: ~5ms
- 10 jobs: ~50ms (parallel)
- 100 jobs: ~500ms (parallel)

**Python Example**:
```python
import httpx

payload = {
    "job_ids": ["job1", "job2", "job3"],
}

response = httpx.post(
    'http://localhost:8765/v1/sac/encode/batch',
    json=payload,
)

result = response.json()
print(f"Encoded {result['encoded_count']} masks")
print(f"Total bytes: {result['total_bytes']:,}")
```

**Use Case**: Bulk processing after protection pipeline runs

---

## SAC Binary Format

### File Structure (24-byte header + payload)

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

**Endianness**: Little-endian throughout

### Browser Parsing Example

```javascript
async function fetchSAC(url) {
  const resp = await fetch(url);
  const buffer = await resp.arrayBuffer();
  const dv = new DataView(buffer);

  // Parse header
  const magic = String.fromCharCode(
    dv.getUint8(0), dv.getUint8(1),
    dv.getUint8(2), dv.getUint8(3)
  );
  if (magic !== 'SAC1') throw new Error('Invalid SAC file');

  const lengthA = dv.getUint32(8, true);
  const lengthB = dv.getUint32(12, true);
  const width = dv.getUint32(16, true);
  const height = dv.getUint32(20, true);

  // Extract arrays
  const a = new Int16Array(buffer, 24, lengthA);
  const b = new Int16Array(buffer, 24 + lengthA * 2, lengthB);

  return { a, b, width, height };
}
```

---

## Integration Workflow

### 1. Protection Pipeline → SAC Generation

```python
# After running protection pipeline
import httpx

# Batch encode all completed jobs
job_ids = ["job1", "job2", "job3"]
response = httpx.post(
    'http://localhost:8765/v1/sac/encode/batch',
    json={"job_ids": job_ids}
)

# Upload .sac files to CDN
results = response.json()
for job_id, info in results['results'].items():
    sac_path = info['sac_path']
    # upload_to_cdn(sac_path, f'{job_id}.sac')
```

### 2. CDN Upload Pattern

```python
import boto3

s3 = boto3.client('s3')

def upload_sac_to_cdn(sac_path: str, key: str, bucket: str):
    """Upload SAC to S3/CloudFront with immutable caching."""
    with open(sac_path, 'rb') as f:
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=f,
            ContentType='application/octet-stream',
            CacheControl='public, max-age=31536000, immutable',
        )
```

### 3. Frontend Retrieval

```javascript
// Fetch image and its SAC mask
const imageUrl = 'https://cdn.example.com/i/12345.jpg';
const sacUrl = imageUrl + '.sac';

const { a, b, width, height } = await fetchSAC(sacUrl);

// Use a/b arrays to reconstruct original or apply effects
```

---

## Performance Characteristics

### Single Encoding
- **Input**: 512x512 RGBA mask pair
- **Processing time**: 5-10ms
- **Output size**: ~2MB (uncompressed)
- **With CDN Brotli**: ~200KB-1MB (depending on mask complexity)

### Batch Encoding (10 jobs)
- **Sequential**: ~100ms
- **Parallel (4 cores)**: ~30-50ms
- **Speedup**: 2-3x

### Scalability
- **CPU-bound**: Scales linearly with cores
- **Memory**: ~10MB per concurrent encoding
- **Recommended**: 4-8 workers for optimal throughput

---

## Error Handling

### Common Errors

**400 Bad Request**:
- Invalid image dimensions (hi/lo mismatch)
- Missing 'hi'/'lo' keys in NPZ
- Corrupted image data

**404 Not Found**:
- Job ID doesn't exist
- Mask files missing from job output

**500 Internal Server Error**:
- Encoding failure (check array bounds)
- Disk I/O errors

### Error Response Format

```json
{
  "detail": "Encoding failed: Array shape mismatch: hi=(512, 512, 4), lo=(256, 256, 4)"
}
```

---

## Testing

See `tests/test_sac_encoding.py` for comprehensive test suite.

**Run tests**:
```bash
$env:PYTHONPATH='.'
pytest tests/test_sac_encoding.py -v
Remove-Item Env:PYTHONPATH
```

---

## Best Practices

1. **Use batch endpoint** for multiple jobs (parallelized)
2. **Upload .sac to CDN** with immutable caching headers
3. **Co-locate .sac with images** (e.g., `image.jpg` → `image.jpg.sac`)
4. **Enable CDN compression** (Brotli/Gzip) for 50-80% size reduction
5. **Validate SAC magic** on client before parsing

---

## URL Convention

For an image at:
```
https://cdn.example.com/i/12345.jpg
```

Serve its SAC mask at:
```
https://cdn.example.com/i/12345.jpg.sac
```

This allows simple concatenation: `imageUrl + '.sac'`

---

## References

- **SAC v1 Specification**: `sac_v_1_cdn_mask_transfer_protocol.md`
- **Poison Mask Processor**: `processors/poison_mask/processor.py`
- **Gateway Source**: `artorize_gateway/sac_encoder.py`, `artorize_gateway/sac_routes.py`
