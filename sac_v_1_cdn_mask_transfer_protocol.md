# SAC v1 — Simple Array Container for CDN Delivery

*A compact binary protocol for shipping two signed 16‑bit arrays from a Python backend to a webpage via your CDN.*

---

## Why this exists
When you compute per‑pixel data (e.g., masks, flow fields, depth slices) on the server in **signed int16**, you want to deliver it to the browser with **minimal overhead** and **great cacheability**. JSON and Base64 add 30–1000% bloat and burn CPU. SAC v1 is a tiny, fixed‑layout binary file designed for CDNs: immutable, compressible, and trivially parsed in JS.

**Key properties**
- **Tiny header** (24 bytes) + raw payload
- **Fixed little‑endian** for portability
- **Two arrays per file** (A and B), both `int16`
- **Optional image shape** in header to sanity‑check lengths
- CDN‑friendly: strong caching, content compression, byte-range support

---

## File & MIME
- **Extension**: `.sac` (e.g., `12345.jpg.sac`)
- **MIME type**: `application/octet-stream`
- **Content-Encoding**: allow CDN to apply Brotli/Gzip when beneficial (no custom compression inside the container)
- **Cache-Control**: `public, max-age=31536000, immutable`

> **URL convention**: for an image at `https://cdn.example.com/i/12345.jpg`, publish its arrays at `https://cdn.example.com/i/12345.jpg.sac`.

---

## Binary layout (SAC v1)
All integers are **little‑endian**. Offsets in bytes.

```
Offset  Size  Field                 Type         Notes
------  ----  --------------------  -----------  -----------------------------------------
0       4     magic                 char[4]      ASCII "SAC1"
4       1     flags                 uint8        bit0=0 (reserved), bit1=0 (reserved)
5       1     dtype_code            uint8        1 = int16 (required in v1)
6       1     arrays_count          uint8        must be 2 in v1
7       1     reserved              uint8        set to 0
8       4     length_a              uint32       number of elements in array A
12      4     length_b              uint32       number of elements in array B
16      4     width                 uint32       optional; set 0 if unknown
20      4     height                uint32       optional; set 0 if unknown
24      2*Na  payload_a             int16[Na]    Na = length_a
24+2Na  2*Nb  payload_b             int16[Nb]    Nb = length_b
```

**Validation rules**
- `magic == "SAC1"`, `dtype_code == 1`, `arrays_count == 2`.
- If `width*height != 0`, then `length_a == width*height` and `length_b == width*height`.

---

## Python: writing `.sac` files
Below is a self‑contained writer that takes two NumPy `int16` arrays and returns bytes ready to upload to your object store/CDN.

```python
import struct
import numpy as np

SAC_MAGIC = b"SAC1"
DTYPE_INT16 = 1

def to_c_contiguous_i16(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.int16)
    if not x.flags['C_CONTIGUOUS']:
        x = np.ascontiguousarray(x)
    return x

def build_sac(a: np.ndarray, b: np.ndarray, width: int = 0, height: int = 0) -> bytes:
    a = to_c_contiguous_i16(a)
    b = to_c_contiguous_i16(b)
    length_a = int(a.size)
    length_b = int(b.size)

    if width and height:
        assert length_a == width * height, "A length != width*height"
        assert length_b == width * height, "B length != width*height"

    header = struct.pack(
        '<4sBBBBIIII',
        SAC_MAGIC,      # 4s
        0,              # flags
        DTYPE_INT16,    # dtype_code
        2,              # arrays_count
        0,              # reserved
        length_a,       # uint32
        length_b,       # uint32
        width,          # uint32
        height          # uint32
    )
    return header + a.tobytes(order='C') + b.tobytes(order='C')
```

**Uploading** (example with boto3 → S3 → CloudFront/Cloudflare R2):
```python
import boto3

s3 = boto3.client('s3')

def upload_sac(bucket: str, key: str, sac_bytes: bytes):
    s3.put_object(
        Bucket=bucket,
        Key=key,  # e.g. 'i/12345.jpg.sac'
        Body=sac_bytes,
        ContentType='application/octet-stream',
        CacheControl='public, max-age=31536000, immutable'
    )
```

---

## Browser: fetching and parsing
**Fetch** the `.sac` alongside the image. HTTP/2/3 will multiplex both requests efficiently.

```js
async function fetchSAC(url) {
  const resp = await fetch(url, { mode: 'cors' });
  if (!resp.ok) throw new Error(`SAC fetch failed: ${resp.status}`);
  const buf = await resp.arrayBuffer();
  return parseSAC(buf);
}

function parseSAC(buffer) {
  const dv = new DataView(buffer);
  // Header
  const m0 = String.fromCharCode(dv.getUint8(0), dv.getUint8(1), dv.getUint8(2), dv.getUint8(3));
  if (m0 !== 'SAC1') throw new Error('Bad magic');
  const flags = dv.getUint8(4);
  const dtype = dv.getUint8(5);
  const arraysCount = dv.getUint8(6);
  if (dtype !== 1 || arraysCount !== 2) throw new Error('Unsupported SAC variant');
  const lengthA = dv.getUint32(8, true);
  const lengthB = dv.getUint32(12, true);
  const width   = dv.getUint32(16, true);
  const height  = dv.getUint32(20, true);

  const offA = 24;
  const offB = offA + lengthA * 2;
  if (offB + lengthB * 2 !== buffer.byteLength) throw new Error('Length mismatch');

  // Typed views: Browsers are little‑endian in practice.
  const a = new Int16Array(buffer, offA, lengthA);
  const b = new Int16Array(buffer, offB, lengthB);

  if (width && height && (lengthA !== width*height || lengthB !== width*height)) {
    throw new Error('Shape mismatch');
  }
  return { a, b, width, height, flags };
}
```

