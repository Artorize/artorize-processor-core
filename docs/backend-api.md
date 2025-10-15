# Artorize Storage Backend API Reference

A Node.js/Express service for secure artwork storage and retrieval using MongoDB GridFS.

**Base URL**: `http://localhost:3000` (configurable)

## Quick Start

```bash
# Health check
curl http://localhost:3000/health

# Search artworks
curl "http://localhost:3000/artworks?artist=Picasso&limit=5"

# Get artwork metadata
curl http://localhost:3000/artworks/{id}/metadata

# Stream artwork file
curl http://localhost:3000/artworks/{id}?variant=original
```

## Rate Limits

- **General**: 300 requests/15min per IP
- **Uploads**: 30 uploads/hour per IP
- **Health**: No limits

## Authentication

The backend uses **token-based authentication** for secure processor integration.

### How It Works

1. **Router generates a token** via `POST /tokens` endpoint
2. **Router passes token to both processor and backend**
3. **Processor includes token** in `Authorization: Bearer <token>` header when uploading
4. **Token is consumed** (single-use) on first successful upload
5. **Expired/used tokens are rejected** with 401 status

### Security Benefits

- **One-time tokens**: Each token can only be used once, preventing replay attacks
- **Time-limited**: Tokens expire after 1 hour (configurable)
- **Per-artwork isolation**: Compromised token affects only one artwork
- **No static credentials**: Eliminates risk of leaked API keys destroying everything

### Protected Endpoints

- `POST /artworks` - **Requires authentication** (token is consumed)

### Public Endpoints

All read endpoints remain public:
- `GET /artworks/*` - Search, metadata, file streaming
- `GET /health` - Health checks

---

## Processor Integration

This backend is designed to support **direct processor uploads** in the Artorize architecture with secure token-based authentication:

**Workflow**:
1. Router receives artwork submission request
2. **Router generates authentication token** via `POST /tokens`
3. **Router passes token to both processor and backend**
4. Processor receives image and token from router
5. Processor generates all variants (original, protected, masks, analysis, summary)
6. **Processor uploads directly to `POST /artworks`** with `Authorization: Bearer <token>` header
7. Backend validates and consumes token (single-use)
8. Backend returns `id` in response (MongoDB ObjectId)
9. Processor sends `id` to router in callback
10. Router uses `id` to retrieve files when needed

**Key Points**:
- ✅ Secure token-based authentication (one-time use)
- ✅ Per-artwork token isolation limits breach impact
- ✅ All required files and metadata are supported
- ✅ Returns `id` field that processor needs for callbacks
- ✅ Handles large files (256MB max) efficiently
- ✅ Rate limiting configured (30 uploads/hour per IP)
- ✅ No temporary storage needed in router
- ✅ Tokens expire after 1 hour (configurable)
- ✅ Automatic cleanup of expired/used tokens

**Security Architecture**:
- Each artwork gets a unique 16-character token
- Tokens are cryptographically random and single-use
- Compromised token only affects one artwork
- No static credentials to leak or crack

---

## Endpoints

### Authentication Endpoints

### `POST /tokens`
Generate a new authentication token (called by router).

**Request Body** (optional):
```json
{
  "artworkId": "60f7b3b3b3b3b3b3b3b3b3b3",
  "expiresIn": 3600000,
  "metadata": { "source": "router" }
}
```

- `artworkId` (optional) - Associate token with specific artwork
- `expiresIn` (optional) - Expiration time in milliseconds (default: 1 hour, max: 24 hours)
- `metadata` (optional) - Additional metadata to store with token

**Response**: `201 Created`
```json
{
  "token": "a1b2c3d4e5f6g7h8",
  "tokenId": "60f7b3b3b3b3b3b3b3b3b3b5",
  "artworkId": "60f7b3b3b3b3b3b3b3b3b3b3",
  "expiresAt": "2023-07-21T10:15:00.000Z",
  "createdAt": "2023-07-21T09:15:00.000Z"
}
```

---

### `DELETE /tokens/:token`
Revoke a token (mark as used).

**Response**: `200 OK`
```json
{
  "success": true,
  "message": "Token revoked successfully"
}
```

**Errors**:
- `404` - Token not found or already revoked

---

### `GET /tokens/stats`
Get token statistics (monitoring).

