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
    assert data["count"] == len(data["candles"])
    assert len(data["candles"]) == 30
    assert "indicators" in data


@pytest.mark.asyncio
async def test_market_klines_empty_regression(client):
    """REGRESSION TEST: Verify empty klines query returns count: 0, candles: [], indicators: {} with valid Pydantic schema."""
    from backend.app.schemas.market import MarketDataResponseSchema

    # Query for a symbol with zero candles
    res = await client.get("/api/v1/market/klines?symbol=ETHUSDT&timeframe=1h")
    assert res.status_code == 200
    data = res.json()

    assert data["symbol"] == "ETHUSDT"
    assert data["timeframe"] == "1h"
    assert data["count"] == 0
    assert data["candles"] == []
    assert data["indicators"] == {}

    # Validate against Pydantic schema
    validated = MarketDataResponseSchema.model_validate(data)
    assert validated.count == 0
    assert len(validated.candles) == 0


@pytest.mark.asyncio
async def test_market_klines_populated_contract(client):
    """Verify populated klines contract: count == len(candles), indicators align in length."""
    from backend.app.schemas.market import MarketDataResponseSchema

    res = await client.get("/api/v1/market/klines?symbol=BTCUSDT&timeframe=1h&limit=30")
    assert res.status_code == 200
    data = res.json()

    validated = MarketDataResponseSchema.model_validate(data)
    assert validated.count == len(validated.candles) == 30

    # Candle fields check
    for c in validated.candles:
        assert c.open > 0
        assert c.high >= c.low
        assert c.close > 0
        assert c.volume >= 0
        assert c.is_closed is True

    # Indicators alignment check: every indicator array has length equal to candles count
    for ind_name, vals in validated.indicators.items():
        assert len(vals) == validated.count, f"Indicator {ind_name} length {len(vals)} does not match candle count {validated.count}"


@pytest.mark.asyncio
async def test_market_klines_parameter_validation(client):
    """Verify 400 Bad Request for invalid parameters."""
    # Invalid timeframe
    res1 = await client.get("/api/v1/market/klines?symbol=BTCUSDT&timeframe=invalid_tf")
    assert res1.status_code == 400
    assert "Unsupported timeframe" in res1.json()["detail"]

    # Invalid symbol format
    res2 = await client.get("/api/v1/market/klines?symbol=BAD!!SYM&timeframe=1h")
    assert res2.status_code == 400
    assert "Invalid symbol format" in res2.json()["detail"]

    # start_time > end_time
    res3 = await client.get(
        "/api/v1/market/klines?symbol=BTCUSDT&timeframe=1h&start_time=2024-07-02T00:00:00&end_time=2024-07-01T00:00:00"
    )
    assert res3.status_code == 400
    assert "start_time must be less than or equal to end_time" in res3.json()["detail"]


@pytest.mark.asyncio
async def test_symbol_summaries_truthfulness_and_states(client, test_db):
    """Verify market symbol summary returns accurate data_status and nullable metrics (no false zeroes)."""
    from datetime import timezone

    # 1. Add ETHUSDT with no candles
    eth = Symbol(symbol="ETHUSDT", base_asset="ETH", quote_asset="USDT", is_active=True)
    test_db.add(eth)

    # 2. Add SOLUSDT with 5 candles (< 24)
    sol = Symbol(symbol="SOLUSDT", base_asset="SOL", quote_asset="USDT", is_active=True)
    test_db.add(sol)
    sol_dt = datetime(2024, 7, 1, 0, 0, 0)
    for i in range(5):
        test_db.add(Kline(
            symbol="SOLUSDT",
            timeframe="1h",
            open_time=sol_dt + timedelta(hours=i),
            close_time=sol_dt + timedelta(hours=i + 1) - timedelta(milliseconds=1),
            open=140.0 + i,
            high=145.0 + i,
            low=139.0 + i,
            close=142.0 + i,
            volume=20.0,
            is_closed=True
        ))

    # 3. Add BNBUSDT with 24 candles but stale last_synced_at (> 2 hours ago)
    stale_time = datetime(2020, 1, 1, 0, 0, 0)
    bnb = Symbol(symbol="BNBUSDT", base_asset="BNB", quote_asset="USDT", is_active=True, last_synced_at=stale_time)
    test_db.add(bnb)
    for i in range(24):
        test_db.add(Kline(
            symbol="BNBUSDT",
            timeframe="1h",
            open_time=stale_time + timedelta(hours=i),
            close_time=stale_time + timedelta(hours=i + 1) - timedelta(milliseconds=1),
            open=580.0,
            high=585.0,
            low=575.0,
            close=582.0,
            volume=10.0,
            is_closed=True
        ))

    await test_db.commit()

    res = await client.get("/api/v1/market/symbols")
    assert res.status_code == 200
    symbols = {s["symbol"]: s for s in res.json()}

    # Check ETHUSDT (empty)
    assert symbols["ETHUSDT"]["current_price"] is None
    assert symbols["ETHUSDT"]["change_24h"] is None
    assert symbols["ETHUSDT"]["volume_24h"] is None
    assert symbols["ETHUSDT"]["data_status"] == "UNAVAILABLE"
    assert symbols["ETHUSDT"]["has_full_24h"] is False

    # Check SOLUSDT (partial)
    assert symbols["SOLUSDT"]["current_price"] is not None
    assert symbols["SOLUSDT"]["data_status"] == "PARTIAL"
    assert symbols["SOLUSDT"]["candle_count_24h"] == 5
    assert symbols["SOLUSDT"]["has_full_24h"] is False

    # Check BTCUSDT (synchronized)
    assert symbols["BTCUSDT"]["current_price"] is not None
    assert symbols["BTCUSDT"]["data_status"] == "SYNCHRONIZED"
    assert symbols["BTCUSDT"]["candle_count_24h"] == 24
    assert symbols["BTCUSDT"]["has_full_24h"] is True

    # Check BNBUSDT (stale)
    assert symbols["BNBUSDT"]["data_status"] == "STALE"


@pytest.mark.asyncio
async def test_sync_parameter_validation_and_safe_errors(client):
    """Verify /api/v1/market/sync input validation and safe exception handling."""
    # Invalid timeframe
    res1 = await client.post("/api/v1/market/sync", json={"symbol": "BTCUSDT", "timeframe": "invalid_tf"})
    assert res1.status_code == 400

    # Invalid symbol
    res2 = await client.post("/api/v1/market/sync", json={"symbol": "BTC$$$", "timeframe": "1h"})
    assert res2.status_code == 400


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

