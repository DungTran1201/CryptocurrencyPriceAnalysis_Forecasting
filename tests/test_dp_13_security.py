"""Comprehensive tests for API Security, Admin Authentication & Response Contract (WI-DP-13)."""

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app.core.config import settings
from backend.app.core.database import get_db
from backend.app.main import app
from backend.app.schemas.market import MarketDataResponseSchema


@pytest.mark.asyncio
async def test_admin_token_protection_on_all_mutations(test_db, monkeypatch):
    """Verify that all mutating endpoints strictly require x-admin-token when configured."""
    monkeypatch.setattr(settings, "admin_api_token", "super-secret-admin-token")

    async def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        mutating_endpoints = [
            ("POST", "/api/v1/market/sync", {"symbol": "BTCUSDT", "timeframe": "1h"}),
            ("POST", "/api/v1/pipelines/trigger", {"symbol": "BTCUSDT", "timeframe": "1h"}),
            ("POST", "/api/v1/models/train", {"symbol": "BTCUSDT", "timeframe": "1h", "model_type": "ridge"}),
            ("POST", "/api/v1/forecasts/generate", {"symbol": "BTCUSDT", "timeframe": "1h", "horizon_steps": 1}),
            ("POST", "/api/v1/forecasts/reconcile", {}),
            ("POST", "/api/v1/data-quality/evaluate", {"symbol": "BTCUSDT", "timeframe": "1h"}),
        ]

        for method, path, body in mutating_endpoints:
            # 1. Without Token -> Must return 401 Unauthorized
            res_no_auth = await ac.request(method, path, json=body)
            assert res_no_auth.status_code == 401, f"{method} {path} should be protected by ADMIN_API_TOKEN"
            assert "Admin-Token" in res_no_auth.json().get("detail", "")

            # 2. With Invalid Token -> Must return 401 Unauthorized
            res_bad_auth = await ac.request(method, path, json=body, headers={"x-admin-token": "wrong-token"})
            assert res_bad_auth.status_code == 401, f"{method} {path} should reject invalid ADMIN_API_TOKEN"

            # 3. With Valid Token -> Must pass auth (not 401)
            # Use an empty or non-synced payload to verify auth passes without running real disk-mutating syncs
            res_valid = await ac.request(
                method, path, json={"symbol": "NONEXISTENT_TEST_PAIR", "timeframe": "1h"}, headers={"x-admin-token": "super-secret-admin-token"}
            )
            assert res_valid.status_code != 401, f"{method} {path} should accept valid token (got {res_valid.status_code})"

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_market_contract_and_empty_candles(test_db):
    """Verify MarketDataResponseSchema guarantees symbol, timeframe, count, candles, indicators."""
    async def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/market/klines?symbol=NONEXISTENT&timeframe=1h")
        assert res.status_code == 200
        data = res.json()

        # Validate against schema
        validated = MarketDataResponseSchema.model_validate(data)
        assert validated.symbol == "NONEXISTENT"
        assert validated.timeframe == "1h"
        assert validated.count == 0
        assert validated.candles == []
        assert isinstance(validated.indicators, dict)

    app.dependency_overrides.clear()
