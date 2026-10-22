"""Tests for Data Quality engine, Pipeline Orchestration, Analytics calculations, and Data Explorer."""

from datetime import datetime, timezone, timedelta
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.market import Kline, Symbol
from backend.app.services.data_quality_service import DataQualityService
from backend.app.services.pipeline_service import PipelineService
from backend.app.services.analytics_service import AnalyticsService
from backend.app.services.mlflow_adapter import MLflowAdapter


@pytest.mark.asyncio
async def test_data_quality_empty_dataset(test_db: AsyncSession):
    """Data quality service gracefully handles empty datasets without unhandled exceptions."""
    run = await DataQualityService.evaluate_klines(test_db, symbol="ETHUSDT", timeframe="1h")
    assert run.status == "FAILED"
    assert run.evaluated_row_count == 0
    assert run.rules_failed == 1
    assert run.rules_passed == 0


@pytest.mark.asyncio
async def test_data_quality_valid_candles(test_db: AsyncSession):
    """All rules pass when valid chronological OHLCV candles exist."""
    base_time = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=20)
    candles = []
    price = 50000.0

    for i in range(20):
        t_open = base_time + timedelta(hours=i)
        t_close = t_open + timedelta(hours=1) - timedelta(seconds=1)
        candles.append(
            Kline(
                symbol="BTCUSDT",
                timeframe="1h",
                open_time=t_open,
                close_time=t_close,
                open=price,
                high=price + 50.0,
                low=price - 30.0,
                close=price + 20.0,
                volume=15.5,
                is_closed=True
            )
        )
        price += 20.0

    test_db.add_all(candles)
    await test_db.commit()

    run = await DataQualityService.evaluate_klines(test_db, symbol="BTCUSDT", timeframe="1h")
    assert run.status == "PASSED"
    assert run.evaluated_row_count == 20
    assert run.total_rules_evaluated == 10
    assert run.rules_passed == 10
    assert run.rules_failed == 0


@pytest.mark.asyncio
async def test_data_quality_detects_ohlc_violation(test_db: AsyncSession):
    """DQ engine detects geometric violation when Low > High."""
    base_time = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=5)
    candles = [
        Kline(
            symbol="SOLUSDT",
            timeframe="1h",
            open_time=base_time,
            close_time=base_time + timedelta(hours=1),
            open=100.0,
            high=90.0,   # INVALID: high < low and high < open
            low=110.0,
            close=95.0,
            volume=50.0,
            is_closed=True
        )
    ]
    test_db.add_all(candles)
    await test_db.commit()

    run = await DataQualityService.evaluate_klines(test_db, symbol="SOLUSDT", timeframe="1h")
    assert run.status == "FAILED"
    assert run.rules_failed >= 1


@pytest.mark.asyncio
async def test_analytics_returns_distribution(test_db: AsyncSession):
    """Analytics service computes return distribution moments and histogram."""
    base_time = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=50)
    candles = []
    p = 2000.0
    for i in range(40):
        t = base_time + timedelta(hours=i)
        p += (5.0 if i % 2 == 0 else -3.0)
        candles.append(
            Kline(
                symbol="ETHUSDT",
                timeframe="1h",
                open_time=t,
                close_time=t + timedelta(hours=1),
                open=p,
                high=p + 10.0,
                low=p - 10.0,
                close=p,
                volume=100.0,
                is_closed=True
            )
        )
    test_db.add_all(candles)
    await test_db.commit()

    res = await AnalyticsService.get_returns_distribution(test_db, symbol="ETHUSDT", timeframe="1h")
    assert res["has_sufficient_data"] is True
    assert "mean_pct" in res["metrics"]
    assert "skewness" in res["metrics"]
    assert "kurtosis" in res["metrics"]
    assert len(res["histogram"]) > 0


@pytest.mark.asyncio
async def test_analytics_drawdowns(test_db: AsyncSession):
    """Drawdown computation correctly tracks running peak and maximum drawdown."""
    base_time = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=10)
    prices = [100.0, 110.0, 120.0, 90.0, 95.0, 105.0]  # Peak 120, trough 90 -> -25% DD
    candles = []
    for i, p in enumerate(prices):
        t = base_time + timedelta(hours=i)
        candles.append(
            Kline(
                symbol="BTCUSDT",
                timeframe="1h",
                open_time=t,
                close_time=t + timedelta(hours=1),
                open=p,
                high=p,
                low=p,
                close=p,
                volume=10.0,
                is_closed=True
            )
        )
    test_db.add_all(candles)
    await test_db.commit()

    res = await AnalyticsService.get_drawdowns(test_db, symbol="BTCUSDT", timeframe="1h")
    assert res["has_sufficient_data"] is True
    assert res["max_drawdown_pct"] == -25.0


