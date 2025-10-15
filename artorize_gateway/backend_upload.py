"""Backend upload client for direct artwork storage."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


class BackendUploadError(Exception):
    """Base exception for backend upload errors."""
    pass


class BackendTimeoutError(BackendUploadError):
    """Backend upload timed out."""
    pass


class BackendRateLimitError(BackendUploadError):
    """Backend rate limit exceeded."""
    pass


class BackendAuthError(BackendUploadError):
    """Backend authentication failed (401 - token invalid/expired/used)."""
    pass


class BackendUploadClient:
    """HTTP client for uploading artwork to backend storage."""

    def __init__(
        self,
        timeout: float = 30.0,
        max_retries: int = 3,
        retry_delay: float = 2.0,
    ):
        """
        Initialize backend upload client.

        Args:
            timeout: HTTP request timeout in seconds
            max_retries: Number of retry attempts on failure
            retry_delay: Base delay between retries (exponential backoff)
        """
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    async def upload_artwork(
        self,
        backend_url: str,
        original_image_path: Path,
        protected_image_path: Path,
        mask_path: Optional[Path],
        analysis: Optional[Dict[str, Any]],
        summary: Dict[str, Any],
        metadata: Dict[str, Any],
        auth_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Upload processed artwork to backend storage.

        Args:
            backend_url: Base URL of backend API (e.g., http://localhost:3002)
            original_image_path: Path to original image file
            protected_image_path: Path to protected image file
            mask_path: Path to combined SAC mask file (contains both hi/lo arrays)
            analysis: Analysis JSON data
            summary: Summary JSON data
            metadata: Artwork metadata (title, artist, description, tags, etc.)
            auth_token: Optional authentication token

        Returns:
            Backend response with artwork_id

        Raises:
            BackendUploadError: If upload fails after retries
        """
        # Prepare headers
        headers = {}
        if auth_token:
            headers['Authorization'] = f'Bearer {auth_token}'
            logger.info('Using per-artwork authentication token for backend upload')
        else:
            logger.warning('No authentication token provided for backend upload')

        # Validate required files
        missing_files = []

        if not original_image_path or not original_image_path.exists():
            missing_files.append('original image')
        if not protected_image_path or not protected_image_path.exists():
            missing_files.append('protected image')
        if not mask_path or not mask_path.exists():
            missing_files.append('SAC mask file')
        if not analysis:
            missing_files.append('analysis JSON')
        if not summary:
            missing_files.append('summary JSON')

        if missing_files:
            error_msg = f"Required files missing for backend upload: {', '.join(missing_files)}"
            logger.error(error_msg)
            raise BackendUploadError(error_msg)

        # Prepare form data
        data = {
            'title': metadata.get('artwork_title', 'Untitled'),
            'artist': metadata.get('artist_name', 'Unknown'),
        }

        if metadata.get('artwork_description'):
            data['description'] = metadata['artwork_description']

        if metadata.get('tags'):
            tags = metadata['tags']
            if isinstance(tags, list):
                data['tags'] = ','.join(tags)
            else:
                data['tags'] = tags

        if metadata.get('artwork_creation_time'):
            data['createdAt'] = metadata['artwork_creation_time']

        # Add extra metadata (hashes, watermark info, processing time)
        extra_metadata = {}
        if metadata.get('hashes'):
            extra_metadata['hashes'] = metadata['hashes']
        if metadata.get('watermark'):
            extra_metadata['watermark'] = metadata['watermark']
        if metadata.get('processing_time_ms'):
            extra_metadata['processing_time_ms'] = metadata['processing_time_ms']
        if metadata.get('processors_used'):
            extra_metadata['processors_used'] = metadata['processors_used']

        if extra_metadata:
            data['extra'] = json.dumps(extra_metadata)

        # Prepare files
        files_to_upload = {}

        # Required files
        files_to_upload['original'] = (
            original_image_path.name,
            open(original_image_path, 'rb'),
            'image/jpeg',
        )
        files_to_upload['protected'] = (
            protected_image_path.name,
            open(protected_image_path, 'rb'),
            'image/jpeg',
        )

        # Required SAC mask (combined hi/lo)
        files_to_upload['mask'] = (
            mask_path.name,
            open(mask_path, 'rb'),
            'application/octet-stream',
        )

        # Required JSON files
        files_to_upload['analysis'] = (
            'analysis.json',
            json.dumps(analysis, indent=2).encode('utf-8'),
            'application/json',
        )
        files_to_upload['summary'] = (
            'summary.json',
            json.dumps(summary, indent=2).encode('utf-8'),
            'application/json',
        )

        # Upload with retry logic
        try:
            return await self._upload_with_retry(
                backend_url,
                files_to_upload,
                data,
                headers,
            )
        finally:
            # Close all file handles
            for file_tuple in files_to_upload.values():
                if hasattr(file_tuple[1], 'close'):
                    file_tuple[1].close()

    async def _upload_with_retry(
        self,
        backend_url: str,
        files: Dict[str, Any],
        data: Dict[str, str],
        headers: Dict[str, str],
    ) -> Dict[str, Any]:
        """Upload with exponential backoff retry."""

        last_error = None

        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        f'{backend_url}/artworks',
                        files=files,
                        data=data,
                        headers=headers,
                        timeout=self.timeout,
                    )

                    if response.status_code == 201:
                        logger.info(f'Backend upload successful (attempt {attempt + 1})')
                        return response.json()

                    elif response.status_code == 401:
                        # Authentication failed - token invalid, expired, or already used
                        error_msg = (
                            'Backend authentication failed. Token may be invalid, expired, or already used.'
                        )
                        logger.error(f'{error_msg} (Status: 401)')
                        raise BackendAuthError(error_msg)

                    elif response.status_code == 429:
                        # Rate limited, retry with backoff
                        wait_time = self.retry_delay * (2 ** attempt)
                        logger.warning(
                            f'Backend rate limited (429), retrying in {wait_time}s '
                            f'(attempt {attempt + 1}/{self.max_retries})'
                        )
                        if attempt < self.max_retries - 1:
                            await asyncio.sleep(wait_time)
                            continue
                        raise BackendRateLimitError(f'Backend rate limit exceeded after {self.max_retries} attempts')

                    else:
                        # Other error, don't retry
                        error_msg = f'Backend returned {response.status_code}: {response.text}'
                        logger.error(error_msg)
                        raise BackendUploadError(error_msg)

            except httpx.TimeoutException as e:
                last_error = e
                logger.error(
                    f'Backend upload timeout: {e} '
                    f'(attempt {attempt + 1}/{self.max_retries})'
                )
                if attempt < self.max_retries - 1:
                    wait_time = self.retry_delay * (2 ** attempt)
                    await asyncio.sleep(wait_time)
                    continue
                raise BackendTimeoutError(f'Backend upload timeout after {self.max_retries} attempts') from e

            except httpx.NetworkError as e:
                last_error = e
                logger.error(
                    f'Backend network error: {e} '
                    f'(attempt {attempt + 1}/{self.max_retries})'
                )
                if attempt < self.max_retries - 1:
                    wait_time = self.retry_delay * (2 ** attempt)
                    await asyncio.sleep(wait_time)
                    continue
                raise BackendUploadError(f'Backend network error after {self.max_retries} attempts: {e}') from e

            except BackendUploadError:
                # Re-raise our own exceptions (BackendAuthError, etc.) without wrapping
                raise

            except Exception as e:
                logger.error(f'Unexpected backend upload error: {e}')
                raise BackendUploadError(f'Backend upload failed: {e}') from e

        # Should not reach here, but just in case
        if last_error:
            raise BackendUploadError(f'Backend upload failed after {self.max_retries} attempts') from last_error
        raise BackendUploadError(f'Backend upload failed after {self.max_retries} attempts')
