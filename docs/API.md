# Artorize Processor API Reference

Complete API reference for the Artorize Processor Core (Gateway).

**Base URL**: `http://localhost:8765` (default)

---

## Table of Contents

1. [Overview](#overview)
2. [Artwork Processing](#artwork-processing)
3. [Job Management](#job-management)
4. [SAC Encoding](#sac-encoding)
5. [Image Similarity](#image-similarity)
6. [Error Codes](#error-codes)

---

## Overview

The Artorize Processor Core handles the heavy lifting of image protection, watermarking, and analysis. It exposes a REST API via the Gateway service.

---

## Artwork Processing

### POST /v1/process/artwork
Process an image with protection layers and optionally upload to backend.

**Content-Type**: `multipart/form-data`

**Parameters**:
- `file` (required): Image file
- `metadata` (required): JSON string

**Metadata Structure**:
```json
{
  "job_id": "string (required)",
  "callback_url": "string (required)",
  "callback_auth_token": "string (required)",
  "backend_url": "string (optional)",
  "backend_auth_token": "string (optional)",
  "processors": ["array of strings"],
  "watermark_strategy": "string"
}
```

**Response (202 Accepted)**:
```json
{
  "job_id": "...",
  "status": "processing",
  "message": "Job queued..."
}
```

---

## Job Management

### POST /v1/jobs
Create a new processing job.

**Content-Type**: `multipart/form-data` or `application/json`

**Parameters (Multipart)**:
- `file`: Image file
- `processors`: Comma-separated list of processors
- `include_hash_analysis`: Boolean
- `include_protection`: Boolean

**Parameters (JSON)**:
```json
{
  "image_url": "https://...",
  "processors": ["fawkes", "mist"],
  "include_hash_analysis": true
}
```

### GET /v1/jobs/:job_id
Check the status of a processing job.

**Response**:
```json
{
  "job_id": "...",
  "status": "running",
  "submitted_at": "..."
}
```

### GET /v1/jobs/:job_id/result
Retrieve the complete result of a finished job.

### DELETE /v1/jobs/:job_id
Clean up job files.

---

## SAC Encoding

### POST /v1/sac/encode
Encode hi/lo mask images to SAC binary format.

**Content-Type**: `multipart/form-data`

**Parameters**:
- `mask_hi`: High-byte mask image
- `mask_lo`: Low-byte mask image

### POST /v1/sac/encode/npz
Encode mask from .npz file containing pre-computed hi/lo arrays.

**Content-Type**: `multipart/form-data`

**Parameters**:
- `npz_file`: NPZ file with 'hi' and 'lo' arrays

### POST /v1/sac/encode/batch
Batch encode SAC files from completed job IDs.

**Content-Type**: `application/json`

**Request**:
```json
{
  "job_ids": ["job1", "job2"],
  "output_dir": "optional/path"
}
```

### GET /v1/sac/encode/job/:job_id
Generate SAC mask from a completed job.

---

## Image Similarity

## Image Similarity

### POST /v1/images/extract-hashes
Extract perceptual hashes from an image.

**Content-Type**: `multipart/form-data` or `application/json`

### POST /v1/images/find-similar
Find similar images based on perceptual hash comparison.

**Content-Type**: `multipart/form-data` or `application/json`

**Parameters**:
- `threshold`: Similarity threshold (0.0-1.0)
- `limit`: Max results
- `hash_types`: Comma-separated hash types

---

## Error Codes

| Code | Description |
|------|-------------|
| `PROCESSING_FAILED` | Image processing error |
| `BACKEND_UPLOAD_FAILED` | Backend upload error |
| `401 Unauthorized` | Invalid authentication token |
| `429 Too Many Requests` | Rate limit exceeded |
