"""Tests for Lakehouse Storage, Manifests, Schema Validation & Sync Service (WI-DP-04)."""

from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.lake import LakeManifestFile, LakeSnapshot
from backend.app.models.market import Kline, SyncCheckpoint
from backend.app.services.sync_service import BinanceSyncService, datetime_to_ms, ms_to_datetime
from backend.app.storage.local import LocalStorageBackend
from backend.app.storage.medallion import (
    GOLD_ANALYTICS_SCHEMA,
    GOLD_FEATURE_SCHEMA,
    SILVER_KLINE_SCHEMA,
    SILVER_TRADE_SCHEMA,
    MedallionStorageManager,
    merge_kline_records,
)


def test_arrow_schemas_completeness():
    """Verify PyArrow schemas match specification strictly."""
    kline_field_names = [f.name for f in SILVER_KLINE_SCHEMA]
    assert "symbol" in kline_field_names
    assert "timeframe" in kline_field_names
    assert "open_time" in kline_field_names
    assert "close_time" in kline_field_names
    assert "open" in kline_field_names
    assert "high" in kline_field_names
    assert "low" in kline_field_names
    assert "close" in kline_field_names
    assert "volume" in kline_field_names
    assert "quote_asset_volume" in kline_field_names
    assert "number_of_trades" in kline_field_names
    assert "taker_buy_base_asset_volume" in kline_field_names
    assert "taker_buy_quote_asset_volume" in kline_field_names
    assert "is_closed" in kline_field_names

    trade_field_names = [f.name for f in SILVER_TRADE_SCHEMA]
    assert "symbol" in trade_field_names
    assert "agg_trade_id" in trade_field_names
    assert "price" in trade_field_names
    assert "quantity" in trade_field_names
    assert "is_buyer_maker" in trade_field_names
    assert "trade_time" in trade_field_names

    assert len(GOLD_ANALYTICS_SCHEMA) >= 10
    assert len(GOLD_FEATURE_SCHEMA) >= 10


def test_merge_kline_records_open_closed_promotion():
    """Verify in-memory merge logic promotes open to closed and rejects downgrades."""
    t0 = datetime(2025, 1, 1, 12, 0, 0)
    t1 = datetime(2025, 1, 1, 12, 1, 0)

    forming = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "open_time": t0,
        "close_time": t1,
        "open": 90000.0,
        "high": 90100.0,
        "low": 89900.0,
        "close": 90050.0,
        "volume": 5.0,
        "is_closed": False,
    }

    closed = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "open_time": t0,
        "close_time": t1,
        "open": 90000.0,
        "high": 90200.0,
        "low": 89900.0,
        "close": 90150.0,
        "volume": 12.0,
        "is_closed": True,
    }

    # Forming + Closed -> Closed wins
    winner = merge_kline_records(forming, closed)
    assert winner["is_closed"] is True
    assert winner["close"] == 90150.0
    assert winner["volume"] == 12.0

    # Closed + Forming (downgrade) -> Closed stays
    forming_late = dict(forming)
    forming_late["close"] = 88000.0
    winner2 = merge_kline_records(closed, forming_late)
    assert winner2["is_closed"] is True
    assert winner2["close"] == 90150.0


