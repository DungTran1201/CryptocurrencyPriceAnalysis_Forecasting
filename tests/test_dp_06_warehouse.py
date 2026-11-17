"""Comprehensive tests for Persistent DuckDB Warehouse, Star Schema & Snapshot Swap (WI-DP-06)."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from backend.app.services.warehouse_service import WarehouseService
from backend.app.storage.local import LocalStorageBackend
from backend.app.storage.medallion import MedallionStorageManager
from backend.app.storage.warehouse import DDL_STATEMENTS, DuckDBWarehouseEngine


def test_duckdb_star_schema_ddl(tmp_path: Path):
    """Verify that all Star Schema tables and dimensions exist and can be queried."""
    engine = DuckDBWarehouseEngine(warehouse_dir=tmp_path / "warehouse")
    with engine.open_reader() as conn:
        tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
        assert "dim_symbols" in tables
        assert "dim_time" in tables
        assert "fact_market_klines_1m" in tables
        assert "fact_market_aggtrades" in tables
        assert "fact_model_forecasts" in tables
        assert "agg_kline_daily_marts" in tables


def test_warehouse_snapshot_build_and_atomic_swap(tmp_path: Path):
    """Verify building DuckDB warehouse from Silver Parquet and promoting versioned snapshots."""
    lake_dir = tmp_path / "lake"
    backend = LocalStorageBackend(root_dir=lake_dir)
    medallion = MedallionStorageManager(backend=backend)

    t0 = datetime(2025, 3, 1, 0, 0, 0)
    klines = [
        {
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "open_time": t0 + timedelta(minutes=i),
            "close_time": t0 + timedelta(minutes=i + 1),
            "open": 85000.0 + i * 5,
            "high": 85050.0 + i * 5,
            "low": 84950.0 + i * 5,
            "close": 85010.0 + i * 5,
            "volume": 2.0,
            "quote_asset_volume": 170020.0,
            "number_of_trades": 15,
            "taker_buy_base_asset_volume": 1.0,
            "taker_buy_quote_asset_volume": 85010.0,
            "is_closed": True,
            "source": "binance_ws",
        }
        for i in range(120)
    ]
    medallion.write_silver_klines("BTCUSDT", "1m", klines)

    wh_dir = tmp_path / "warehouse"
    engine = DuckDBWarehouseEngine(warehouse_dir=wh_dir)

    # Build Snapshot v1
    meta1 = engine.build_snapshot(silver_root=lake_dir / "silver")
    assert meta1["version"] == 1
    assert meta1["klines_count"] == 120
    assert meta1["daily_marts_count"] >= 1

    # Readers can query active snapshot
    res = engine.query("SELECT count(*) as cnt FROM fact_market_klines_1m")
    assert res[0]["cnt"] == 120

    marts = engine.query("SELECT symbol, volume, trade_count FROM agg_kline_daily_marts")
    assert len(marts) >= 1
    assert marts[0]["symbol"] == "BTCUSDT"
    assert marts[0]["volume"] == 240.0

    # Build Snapshot v2 (incremental promotion)
    meta2 = engine.build_snapshot(silver_root=lake_dir / "silver")
    assert meta2["version"] == 2
    assert Path(meta2["path"]).name == "dw-v2.duckdb"

    active_meta = engine.get_active_manifest()
    assert active_meta is not None
    assert active_meta["version"] == 2


def test_concurrent_read_only_access(tmp_path: Path):
    """Verify that multiple concurrent read_only connections do not lock or throw IOException on Windows."""
    wh_dir = tmp_path / "warehouse"
    engine = DuckDBWarehouseEngine(warehouse_dir=wh_dir)
    engine.build_snapshot()

    # Open reader 1
    with engine.open_reader() as conn1:
        res1 = conn1.execute("SELECT 1 as val").fetchone()[0]
        assert res1 == 1

        # Open reader 2 while reader 1 is still open
        with engine.open_reader() as conn2:
            res2 = conn2.execute("SELECT 2 as val").fetchone()[0]
            assert res2 == 2


def test_warehouse_service_facade_and_query_validation(tmp_path: Path):
    """Verify WarehouseService queries, status reporting, and SQL mutation rejection."""
    wh_dir = tmp_path / "warehouse"
    engine = DuckDBWarehouseEngine(warehouse_dir=wh_dir)
    svc = WarehouseService(engine=engine)

    status_before = svc.get_status()
    assert status_before["status"] == "UNINITIALIZED"

    engine.build_snapshot()
    status_after = svc.get_status()
    assert status_after["status"] == "ACTIVE"
    assert status_after["version"] == 1

    # Permitted SELECT query
    rows = svc.query_star_schema("SELECT 42 AS answer")
    assert rows[0]["answer"] == 42

    # Mutating query rejected by safety check
    with pytest.raises(ValueError, match="Only SELECT queries are permitted"):
        svc.query_star_schema("DROP TABLE dim_symbols")
