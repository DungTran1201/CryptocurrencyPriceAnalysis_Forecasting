"""Comprehensive tests for Data Governance, Catalog, Lineage & Retention (WI-DP-09)."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.governance import DataCatalogEntry, DataLineageEdge
from backend.app.services.governance_service import GovernanceService
from backend.app.storage.local import LocalStorageBackend


@pytest.mark.asyncio
async def test_governance_catalog_sync_and_list(test_db: AsyncSession):
    """Verify that catalog sync persists all core Medallion dataset entries."""
    entries = await GovernanceService.sync_catalog_entries(test_db)
    assert len(entries) >= 7

    dataset_ids = {e.dataset_id for e in entries}
    assert "binance_public_stream" in dataset_ids
    assert "bronze_market_events" in dataset_ids
    assert "silver_klines" in dataset_ids
    assert "silver_agg_trades" in dataset_ids
    assert "gold_analytics_marts" in dataset_ids
    assert "gold_feature_sets" in dataset_ids
    assert "forecast_records" in dataset_ids

    # Query catalog via list_catalog
    catalog = await GovernanceService.list_catalog(test_db)
    assert len(catalog) >= 7
    first = catalog[0]
    assert "dataset_id" in first
    assert "layer" in first
    assert "schema" in first


@pytest.mark.asyncio
async def test_governance_lineage_recording_and_graph(test_db: AsyncSession):
    """Verify lineage edge tracking and graph generation."""
    edge = await GovernanceService.record_lineage_edge(
        test_db,
        run_id="run-test-lin-01",
        source_dataset="bronze_market_events",
        target_dataset="silver_klines",
        transformation="test_transformation",
        records_in=500,
        records_out=500,
        metadata={"test_key": "test_val"},
    )
    await test_db.commit()

    assert edge.source_dataset == "bronze_market_events"
    assert edge.target_dataset == "silver_klines"
    assert edge.records_in == 500

    graph = await GovernanceService.get_lineage_graph(test_db)
    assert len(graph["nodes"]) >= 5
    assert len(graph["edges"]) >= 4
    assert any(r["run_id"] == "run-test-lin-01" for r in graph["recorded_runs"])


def test_retention_enforcement_prunes_aged_files(tmp_path: Path, monkeypatch):
    """Verify retention policy accurately deletes files exceeding time/size budgets."""
    storage = LocalStorageBackend(root_dir=tmp_path)
    monkeypatch.setattr("backend.app.services.governance_service.get_storage_backend", lambda: storage)

    # Create dummy bronze files
    b_file = "bronze/source=binance/test_old.jsonl.zst"
    storage.write_bytes(b_file, b"old_data" * 100)

    # Artificially age the file
    old_time = (datetime.now(timezone.utc) - timedelta(days=45)).timestamp()
    p = storage.local_path(b_file)
    import os
    os.utime(p, (old_time, old_time))

    res = GovernanceService.enforce_retention()
    assert "bronze" in res["layers"]
    assert res["deleted_files"] >= 1
    assert res["freed_bytes"] > 0
    assert not storage.exists(b_file)
