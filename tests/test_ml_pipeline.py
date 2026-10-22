"""Tests for ML feature pipeline, baselines, chronological evaluation, model gating, and forecast persistence."""

from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import pytest

from ml.features import extract_features, prepare_supervised_dataset
from ml.baselines import NaivePersistenceBaseline, RollingMeanBaseline
from ml.models import CryptoTimeSeriesModel
from ml.evaluation import chronological_split, walk_forward_evaluate, calculate_metrics
from ml.registry import ModelRegistry
from backend.app.services.forecast_service import ForecastService
from backend.app.models.market import Kline


def create_synthetic_market_data(n_candles: int = 300, base_price: float = 60000.0) -> pd.DataFrame:
    """Generate realistic synthetic OHLCV time-series for tests."""
    np.random.seed(42)
    start_dt = datetime(2024, 1, 1, 0, 0, 0)
    
    # Random walk returns with slight drift
    returns = np.random.normal(0.0002, 0.008, n_candles)
    prices = base_price * np.exp(np.cumsum(returns))
    
    records = []
    for i in range(n_candles):
        c = prices[i]
        h = c * (1.0 + abs(np.random.normal(0, 0.003)))
        l = c * (1.0 - abs(np.random.normal(0, 0.003)))
        o = (c + l) / 2.0
        v = float(np.random.uniform(10.0, 150.0))
        t = start_dt + timedelta(hours=i)
        records.append({
            "open_time": t,
            "open": o,
            "high": max(h, o, c),
            "low": min(l, o, c),
            "close": c,
            "volume": v
        })
    return pd.DataFrame(records)


def test_feature_extraction_no_lookahead():
    """Verify indicators and features depend only on past and current values."""
    df = create_synthetic_market_data(100)
    features = extract_features(df)
    
    assert "return_1" in features.columns
    assert "rsi_14" in features.columns
    assert "boll_pct_b" in features.columns
    assert "macd_line" in features.columns
    assert "atr_norm" in features.columns

    # Verify that modifying future data at index 90 has ZERO effect on features at index 50
    df_modified = df.copy()
    df_modified.loc[90:, "close"] = df_modified.loc[90:, "close"] * 2.0
    features_modified = extract_features(df_modified)
    
    np.testing.assert_almost_equal(
        features.loc[50, "rsi_14"],
        features_modified.loc[50, "rsi_14"]
    )
    np.testing.assert_almost_equal(
        features.loc[50, "boll_pct_b"],
        features_modified.loc[50, "boll_pct_b"]
    )


def test_baselines_prediction():
    """Verify Naive and Rolling SMA baseline outputs."""
    df = create_synthetic_market_data(50)
    
    # 1. Naive Persistence Baseline
    naive = NaivePersistenceBaseline()
    pred_p, pred_r, probs = naive.predict(df)
    assert len(pred_p) == len(df)
    np.testing.assert_array_equal(pred_p, df["close"].values)
    np.testing.assert_array_equal(pred_r, np.zeros(len(df)))
    np.testing.assert_array_equal(probs, np.full(len(df), 0.5))

    # 2. Rolling Mean Baseline
    sma_model = RollingMeanBaseline(window=10)
    sma_p, sma_r, sma_probs = sma_model.predict(df)
    assert len(sma_p) == len(df)
    assert np.all(sma_probs >= 0.05) and np.all(sma_probs <= 0.95)


def test_walk_forward_evaluation():
    """Verify chronological walk forward evaluation runs and computes comparative metrics."""
    df = create_synthetic_market_data(250)
    supervised_df, feature_cols, target_col = prepare_supervised_dataset(df, horizon_steps=3)
    
    results = walk_forward_evaluate(
        df=supervised_df,
        feature_cols=feature_cols,
        horizon_steps=3,
        n_splits=3,
        model_type="gradient_boosting"
    )
    
    assert "candidate" in results
    assert "naive_baseline" in results
    assert "mae" in results["candidate"]
    assert "directional_accuracy" in results["candidate"]
    assert results["folds_evaluated"] == 3


@pytest.mark.asyncio
async def test_forecast_lifecycle_and_reconciliation(test_db):
    """Test generating a forecast, persisting it, and reconciling against actual mature candle."""
    # Seed 30 synthetic candles in test_db
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
            volume=100.0,
            is_closed=True
        )
        for i in range(30)
    ]
    test_db.add_all(candles)
    await test_db.commit()

    service = ForecastService()
    # Generate forecast
    forecast = await service.generate_forecast(test_db, "BTCUSDT", "1h", horizon_steps=2)
    assert forecast.status == "PENDING"
    assert forecast.symbol == "BTCUSDT"
    assert forecast.predicted_price > 0
    assert forecast.direction_probability >= 0.0 and forecast.direction_probability <= 1.0

    # Add the realized candle for target_time
    target_candle = Kline(
        symbol="BTCUSDT",
        timeframe="1h",
        open_time=forecast.target_time,
        close_time=forecast.target_time + delta - timedelta(milliseconds=1),
        open=60300.0,
        high=60400.0,
        low=60250.0,
        close=60350.0,
        volume=120.0,
        is_closed=True
    )
    test_db.add(target_candle)
    await test_db.commit()

    # Reconcile
    reconciled = await service.reconcile_pending_forecasts(test_db)
    assert reconciled >= 1

    await test_db.refresh(forecast)
    assert forecast.status == "RECONCILED"
    assert forecast.realized_price == 60350.0
    assert forecast.absolute_error is not None
    assert forecast.percentage_error is not None
    assert forecast.direction_correct in [True, False]
