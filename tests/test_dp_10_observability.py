"""Targeted regression tests for WI-DP-10 (Observability, Staleness, Health, Logging & Metrics)."""

import asyncio
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
from types import SimpleNamespace
import httpx
from httpx import ASGITransport
import pytest
import pytest_asyncio

from backend.app.core.config import settings
from backend.app.core.database import get_db
from backend.app.core.logging import JsonLogFormatter, configure_logging
from backend.app.core.metrics import (
    ACTIVE_DATA_FRESHNESS_SECONDS,
    CACHE_HITS_TOTAL,
    CACHE_MISSES_TOTAL,
    DATA_GAPS_DETECTED_TOTAL,
    REGISTRY,
    STAGE_FAILURES_TOTAL,
    WORKFLOW_LEASE_RECLAIMED_TOTAL,
    WORKFLOW_RUNS_TOTAL,
    clear_observability_caches,
    collect_resource_snapshot_async,
    refresh_active_freshness,
    update_active_freshness_from_db,
)
import backend.app.core.metrics as metrics_mod
from backend.app.main import app
from backend.app.models.market import Kline
from backend.app.streaming.runtime import stream_runtime
from backend.app.streaming.telemetry import merge_worker_snapshots, serialize_worker_heartbeat


@pytest_asyncio.fixture(scope="function")
async def obs_client(test_db):
    async def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_collect_resource_snapshot_async_off_loop_and_cached(isolated_data_dir: Path, monkeypatch):
    """Verify collect_resource_snapshot_async scans all layers off-event-loop and caches within TTL."""
    import threading

    clear_observability_caches()
    for sub, content in [
        ("dlq/item.json", b"dlq-bytes" * 300),
        ("models/m.joblib", b"model-bytes" * 300),
        ("checkpoints/ckpt.json", b"ckpt-bytes" * 300),
        ("warehouse/snapshots/dw-v1.duckdb", b"dw-bytes" * 300),
    ]:
        p = isolated_data_dir / sub
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
    (isolated_data_dir / "crypto_market.db-wal").write_bytes(b"wal-bytes" * 300)

    loop_tid = threading.get_ident()
    scan_tids = []
    orig_scan = metrics_mod._scan_storage_layers

    def counting_scan(base: Path):
        scan_tids.append(threading.get_ident())
        return orig_scan(base)

    monkeypatch.setattr(metrics_mod, "_scan_storage_layers", counting_scan)

    snap1 = await collect_resource_snapshot_async(str(isolated_data_dir), 450, ttl_sec=10.0)
    snap2 = await collect_resource_snapshot_async(str(isolated_data_dir), 450, ttl_sec=10.0)

    assert len(scan_tids) == 1
    assert scan_tids[0] != loop_tid
    assert snap1["disk_free_gb"] > 0
    assert snap1["host_ram_available_mb"] > 0
    for layer in ("dlq", "models", "checkpoints", "warehouse", "metadata_wal", "bronze"):
        assert layer in snap1["storage_mb"]
        assert layer in snap2["storage_mb"]
    assert snap1["storage_mb"]["warehouse"] > 0


@pytest.mark.asyncio
async def test_active_data_freshness_rises_honestly_on_stall(test_db):
    """Verify active_data_freshness_seconds increases monotonically when upstream stalls."""
    clear_observability_caches()
    t0 = datetime(2026, 11, 17, 12, 0, 0)
    test_db.add(
        Kline(
            symbol="BTCUSDT",
            timeframe="1m",
            open_time=t0 - timedelta(minutes=11),
            close_time=t0 - timedelta(minutes=10),
            open=65000.0,
            high=65100.0,
            low=64900.0,
            close=65050.0,
            volume=12.0,
            is_closed=True,
        )
    )
    await test_db.commit()

    ages1 = await update_active_freshness_from_db(test_db, now_utc=t0)
    assert ages1[("BTCUSDT", "1m")] == pytest.approx(600.0, abs=1.0)
    val1 = REGISTRY.get_sample_value(
        "platform_active_data_freshness_seconds",
        {"symbol": "BTCUSDT", "timeframe": "1m"},
    )
    assert val1 == pytest.approx(600.0, abs=1.0)

    # Simulate 5 minutes passing with zero new incoming bars (stall)
    ages2 = refresh_active_freshness(now_utc=t0 + timedelta(minutes=5))
    assert ages2[("BTCUSDT", "1m")] == pytest.approx(900.0, abs=1.0)
    val2 = REGISTRY.get_sample_value(
        "platform_active_data_freshness_seconds",
        {"symbol": "BTCUSDT", "timeframe": "1m"},
    )
    assert val2 > val1