**Response**: `200 OK`
```json
{
  "stats": {
    "total": 150,
    "active": 5,
    "used": 120,
    "expired": 25
  },
  "timestamp": "2023-07-21T09:15:00.000Z"
}
```

---

### `GET /health`
Service health status.

**Response**: `200 OK`
```json
{ "ok": true, "uptime": 12345.67 }
```

---

### `POST /artworks`
Upload artwork with multiple file variants.

**Authentication**: Required
**Header**: `Authorization: Bearer <token>`

**Content-Type**: `multipart/form-data`

**Required Files**:
- `original` - Original image (JPEG/PNG/WebP/AVIF/GIF, max 256MB)
- `protected` - Protected variant (same formats)
- `maskHi` - High-res mask (SAC v1 binary format, .sac extension)
- `maskLo` - Low-res mask (SAC v1 binary format, .sac extension)
- `analysis` - Analysis JSON document
- `summary` - Summary JSON document

**Optional Fields**:
- `title` (200 chars max)
- `artist` (120 chars max)
- `description` (2000 chars max)
- `tags` (25 tags max, 50 chars each)
- `createdAt` (ISO date string)
- `extra` (5000 chars max JSON)

**Success**: `201 Created`
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
    "protected": { /* ... */ },
    "mask_hi": { /* ... */ },
    "mask_lo": { /* ... */ }
  }
}
```

**Important**: The `id` field in the response is a MongoDB ObjectId that **must be used by the processor in callbacks** to the router. This allows the router to retrieve artwork files using other endpoints.

**Errors**:
- `400` - Missing files, invalid types, malformed JSON
- `401` - Missing/invalid/expired authentication token
- `429` - Rate limit exceeded

---

### `GET /artworks/{id}`
Stream artwork file.

**Parameters**:
- `variant` (query) - `original|protected|mask_hi|mask_lo` (default: `original`)

**Response**: `200 OK`
- Binary file stream with proper MIME type
- For images: returns JPEG/PNG/WebP/etc. as appropriate
- For masks: returns SAC v1 binary format (application/octet-stream)
- Cache headers: `public, max-age=31536000, immutable`
- ETag: `{id}-{variant}`

**Note**: For mask files, prefer using the dedicated `/artworks/{id}/mask` endpoint with the `resolution` parameter.

**Errors**:
- `400` - Invalid ID format
- `404` - Artwork/variant not found

---

### `GET /artworks/{id}/metadata`
Complete artwork metadata.

**Response**: `200 OK`
```json
{
  "_id": "60f7b3b3b3b3b3b3b3b3b3b3",
  "title": "Artwork Title",
  "artist": "Artist Name",
  "description": "Description...",
  "tags": ["tag1", "tag2"],
  "createdAt": "2023-07-20T15:30:00Z",
  "uploadedAt": "2023-07-21T09:15:00Z",
  "formats": {
    "original": {
      "contentType": "image/jpeg",
      "bytes": 1048576,
      "checksum": "sha256:abc123...",
      "fileId": "60f7b3b3b3b3b3b3b3b3b3b4",
      "bucket": "originals"
    }
  },
  "analysis": { /* JSON payload */ },
  "summary": { /* JSON payload */ },
  "extra": { /* Additional metadata */ }
}
```

---

### `GET /artworks/{id}/variants`
Available variant information.

**Response**: `200 OK`
```json
{
  "id": "60f7b3b3b3b3b3b3b3b3b3b3",
  "title": "Artwork Title",
  "variants": {
    "original": {
      "available": true,
      "contentType": "image/jpeg",
      "size": 1048576,
      "checksum": "sha256:abc123...",
      "url": "/artworks/{id}?variant=original"
    }
  }
}
```

---

### `GET /artworks/{id}/mask`
Stream artwork mask file in SAC v1 binary format.

**Parameters**:
- `resolution` (query) - `hi|lo` (default: `hi`)

**Response**: `200 OK`
- Binary SAC v1 file stream (application/octet-stream)
- Cache headers: `public, max-age=31536000, immutable`
- ETag: `{id}-mask_{resolution}`
- Content-Disposition: `inline; filename="{title}-mask-{resolution}.sac"`

**Example**:
```bash
# Get high-resolution mask (default)
curl http://localhost:3000/artworks/{id}/mask

# Get low-resolution mask
curl http://localhost:3000/artworks/{id}/mask?resolution=lo

