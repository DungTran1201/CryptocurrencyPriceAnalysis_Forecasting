"""Comprehensive tests for Ingestion, Canonical Schemas, Bounded Queue, and Broker Resilience (WI-DP-03)."""

import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import pytest

from backend.app.schemas.events import CanonicalKlineEvent
from backend.app.streaming.normalizer import normalize_binance_ws_payload
from backend.app.streaming.binance_ws import BinanceWebSocketIngestor
from backend.app.streaming.broker import InMemoryBroker
from backend.app.streaming.producer import BoundedEventProducer


def test_canonical_kline_validation_ohlc_and_dates():
    """Verify CanonicalKlineEvent rejects invalid timeframes, reversed timestamps, and broken OHLC."""
    t0 = datetime(2025, 1, 1, 12, 0, 0)
    t1 = datetime(2025, 1, 1, 12, 1, 0)

    # Valid event
    evt = CanonicalKlineEvent(
        event_id="evt_valid_01",
        symbol="BTCUSDT",
        timeframe="1m",
        open_time=t0,
        close_time=t1,
        open=95000.0,
        high=95200.0,
        low=94900.0,
        close=95100.0,
        volume=12.5,
        is_closed=True,
        event_time=t1,
        ingestion_time=t1,
    )
    assert evt.symbol == "BTCUSDT"
    assert evt.timeframe == "1m"

    # 1. Reversed dates (open_time > close_time) -> Must raise ValueError
    with pytest.raises(ValueError, match="open_time must not exceed close_time"):
        CanonicalKlineEvent(
            event_id="evt_bad_dates",
            symbol="BTCUSDT",
            timeframe="1m",
            open_time=t1,
            close_time=t0,
            open=95000.0,
            high=95200.0,
            low=94900.0,
            close=95100.0,
            volume=12.5,
            is_closed=True,
            event_time=t1,
            ingestion_time=t1,
        )

    # 2. Unsupported timeframe -> Must raise ValueError
    with pytest.raises(ValueError, match="Unsupported timeframe"):
        CanonicalKlineEvent(
            event_id="evt_bad_tf",
            symbol="BTCUSDT",
            timeframe="7m",
            open_time=t0,
            close_time=t1,
            open=95000.0,
            high=95200.0,
            low=94900.0,
            close=95100.0,
            volume=12.5,
            is_closed=True,
            event_time=t1,
            ingestion_time=t1,
        )

    # 3. Broken OHLC geometry (low > high) -> Must raise ValueError
    with pytest.raises(ValueError, match="OHLC geometry invalid"):
        CanonicalKlineEvent(
            event_id="evt_bad_ohlc",
            symbol="BTCUSDT",
            timeframe="1m",
            open_time=t0,
            close_time=t1,
            open=95000.0,
            high=94000.0,
            low=96000.0,
            close=95100.0,
            volume=12.5,
            is_closed=True,
            event_time=t1,
            ingestion_time=t1,
        )


@pytest.mark.asyncio
async def test_bounded_producer_shutdown_spooling(tmp_path: Path, monkeypatch):
    """Verify that undrained events during shutdown spill to producer_spool.jsonl without loss."""
    monkeypatch.setattr("backend.app.storage.get_data_root", lambda: tmp_path)

    broker = InMemoryBroker()
    await broker.connect()

    # Create a producer with maxsize=10
    producer = BoundedEventProducer(broker=broker, maxsize=10)
    await producer.start()

    # Enqueue 3 items
    for i in range(3):
        await producer.enqueue(
            subject=f"market.test.{i}",
            payload=f'{{"msg": "data_{i}"}}'.encode("utf-8"),
            msg_id=f"spool_test_{i}",
            symbol="BTCUSDT",
            stream_label="test",
        )

    # Stop with drain_timeout=0.0 to simulate immediate shutdown with items still in queue
    await producer.stop(drain_timeout=0.0)

    # Verify producer spool file exists and contains spooled items
    spool_file = tmp_path / "dlq" / "producer_spool.jsonl"
    assert spool_file.exists()
    lines = spool_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 1
    record = json.loads(lines[0])
    assert "market.test." in record["subject"]
    assert "data_" in record["payload"]

    await broker.close()


@pytest.mark.asyncio
async def test_binance_ws_single_flight_gap_heal():
    """Verify that concurrent reconnects do not trigger duplicate gap heal executions."""
    broker = InMemoryBroker()
    producer = BoundedEventProducer(broker=broker, maxsize=50)

    heal_call_count = 0

    async def mock_gap_heal():
        nonlocal heal_call_count
        heal_call_count += 1
        await asyncio.sleep(0.05)

    ingestor = BinanceWebSocketIngestor(
        producer=producer,
        symbols=["BTCUSDT"],
        streams=["kline_1m"],
        on_reconnect_gap_heal=mock_gap_heal,
    )

    # Concurrently trigger two gap heals
    t1 = asyncio.create_task(ingestor._safe_gap_heal())
    t2 = asyncio.create_task(ingestor._safe_gap_heal())
    await asyncio.gather(t1, t2)

    # Single-flight lock should ensure only 1 executed
    assert heal_call_count == 1