@pytest.mark.asyncio
async def test_health_endpoint_probes_db_and_disk_honestly(obs_client, monkeypatch):
    """Verify /api/v1/health probes DB/disk and returns 503 unhealthy on DB error or degraded on low disk."""
    r_ok = await obs_client.get("/api/v1/health")
    assert r_ok.status_code == 200
    body_ok = r_ok.json()
    assert body_ok["status"] == "healthy"
    assert body_ok["checks"]["database"]["status"] == "OK"
    assert body_ok["checks"]["disk"]["status"] == "OK"

    # Low disk -> degraded (200)
    monkeypatch.setattr(
        "backend.app.api.v1.system.psutil.disk_usage",
        lambda _p: SimpleNamespace(free=5 * (1024 ** 3), percent=88.0),
    )
    r_deg = await obs_client.get("/api/v1/health")
    assert r_deg.status_code == 200
    assert r_deg.json()["status"] == "degraded"
    assert r_deg.json()["checks"]["disk"]["status"] == "DEGRADED"

    # Mocked DB failure -> 503 unhealthy without leaking internal exception string
    class _BrokenSession:
        async def execute(self, *_args, **_kwargs):
            raise RuntimeError("sqlite error at C:\\secret\\db\\crypto_market.db")

    async def broken_db():
        yield _BrokenSession()

    app.dependency_overrides[get_db] = broken_db
    r_fail = await obs_client.get("/api/v1/health")
    assert r_fail.status_code == 503
    fail_body = r_fail.json()
    assert fail_body["status"] == "unhealthy"
    assert fail_body["checks"]["database"]["status"] == "FAILED"
    assert "C:\\secret" not in r_fail.text


@pytest.mark.asyncio
async def test_metrics_endpoint_exposes_ifc_dp_010_gauges_and_counters(obs_client):
    """Verify /metrics exports host RAM/disk gauges and IFC-DP-010 workflow/cache/failure counters."""
    STAGE_FAILURES_TOTAL.labels(process="workflow_worker", stage="warehouse_build").inc()
    WORKFLOW_RUNS_TOTAL.labels(workflow_type="MEDALLION_DAG", status="SUCCESS").inc()
    WORKFLOW_LEASE_RECLAIMED_TOTAL.inc()
    DATA_GAPS_DETECTED_TOTAL.labels(symbol="BTCUSDT", timeframe="1m").inc()
    CACHE_HITS_TOTAL.labels(cache="hot_state_l1").inc()
    CACHE_MISSES_TOTAL.labels(cache="hot_state_l1").inc()

    res = await obs_client.get("/metrics")
    assert res.status_code == 200
    text = res.text
    for metric_name in (
        "platform_host_ram_available_bytes",
        "platform_host_ram_used_percent",
        "platform_host_disk_free_bytes",
        "platform_host_disk_used_percent",
        "platform_stage_failures_total",
        "platform_workflow_runs_total",
        "platform_workflow_lease_reclaimed_total",
        "platform_data_gaps_detected_total",
        "platform_cache_hits_total",
        "platform_cache_misses_total",
        "platform_active_data_freshness_seconds",
    ):
        assert metric_name in text, f"Missing Prometheus metric {metric_name}"


def test_json_log_formatter_extra_and_secret_redaction():
    """Verify JsonLogFormatter serializes extra context and redacts sensitive fields."""
    formatter = JsonLogFormatter()
    record = logging.LogRecord(
        name="TestLogger",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="Workflow completed",
        args=(),
        exc_info=None,
    )
    record.run_id = "run-123"
    record.symbol = "BTCUSDT"
    record.admin_token = "super-secret-token"

    rendered = json.loads(formatter.format(record))
    assert rendered["logger"] == "TestLogger"
    assert rendered["message"] == "Workflow completed"
    assert rendered["extra"]["run_id"] == "run-123"
    assert rendered["extra"]["symbol"] == "BTCUSDT"
    assert rendered["extra"]["admin_token"] == "[REDACTED]"

    configure_logging(level="WARNING", log_format="json")
    assert logging.getLogger("uvicorn").level == logging.WARNING
    configure_logging(level="INFO", log_format="text")


@pytest.mark.asyncio
async def test_decoupled_resources_reports_worker_staleness_honestly(obs_client, monkeypatch):
    """Verify /system/resources reports UNAVAILABLE/STALE when decoupled and no fresh worker heartbeat exists."""
    now = datetime(2026, 11, 17, 12, 0, 0, tzinfo=timezone.utc)
    stale_hb = serialize_worker_heartbeat(
        worker_id="stream-1",
        role="stream_worker",
        pid=999,
        rss_mb=120.5,
        cpu_percent=4.2,
    )
    stale_hb["updated_at"] = (now - timedelta(seconds=30)).isoformat()
    merged_stale = merge_worker_snapshots({"worker.stream_worker.stream-1": stale_hb}, now_utc=now)
    assert merged_stale["status"] == "STALE"
    assert merged_stale["workers"]["worker.stream_worker.stream-1"]["state"] == "STALE"

    monkeypatch.setattr(settings.streaming, "embedded_in_api", False)
    res = await obs_client.get("/api/v1/system/resources")
    assert res.status_code == 200
    body = res.json()
    assert body["embedded_in_api"] is False
    assert body["streaming"]["status"] in {"UNAVAILABLE", "STALE"}
    assert body["workers"]["status"] in {"UNAVAILABLE", "STALE"}
