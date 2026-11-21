"""Comprehensive tests for Hot State Caching & Serving Gateway Bridge (WI-DP-08)."""

import asyncio
from datetime import datetime, timedelta, timezone
import time
import pytest

from backend.app.streaming.broker import InMemoryBroker
from backend.app.streaming.hot_state import HotStateCache, TTLCache
from backend.app.streaming.serving_bridge import ServingGatewayBridge


def test_ttl_cache_expiration_and_capacity():
    """Verify in-process TTLCache adheres to maxsize and per-item expiration."""
    cache = TTLCache(maxsize=3, default_ttl_sec=0.2)

    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)
    assert cache.get("a") == 1
    assert cache.get("b") == 2
    assert cache.get("c") == 3

    # Adding a 4th key evicts the LRU item ("a" was accessed first, then b, c -> LRU is "a")
    cache.set("d", 4)
    assert cache.size() == 3
    assert cache.get("a") is None
    assert cache.get("d") == 4

    # Wait for TTL expiration
    time.sleep(0.25)
    assert cache.get("b") is None
    assert cache.get("c") is None
    assert cache.get("d") is None


@pytest.mark.asyncio
async def test_hot_state_cache_local_and_stats():
    """Verify HotStateCache tracks hits, misses, and stats cleanly."""
    cache = HotStateCache(local_maxsize=10, local_ttl_sec=60.0)

    # Miss
    val = await cache.get_json("test.key.1")
    assert val is None

    # Put and Hit
    await cache.put_json("test.key.1", {"price": 95000.0, "symbol": "BTCUSDT"})
    val2 = await cache.get_json("test.key.1")
    assert val2 is not None
    assert val2["price"] == 95000.0

    stats = cache.stats()
    assert stats["hits"] >= 1
    assert stats["misses"] >= 1
    assert stats["local_size"] == 1

    # Invalidate
    cache.invalidate_local("test.key.1")
    assert await cache.get_json("test.key.1") is None


@pytest.mark.asyncio
async def test_serving_gateway_bridge_heartbeats_and_snapshots():
    """Verify ServingGatewayBridge caches snapshots and manages worker heartbeats."""
    broker = InMemoryBroker()
    await broker.connect()

    bridge = ServingGatewayBridge(broker=broker)

    # 1. Snapshot publication
    snap = {"symbol": "ETHUSDT", "price": 3500.0, "timeframe": "1m"}
    await bridge.publish_market_snapshot("ETHUSDT", snap)

    cached_snap = await bridge.hot_state.get_json("market.snapshot.ETHUSDT")
    assert cached_snap is not None
    assert cached_snap["price"] == 3500.0

    # 2. Worker Heartbeat publication
    await bridge.publish_heartbeat(
        role="stream_worker",
        worker_id="stream-proc-101",
        data={"status": "HEALTHY", "lag": 0},
    )

    heartbeats = bridge.get_worker_heartbeats()
    assert len(heartbeats) == 1
    assert heartbeats[0]["worker_id"] == "stream-proc-101"
    assert heartbeats[0]["status"] == "HEALTHY"

    # 3. Simulated stale heartbeat eviction
    stale_time = (datetime.now(timezone.utc) - timedelta(seconds=45)).isoformat()
    bridge._heartbeats["stale-worker"] = {
        "role": "workflow_worker",
        "worker_id": "stale-worker",
        "timestamp": stale_time,
    }

    # Should filter out the stale worker
    active = bridge.get_worker_heartbeats()
    assert not any(h["worker_id"] == "stale-worker" for h in active)

    await broker.close()
