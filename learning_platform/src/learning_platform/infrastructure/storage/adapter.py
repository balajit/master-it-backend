"""Storage adapter for images and documents.

Provides a unified interface for storing and retrieving images,
with support for local filesystem and S3/MinIO backends.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from pathlib import Path

from learning_platform.config import Settings

_LOG = logging.getLogger(__name__)


class StorageAdapter:
    """Unified storage interface for images and documents.

    By default, stores images locally at:
        {upload_dir}/{doc_id}/images/{generated_name}.{ext}

    For S3/MinIO, configure via environment variables:
        - S3_ENDPOINT
        - S3_ACCESS_KEY
        - S3_SECRET_KEY
        - S3_BUCKET
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings
        self._local_mode = settings is None or not getattr(settings, "s3_endpoint", None)

    def store_image(
        self,
        doc_id: str,
        image_bytes: bytes,
        ext: str = "png",
        content_type: str = "image/png",
    ) -> str:
        """Store image and return storage key.

        Parameters
        ----------
        doc_id : str
            Document identifier.
        image_bytes : bytes
            Raw image data.
        ext : str
            File extension (e.g., "png", "jpg", "webp").
        content_type : str
            MIME type for the image.

        Returns
        -------
        str
            Storage key that can be used to retrieve the image.
        """
        if self._local_mode:
            return self._store_local(doc_id, image_bytes, ext)
        return self._store_s3(doc_id, image_bytes, ext, content_type)

    def get_image_url(self, storage_key: str) -> str:
        """Get URL for serving the image.

        Parameters
        ----------
        storage_key : str
            The storage key returned by ``store_image``.

        Returns
        -------
        str
            URL to access the image.
        """
        if self._local_mode:
            return self._get_local_url(storage_key)
        return self._get_s3_url(storage_key)

    def get_image_bytes(self, storage_key: str) -> bytes | None:
        """Retrieve image bytes from storage.

        Parameters
        ----------
        storage_key : str
            The storage key returned by ``store_image``.

        Returns
        -------
        bytes or None
            Image data, or None if not found.
        """
        if self._local_mode:
            return self._get_local_bytes(storage_key)
        return self._get_s3_bytes(storage_key)

    def _store_local(self, doc_id: str, image_bytes: bytes, ext: str) -> str:
        """Store image to local filesystem."""
        # Generate unique filename
        filename = f"{uuid.uuid4().hex}.{ext}"
        storage_key = f"{doc_id}/images/{filename}"

        # Create directory
        upload_dir = Path("uploads") / doc_id / "images"
        upload_dir.mkdir(parents=True, exist_ok=True)

        # Write file
        file_path = upload_dir / filename
        file_path.write_bytes(image_bytes)

        _LOG.info("Stored image locally: %s (%d bytes)", storage_key, len(image_bytes))
        return storage_key

    def _get_local_url(self, storage_key: str) -> str:
        """Get local file URL."""
        # Return a relative URL that can be served by FastAPI
        return f"/api/images/{storage_key}"

    def _get_local_bytes(self, storage_key: str) -> bytes | None:
        """Retrieve image bytes from local filesystem."""
        file_path = Path("uploads") / storage_key
        if file_path.exists():
            return file_path.read_bytes()
        return None

    def _store_s3(
        self,
        doc_id: str,
        image_bytes: bytes,
        ext: str,
        content_type: str,
    ) -> str:
        """Store image to S3/MinIO."""
        from learning_platform.infrastructure.storage.s3 import S3Storage

        if self._settings is None:
            raise ValueError("Settings required for S3 storage")

        s3 = S3Storage(self._settings)
        filename = f"{uuid.uuid4().hex}.{ext}"
        key = f"{doc_id}/images/{filename}"

        s3.upload_file(key, image_bytes)
        _LOG.info("Stored image to S3: %s (%d bytes)", key, len(image_bytes))
        return key

    def _get_s3_url(self, storage_key: str) -> str:
        """Get S3 presigned URL."""
        from learning_platform.infrastructure.storage.s3 import S3Storage

        if self._settings is None:
            raise ValueError("Settings required for S3 storage")

        s3 = S3Storage(self._settings)
        return s3.get_presigned_url(storage_key)

    def _get_s3_bytes(self, storage_key: str) -> bytes | None:
        """Retrieve image bytes from S3."""
        # S3 retrieval would require additional implementation
        _LOG.warning("S3 byte retrieval not yet implemented")
        return None


def compute_image_hash(image_bytes: bytes) -> str:
    """Compute SHA-256 hash of image bytes for deduplication."""
    return hashlib.sha256(image_bytes).hexdigest()
