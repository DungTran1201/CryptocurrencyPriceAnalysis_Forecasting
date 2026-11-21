"""Tests for Medallion Storage (Bronze/Silver/Gold), DuckDB, Governance Catalog, Lineage & Retention."""

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import time
import pandas as pd
import pytest

from backend.app.models.governance import DataCatalogEntry, DataLineageEdge
from backend.app.models.market import Kline, Symbol
from backend.app.services.governance_service import GovernanceService
from backend.app.services.pipeline_service import PipelineService
from backend.app.storage.local import LocalStorageBackend
from backend.app.storage.medallion import MedallionStorageManager
from sqlalchemy import select


def test_local_storage_security_and_atomic_write(tmp_path: Path):
    """Verify path traversal guard and atomic write/read/list/delete."""
    store = LocalStorageBackend(tmp_path)
    with pytest.raises(ValueError):
        store.write_bytes("../../escape.txt", b"bad")

    n = store.write_bytes("bronze/test/part.bin", b"hello-lakehouse")
    assert n == 15
    assert store.exists("bronze/test/part.bin")
    assert store.read_bytes("bronze/test/part.bin") == b"hello-lakehouse"
    assert store.list_keys("bronze") == ["bronze/test/part.bin"]
    assert store.delete("bronze/test/part.bin") is True


def test_medallion_bronze_silver_gold_duckdb_roundtrip(tmp_path: Path):
    """Verify Bronze zstd JSONL, Silver Parquet dedup/compaction, and Gold DuckDB Parquet queries."""
    store = LocalStorageBackend(tmp_path)
    med = MedallionStorageManager(store)

    # 1. Bronze zstd JSONL
    b_res = med.write_bronze_batch("kline_1m", "BTCUSDT", [{"event_id": "e1", "price": 65000}])
    assert b_res["records"] == 1
    assert b_res["bytes"] > 0
    read_b = med.read_bronze_records(limit=10)
    assert len(read_b) == 1 and read_b[0]["event_id"] == "e1"

    # 2. Silver Parquet Klines + Idempotent Dedup
    t0 = datetime(2026, 1, 1, 0, 0, 0)
    bars = [
        {
            "symbol": "BTCUSDT",
            "timeframe": "1h",
            "open_time": t0 + timedelta(hours=i),
            "close_time": t0 + timedelta(hours=i + 1) - timedelta(seconds=1),
            "open": 50000.0 + i * 10,
            "high": 50060.0 + i * 10,
            "low": 49940.0 + i * 10,
            "close": 50020.0 + i * 10,
            "volume": 100.0 + i,
            "is_closed": True,
        }
        for i in range(65)
    ]
    s_res1 = med.write_silver_klines("BTCUSDT", "1h", bars)
    s_res2 = med.write_silver_klines("BTCUSDT", "1h", bars[:10])  # Re-write duplicates
    assert s_res1["records"] == 65
    assert s_res2["records"] == 10

    silver_df = med.read_silver_klines_df("BTCUSDT", "1h", limit=100)
    assert len(silver_df) == 65  # Deduplicated strictly to 65 rows via DuckDB read_parquet

    # 3. Silver Trade Partition Compaction (>= 6 fragments)
    for batch_idx in range(6):
        med.write_silver_trades(
            "BTCUSDT",
            [
                {
                    "symbol": "BTCUSDT",
                    "agg_trade_id": batch_idx * 10 + j,
                    "price": 60000.0 + j,
                    "quantity": 0.1,
                    "is_buyer_maker": False,
                    "trade_time": t0 + timedelta(seconds=batch_idx * 10 + j),
                }
                for j in range(5)
            ],
        )
    trade_files = store.list_keys("silver/source=binance/event_type=agg_trades", ".parquet")
    assert len(trade_files) == 1
    assert "compacted-" in trade_files[0]

    # 4. Gold Materialization & DuckDB Read
    gold_res = med.materialize_gold_marts("BTCUSDT", "1h", silver_df)
    assert gold_res["analytics_rows"] == 65
    assert gold_res["feature_rows"] == 65
    marts_rows = med.read_gold_dataset("analytics_marts", symbol="BTCUSDT", limit=20)
    assert len(marts_rows) == 20
    assert "atr_14" in marts_rows[0] and "vwap" in marts_rows[0]


@pytest.mark.asyncio
async def test_pipeline_real_medallion_and_governance_lineage(test_db, tmp_path: Path, monkeypatch):
    """Verify PipelineService executes real Gold/Feature materialization and updates Catalog & Lineage."""
    from backend.app.core.config import settings
    monkeypatch.setattr(settings.storage, "data_dir", str(tmp_path))

    test_db.add(Symbol(symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT", is_active=True))
    t0 = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=65)
    candles = [
        Kline(
            symbol="BTCUSDT",
            timeframe="1h",
            open_time=t0 + timedelta(hours=i),
            close_time=t0 + timedelta(hours=i + 1) - timedelta(seconds=1),
            open=60000.0 + i * 5,
            high=60040.0 + i * 5,
            low=59960.0 + i * 5,
            close=60015.0 + i * 5,
            volume=40.0 + i,
            is_closed=True,
        )
        for i in range(60)
    ]
    test_db.add_all(candles)
    await test_db.commit()

    run = await PipelineService.execute_medallion_pipeline(
        test_db,
        symbol="BTCUSDT",
        timeframe="1h",
        trigger_type="RECOMPUTE",
        skip_network_ingest=True,
    )
    assert run.status == "SUCCESS"

    details = await PipelineService.get_run_details(test_db, run.id)
    assert details is not None
    tasks_by_name = {t["task_name"]: t for t in details["tasks"]}
    assert tasks_by_name["build_gold_marts"]["status"] == "SUCCESS"
    assert tasks_by_name["build_gold_marts"]["records_processed"] == 60
    assert tasks_by_name["extract_features"]["status"] == "SUCCESS"
    assert tasks_by_name["extract_features"]["records_processed"] == 60

    # Verify Catalog & Lineage persisted
    catalog = await GovernanceService.list_catalog(test_db)
    cat_map = {c["dataset_id"]: c for c in catalog}
    assert cat_map["gold_analytics_marts"]["row_count"] == 60
    assert cat_map["gold_feature_sets"]["row_count"] == 60

    lineage_edges = (await test_db.execute(select(DataLineageEdge))).scalars().all()
    assert len(lineage_edges) >= 3

    # Verify retention pruning cleans expired files
    old_file = tmp_path / "bronze" / "old.jsonl.zst"
    old_file.parent.mkdir(parents=True, exist_ok=True)
    old_file.write_bytes(b"expired-data")
    old_ts = time.time() - (40 * 86400)
    os.utime(old_file, (old_ts, old_ts))

    ret_res = GovernanceService.enforce_retention()
    assert ret_res["deleted_files"] >= 1
    assert not old_file.exists()

