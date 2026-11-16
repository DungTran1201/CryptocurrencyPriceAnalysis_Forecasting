"""Financial Analytics Formula Tests, Stream-vs-Batch Parity Tests, & ML Guard Tests."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from backend.app.models.market import Kline
from backend.app.services.analytics_service import AnalyticsService
from backend.app.services.forecast_service import ForecastService
from ml.incremental_analytics import (
    IncrementalAnalyticsEngine,
    IncrementalSymbolState,
    compute_batch_reference_metrics,
)
from ml.models import CryptoTimeSeriesModel


def _make_ohlcv(n: int = 80, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    start = datetime(2026, 2, 1, 0, 0, 0)
    rets = rng.normal(0.0005, 0.012, size=n)
    closes = 50000.0 * np.exp(np.cumsum(rets))
    rows = []
    for i in range(n):
        c = float(closes[i])
        o = float(closes[i - 1]) if i > 0 else c * 0.999
        h = max(o, c) * (1.0 + float(abs(rng.normal(0, 0.004))))
        l = min(o, c) * (1.0 - float(abs(rng.normal(0, 0.004))))
        v = float(rng.uniform(20.0, 200.0))
        rows.append({
            "open_time": start + timedelta(hours=i),
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": v,
        })
    return pd.DataFrame(rows)


def test_stream_vs_batch_financial_parity():
    """Verify O(1) incremental stream analytics match independent batch formulas on all indicators & risk metrics."""
    df = _make_ohlcv(80)
    batch = compute_batch_reference_metrics(df, timeframe="1h")

    state = IncrementalSymbolState(symbol="BTCUSDT", timeframe="1h", max_bars=300)
    snap = {}
    for _, row in df.iterrows():
        snap = state.update_closed_bar(
            open_time=row["open_time"].to_pydatetime(),
            open_price=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
        )

    numeric_keys = [
        "simple_return",
        "log_return",
        "sma_7",
        "sma_25",
        "ema_12",
        "ema_26",
        "rsi_14",
        "macd_line",
        "macd_signal",
        "macd_hist",
        "boll_mid",
        "boll_upper",
        "boll_lower",
        "atr_14",
        "vwap",
        "vol_7_ann_pct",
        "vol_14_ann_pct",
        "vol_30_ann_pct",
        "var_95_pct",
        "cvar_95_pct",
        "var_99_pct",
        "cvar_99_pct",
        "running_peak",
        "current_drawdown_pct",
        "max_drawdown_pct",
    ]
    for key in numeric_keys:
        assert snap[key] is not None, f"Stream metric {key} unexpectedly None"
        assert batch[key] is not None, f"Batch metric {key} unexpectedly None"
        np.testing.assert_allclose(
            snap[key],
            batch[key],
            rtol=1e-7,
            atol=1e-7,
            err_msg=f"Stream/Batch parity mismatch for {key}",
        )


def test_incremental_checkpoint_save_and_restore(tmp_path: Path):
    """Verify incremental analytics engine recovers identical state across restarts."""
    df = _make_ohlcv(50)
    eng1 = IncrementalAnalyticsEngine(checkpoint_dir=tmp_path, max_bars=200)
    st1 = eng1.get_or_create("ETHUSDT", "1m")
    for _, r in df.iloc[:40].iterrows():
        st1.update_closed_bar(r["open_time"].to_pydatetime(), r["open"], r["high"], r["low"], r["close"], r["volume"])
    assert eng1.save_checkpoints() == 1

    # Reload in fresh engine and process remaining 10 bars
    eng2 = IncrementalAnalyticsEngine(checkpoint_dir=tmp_path, max_bars=200)
    st2 = eng2.get_or_create("ETHUSDT", "1m")
    for _, r in df.iloc[40:].iterrows():
        st1.update_closed_bar(r["open_time"].to_pydatetime(), r["open"], r["high"], r["low"], r["close"], r["volume"])
        st2.update_closed_bar(r["open_time"].to_pydatetime(), r["open"], r["high"], r["low"], r["close"], r["volume"])

    snap1 = st1.snapshot()
    snap2 = st2.snapshot()
    for k in ("ema_12", "rsi_14", "atr_14", "vwap", "var_95_pct", "cvar_95_pct", "max_drawdown_pct"):
        assert snap1[k] == pytest.approx(snap2[k], rel=1e-10)


@pytest.mark.asyncio
async def test_analytics_service_cvar_and_covariance(test_db):
    """Verify AnalyticsService returns CVaR, log mean, ATR, VWAP, and Covariance matrix."""
    df_btc = _make_ohlcv(50, seed=1)
    df_eth = _make_ohlcv(50, seed=2)
    candles = []
    for sym, df in [("BTCUSDT", df_btc), ("ETHUSDT", df_eth)]:
        for _, r in df.iterrows():
            candles.append(
                Kline(
                    symbol=sym,
                    timeframe="1h",
                    open_time=r["open_time"].to_pydatetime(),
                    close_time=r["open_time"].to_pydatetime() + timedelta(hours=1) - timedelta(seconds=1),
                    open=float(r["open"]),
                    high=float(r["high"]),
                    low=float(r["low"]),
                    close=float(r["close"]),
                    volume=float(r["volume"]),
                    is_closed=True,
                )
            )
    test_db.add_all(candles)
    await test_db.commit()

    ret_res = await AnalyticsService.get_returns_distribution(test_db, "BTCUSDT", "1h", limit=100)
    assert ret_res["has_sufficient_data"] is True
    metrics = ret_res["metrics"]
    assert metrics["cvar_95_pct"] <= metrics["var_95_pct"]
    assert metrics["cvar_99_pct"] <= metrics["var_99_pct"]
    assert metrics["atr_14"] > 0
    assert metrics["vwap"] > 0

    corr_res = await AnalyticsService.get_correlation_matrix(test_db, ["BTCUSDT", "ETHUSDT"], "1h", limit=100)
    assert corr_res["has_sufficient_data"] is True
    assert len(corr_res["matrix"]) == 2
    assert len(corr_res["covariance_matrix"]) == 2


@pytest.mark.asyncio
async def test_ml_single_class_guard_and_triggered_inference(test_db):
    """Verify ML model handles single-class fold gracefully and triggered inference deduplicates."""
    df = _make_ohlcv(40, seed=9)
    df["feat1"] = np.linspace(0.0, 1.0, len(df))
    y_ret = pd.Series(np.full(len(df), 0.005))
    y_dir = pd.Series(np.ones(len(df), dtype=int))  # Single class!

    model = CryptoTimeSeriesModel(model_type="ridge", horizon_steps=3)
    model.fit(df, y_ret, y_dir, feature_cols=["feat1"])
    preds, _, probs, _, _ = model.predict(df.tail(5))
    assert len(preds) == 5
    assert np.all(probs > 0.9)

    # Triggered forecast idempotency check
    candles = [
        Kline(
            symbol="SOLUSDT",
            timeframe="1m",
            open_time=r["open_time"].to_pydatetime(),
            close_time=r["open_time"].to_pydatetime() + timedelta(minutes=1) - timedelta(seconds=1),
            open=float(r["open"]),
            high=float(r["high"]),
            low=float(r["low"]),
            close=float(r["close"]),
            volume=float(r["volume"]),
            is_closed=True,
        )
        for _, r in df.iloc[:20].iterrows()
    ]
    test_db.add_all(candles)
    await test_db.commit()

    fc_svc = ForecastService()
    fc1 = await fc_svc.try_triggered_forecast(test_db, "SOLUSDT", "1m", horizon_steps=3)
    fc2 = await fc_svc.try_triggered_forecast(test_db, "SOLUSDT", "1m", horizon_steps=3)
    assert fc1 is not None
    assert fc2 is None  # Deduplicated for identical cutoff bar