# Save to file
curl http://localhost:3000/artworks/{id}/mask -o mask.sac
```

**Errors**:
- `400` - Invalid ID format
- `404` - Artwork not found or mask not available

---

### `GET /artworks`
Search artworks.

**Query Parameters**:
- `artist` (120 chars max) - Filter by artist
- `q` (200 chars max) - Full-text search (title/description)
- `tags` - Comma-separated tags
- `limit` (1-10000, default: 20) - Results per page
- `skip` (0-5000, default: 0) - Pagination offset

**Response**: `200 OK`
```json
[
  {
    "_id": "60f7b3b3b3b3b3b3b3b3b3b3",
    "title": "Artwork Title",
    "artist": "Artist Name",
    "description": "Description...",
    "tags": ["tag1", "tag2"],
    "createdAt": "2023-07-20T15:30:00Z",
    "uploadedAt": "2023-07-21T09:15:00Z"
  }
]
```

---

### `GET /artworks/check-exists`
Check if artwork already exists.

**Query Parameters** (at least one required):
- `id` - 24-char hex string
- `checksum` - 64-char SHA256 hash
- `title` + `artist` - Combined search
- `tags` - Comma-separated tags

**Response**: `200 OK`
```json
{
  "exists": true,
  "matchCount": 1,
  "matches": [
    {
      "_id": "60f7b3b3b3b3b3b3b3b3b3b3",
      "title": "Artwork Title",
      "artist": "Artist Name",
      "checksum": "sha256:abc123...",
      "tags": ["tag1", "tag2"],
      "uploadedAt": "2023-07-21T09:15:00Z",
      "createdAt": "2023-07-20T15:30:00Z"
    }
  ]
}
```

---

### `POST /artworks/batch`
Retrieve multiple artworks by IDs.

**Request Body**:
```json
{
  "ids": ["60f7b3b3b3b3b3b3b3b3b3b3", "60f7b3b3b3b3b3b3b3b3b3b4"],
  "fields": "title,artist,tags"
}
```

- `ids` - Array of 1-100 artwork IDs
- `fields` (optional) - Comma-separated field list

**Response**: `200 OK`
```json
{
  "artworks": [
    {
      "_id": "60f7b3b3b3b3b3b3b3b3b3b3",
      "title": "Artwork Title",
      "artist": "Artist Name",
      "tags": ["tag1", "tag2"]
    }
  ]
}
```

---

### `GET /artworks/{id}/download`
Download artwork with attachment headers.

**Parameters**:
- `variant` (query) - File variant (default: `original`)

**Response**: `200 OK`
- Binary file stream
- `Content-Disposition: attachment; filename="title-variant.ext"`
- `Content-Type` and `Content-Length` headers

---

### `GET /artworks/{id}/download-url`
Generate temporary download URLs.

**Parameters**:
- `variant` (query) - File variant (default: `original`)
- `expires` (query) - Expiration seconds (60-86400, default: 3600)

**Response**: `200 OK`
```json
{
  "downloadUrl": "http://localhost:3000/artworks/{id}/download?variant=original",
  "directUrl": "http://localhost:3000/artworks/{id}?variant=original",
  "variant": "original",
  "contentType": "image/jpeg",
  "size": 1048576,
  "checksum": "sha256:abc123...",
  "expiresAt": "2023-07-21T10:15:00.000Z"
}
```

---

## Error Responses

All errors return JSON:
```json
{ "error": "Human-readable error message" }
```

**Status Codes**:
- `400` - Bad Request (validation errors, malformed data)
- `401` - Unauthorized (missing, invalid, or expired authentication token)
- `404` - Not Found (artwork/variant doesn't exist)
- `429` - Too Many Requests (rate limit exceeded)
- `500` - Internal Server Error

---

## Storage Architecture

**GridFS Buckets**:
- `artwork_originals` - Original images
- `artwork_protected` - Protected variants
- `artwork_masks` - High/low resolution masks (SAC v1 binary format)

**Features**:
- 1MB chunk size
- SHA256 checksums for integrity
- Automatic compression (WiredTiger + zstd)
- Masks stored in SAC v1 format for efficient CDN delivery

**Database Indexes**:
- `{ artist: 1, createdAt: -1 }` - Artist queries
- `{ tags: 1 }` - Tag filtering
- `{ title: "text", description: "text" }` - Full-text search

---

## File Format Support

**Images**: JPEG, PNG, WebP, AVIF, GIF
**Masks**: SAC v1 binary format (.sac files, application/octet-stream)
**Metadata**: JSON only
**Max Size**: 256MB per file

### SAC v1 Format
Masks use the Simple Array Container (SAC) v1 protocol - a compact binary format for shipping two signed 16-bit arrays. This format is optimized for CDN delivery with:
- Minimal overhead (24-byte header + raw int16 data)
- Fixed little-endian layout for browser compatibility
- Immutable caching support
- Efficient parsing in JavaScript
- See `sac_v_1_cdn_mask_transfer_protocol.md` for complete specification

---

## Security Features

- Rate limiting per IP
- Input validation (Zod schemas)
- Security headers (Helmet.js)
- Structured logging with header redaction
- File type validation
- Size limits enforcement

---

## Examples

### Complete Workflow Example

```bash
# Step 1: Router generates a token
TOKEN_RESPONSE=$(curl -X POST http://localhost:3000/tokens \
  -H "Content-Type: application/json" \
  -d '{"metadata": {"source": "router"}}')

