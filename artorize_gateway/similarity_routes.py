"""
Similarity search routes for hash-based image comparison.

Provides endpoints for:
- Hash extraction from images
- Finding similar images based on perceptual hashes
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from .hash_extractor import extract_hashes
from .input_utils import handle_image_input, parse_hash_types_param, temp_directory
from .storage_client import get_storage_client


router = APIRouter(prefix="/v1/images", tags=["similarity"])


class HashExtractionPayload(BaseModel):
    """JSON payload for hash extraction request."""
    image_url: Optional[str] = None
    local_path: Optional[str] = None
    hash_types: Optional[Sequence[str]] = None


class SimilaritySearchPayload(BaseModel):
    """JSON payload for similarity search request."""
    image_url: Optional[str] = None
    local_path: Optional[str] = None
    threshold: Optional[float] = 0.85
    limit: Optional[int] = 10
    hash_types: Optional[Sequence[str]] = None


class HashExtractionResponse(BaseModel):
    """Response for hash extraction endpoint."""
    hashes: Dict[str, str]
    metadata: Dict[str, Any]


class SimilarImageResponse(BaseModel):
    """Similar image result item."""
    artwork_id: str
    title: str
    artist: str
    similarity_score: float
    matching_hashes: Dict[str, float]
    thumbnail_url: str
    uploaded_at: str


class SimilaritySearchResponse(BaseModel):
    """Response for similarity search endpoint."""
    query_hashes: Dict[str, str]
    similar_images: List[SimilarImageResponse]
    total_matches: int
    search_time_ms: int


@router.post("/extract-hashes", response_model=HashExtractionResponse)
async def extract_hashes_endpoint(
    file: UploadFile = File(None),
    hash_types: Optional[str] = Form(None),
    payload: Optional[HashExtractionPayload] = Body(None),
) -> HashExtractionResponse:
    """
    Extract perceptual hashes from an image.

    Accepts either:
    - Multipart file upload with optional form fields
    - JSON payload with image_url or local_path

    **Hash Types** (comma-separated or list):
    - `phash` - Perceptual hash (most robust)
    - `ahash` - Average hash (fast, good for duplicates)
    - `dhash` - Difference hash (edge-based)
    - `whash` - Wavelet hash (texture-based)
    - `colorhash` - Color distribution hash
    - `blockhash` or `blockhash8` - 8-bit block hash
    - `blockhash16` - 16-bit block hash
    - `all` - Compute all available hashes (default)

    **Returns**:
    - `hashes`: Dictionary of hash type -> hex string (with 0x prefix)
    - `metadata`: Image dimensions and format info
    """
    async with temp_directory(Path("gateway_jobs"), "hash_extraction") as temp_dir:
        # Get image file path
        image_path = await handle_image_input(file, payload, temp_dir)

        # Parse hash types
        types = parse_hash_types_param(hash_types, payload)

        # Extract hashes
        result = await asyncio.to_thread(extract_hashes, image_path, types)

        if result.get("error"):
            raise HTTPException(status_code=400, detail=result["error"])

        return HashExtractionResponse(
            hashes=result["hashes"],
            metadata=result["metadata"]
        )


@router.post("/find-similar", response_model=SimilaritySearchResponse)
async def find_similar_endpoint(
    file: UploadFile = File(None),
    threshold: Optional[str] = Form(None),
    limit: Optional[str] = Form(None),
    hash_types: Optional[str] = Form(None),
    payload: Optional[SimilaritySearchPayload] = Body(None),
) -> SimilaritySearchResponse:
    """
    Find similar images based on perceptual hash comparison.

    Accepts either:
    - Multipart file upload with optional form fields
    - JSON payload with image_url or local_path

    **Parameters**:
    - `threshold`: Similarity threshold 0.0-1.0 (default: 0.85)
    - `limit`: Maximum number of results (default: 10)
    - `hash_types`: Comma-separated hash types to use (default: all)

    **Returns**:
    - `query_hashes`: Computed hashes for the input image
    - `similar_images`: List of similar images found
    - `total_matches`: Total number of matches found
    - `search_time_ms`: Search duration in milliseconds

    **NOTE**: This endpoint requires an external backend storage service.
    Configure via STORAGE_BACKEND_URL environment variable.
    """
    async with temp_directory(Path("gateway_jobs"), "similarity_search") as temp_dir:
        # Get image file path
        image_path = await handle_image_input(file, payload, temp_dir)

        # Parse parameters
        types = parse_hash_types_param(hash_types, payload)
        threshold_val = float(threshold) if threshold else (payload.threshold if payload else 0.85)
        limit_val = int(limit) if limit else (payload.limit if payload else 10)

        # Validate parameters
        if not 0.0 <= threshold_val <= 1.0:
            raise HTTPException(status_code=400, detail="threshold must be between 0.0 and 1.0")
        if limit_val < 1 or limit_val > 100:
            raise HTTPException(status_code=400, detail="limit must be between 1 and 100")

        # Extract hashes
        start_time = time.time()
        hash_result = await asyncio.to_thread(extract_hashes, image_path, types)

        if hash_result.get("error"):
            raise HTTPException(status_code=400, detail=hash_result["error"])

        query_hashes = hash_result["hashes"]

        # Query backend storage for similar images
        storage_client = get_storage_client()
        try:
            search_result = await storage_client.find_similar_by_hashes(
                hashes=query_hashes,
                threshold=threshold_val,
                limit=limit_val
            )

            elapsed_ms = int((time.time() - start_time) * 1000)

            return SimilaritySearchResponse(
                query_hashes=query_hashes,
                similar_images=[
                    SimilarImageResponse(
                        artwork_id=img.artwork_id,
                        title=img.title,
                        artist=img.artist,
                        similarity_score=img.similarity_score,
                        matching_hashes=img.matching_hashes,
                        thumbnail_url=img.thumbnail_url,
                        uploaded_at=img.uploaded_at
                    )
                    for img in search_result.similar_images
                ],
                total_matches=search_result.total_matches,
                search_time_ms=elapsed_ms
            )

        except NotImplementedError as e:
            # Backend not configured - return hashes with empty results and clear message
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "Backend storage service not configured",
                    "message": str(e),
                    "query_hashes": query_hashes,
                    "similar_images": [],
                    "total_matches": 0
                }
            ) from e

        except Exception as e:
            raise HTTPException(
                status_code=503,
                detail=f"Backend storage service error: {e}"
            ) from e
