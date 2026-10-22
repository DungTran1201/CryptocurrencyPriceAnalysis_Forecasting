"""Baseline time-series models for benchmark comparison.

Enforces ML Reliability principle: complex models must provably outperform
naive and moving-average heuristics before being eligible for production.
"""

from typing import Dict, Any, Tuple
import numpy as np
import pandas as pd


class NaivePersistenceBaseline:
    """Predicts future price as identical to current price (zero change)."""
    
    def __init__(self):
        self.model_type = "baseline_naive"
        self.version = "1.0.0"

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "NaivePersistenceBaseline":
        """No parameters to fit."""
        return self

    def predict(self, df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Generate predictions.
        
        Returns:
            (predicted_prices, predicted_returns, probabilities)
        """
        current_prices = df["close"].values
        # Predicted return is exactly 0
        predicted_returns = np.zeros(len(current_prices))
        predicted_prices = current_prices.copy()
        # Direction probability is neutral 0.5
        probabilities = np.full(len(current_prices), 0.5)
        return predicted_prices, predicted_returns, probabilities


class RollingMeanBaseline:
    """Predicts future price as the rolling simple moving average."""

    def __init__(self, window: int = 14):
        self.window = window
        self.model_type = "baseline_sma"
        self.version = "1.0.0"

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "RollingMeanBaseline":
        """No parameters to fit."""
        return self

    def predict(self, df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Generate predictions based on rolling SMA."""
        current_prices = df["close"].values
        sma = df["close"].rolling(self.window, min_periods=1).mean().values
        
        predicted_prices = sma
        predicted_returns = (predicted_prices - current_prices) / current_prices
        # Probability scaled by distance from mean
        raw_prob = 0.5 + (predicted_returns * 5.0)
        probabilities = np.clip(raw_prob, 0.05, 0.95)
        
        return predicted_prices, predicted_returns, probabilities
