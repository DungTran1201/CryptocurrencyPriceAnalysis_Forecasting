"""Tiered Hot State Cache: In-Process TTLCache + NATS JetStream KV (ADR-DP-005, IFC-DP-009).

Provides:
- In-process bounded TTL cache (< 10 MB cap)
- Distributed memory-backed NATS KV store (`StorageType.MEMORY`)
- Transparent cache fallback on NATS disconnect
- Observability counters for cache hits and misses
"""

from collections import OrderedDict
from datetime import datetime, timezone
import json
import threading
import time
from typing import Any, Dict, List, Optional

from backend.app.core.config import settings
from backend.app.core.logging import get_logger
from backend.app.core.metrics import CACHE_HITS_TOTAL, CACHE_MISSES_TOTAL

logger = get_logger("HotStateCache")


class TTLCache:
    """Bounded thread-safe in-process LRU/FIFO cache with per-item TTL expiration."""

    def __init__(self, maxsize: int = 1000, default_ttl_sec: float = 60.0):
        self.maxsize = maxsize
        self.default_ttl_sec = default_ttl_sec
        self._cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key not in self._cache:
                return None
            val, expire_at = self._cache[key]
            if time.monotonic() > expire_at:
                del self._cache[key]
                return None
            self._cache.move_to_end(key)
            return val

    def set(self, key: str, value: Any, ttl_sec: Optional[float] = None) -> None:
        ttl = ttl_sec if ttl_sec is not None else self.default_ttl_sec
        expire_at = time.monotonic() + ttl
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = (value, expire_at)
            while len(self._cache) > self.maxsize:
                self._cache.popitem(last=False)

    def delete(self, key: str) -> bool:
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._cache)


class HotStateCache:
    """Tiered cache combining local TTLCache with NATS JetStream KV in StorageType.MEMORY."""

    def __init__(
        self,
        kv_bucket_name: str = "hot_state",
        local_maxsize: int = 1000,
        local_ttl_sec: float = 30.0,
        js_context: Optional[Any] = None,
    ):
        self.kv_bucket_name = kv_bucket_name
        self._local = TTLCache(maxsize=local_maxsize, default_ttl_sec=local_ttl_sec)
        self._js = js_context
        self._kv: Any = None
        self._hits = 0
        self._misses = 0

    async def initialize_kv(self, js: Any, storage_type: Optional[Any] = None) -> bool:
        """Bind or create the NATS KeyValue bucket in StorageType.MEMORY."""
        self._js = js
        if not js:
            return False

        from nats.js.api import KeyValueConfig, StorageType

        st = storage_type or StorageType.MEMORY
        try:
            self._kv = await js.key_value(self.kv_bucket_name)
            logger.info("Bound to existing NATS KV bucket '%s'", self.kv_bucket_name)
            return True
        except Exception:
            pass

        try:
            cfg = KeyValueConfig(
                bucket=self.kv_bucket_name,
                history=1,
                ttl=300,
                storage=st,
                max_bytes=16 * 1024 * 1024,
            )
            self._kv = await js.create_key_value(cfg)
            logger.info("Created NATS KV bucket '%s' with StorageType.MEMORY", self.kv_bucket_name)
            return True
        except Exception as exc:
            logger.warning("Failed initializing NATS KV bucket '%s': %s", self.kv_bucket_name, exc)
            return False

    async def get_json(self, key: str) -> Optional[Dict[str, Any]]:
        """Retrieve JSON payload: checks local TTLCache first, then NATS KV."""
        # 1. Local Cache Check
        val = self._local.get(key)
        if val is not None:
            self._hits += 1
            CACHE_HITS_TOTAL.labels(cache="hot_state_local").inc()
            return val

        # 2. NATS KV Check
        if self._kv is not None:
            try:
                entry = await self._kv.get(key)
                if entry and entry.value:
                    data = json.loads(entry.value.decode("utf-8"))
                    self._local.set(key, data)
                    self._hits += 1
                    CACHE_HITS_TOTAL.labels(cache="hot_state_kv").inc()
                    return data
            except Exception:
                pass

        self._misses += 1
        CACHE_MISSES_TOTAL.labels(cache="hot_state").inc()
        return None

    async def put_json(
        self,
        key: str,
        value: Dict[str, Any],
        ttl_sec: Optional[float] = None,
    ) -> None:
        """Store JSON payload in both local TTLCache and NATS KV."""
        self._local.set(key, value, ttl_sec=ttl_sec)

        if self._kv is not None:
            try:
                payload = json.dumps(value).encode("utf-8")
                await self._kv.put(key, payload)
            except Exception as exc:
                logger.debug("Failed writing to NATS KV for key %s: %s", key, exc)

    async def delete(self, key: str) -> bool:
        """Delete key from local cache and NATS KV."""
        deleted = self._local.delete(key)
        if self._kv is not None:
            try:
                await self._kv.delete(key)
                deleted = True
            except Exception:
                pass
        return deleted

    def invalidate_local(self, key: Optional[str] = None) -> None:
        """Invalidate local process memory cache (called when bar closes)."""
        if key:
            self._local.delete(key)
        else:
            self._local.clear()

    def stats(self) -> Dict[str, Any]:
        """Return cache health and hit/miss statistics."""
        return {
            "local_size": self._local.size(),
            "local_maxsize": self._local.maxsize,
            "hits": self._hits,
            "misses": self._misses,
            "hit_ratio_pct": round(self._hits / (self._hits + self._misses) * 100.0, 1) if (self._hits + self._misses) > 0 else 0.0,
            "kv_connected": self._kv is not None,
            "kv_bucket": self.kv_bucket_name,
        }
