"""Storage package factory and exports."""

from pathlib import Path
from typing import Optional

from backend.app.core.config import settings
from backend.app.storage.base import StorageBackend
from backend.app.storage.local import LocalStorageBackend
from backend.app.storage.s3 import S3StorageBackend


def get_data_root() -> Path:
    """Resolve absolute data directory path."""
    root = Path(settings.storage.data_dir)
    if not root.is_absolute():
        root = Path(settings.base_dir) / root
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_storage_backend(force_local_dir: Optional[Path] = None) -> StorageBackend:
    """Instantiate configured StorageBackend (Local FS default, S3/MinIO in EXTENDED)."""
    if force_local_dir is not None:
        return LocalStorageBackend(force_local_dir)
    if settings.storage.backend == "s3" and settings.storage.s3_endpoint_url:
        return S3StorageBackend(
            bucket=settings.storage.s3_bucket,
            endpoint_url=settings.storage.s3_endpoint_url,
            access_key=settings.storage.s3_access_key,
            secret_key=settings.storage.s3_secret_key,
            region_name=settings.storage.s3_region,
        )
    return LocalStorageBackend(get_data_root())


__all__ = [
    "StorageBackend",
    "LocalStorageBackend",
    "S3StorageBackend",
    "get_data_root",
    "get_storage_backend",
]

