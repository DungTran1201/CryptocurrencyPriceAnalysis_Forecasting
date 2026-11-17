"""Tests for Prometheus /metrics, Resource telemetry, Streaming/Governance APIs, and Security controls."""

import pytest
import pytest_asyncio
import httpx
from httpx import ASGITransport

from backend.app.core.config import settings
from backend.app.core.database import get_db
from backend.app.main import app


@pytest_asyncio.fixture(scope="function")
async def api_client(test_db):
    async def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_observability_metrics_and_resources_endpoints(api_client):
    """Verify /metrics Prometheus exposition, /system/resources, streaming status, & catalog APIs."""
    r_metrics = await api_client.get("/metrics")
    assert r_metrics.status_code == 200
    assert "platform_process_rss_bytes" in r_metrics.text
    assert r_metrics.headers.get("x-content-type-options") == "nosniff"
    assert r_metrics.headers.get("x-frame-options") == "DENY"

    r_res = await api_client.get("/api/v1/system/resources")
    assert r_res.status_code == 200
    data = r_res.json()
    assert data["profile"] in {"lite", "standard", "extended"}
    assert data["measured"]["process_rss_mb"] > 0
    assert "bronze" in data["measured"]["storage_mb"]

    r_stream = await api_client.get("/api/v1/streaming/status")
    assert r_stream.status_code == 200
    assert "producer" in r_stream.json() and "consumer" in r_stream.json()

    r_dlq = await api_client.get("/api/v1/streaming/dlq")
    assert r_dlq.status_code == 200 and isinstance(r_dlq.json(), list)

    r_cat = await api_client.get("/api/v1/governance/catalog")
    assert r_cat.status_code == 200
    cat_ids = {c["dataset_id"] for c in r_cat.json()}
    assert {"bronze_market_events", "silver_klines", "gold_analytics_marts", "gold_feature_sets"}.issubset(cat_ids)


@pytest.mark.asyncio
async def test_analytics_parameter_validation_and_admin_token(api_client, isolated_data_dir, monkeypatch):
    """Verify strict validation on analytics routes and optional X-Admin-Token enforcement in isolated tmp storage."""
    import os
    import time
    from pathlib import Path

    r_bad_sym = await api_client.get("/api/v1/analytics/returns?symbol=BAD!!&timeframe=1h")
    assert r_bad_sym.status_code == 400

    r_bad_tf = await api_client.get("/api/v1/analytics/volatility?symbol=BTCUSDT&timeframe=badtf")
    assert r_bad_tf.status_code == 400

    # Verify TEST-ISO redirection & seed an expired artifact strictly in isolated tmp storage
    assert Path(settings.storage.data_dir).resolve() == isolated_data_dir.resolve()
    expired_bronze = isolated_data_dir / "bronze" / "expired_test.jsonl.zst"
    expired_bronze.parent.mkdir(parents=True, exist_ok=True)
    expired_bronze.write_bytes(b"expired-test-artifact")
    expired_ts = time.time() - (40 * 86400)
    os.utime(expired_bronze, (expired_ts, expired_ts))

    # Admin token enforcement when configured
    monkeypatch.setattr(settings, "admin_api_token", "secret-ops-token")
    r_unauth = await api_client.post("/api/v1/governance/retention/run")
    assert r_unauth.status_code == 401
    assert expired_bronze.exists()

    r_auth = await api_client.post(
        "/api/v1/governance/retention/run",
        headers={"X-Admin-Token": "secret-ops-token"},
    )
    assert r_auth.status_code == 200
    assert r_auth.json()["deleted_files"] >= 1
    assert not expired_bronze.exists()

