"""Storage infrastructure for images and documents."""

from learning_platform.infrastructure.storage.adapter import StorageAdapter
from learning_platform.infrastructure.storage.s3 import S3Storage

__all__ = ["S3Storage", "StorageAdapter"]
