"""S3/MinIO storage client."""

from __future__ import annotations

import logging

from learning_platform.config import Settings

_LOG = logging.getLogger(__name__)


class S3Storage:
    """S3-compatible object storage client (MinIO, AWS S3, etc.)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def get_presigned_url(self, key: str) -> str:
        """Return a presigned URL for the given object key."""
        _LOG.info("Generating presigned URL for: %s", key)
        raise NotImplementedError

    def upload_file(self, key: str, data: bytes) -> None:
        """Upload raw bytes to the configured bucket."""
        _LOG.info("Uploading: %s (%d bytes)", key, len(data))
        raise NotImplementedError