@pytest.mark.asyncio
async def test_sql_upsert_promotion_matrix(test_db: AsyncSession):
    """Verify database-level open->closed promotion and downgrade rejection."""
    sync_svc = BinanceSyncService()
    t0 = datetime(2025, 6, 1, 0, 0, 0)
    t1 = datetime(2025, 6, 1, 0, 1, 0)

    # 1. Insert forming candle
    await sync_svc.upsert_klines_sql(
        test_db,
        [
            {
                "symbol": "BTCUSDT",
                "timeframe": "1m",
                "open_time": t0,
                "close_time": t1,
                "open": 65000.0,
                "high": 65100.0,
                "low": 64900.0,
                "close": 65050.0,
                "volume": 10.0,
                "quote_asset_volume": 650500.0,
                "number_of_trades": 100,
                "taker_buy_base_asset_volume": 5.0,
                "taker_buy_quote_asset_volume": 325250.0,
                "is_closed": False,
            }
        ],
    )
    await test_db.commit()

    kline = (
        await test_db.execute(
            select(Kline).where(
                Kline.symbol == "BTCUSDT",
                Kline.timeframe == "1m",
                Kline.open_time == t0,
            )
        )
    ).scalar_one()
    assert kline.is_closed is False
    assert kline.close == 65050.0

    # 2. Ingest closed candle for same timestamp -> Must promote
    await sync_svc.upsert_klines_sql(
        test_db,
        [
            {
                "symbol": "BTCUSDT",
                "timeframe": "1m",
                "open_time": t0,
                "close_time": t1,
                "open": 65000.0,
                "high": 65200.0,
                "low": 64900.0,
                "close": 65150.0,
                "volume": 25.0,
                "quote_asset_volume": 1628750.0,
                "number_of_trades": 250,
                "taker_buy_base_asset_volume": 15.0,
                "taker_buy_quote_asset_volume": 977250.0,
                "is_closed": True,
            }
        ],
    )
    await test_db.commit()

    await test_db.refresh(kline)
    assert kline.is_closed is True
    assert kline.close == 65150.0
    assert kline.volume == 25.0

    # 3. Ingest forming candle again -> Must NOT overwrite closed candle
    await sync_svc.upsert_klines_sql(
        test_db,
        [
            {
                "symbol": "BTCUSDT",
                "timeframe": "1m",
                "open_time": t0,
                "close_time": t1,
                "open": 65000.0,
                "high": 65300.0,
                "low": 64900.0,
                "close": 63000.0,
                "volume": 5.0,
                "is_closed": False,
            }
        ],
    )
    await test_db.commit()

    await test_db.refresh(kline)
    assert kline.is_closed is True
    assert kline.close == 65150.0
    assert kline.volume == 25.0


@pytest.mark.asyncio
async def test_detect_gaps_interior_and_trailing(test_db: AsyncSession):
    """Verify gap detection accurately finds missing internal intervals."""
    sync_svc = BinanceSyncService()
    base_time = datetime(2025, 1, 1, 0, 0, 0)

    # Insert hours 0, 1, 2, skip 3, insert 4, 5
    candles = []
    for h in [0, 1, 2, 4, 5]:
        t = base_time + timedelta(hours=h)
        candles.append(
            {
                "symbol": "ETHUSDT",
                "timeframe": "1h",
                "open_time": t,
                "close_time": t + timedelta(hours=1),
                "open": 3000.0,
                "high": 3050.0,
                "low": 2980.0,
                "close": 3020.0,
                "volume": 50.0,
                "is_closed": True,
            }
        )
    await sync_svc.upsert_klines_sql(test_db, candles)
    await test_db.commit()

    gaps = await sync_svc.detect_gaps(test_db, "ETHUSDT", "1h", include_trailing=False)
    assert len(gaps) == 1
    gap_start, gap_end = gaps[0]
    expected_missing = base_time + timedelta(hours=3)
    assert gap_start == expected_missing
    assert gap_end == expected_missing


@pytest.mark.asyncio
async def test_silver_trade_parquet_and_manifest(test_db: AsyncSession, tmp_path):
    """Verify Silver trades storage and SQL LakeSnapshot manifest registration."""
    backend = LocalStorageBackend(root_dir=tmp_path / "lake")
    medallion = MedallionStorageManager(backend=backend)

    trades = [
        {
            "symbol": "SOLUSDT",
            "agg_trade_id": 10001 + i,
            "price": 150.0 + i * 0.1,
            "quantity": 2.5 + i,
            "quote_quantity": (150.0 + i * 0.1) * (2.5 + i),
            "is_buyer_maker": (i % 2 == 0),
            "trade_time": datetime(2025, 7, 10, 10, 0, i, tzinfo=timezone.utc),
            "event_time": datetime(2025, 7, 10, 10, 0, i, tzinfo=timezone.utc),
            "source": "binance_ws",
        }
        for i in range(10)
    ]

    res = medallion.write_silver_trades("SOLUSDT", trades)
    assert res["records"] == 10
    assert len(res["files"]) == 1

    # Commit snapshot manifest to SQL
    snap = await medallion.commit_manifest(
        test_db,
        dataset_id="silver_trades",
        new_file_metas=res["file_metas"],
        schema_version="1.0.0",
        schema_hash="fake_hash_trades",
        symbol="SOLUSDT",
    )
    await test_db.commit()
    assert snap.total_rows == 10
    assert snap.status == "ACTIVE"

    # Verify queryable from DB
    files = (
        await test_db.execute(
            select(LakeManifestFile).where(LakeManifestFile.snapshot_id == snap.snapshot_id)
        )
    ).scalars().all()
    assert len(files) == 1
    assert files[0].row_count == 10
    assert files[0].partition_symbol == "SOLUSDT"
