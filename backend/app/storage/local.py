"""Local filesystem storage backend with atomic writes and path traversal guards."""

from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from backend.app.storage.base import StorageBackend, StorageObjectMeta


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
        # Keep tmp suffix short to avoid exceeding Windows MAX_PATH (260 chars) on deep folder trees
        tmp_path = target.with_name(f".{uuid.uuid4().hex[:10]}.tmp")
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

    def head_object(self, key: str) -> Optional[StorageObjectMeta]:
        target = self._safe_path(key)
        if not target.exists() or not target.is_file():
            return None
        try:
            st = target.stat()
            rel = target.relative_to(self.root_dir).as_posix()
            mtime_utc = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).replace(tzinfo=None)
            return StorageObjectMeta(
                key=rel,
                size_bytes=st.st_size,
                last_modified_utc=mtime_utc,
                etag=None,
            )
        except OSError:
            return None

    def list_objects(self, prefix: str = "", suffix: str = "") -> List[StorageObjectMeta]:
        base = self._safe_path(prefix) if prefix else self.root_dir
        if not base.exists():
            return []
        objs: List[StorageObjectMeta] = []
        if base.is_file():
            meta = self.head_object(base.relative_to(self.root_dir).as_posix())
            if meta and (not suffix or meta.key.endswith(suffix)):
                return [meta]
            return []
        for entry in base.rglob("*"):
            if entry.is_file() and not entry.name.startswith("."):
                rel = entry.relative_to(self.root_dir).as_posix()
                if suffix and not rel.endswith(suffix):
                    continue
                try:
                    st = entry.stat()
                    mtime_utc = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).replace(tzinfo=None)
                    objs.append(StorageObjectMeta(
                        key=rel,
                        size_bytes=st.st_size,
                        last_modified_utc=mtime_utc,
                        etag=None,
                    ))
                except OSError:
                    continue
        objs.sort(key=lambda o: o.key)
        return objs

    def list_keys(self, prefix: str = "", suffix: str = "") -> List[str]:
        return [o.key for o in self.list_objects(prefix=prefix, suffix=suffix)]

    def delete(self, key: str) -> bool:
        target = self._safe_path(key)
        if target.exists() and target.is_file():
            target.unlink()
            return True
        return False

    def stat_prefix(self, prefix: str = "") -> Dict[str, Any]:
        objs = self.list_objects(prefix=prefix)
        total_bytes = sum(o.size_bytes for o in objs)
        oldest_mtime = min((o.last_modified_utc.replace(tzinfo=timezone.utc).timestamp() for o in objs), default=None)
        newest_mtime = max((o.last_modified_utc.replace(tzinfo=timezone.utc).timestamp() for o in objs), default=None)
        return {
            "prefix": prefix,
            "file_count": len(objs),
            "total_bytes": total_bytes,
            "oldest_mtime": oldest_mtime,
            "newest_mtime": newest_mtime,
        }