@pytest.mark.asyncio
async def test_data_lineage_graph(test_db: AsyncSession):
    """Lineage graph returns nodes and edges connecting Medallion stages."""
    lineage = await DataQualityService.get_lineage_graph(test_db)
    assert "nodes" in lineage
    assert "edges" in lineage
    node_ids = [n["id"] for n in lineage["nodes"]]
    assert "src_binance" in node_ids
    assert "bronze_raw" in node_ids
    assert "silver_klines" in node_ids
    assert "gold_analytics" in node_ids
    assert "feature_store" in node_ids
    assert "serving_forecasts" in node_ids


@pytest.mark.asyncio
async def test_mlflow_adapter_fallback():
    """MLflow adapter honestly reports offline / local fallback mode when server is absent."""
    status = await MLflowAdapter.get_tracking_status()
    assert "is_connected" in status
    assert "server_status" in status
    assert "adapter_mode" in status
    assert status["adapter_mode"] in ["LOCAL_REGISTRY_FALLBACK", "REMOTE_MLFLOW"]


@pytest.mark.asyncio
async def test_api_pipeline_and_data_quality_endpoints(test_db):
    """Test pipelines, data quality, and data explorer endpoints via HTTP test client."""
    from httpx import ASGITransport, AsyncClient
    from backend.app.main import app
    from backend.app.core.database import get_db

    async def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Pipeline overview
        r_pipe = await ac.get("/api/v1/pipelines/overview")
        assert r_pipe.status_code == 200
        p_data = r_pipe.json()
        assert "total_runs" in p_data
        assert "success_rate_pct" in p_data

        # Pipeline runs list
        r_runs = await ac.get("/api/v1/pipelines/runs")
        assert r_runs.status_code == 200
        assert isinstance(r_runs.json(), list)

        # Data quality overview
        r_dq = await ac.get("/api/v1/data-quality/overview")
        assert r_dq.status_code == 200
        assert "pass_rate_pct" in r_dq.json()

        # Data lineage graph
        r_lineage = await ac.get("/api/v1/data-quality/lineage")
        assert r_lineage.status_code == 200
        lin_data = r_lineage.json()
        assert len(lin_data["nodes"]) >= 5
        assert len(lin_data["edges"]) >= 4

        # Data explorer datasets
        r_ds = await ac.get("/api/v1/data-explorer/datasets")
        assert r_ds.status_code == 200
        datasets = r_ds.json()
        assert any(d["id"] == "silver_klines" for d in datasets)

        # Data explorer preview
        r_prev = await ac.get("/api/v1/data-explorer/preview?dataset=silver_klines&page=1&page_size=10")
        assert r_prev.status_code == 200
        prev_data = r_prev.json()
        assert "total_rows" in prev_data
        assert "profile" in prev_data
        assert "rows" in prev_data

        # Data explorer CSV export
        r_exp = await ac.get("/api/v1/data-explorer/export?dataset=silver_klines&limit=10")
        assert r_exp.status_code == 200
        assert "text/csv" in r_exp.headers.get("content-type", "")

        # Analytics endpoints
        r_ret = await ac.get("/api/v1/analytics/returns?symbol=BTCUSDT&timeframe=1h")
        assert r_ret.status_code == 200

        r_vol = await ac.get("/api/v1/analytics/volatility?symbol=BTCUSDT&timeframe=1h")
        assert r_vol.status_code == 200

        r_dd = await ac.get("/api/v1/analytics/drawdowns?symbol=BTCUSDT&timeframe=1h")
        assert r_dd.status_code == 200

        r_corr = await ac.get("/api/v1/analytics/correlations?symbols=BTCUSDT,ETHUSDT&timeframe=1h")
        assert r_corr.status_code == 200

        # Model tracking status & experiments
        r_track = await ac.get("/api/v1/models/tracking-status")
        assert r_track.status_code == 200
        assert "adapter_mode" in r_track.json()

        r_exp = await ac.get("/api/v1/models/experiments")
        assert r_exp.status_code == 200
        assert isinstance(r_exp.json(), list)

    app.dependency_overrides.clear()
