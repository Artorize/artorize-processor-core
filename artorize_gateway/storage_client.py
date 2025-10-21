"""
Backend storage service client for similarity search.

This module provides a client interface for querying the backend storage service
to find similar images based on perceptual hashes.

NOTE: This is a STUB implementation. Actual similarity search requires an external
backend storage service with:
  - Database of artwork images and their precomputed hashes
  - Similarity search API endpoint (Hamming distance comparison)
  - Artwork metadata (title, artist, thumbnail URLs, upload timestamps)

See mod-processor.md for backend API requirements.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx


@dataclass
class SimilarImage:
    """Result item from similarity search."""
    artwork_id: str
    title: str
    artist: str
    similarity_score: float
    matching_hashes: Dict[str, float]
    thumbnail_url: str
    uploaded_at: str


@dataclass
class SimilaritySearchResult:
    """Complete similarity search response."""
    similar_images: List[SimilarImage]
    total_matches: int
    search_time_ms: int


class StorageClient:
    """
    HTTP client for backend storage service.

    Configuration via environment variables:
    - STORAGE_BACKEND_URL: Backend service base URL (default: http://localhost:5001)
    - STORAGE_BACKEND_TIMEOUT: Request timeout in seconds (default: 30)
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = 30.0
    ):
        self.base_url = base_url or os.getenv("STORAGE_BACKEND_URL", "http://localhost:5001")
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create async HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                follow_redirects=True
            )
        return self._client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def health_check(self) -> bool:
        """
        Check if backend storage service is available.

        Returns:
            True if service responds, False otherwise
        """
        try:
            client = await self._get_client()
            response = await client.get("/health")
            return response.status_code == 200
        except Exception:
            return False

    async def find_similar_by_hashes(
        self,
        hashes: Dict[str, str],
        threshold: float = 0.85,
        limit: int = 10
    ) -> SimilaritySearchResult:
        """
        Query backend for similar images based on perceptual hashes.

        Args:
            hashes: Dictionary of hash type -> hex string value
            threshold: Similarity threshold (0.0-1.0)
            limit: Maximum number of results to return

        Returns:
            SimilaritySearchResult with similar images

        Raises:
            NotImplementedError: Backend service not configured
            httpx.HTTPError: Backend request failed

        NOTE: This is a STUB implementation. Returns empty results with a warning.
              Requires external backend storage service to be implemented.
        """
        # Check if backend is configured
        if self.base_url == "http://localhost:5001":
            # Default value - backend not configured
            raise NotImplementedError(
                "Backend storage service not configured. "
                "Set STORAGE_BACKEND_URL environment variable to the backend API endpoint. "
                "See mod-processor.md for backend implementation requirements."
            )

        # Attempt to query backend
        try:
            client = await self._get_client()
            response = await client.post(
                "/v1/similarity/search",
                json={
                    "hashes": hashes,
                    "threshold": threshold,
                    "limit": limit
                }
            )
            response.raise_for_status()

            data = response.json()
            similar_images = [
                SimilarImage(
                    artwork_id=item["artwork_id"],
                    title=item["title"],
                    artist=item["artist"],
                    similarity_score=item["similarity_score"],
                    matching_hashes=item["matching_hashes"],
                    thumbnail_url=item["thumbnail_url"],
                    uploaded_at=item["uploaded_at"]
                )
                for item in data.get("similar_images", [])
            ]

            return SimilaritySearchResult(
                similar_images=similar_images,
                total_matches=data.get("total_matches", len(similar_images)),
                search_time_ms=data.get("search_time_ms", 0)
            )

        except httpx.HTTPError as e:
            raise RuntimeError(f"Backend storage service request failed: {e}") from e


# Singleton instance for dependency injection
_storage_client: Optional[StorageClient] = None


def get_storage_client() -> StorageClient:
    """Get singleton storage client instance."""
    global _storage_client
    if _storage_client is None:
        _storage_client = StorageClient()
    return _storage_client