**Usage example** (draw a heatmap overlay on `<canvas>`):
```js
async function loadMaskAndOverlay(imgEl, sacUrl, canvas) {
  const { a, b, width, height } = await fetchSAC(sacUrl);
  const W = width  || imgEl.naturalWidth;
  const H = height || imgEl.naturalHeight;

  canvas.width = W; canvas.height = H;
  const ctx = canvas.getContext('2d');
  const imgData = ctx.createImageData(W, H);
  // Example visualization: magnitude of (a,b) scaled to alpha
  for (let i = 0; i < a.length; i++) {
    const ax = a[i];
    const by = b[i];
    const mag = Math.min(255, Math.hypot(ax, by)); // simple demo scaling
    const j = i * 4;
    imgData.data[j + 0] = 255;     // R
    imgData.data[j + 1] = 0;       // G
    imgData.data[j + 2] = 0;       // B
    imgData.data[j + 3] = mag;     // A
  }
  ctx.putImageData(imgData, 0, 0);
}
```

> For WebGL/WebGPU, upload `a` and `b` as textures or a single RG16I texture if supported; the binary layout already matches little‑endian `R16I`/`RG16I` expectations.

---

## End‑to‑end example
**Server**
```python
# Assume you computed int16 mask components ax, ay of shape (H, W)
sac = build_sac(ax.ravel(), ay.ravel(), width=W, height=H)
upload_sac('my-bucket', f'i/{image_id}.jpg.sac', sac)
```

**Client**
```js
const img = document.querySelector('#photo');
const canvas = document.querySelector('#overlay');
const sacUrl = img.src + '.sac';
loadMaskAndOverlay(img, sacUrl, canvas);
```

---

## CDN, caching, and integrity
- **Immutability**: include a content hash in the base image name or path (e.g., `/i/abc123...jpg`). The `.sac` should reuse that stem so both files share cache lifetimes.
- **ETag/Last‑Modified**: let the CDN origin set these; browsers will validate efficiently.
- **Compression**: Brotli often shrinks noisy `int16` payloads modestly; for sparse masks it can shrink dramatically. Enable CDN auto compression for `application/octet-stream`.
- **CORS**: if the mask lives on a different origin, add `Access-Control-Allow-Origin: *` (or your site origin) at the CDN edge.
- **SRI (optional)**: If you compute an out‑of‑band hash, you can keep it in your page manifest and verify the `.sac` client‑side before use.

---

## Error handling & resilience
- **Header sanity**: always check magic, dtype, counts, and lengths.
- **Shape checks**: if width/height are present, confirm `len == W*H`.
- **Graceful degrade**: if the mask fetch fails, continue rendering the base image without overlay.
- **Versioning**: bump magic to `SAC2` if you add more dtypes/arrays; clients can branch on magic.

---

## FAQ
**Why not JSON or Base64?**  Bandwidth and CPU. Numbers in JSON are ~8–12× larger and slower to parse. Base64 adds ~33% and still needs decoding.

**Why little‑endian only?**  All major browsers run on little‑endian hardware. Fixing endianness removes ambiguity; the `DataView` path remains available if you ever target exotic platforms.

**What if I already split each int16 into two int8 arrays?**  Don’t—SAC v1 puts the *actual* `int16` payloads on the wire. If you only have split bytes, concatenate low/high into the same order used here before writing.

**Can I stream progressively?**  Yes. SAC is contiguous; you can ship chunks and parse once the full payload arrives. For true progressive decoding, keep the header (24 bytes) first and stream the two segments in order.

---

## Test vectors
Create a tiny 2×3 sample and verify round‑trip.
```python
import numpy as np
ax = np.array([[0, 1, -1],[2, -2, 3]], dtype=np.int16)
ay = np.array([[5, -5, 4],[-4, 0, 1]], dtype=np.int16)
sac = build_sac(ax.ravel(), ay.ravel(), width=3, height=2)
open('sample.sac', 'wb').write(sac)
```

```js
// After serving sample.sac locally, parse and assert fields
fetch('sample.sac').then(r=>r.arrayBuffer()).then(buf=>{
  const {a,b,width,height}=parseSAC(buf);
  console.assert(width===3 && height===2);
  console.assert(a[0]===0 && a[1]===1 && a[2]===-1);
  console.assert(b[0]===5 && b[1]===-5 && b[2]===4);
  console.log('SAC ok');
});
```

---

## Extension ideas (future SAC2)
- Arbitrary `dtype_code` (e.g., `float32`, `uint8`)
- `arrays_count > 2` with per-array descriptors
- Optional CRC32 for payload integrity
- Optional per-array compression blocks
- Named arrays and metadata TLVs

---

## TL;DR
Ship `int16` arrays as raw binary with a 24‑byte header. Cache forever on your CDN. Parse in JS with a `DataView`/`Int16Array`. No JSON, no Base64, no nonsense.

