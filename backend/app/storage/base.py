"""Abstract Storage Backend contract for Medallion Bronze, Silver, and Gold layers."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Dict, Any


class StorageBackend(ABC):
    """Unified storage interface supporting Local Filesystem and S3/MinIO."""

    @abstractmethod
    def resolve_uri(self, key: str) -> str:
        """Return canonical URI/path for a relative object key."""

    @abstractmethod
    def write_bytes(self, key: str, data: bytes) -> int:
        """Atomically persist bytes under key and return byte count written."""

    @abstractmethod
    def read_bytes(self, key: str) -> bytes:
        """Read complete byte content for key."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Return True if object exists."""

    @abstractmethod
    def list_keys(self, prefix: str = "", suffix: str = "") -> List[str]:
        """List relative keys matching prefix and optional suffix sorted ascending."""

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Delete object by key if it exists."""

    @abstractmethod
    def stat_prefix(self, prefix: str = "") -> Dict[str, Any]:
        """Return aggregate object count and byte usage under prefix."""

    def local_path(self, key: str) -> Path:
        """Optional filesystem path for local backends (DuckDB/PyArrow direct read)."""
        raise NotImplementedError("Backend does not expose direct POSIX paths")

