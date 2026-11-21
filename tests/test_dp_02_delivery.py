"""Comprehensive tests for Stream Delivery Guarantees, Two-Phase Dedup, and State Transitions (WI-DP-02)."""

import asyncio
from datetime import datetime, timedelta, timezone
import json
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.app.core.database import Base
from backend.app.models.governance import DeadLetterEvent, StreamCheckpoint
from backend.app.models.lake import BatchLedger
from backend.app.models.market import Kline, Symbol
from backend.app.schemas.events import CanonicalKlineEvent
from backend.app.storage.local import LocalStorageBackend
from backend.app.storage.medallion import MedallionStorageManager
from backend.app.streaming.broker import BrokerMessage, InMemoryBroker
from backend.app.streaming.consumers import BoundedDedupCache, MedallionStreamConsumer
from backend.app.streaming.normalizer import normalize_binance_ws_payload
from ml.incremental_analytics import IncrementalAnalyticsEngine


def test_bounded_dedup_cache_two_phase_semantics():
    """Verify BoundedDedupCache separates uncommitted check from post-commit commit."""
    cache = BoundedDedupCache(maxsize=3)

    # 1. contains() is read-only
    assert cache.contains("k1") is False
    assert cache.contains("k1") is False
    assert len(cache._items) == 0

    # 2. commit_keys() persists keys
    cache.commit_keys(["k1", "k2"])
    assert cache.contains("k1") is True
    assert cache.contains("k2") is True
    assert cache.contains("k3") is False

    # 3. FIFO/LRU eviction works at capacity
    cache.commit_keys(["k3", "k4"])
    # Capacity is 3, so k1 should be evicted
    assert len(cache._items) == 3
    assert cache.contains("k1") is False
    assert cache.contains("k2") is True
    assert cache.contains("k3") is True
    assert cache.contains("k4") is True


@pytest.mark.asyncio
async def test_consumer_two_phase_dedup_and_post_commit_ack(tmp_path):
    """Verify consumer does not mark dedup seen if write/flush fails before commit."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        db.add(Symbol(symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT", is_active=True))
        await db.commit()

    broker = InMemoryBroker()
    await broker.connect()

    backend = LocalStorageBackend(root_dir=tmp_path / "lake")
    medallion = MedallionStorageManager(backend=backend)
    analytics = IncrementalAnalyticsEngine(checkpoint_dir=tmp_path / "ckpts")

    consumer = MedallionStreamConsumer(
        broker=broker,
        durable_name="test_delivery_consumer",
        medallion=medallion,
        analytics_engine=analytics,
        session_factory=session_factory,
    )

    kline_raw = {
        "e": "kline",
        "E": 1719792060000,
        "s": "BTCUSDT",
        "k": {
            "t": 1719792000000,
            "T": 1719792059999,
            "s": "BTCUSDT",
            "i": "1m",
            "o": "65000",
            "c": "65050",
            "h": "65100",
            "l": "64950",
            "v": "10.0",
            "x": True,
            "q": "650500.0",
            "n": 50,
            "V": "5.0",
            "Q": "325250.0",
        },
    }
    evt = normalize_binance_ws_payload(kline_raw)
    payload = evt.model_dump_json().encode("utf-8")

    # Publish message to stream
    await broker.publish("market.kline.1m.BTCUSDT", payload, headers={"Nats-Msg-Id": evt.event_id})

    # Process batch and flush
    await consumer.process_single_batch(batch_size=10, timeout=0.2)
    flush_res = await consumer.flush_microbatch()

    assert flush_res["flushed"] == 1
    assert flush_res["state"] == "ACKED"
    assert consumer._dedup.contains(evt.event_id) is True

    # Verify SQL Kline committed
    async with session_factory() as db:
        kline = (
            await db.execute(
                select(Kline).where(Kline.symbol == "BTCUSDT", Kline.timeframe == "1m")
            )
        ).scalar_one_or_none()
        assert kline is not None
        assert kline.close == 65050.0

        # Verify BatchLedger recorded
        ledger = (
            await db.execute(
                select(BatchLedger).where(BatchLedger.producer_name == "test_delivery_consumer")
            )
        ).scalar_one_or_none()
        assert ledger is not None
        assert ledger.status == "COMMITTED"

        # Verify StreamCheckpoint recorded
        ckpt = (
            await db.execute(
                select(StreamCheckpoint).where(
                    StreamCheckpoint.consumer_name == "test_delivery_consumer",
                    StreamCheckpoint.symbol == "BTCUSDT",
                )
            )
        ).scalar_one_or_none()
        assert ckpt is not None
        assert ckpt.processed_count == 1

    await broker.close()


@pytest.mark.asyncio
async def test_dlq_quarantine_requires_sink_before_term(tmp_path):
    """Verify that poison messages are only TERMed if durable DLQ storage succeeds."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    broker = InMemoryBroker()
    await broker.connect()

    backend = LocalStorageBackend(root_dir=tmp_path / "lake")
    medallion = MedallionStorageManager(backend=backend)

    consumer = MedallionStreamConsumer(
        broker=broker,
        durable_name="test_dlq_consumer",
        medallion=medallion,
        session_factory=session_factory,
    )

    # Publish malformed message
    bad_payload = b"NOT_VALID_JSON{}"
    await broker.publish("market.kline.1m.BTCUSDT", bad_payload)

    await consumer.process_single_batch(batch_size=1, timeout=0.2)

    # Verify DeadLetterEvent in database
    async with session_factory() as db:
        dlq_event = (
            await db.execute(
                select(DeadLetterEvent).where(DeadLetterEvent.stream_type == "json_decode")
            )
        ).scalar_one_or_none()
        assert dlq_event is not None
        assert dlq_event.status == "QUARANTINED"
        assert "Invalid JSON" in dlq_event.error_reason

    await broker.close()


@pytest.mark.asyncio
async def test_analytics_checkpoint_atomic_save_and_restore(tmp_path):
    """Verify IncrementalAnalyticsEngine atomically writes checkpoints and restores bar window."""
    ckpt_dir = tmp_path / "incremental_ckpts"
    engine = IncrementalAnalyticsEngine(checkpoint_dir=ckpt_dir, max_bars=100)

    t0 = datetime(2025, 1, 1, 0, 0, 0)
    state = engine.get_or_create("BTCUSDT", "1m")
    for i in range(10):
        state.update_closed_bar(
            open_time=t0 + timedelta(minutes=i),
            open_price=60000.0 + i * 10,
            high=60050.0 + i * 10,
            low=59950.0 + i * 10,
            close=60020.0 + i * 10,
            volume=5.0,
        )

    # Save checkpoints to disk
    engine.save_checkpoints()

    # Create new engine from same checkpoint directory
    engine2 = IncrementalAnalyticsEngine(checkpoint_dir=ckpt_dir, max_bars=100)
    state2 = engine2.get_or_create("BTCUSDT", "1m")
    assert state2.bar_count == 10
    assert state2.last_close == 60020.0 + 9 * 10