TOKEN=$(echo $TOKEN_RESPONSE | jq -r '.token')
echo "Generated token: $TOKEN"

# Step 2: Router passes token to processor (and to backend for reference)

# Step 3: Processor uploads artwork with the token
curl -X POST http://localhost:3000/artworks \
  -H "Authorization: Bearer $TOKEN" \
  -F "original=@image.jpg" \
  -F "protected=@protected.jpg" \
  -F "maskHi=@mask_hi.sac" \
  -F "maskLo=@mask_lo.sac" \
  -F "analysis=@analysis.json" \
  -F "summary=@summary.json" \
  -F "title=My Artwork" \
  -F "artist=Artist Name" \
  -F "tags=abstract,modern"

# Response contains the artwork ID
# {
#   "id": "671924a5c3d8e8f9a1b2c3d4",
#   "formats": { ... }
# }
```

**Note**: Mask files must be in SAC v1 binary format. You can generate them using the Python code provided in `sac_v_1_cdn_mask_transfer_protocol.md`.

### Processor Upload Example
```bash
# Step 1: Get token from router (router already generated it)
TOKEN="a1b2c3d4e5f6g7h8"

# Step 2: Processor uploads after processing artwork
curl -X POST http://localhost:3000/artworks \
  -H "Authorization: Bearer $TOKEN" \
  -F "original=@mona_lisa.jpg;type=image/jpeg" \
  -F "protected=@mona_lisa_protected.jpg;type=image/jpeg" \
  -F "maskHi=@mask_hi.sac;type=application/octet-stream" \
  -F "maskLo=@mask_lo.sac;type=application/octet-stream" \
  -F "analysis=@analysis.json;type=application/json" \
  -F "summary=@summary.json;type=application/json" \
  -F "title=Mona Lisa" \
  -F "artist=Leonardo da Vinci" \
  -F "description=Famous Renaissance portrait" \
  -F "tags=renaissance,portrait,famous" \
  -F "createdAt=1503-01-01T00:00:00Z" \
  -F "extra={\"processing_time_ms\":64000}"

# Response contains the artwork ID
# {
#   "id": "671924a5c3d8e8f9a1b2c3d4",
#   "formats": { ... }
# }

# Step 3: Processor sends this ID to router in callback for retrieval
```

### Search Example
```bash
# Search by artist
curl "http://localhost:3000/artworks?artist=Picasso"

# Full-text search
curl "http://localhost:3000/artworks?q=landscape"

# Search by tags
curl "http://localhost:3000/artworks?tags=abstract,modern"

# Combined with pagination
curl "http://localhost:3000/artworks?artist=Picasso&limit=10&skip=20"
```

### Mask Retrieval Example
```bash
# Get high-resolution mask (default)
curl "http://localhost:3000/artworks/{id}/mask" -o mask-hi.sac

# Get low-resolution mask
curl "http://localhost:3000/artworks/{id}/mask?resolution=lo" -o mask-lo.sac

# Alternative: using variant parameter (legacy)
curl "http://localhost:3000/artworks/{id}?variant=mask_hi" -o mask-hi.sac
```

### Check Existence Example
```bash
# Check by checksum
curl "http://localhost:3000/artworks/check-exists?checksum=abc123..."

# Check by title and artist
curl "http://localhost:3000/artworks/check-exists?title=Mona Lisa&artist=Leonardo"
```