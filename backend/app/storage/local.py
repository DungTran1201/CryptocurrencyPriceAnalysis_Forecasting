"""Local filesystem storage backend with atomic writes and path traversal guards."""

import os
from pathlib import Path
from typing import List, Dict, Any
import uuid

from backend.app.storage.base import StorageBackend


class LocalStorageBackend(StorageBackend):
    """Stores Medallion Bronze/Silver/Gold files on the local filesystem."""

    def __init__(self, root_dir: Path | str):
        self.root_dir = Path(root_dir).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _safe_path(self, key: str) -> Path:
        clean_key = key.lstrip("/\\").replace("\\", "/")
        target = (self.root_dir / clean_key).resolve()
        if target != self.root_dir and self.root_dir not in target.parents:
            raise ValueError(f"Unsafe storage key outside root: {key}")
        return target

    def resolve_uri(self, key: str) -> str:
        return str(self._safe_path(key))

    def local_path(self, key: str) -> Path:
        return self._safe_path(key)

    def write_bytes(self, key: str, data: bytes) -> int:
        target = self._safe_path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            with open(tmp_path, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, target)
            return len(data)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    def read_bytes(self, key: str) -> bytes:
        target = self._safe_path(key)
        with open(target, "rb") as f:
            return f.read()

    def exists(self, key: str) -> bool:
        return self._safe_path(key).exists()

    def list_keys(self, prefix: str = "", suffix: str = "") -> List[str]:
        base = self._safe_path(prefix) if prefix else self.root_dir
        if not base.exists():
            return []
        keys: List[str] = []
        if base.is_file():
            rel = base.relative_to(self.root_dir).as_posix()
            if not suffix or rel.endswith(suffix):
                return [rel]
            return []
        for entry in base.rglob("*"):
            if entry.is_file() and not entry.name.startswith("."):
                rel = entry.relative_to(self.root_dir).as_posix()
                if not suffix or rel.endswith(suffix):
                    keys.append(rel)
        keys.sort()
        return keys

    def delete(self, key: str) -> bool:
        target = self._safe_path(key)
        if target.exists() and target.is_file():
            target.unlink()
            return True
        return False

    def stat_prefix(self, prefix: str = "") -> Dict[str, Any]:
        keys = self.list_keys(prefix=prefix)
        total_bytes = 0
        oldest_mtime = None
        newest_mtime = None
        for k in keys:
            p = self._safe_path(k)
            try:
                st = p.stat()
                total_bytes += st.st_size
                if oldest_mtime is None or st.st_mtime < oldest_mtime:
                    oldest_mtime = st.st_mtime
                if newest_mtime is None or st.st_mtime > newest_mtime:
                    newest_mtime = st.st_mtime
            except OSError:
                pass
        return {
            "prefix": prefix,
            "file_count": len(keys),
            "total_bytes": total_bytes,
            "oldest_mtime": oldest_mtime,
            "newest_mtime": newest_mtime,
        }

