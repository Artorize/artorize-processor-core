"""Configuration loader for processor gateway - loads from environment variables."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from .app import GatewayConfig


def load_config_from_env() -> GatewayConfig:
    """
    Load GatewayConfig from environment variables.

    Loads .env file if present and reads configuration values.

    Environment Variables:
        HOST: Server host (default: 0.0.0.0)
        PORT: Server port (default: 8765)
        PROCESSED_IMAGE_STORAGE: Storage type - "local", "s3", or "backend" (default: local)
        STORAGE_BACKEND_URL: Backend API base URL for uploads (default: http://localhost:5001)
        CDN_BASE_URL: CDN base URL (for S3/CDN storage)
        S3_BUCKET_NAME: S3 bucket name (for S3 storage)
        S3_REGION: AWS region (default: us-east-1)
        MAX_FILE_SIZE: Maximum file size in bytes (default: 268435456 = 256MB)
        CALLBACK_TIMEOUT_MS: Callback timeout in milliseconds (default: 10000)
        CALLBACK_RETRY_ATTEMPTS: Number of retry attempts (default: 3)
        CALLBACK_RETRY_DELAY_MS: Delay between retries in milliseconds (default: 2000)
        WORKER_CONCURRENCY: Number of worker threads (default: 1)

    Returns:
        GatewayConfig object with values from environment
    """
    # Load .env file if it exists
    load_dotenv()

    # Parse storage type - support both "backend" and "local"
    storage_type = os.getenv("PROCESSED_IMAGE_STORAGE", "local").lower()
    # Map "backend" to "local" since both use HTTP upload
    if storage_type == "backend":
        storage_type = "local"

    # Build config
    config = GatewayConfig(
        base_dir=Path(os.getenv("GATEWAY_BASE_DIR", "gateway_jobs")),
        output_parent=Path(os.getenv("OUTPUT_DIR", "outputs")),
        worker_concurrency=int(os.getenv("WORKER_CONCURRENCY", "1")),
        request_timeout=float(os.getenv("REQUEST_TIMEOUT", "30.0")),
        # Callback settings
        callback_timeout=float(os.getenv("CALLBACK_TIMEOUT_MS", "10000")) / 1000.0,
        callback_retry_attempts=int(os.getenv("CALLBACK_RETRY_ATTEMPTS", "3")),
        callback_retry_delay=float(os.getenv("CALLBACK_RETRY_DELAY_MS", "2000")) / 1000.0,
        # Storage settings
        storage_type=storage_type,
        s3_bucket_name=os.getenv("S3_BUCKET_NAME", "artorizer-protected-images"),
        s3_region=os.getenv("S3_REGION", "us-east-1"),
        cdn_base_url=os.getenv("CDN_BASE_URL", "https://cdn.artorizer.com"),
        local_storage_base_url=os.getenv("STORAGE_BACKEND_URL", "http://localhost:5001"),
    )

    return config


def get_storage_info() -> dict:
    """
    Get current storage configuration info for debugging.

    Returns:
        Dictionary with current storage settings
    """
    load_dotenv()

    return {
        "storage_type": os.getenv("PROCESSED_IMAGE_STORAGE", "local"),
        "backend_url": os.getenv("STORAGE_BACKEND_URL", "http://localhost:5001"),
        "cdn_url": os.getenv("CDN_BASE_URL", ""),
        "s3_bucket": os.getenv("S3_BUCKET_NAME", ""),
        "s3_region": os.getenv("S3_REGION", "us-east-1"),
    }
