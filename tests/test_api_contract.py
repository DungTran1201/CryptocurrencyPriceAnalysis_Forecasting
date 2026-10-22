"""Automated API contract and REST integration tests."""

from datetime import datetime, timedelta
import pytest
import pytest_asyncio
import httpx
from httpx import ASGITransport

from backend.app.main import app
from backend.app.core.database import get_db, Base
from backend.app.models.market import Symbol, Kline


@pytest_asyncio.fixture(scope="function")
async def client(test_db):
    """Provide an async test client connected to the in-memory test database."""
    async def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db
    
    # Pre-seed Symbol
    sym = Symbol(symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT", is_active=True)
    test_db.add(sym)

    # Pre-seed some candles
    start_dt = datetime(2024, 7, 1, 0, 0, 0)
    delta = timedelta(hours=1)
    candles = [
        Kline(
            symbol="BTCUSDT",
            timeframe="1h",
            open_time=start_dt + (delta * i),
            close_time=start_dt + (delta * (i + 1)) - timedelta(milliseconds=1),
            open=60000.0 + (i * 10),
            high=60050.0 + (i * 10),
            low=59950.0 + (i * 10),
            close=60020.0 + (i * 10),
            volume=50.0,
            is_closed=True
        )
        for i in range(40)
    ]
    test_db.add_all(candles)
    await test_db.commit()

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_health_check_endpoint(client):
    """Verify /api/v1/health returns 200 and healthy status."""
    res = await client.get("/api/v1/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert "version" in data


@pytest.mark.asyncio
async def test_system_status_endpoint(client):
    """Verify /api/v1/system/status returns metrics."""
    res = await client.get("/api/v1/system/status")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "OPERATIONAL"
    assert data["total_candles_stored"] >= 40


@pytest.mark.asyncio
async def test_market_symbols_endpoint(client):
    """Verify /api/v1/market/symbols returns symbol listing."""
    res = await client.get("/api/v1/market/symbols")
    assert res.status_code == 200
    symbols = res.json()
    assert len(symbols) >= 1
    assert symbols[0]["symbol"] == "BTCUSDT"
    assert "current_price" in symbols[0]


@pytest.mark.asyncio
async def test_market_klines_endpoint(client):
    """Verify /api/v1/market/klines returns candles and indicators."""
    res = await client.get("/api/v1/market/klines?symbol=BTCUSDT&timeframe=1h&limit=30")
    assert res.status_code == 200
    data = res.json()
    assert data["symbol"] == "BTCUSDT"
    assert data["timeframe"] == "1h"
    assert len(data["candles"]) > 0
    assert "indicators" in data


@pytest.mark.asyncio
async def test_forecast_generate_and_list_lifecycle(client):
    """Verify creating a forecast via POST /api/v1/forecasts/generate and listing via GET."""
    # 1. Generate forecast
    payload = {
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "horizon_steps": 4
    }
    gen_res = await client.post("/api/v1/forecasts/generate", json=payload)
    assert gen_res.status_code == 200
    fc_data = gen_res.json()
    assert fc_data["symbol"] == "BTCUSDT"
    assert fc_data["horizon_steps"] == 4
    assert fc_data["status"] == "PENDING"
    assert fc_data["predicted_direction"] in ["UP", "DOWN", "FLAT"]
    assert fc_data["direction_probability"] >= 0.0 and fc_data["direction_probability"] <= 1.0

    # 2. List forecasts
    list_res = await client.get("/api/v1/forecasts?symbol=BTCUSDT")
    assert list_res.status_code == 200
    list_data = list_res.json()
    assert list_data["total_count"] >= 1
    assert len(list_data["records"]) >= 1


@pytest.mark.asyncio
async def test_model_listing_endpoint(client):
    """Verify /api/v1/models returns model list."""
    res = await client.get("/api/v1/models")
    assert res.status_code == 200
    assert isinstance(res.json(), list)
