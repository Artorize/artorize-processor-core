"""Storage client for uploading processed images to local, S3, or CDN."""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Dict, Optional

from PIL import Image

logger = logging.getLogger(__name__)


class StorageUploader:
    """Upload processed images to local storage, S3, or CDN."""

    def __init__(
        self,
        storage_type: str = "local",
        s3_bucket_name: Optional[str] = None,
        s3_region: str = "us-east-1",
        cdn_base_url: Optional[str] = None,
        local_storage_base_url: str = "http://localhost:8000/v1/storage",
        output_dir: Optional[Path] = None,
    ):
        """
        Initialize storage uploader.

        Args:
            storage_type: Storage type - "local", "s3", or "cdn"
            s3_bucket_name: S3 bucket name (required for S3 storage)
            s3_region: AWS region for S3
            cdn_base_url: Base URL for CDN
            local_storage_base_url: Base URL for local storage endpoints
            output_dir: Local directory for storing files (required for local storage)
        """
        self.storage_type = storage_type
        self.s3_bucket_name = s3_bucket_name
        self.s3_region = s3_region
        self.cdn_base_url = cdn_base_url
        self.local_storage_base_url = local_storage_base_url
        self.output_dir = output_dir
        self.s3_client = None

        if storage_type == "s3":
            try:
                import boto3

                self.s3_client = boto3.client("s3", region_name=s3_region)
                logger.info(f"Initialized S3 storage client for bucket {s3_bucket_name}")
            except ImportError:
                logger.error(
                    "S3 storage requested but boto3 not installed. "
                    "Install with: pip install boto3"
                )
                raise RuntimeError("boto3 required for S3 storage")

        elif storage_type == "local":
            if not output_dir:
                raise ValueError("output_dir required for local storage")
            self.output_dir = Path(output_dir)
            self.output_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Initialized local storage at {self.output_dir}")

    async def upload_protected_image(
        self,
        image_path: Path,
        job_id: str,
        image_format: str = "jpeg",
    ) -> Dict[str, str]:
        """
        Upload protected image and thumbnail to storage.

        Args:
            image_path: Path to the image file to upload
            job_id: Unique job identifier
            image_format: Image format (jpeg, png, etc.)

        Returns:
            Dictionary with 'protected_image_url' and 'thumbnail_url'
        """
        if self.storage_type == "s3":
            return await self._upload_to_s3(image_path, job_id, image_format)
        else:
            return await self._upload_to_local(image_path, job_id, image_format)

    async def _upload_to_s3(
        self,
        image_path: Path,
        job_id: str,
        image_format: str,
    ) -> Dict[str, str]:
        """Upload to S3 storage."""
        if not self.s3_client or not self.s3_bucket_name:
            raise RuntimeError("S3 client not initialized")

        # Generate S3 keys
        full_key = f"protected/{job_id}.{image_format}"
        thumb_key = f"thumbnails/{job_id}_thumb.{image_format}"

        # Upload full image
        with open(image_path, "rb") as f:
            image_data = f.read()

        self.s3_client.put_object(
            Bucket=self.s3_bucket_name,
            Key=full_key,
            Body=image_data,
            ContentType=f"image/{image_format}",
            CacheControl="public, max-age=31536000",
        )
        logger.info(f"Uploaded full image to S3: {full_key}")

        # Generate and upload thumbnail
        thumbnail_data = await self._generate_thumbnail(image_path, max_size=(300, 300))
        self.s3_client.put_object(
            Bucket=self.s3_bucket_name,
            Key=thumb_key,
            Body=thumbnail_data,
            ContentType=f"image/{image_format}",
            CacheControl="public, max-age=31536000",
        )
        logger.info(f"Uploaded thumbnail to S3: {thumb_key}")

        # Build URLs
        base_url = self.cdn_base_url or f"https://{self.s3_bucket_name}.s3.{self.s3_region}.amazonaws.com"
        return {
            "protected_image_url": f"{base_url}/{full_key}",
            "thumbnail_url": f"{base_url}/{thumb_key}",
        }

    async def _upload_to_local(
        self,
        image_path: Path,
        job_id: str,
        image_format: str,
    ) -> Dict[str, str]:
        """Store locally and return local URLs."""
        if not self.output_dir:
            raise RuntimeError("output_dir not set for local storage")

        # Create storage directories
        protected_dir = self.output_dir / "protected"
        thumbnails_dir = self.output_dir / "thumbnails"
        protected_dir.mkdir(parents=True, exist_ok=True)
        thumbnails_dir.mkdir(parents=True, exist_ok=True)

        # Copy full image
        full_filename = f"{job_id}.{image_format}"
        thumb_filename = f"{job_id}_thumb.{image_format}"
        full_path = protected_dir / full_filename
        thumb_path = thumbnails_dir / thumb_filename

        # Copy or move the original
        import shutil

        shutil.copy2(image_path, full_path)
        logger.info(f"Stored full image locally: {full_path}")

        # Generate and save thumbnail
        thumbnail_data = await self._generate_thumbnail(image_path, max_size=(300, 300))
        with open(thumb_path, "wb") as f:
            f.write(thumbnail_data)
        logger.info(f"Stored thumbnail locally: {thumb_path}")

        # Build URLs
        return {
            "protected_image_url": f"{self.local_storage_base_url}/protected/{full_filename}",
            "thumbnail_url": f"{self.local_storage_base_url}/thumbnails/{thumb_filename}",
        }

    async def _generate_thumbnail(
        self,
        image_path: Path,
        max_size: tuple[int, int] = (300, 300),
    ) -> bytes:
        """
        Generate a thumbnail from the image.

        Args:
            image_path: Path to the source image
            max_size: Maximum thumbnail dimensions (width, height)

        Returns:
            Thumbnail image data as bytes
        """
        with Image.open(image_path) as img:
            # Convert to RGB if necessary
            if img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGB")

            # Create thumbnail
            img.thumbnail(max_size, Image.Resampling.LANCZOS)

            # Save to bytes
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=85, optimize=True)
            return buffer.getvalue()
