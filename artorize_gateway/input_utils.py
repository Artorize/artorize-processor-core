"""
Shared utilities for handling image inputs across gateway endpoints.

Provides common functions for:
- File downloading from URLs
- Local path resolution and validation
- Parameter parsing from Form and JSON payloads
- Temporary file management
"""

from __future__ import annotations

import asyncio
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, Protocol

import aiofiles
import httpx
from fastapi import HTTPException, UploadFile


async def download_to_path(url: str, dest: Path, timeout: float = 30.0) -> None:
    """
    Download file from URL to local path.

    Args:
        url: Source URL
        dest: Destination path
        timeout: Request timeout in seconds

    Raises:
        httpx.HTTPError: Download failed
    """
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(dest, "wb") as out:
                async for chunk in response.aiter_bytes():
                    await out.write(chunk)


def resolve_local_path(raw: str) -> Path:
    """
    Resolve and validate local file path.

    Args:
        raw: Raw path string (supports ~ expansion)

    Returns:
        Resolved absolute path

    Raises:
        FileNotFoundError: File does not exist
    """
    path = Path(raw).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"local file not found: {path}")
    return path


def parse_comma_separated(raw: Optional[str]) -> Optional[list[str]]:
    """
    Parse comma-separated string into list.

    Args:
        raw: Comma-separated string or None

    Returns:
        List of stripped non-empty strings, or None if input is None/empty
    """
    if not raw:
        return None
    items = [item.strip() for item in raw.split(",") if item.strip()]
    return items if items else None


def boolean_from_form(value: Optional[str], default: bool) -> bool:
    """
    Parse boolean from form field string.

    Args:
        value: Form field value (e.g., "1", "true", "yes", "on")
        default: Default value if None

    Returns:
        Parsed boolean value
    """
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


class ImagePayload(Protocol):
    """Protocol for payload types with image sources."""
    image_url: Optional[str]
    local_path: Optional[str]


async def handle_image_input(
    file: Optional[UploadFile],
    payload: Optional[ImagePayload],
    temp_dir: Path,
    timeout: float = 30.0,
) -> Path:
    """
    Handle image input from multiple sources (file upload, URL, or local path).

    Args:
        file: Uploaded file (multipart)
        payload: JSON payload with image_url or local_path
        temp_dir: Directory for temporary file storage
        timeout: Download timeout for URLs

    Returns:
        Path to image file (may be temporary or original local file)

    Raises:
        HTTPException: Invalid input or file not found
    """
    temp_dir.mkdir(parents=True, exist_ok=True)

    # Handle multipart file upload
    if file is not None:
        suffix = Path(file.filename or "image").suffix or ".bin"
        temp_path = temp_dir / f"{uuid.uuid4().hex}{suffix}"
        async with aiofiles.open(temp_path, "wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                await out.write(chunk)
        return temp_path

    # Handle JSON payload
    if payload is not None:
        if payload.local_path:
            try:
                return resolve_local_path(payload.local_path)
            except FileNotFoundError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e

        if payload.image_url:
            suffix = Path(payload.image_url).suffix or ".bin"
            temp_path = temp_dir / f"{uuid.uuid4().hex}{suffix}"
            try:
                await download_to_path(payload.image_url, temp_path, timeout)
            except httpx.HTTPError as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to download image: {e}"
                ) from e
            return temp_path

        raise HTTPException(status_code=400, detail="image_url or local_path required")

    raise HTTPException(status_code=400, detail="file upload or JSON payload required")


def parse_hash_types_param(
    form_value: Optional[str],
    payload: Optional[object],
) -> Optional[list[str]]:
    """
    Parse hash_types parameter from form or payload.

    Args:
        form_value: Comma-separated string from form
        payload: Payload object with hash_types attribute

    Returns:
        List of hash type strings, or None for all types
    """
    if form_value:
        return parse_comma_separated(form_value)
    if payload is not None and hasattr(payload, 'hash_types') and payload.hash_types:
        return list(payload.hash_types)
    return None


@asynccontextmanager
async def temp_directory(base_path: Path, prefix: str = "temp"):
    """
    Context manager for temporary directory with automatic cleanup.

    Args:
        base_path: Base directory for temp folder
        prefix: Prefix for temp directory name

    Yields:
        Path to temporary directory

    Example:
        async with temp_directory(Path("gateway_jobs"), "hash_extract") as temp_dir:
            # Work with temp_dir
            pass
        # Directory automatically cleaned up
    """
    temp_dir = base_path / prefix / uuid.uuid4().hex
    temp_dir.mkdir(parents=True, exist_ok=True)
    try:
        yield temp_dir
    finally:
        if temp_dir.exists():
            await asyncio.to_thread(shutil.rmtree, temp_dir, ignore_errors=True)
