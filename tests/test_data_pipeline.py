"""Automated tests for data ingestion, timestamp normalization, closed candles, duplicate prevention, and gap detection."""

from datetime import datetime, timedelta
import pytest
from sqlalchemy import select, func

from backend.app.services.sync_service import (
    BinanceSyncService,
    ms_to_datetime,
    datetime_to_ms,
    get_interval_delta
)
from backend.app.models.market import Kline, SyncCheckpoint


def generate_mock_kline_raw(start_ms: int, close: float = 65000.0, step_ms: int = 3600000):
    """Generate mock Binance Kline array: [open_time, open, high, low, close, volume, close_time, ...]"""
    end_ms = start_ms + step_ms - 1
    return [
        start_ms,
        str(close - 10),
        str(close + 50),
        str(close - 30),
        str(close),
        "125.5",
        end_ms,
        "8157500.0",
        450,
        "60.2",
        "3913000.0",
        "0"
    ]


@pytest.mark.asyncio
async def test_kline_payload_parsing_and_normalization():
    """Verify parsing normalizes timestamps to UTC, extracts numeric fields, and sets closed state."""
    service = BinanceSyncService()
    base_ms = 1719792000000  # 2024-07-01 00:00:00 UTC
    raw_klines = [
        generate_mock_kline_raw(base_ms, close=62776.0),
        generate_mock_kline_raw(base_ms + 3600000, close=62850.0),
    ]

    parsed = service.parse_kline_payload("BTCUSDT", "1h", raw_klines)
    assert len(parsed) == 2
    assert parsed[0]["symbol"] == "BTCUSDT"
    assert parsed[0]["timeframe"] == "1h"
    assert parsed[0]["close"] == 62776.0
    assert parsed[0]["open"] == 62766.0
    assert isinstance(parsed[0]["open_time"], datetime)
    assert parsed[0]["is_closed"] is True


@pytest.mark.asyncio
async def test_duplicate_prevention_idempotency(test_db):
    """Ensure saving identical candles multiple times does not create duplicates."""
    service = BinanceSyncService()
    base_ms = 1719792000000
    raw_klines = [
        generate_mock_kline_raw(base_ms, close=60000.0),
        generate_mock_kline_raw(base_ms + 3600000, close=60500.0),
        generate_mock_kline_raw(base_ms + 7200000, close=61000.0),
    ]

    parsed = service.parse_kline_payload("BTCUSDT", "1h", raw_klines)
    
    # First save: all 3 should be added
    added_1 = await service.save_klines_idempotent(test_db, parsed)
    assert added_1 == 3

    # Second save with exact same data: 0 should be added
    added_2 = await service.save_klines_idempotent(test_db, parsed)
    assert added_2 == 0

    # Total in DB should still be 3
    count_stmt = select(func.count(Kline.id)).where(Kline.symbol == "BTCUSDT")
    res = await test_db.execute(count_stmt)
    assert res.scalar() == 3


@pytest.mark.asyncio
async def test_gap_detection(test_db):
    """Verify that gaps in the time-series are accurately detected."""
    service = BinanceSyncService()
    start_dt = datetime(2024, 7, 1, 0, 0, 0)
    delta = timedelta(hours=1)

    # Insert candles with a deliberate 3-hour gap (e.g. hour 0, 1, then jump to hour 5, 6)
    timestamps = [
        start_dt,
        start_dt + delta,
        start_dt + (delta * 5),
        start_dt + (delta * 6),
    ]

    klines = [
        Kline(
            symbol="ETHUSDT",
            timeframe="1h",
            open_time=t,
            close_time=t + delta - timedelta(milliseconds=1),
            open=3000.0,
            high=3050.0,
            low=2990.0,
            close=3020.0,
            volume=50.0,
            is_closed=True
        )
        for t in timestamps
    ]
    test_db.add_all(klines)
    await test_db.flush()

    gaps = await service.detect_gaps(test_db, "ETHUSDT", "1h")
    assert len(gaps) == 1
    gap_start, gap_end = gaps[0]
    # Expected gap between hour 2 and hour 4
    assert gap_start == start_dt + (delta * 2)
    assert gap_end == start_dt + (delta * 4)


def test_timeframe_delta_helpers():
    """Verify timeframe conversion mapping."""
    assert get_interval_delta("1m") == timedelta(minutes=1)
    assert get_interval_delta("15min") == timedelta(minutes=15)
    assert get_interval_delta("1h") == timedelta(hours=1)
    assert get_interval_delta("4h") == timedelta(hours=4)
    assert get_interval_delta("1d") == timedelta(days=1)


def test_datetime_and_ms_conversions():
    """Verify roundtrip conversion between milliseconds and UTC datetime."""
    original_dt = datetime(2024, 8, 15, 12, 30, 0)
    ms = datetime_to_ms(original_dt)
    reconstructed_dt = ms_to_datetime(ms)
    assert original_dt == reconstructed_dt
