"""Tests for backend upload functionality."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx

from artorize_gateway.backend_upload import (
    BackendUploadClient,
    BackendUploadError,
    BackendTimeoutError,
    BackendRateLimitError,
    BackendAuthError,
)


@pytest.fixture
def backend_client():
    """Create a backend upload client for testing."""
    return BackendUploadClient(timeout=10.0, max_retries=3, retry_delay=0.1)


@pytest.fixture
def mock_files(tmp_path):
    """Create mock image and mask files."""
    original = tmp_path / "original.jpg"
    protected = tmp_path / "protected.jpg"
    mask_hi = tmp_path / "mask_hi.sac"
    mask_lo = tmp_path / "mask_lo.sac"

    original.write_bytes(b"original image data")
    protected.write_bytes(b"protected image data")
    mask_hi.write_bytes(b"mask hi data")
    mask_lo.write_bytes(b"mask lo data")

    return {
        "original": original,
        "protected": protected,
        "mask_hi": mask_hi,
        "mask_lo": mask_lo,
    }


@pytest.fixture
def mock_metadata():
    """Create mock artwork metadata."""
    return {
        "artwork_title": "Test Artwork",
        "artist_name": "Test Artist",
        "artwork_description": "Test description",
        "tags": ["test", "art"],
        "artwork_creation_time": "2025-10-11T12:00:00Z",
        "hashes": {
            "perceptual_hash": "0x123abc",
            "average_hash": "0x456def",
        },
        "watermark": {
            "strategy": "invisible-watermark",
            "strength": 0.5,
        },
        "processing_time_ms": 64000,
    }


@pytest.mark.asyncio
async def test_successful_upload(backend_client, mock_files, mock_metadata):
    """Test successful backend upload."""
    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_response.json.return_value = {
        "id": "60f7b3b3b3b3b3b3b3b3b3b3",
        "formats": {
            "original": {"fileId": "file1"},
            "protected": {"fileId": "file2"},
        },
    }

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client

        result = await backend_client.upload_artwork(
            backend_url="http://localhost:3002",
            original_image_path=mock_files["original"],
            protected_image_path=mock_files["protected"],
            mask_hi_path=mock_files["mask_hi"],
            mask_lo_path=mock_files["mask_lo"],
            analysis={"test": "analysis"},
            summary={"test": "summary"},
            metadata=mock_metadata,
        )

        assert result["id"] == "60f7b3b3b3b3b3b3b3b3b3b3"
        mock_client.post.assert_called_once()


@pytest.mark.asyncio
async def test_upload_with_auth_token(backend_client, mock_files, mock_metadata):
    """Test upload with authentication token."""
    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_response.json.return_value = {"id": "artwork-id"}

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client

        await backend_client.upload_artwork(
            backend_url="http://localhost:3002",
            original_image_path=mock_files["original"],
            protected_image_path=mock_files["protected"],
            mask_hi_path=None,
            mask_lo_path=None,
            analysis=None,
            summary={"test": "summary"},
            metadata=mock_metadata,
            auth_token="test-token",
        )

        # Verify auth header was included
        call_kwargs = mock_client.post.call_args[1]
        assert "headers" in call_kwargs
        assert call_kwargs["headers"]["Authorization"] == "Bearer test-token"


@pytest.mark.asyncio
async def test_upload_timeout_with_retry(backend_client, mock_files, mock_metadata):
    """Test upload timeout triggers retry logic."""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.TimeoutException("Timeout")
        mock_client_class.return_value.__aenter__.return_value = mock_client

        with pytest.raises(BackendTimeoutError):
            await backend_client.upload_artwork(
                backend_url="http://localhost:3002",
                original_image_path=mock_files["original"],
                protected_image_path=mock_files["protected"],
                mask_hi_path=None,
                mask_lo_path=None,
                analysis=None,
                summary={"test": "summary"},
                metadata=mock_metadata,
            )

        # Should retry 3 times
        assert mock_client.post.call_count == 3


@pytest.mark.asyncio
async def test_upload_rate_limit_with_retry(backend_client, mock_files, mock_metadata):
    """Test rate limit (429) triggers retry with backoff."""
    mock_response_429 = MagicMock()
    mock_response_429.status_code = 429

    mock_response_success = MagicMock()
    mock_response_success.status_code = 201
    mock_response_success.json.return_value = {"id": "artwork-id"}

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        # First attempt: rate limited, second attempt: success
        mock_client.post.side_effect = [mock_response_429, mock_response_success]
        mock_client_class.return_value.__aenter__.return_value = mock_client

        result = await backend_client.upload_artwork(
            backend_url="http://localhost:3002",
            original_image_path=mock_files["original"],
            protected_image_path=mock_files["protected"],
            mask_hi_path=None,
            mask_lo_path=None,
            analysis=None,
            summary={"test": "summary"},
            metadata=mock_metadata,
        )

        assert result["id"] == "artwork-id"
        assert mock_client.post.call_count == 2


@pytest.mark.asyncio
async def test_upload_auth_error_401(backend_client, mock_files, mock_metadata):
    """Test authentication error (401) raises BackendAuthError and does not retry."""
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.text = "Unauthorized"

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client

        with pytest.raises(BackendAuthError) as exc_info:
            await backend_client.upload_artwork(
                backend_url="http://localhost:3002",
                original_image_path=mock_files["original"],
                protected_image_path=mock_files["protected"],
                mask_hi_path=None,
                mask_lo_path=None,
                analysis=None,
                summary={"test": "summary"},
                metadata=mock_metadata,
                auth_token="invalid-token",
            )

        # Verify error message
        error_msg = str(exc_info.value)
        assert "authentication failed" in error_msg.lower()
        assert "invalid" in error_msg.lower() or "expired" in error_msg.lower() or "used" in error_msg.lower()

        # Should not retry on 401 (authentication errors are not transient)
        assert mock_client.post.call_count == 1


@pytest.mark.asyncio
async def test_upload_backend_error(backend_client, mock_files, mock_metadata):
    """Test backend error (500) does not retry."""
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client

        with pytest.raises(BackendUploadError) as exc_info:
            await backend_client.upload_artwork(
                backend_url="http://localhost:3002",
                original_image_path=mock_files["original"],
                protected_image_path=mock_files["protected"],
                mask_hi_path=None,
                mask_lo_path=None,
                analysis=None,
                summary={"test": "summary"},
                metadata=mock_metadata,
            )

        assert "500" in str(exc_info.value)
        # Should not retry on 500
        assert mock_client.post.call_count == 1


@pytest.mark.asyncio
async def test_upload_network_error_with_retry(backend_client, mock_files, mock_metadata):
    """Test network error triggers retry logic."""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.NetworkError("Network error")
        mock_client_class.return_value.__aenter__.return_value = mock_client

        with pytest.raises(BackendUploadError):
            await backend_client.upload_artwork(
                backend_url="http://localhost:3002",
                original_image_path=mock_files["original"],
                protected_image_path=mock_files["protected"],
                mask_hi_path=None,
                mask_lo_path=None,
                analysis=None,
                summary={"test": "summary"},
                metadata=mock_metadata,
            )

        # Should retry 3 times
        assert mock_client.post.call_count == 3


@pytest.mark.asyncio
async def test_upload_without_optional_files(backend_client, mock_files, mock_metadata):
    """Test upload works without optional mask files."""
    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_response.json.return_value = {"id": "artwork-id"}

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client

        result = await backend_client.upload_artwork(
            backend_url="http://localhost:3002",
            original_image_path=mock_files["original"],
            protected_image_path=mock_files["protected"],
            mask_hi_path=None,  # No masks
            mask_lo_path=None,
            analysis=None,  # No analysis
            summary={"test": "summary"},
            metadata=mock_metadata,
        )

        assert result["id"] == "artwork-id"
        # Verify only required files were uploaded
        call_kwargs = mock_client.post.call_args[1]
        files = call_kwargs["files"]
        assert "original" in files
        assert "protected" in files
        assert "summary" in files
        assert "maskHi" not in files
        assert "maskLo" not in files
        assert "analysis" not in files


@pytest.mark.asyncio
async def test_upload_with_metadata_variations(backend_client, mock_files):
    """Test upload with different metadata variations."""
    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_response.json.return_value = {"id": "artwork-id"}

    # Minimal metadata
    minimal_metadata = {
        "artwork_title": "Title",
        "artist_name": "Artist",
    }

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client

        result = await backend_client.upload_artwork(
            backend_url="http://localhost:3002",
            original_image_path=mock_files["original"],
            protected_image_path=mock_files["protected"],
            mask_hi_path=None,
            mask_lo_path=None,
            analysis=None,
            summary={"test": "summary"},
            metadata=minimal_metadata,
        )

        assert result["id"] == "artwork-id"

        # Verify data fields
        call_kwargs = mock_client.post.call_args[1]
        data = call_kwargs["data"]
        assert data["title"] == "Title"
        assert data["artist"] == "Artist"
        assert "description" not in data
        assert "tags" not in data
