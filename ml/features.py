"""Zero-leakage technical feature engineering and dataset generation.

Calculates technical indicators, multi-period momentum, volatility, and volume
features strictly using historical candle data up to time t, completely eliminating
look-ahead bias.
"""

from typing import Tuple, List, Optional
import numpy as np
import pandas as pd


def compute_sma(series: pd.Series, window: int) -> pd.Series:
    """Simple Moving Average."""
    return series.rolling(window=window, min_periods=window).mean()


def compute_ema(series: pd.Series, window: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=window, adjust=False, min_periods=window).mean()


def compute_rsi(series: pd.Series, window: int = 14) -> pd.Series:
    """Relative Strength Index (RSI)."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    
    avg_gain = gain.rolling(window=window, min_periods=window).mean()
    avg_loss = loss.rolling(window=window, min_periods=window).mean()
    
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50.0)


def compute_bollinger_bands(
    series: pd.Series,
    window: int = 20,
    num_std: float = 2.0
) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """Bollinger Bands: Middle, Upper, Lower, and Percent B."""
    middle = series.rolling(window=window, min_periods=window).mean()
    std = series.rolling(window=window, min_periods=window).std()
    upper = middle + (std * num_std)
    lower = middle - (std * num_std)
    
    # %B = (Price - Lower) / (Upper - Lower)
    band_width = upper - lower
    pct_b = (series - lower) / band_width.replace(0, np.nan)
    pct_b = pct_b.fillna(0.5)
    return middle, upper, lower, pct_b


def compute_macd(
    series: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """Moving Average Convergence Divergence."""
    ema_fast = compute_ema(series, fast)
    ema_slow = compute_ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = compute_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def compute_atr(
    df: pd.DataFrame,
    window: int = 14
) -> pd.Series:
    """Average True Range normalized by close price."""
    high = df["high"]
    low = df["low"]
    close_prev = df["close"].shift(1)
    
    tr1 = high - low
    tr2 = (high - close_prev).abs()
    tr3 = (low - close_prev).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    atr = tr.rolling(window=window, min_periods=window).mean()
    # Normalize by close price to make scale-invariant
    return (atr / df["close"]).fillna(0.0)


def extract_features(df: pd.DataFrame) -> pd.DataFrame:
    """Extract comprehensive technical features without lookahead bias.
    
    Expects DataFrame with columns: open_time, open, high, low, close, volume.
    Sorts by open_time strictly ascending.
    """
    data = df.copy().sort_values("open_time").reset_index(drop=True)
    close = data["close"]
    volume = data["volume"]

    feat = pd.DataFrame(index=data.index)
    feat["open_time"] = data["open_time"]
    feat["close"] = close

    # 1. Log Returns and Momentum
    feat["return_1"] = np.log(close / close.shift(1))
    feat["return_3"] = np.log(close / close.shift(3))
    feat["return_6"] = np.log(close / close.shift(6))
    feat["return_12"] = np.log(close / close.shift(12))
    feat["return_24"] = np.log(close / close.shift(24))

    # 2. Moving Averages & Price-to-MA ratios
    sma_7 = compute_sma(close, 7)
    sma_14 = compute_sma(close, 14)
    sma_50 = compute_sma(close, 50)
    ema_14 = compute_ema(close, 14)

    feat["ratio_sma_7"] = close / sma_7 - 1.0
    feat["ratio_sma_14"] = close / sma_14 - 1.0
    feat["ratio_sma_50"] = close / sma_50 - 1.0
    feat["ratio_ema_14"] = close / ema_14 - 1.0
    feat["ratio_sma_cross"] = (sma_7 - sma_50) / close

    # 3. Volatility
    feat["volatility_7"] = feat["return_1"].rolling(7).std()
    feat["volatility_14"] = feat["return_1"].rolling(14).std()
    feat["volatility_30"] = feat["return_1"].rolling(30).std()

    # 4. RSI
    feat["rsi_14"] = compute_rsi(close, 14) / 100.0  # Normalized to 0.0-1.0
    feat["rsi_7"] = compute_rsi(close, 7) / 100.0

    # 5. Bollinger Bands
    _, _, _, pct_b = compute_bollinger_bands(close, window=20, num_std=2.0)
    feat["boll_pct_b"] = pct_b

    # 6. MACD
    macd, signal, hist = compute_macd(close)
    feat["macd_line"] = macd / close
    feat["macd_signal"] = signal / close
    feat["macd_hist"] = hist / close

    # 7. ATR (Normalized)
    feat["atr_norm"] = compute_atr(data, window=14)

    # 8. Volume Dynamics
    vol_sma_14 = compute_sma(volume, 14)
    feat["volume_ratio_14"] = (volume / vol_sma_14.replace(0, np.nan)).fillna(1.0)
    feat["volume_change_1"] = volume.pct_change().fillna(0.0).clip(-5.0, 5.0)

    # 9. Lagged Returns
    feat["lag_return_1"] = feat["return_1"].shift(1)
    feat["lag_return_2"] = feat["return_1"].shift(2)
    feat["lag_return_3"] = feat["return_1"].shift(3)

    return feat


def prepare_supervised_dataset(
    df: pd.DataFrame,
    horizon_steps: int = 6
) -> Tuple[pd.DataFrame, List[str], str]:
    """Transform raw OHLCV time-series into supervised (X, y) dataset.
    
    Target:
    - target_price: close price at t + horizon_steps
    - target_return: (close[t + horizon_steps] - close[t]) / close[t]
    - target_direction: 1 if target_return > 0 else 0
    """
    features_df = extract_features(df)
    
    # Construct strictly forward-looking targets
    close = features_df["close"]
    features_df["target_price"] = close.shift(-horizon_steps)
    features_df["target_return"] = (features_df["target_price"] - close) / close
    features_df["target_direction"] = (features_df["target_return"] > 0).astype(int)

    feature_cols = [
        col for col in features_df.columns
        if col not in ["open_time", "close", "target_price", "target_return", "target_direction"]
    ]

    # Drop rows that have NaN values from moving windows or forward horizon shifts
    cleaned_df = features_df.dropna().reset_index(drop=True)
    return cleaned_df, feature_cols, "target_return"
