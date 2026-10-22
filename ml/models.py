"""Trained machine learning models for crypto return and direction forecasting.

Features:
- Dual-head architecture: Regresses return percentage and classifies direction probability
- Preprocessing scaler strictly fit on training data fold
- Empirical residual confidence intervals (no fabricated metrics)
- Feature importance analysis
"""

from typing import List, Dict, Any, Tuple, Optional
import numpy as np
import pandas as pd
from sklearn.preprocessing import RobustScaler
from sklearn.ensemble import HistGradientBoostingRegressor, HistGradientBoostingClassifier
from sklearn.linear_model import Ridge, LogisticRegression


class CryptoTimeSeriesModel:
    """Supervised machine learning model for multi-horizon price and direction forecasting."""

    def __init__(
        self,
        model_type: str = "gradient_boosting",
        horizon_steps: int = 6,
        confidence_level: float = 0.95
    ):
        self.model_type = model_type
        self.horizon_steps = horizon_steps
        self.confidence_level = confidence_level
        self.version = "1.0.0"
        
        self.scaler = RobustScaler()
        self.feature_names: List[str] = []
        self.residual_std: float = 0.02  # Initial default
        
        if model_type == "ridge":
            self.regressor = Ridge(alpha=1.0)
            self.classifier = LogisticRegression(C=1.0, max_iter=500)
        else:
            # High performance HistGradientBoosting
            self.regressor = HistGradientBoostingRegressor(
                max_iter=100,
                learning_rate=0.05,
                max_depth=5,
                random_state=42
            )
            self.classifier = HistGradientBoostingClassifier(
                max_iter=100,
                learning_rate=0.05,
                max_depth=5,
                random_state=42
            )

    def fit(
        self,
        X_train: pd.DataFrame,
        y_return: pd.Series,
        y_direction: pd.Series,
        feature_cols: List[str]
    ) -> "CryptoTimeSeriesModel":
        """Fit preprocessors and estimators strictly on training data."""
        self.feature_names = list(feature_cols)
        X_mat = X_train[self.feature_names].values
        
        # Fit scaler on train only
        X_scaled = self.scaler.fit_transform(X_mat)
        
        # Fit models
        self.regressor.fit(X_scaled, y_return.values)
        self.classifier.fit(X_scaled, y_direction.values)
        
        # Compute empirical residual standard deviation for bounds
        train_preds = self.regressor.predict(X_scaled)
        residuals = y_return.values - train_preds
        self.residual_std = float(np.std(residuals))
        if self.residual_std < 1e-4:
            self.residual_std = 0.01

        return self

    def predict(
        self,
        df: pd.DataFrame
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Generate point forecast, expected returns, probabilities, and confidence intervals.
        
        Returns:
            (predicted_prices, predicted_returns, probabilities, lower_bounds, upper_bounds)
        """
        current_prices = df["close"].values
        X_mat = df[self.feature_names].values
        X_scaled = self.scaler.transform(X_mat)
        
        # Predict return percentage
        predicted_returns = self.regressor.predict(X_scaled)
        
        # Predict direction probability (prob of UP, class 1)
        if hasattr(self.classifier, "predict_proba"):
            probs = self.classifier.predict_proba(X_scaled)[:, 1]
        else:
            probs = 1.0 / (1.0 + np.exp(-predicted_returns * 50.0))
            
        # Point estimate of future price
        predicted_prices = current_prices * (1.0 + predicted_returns)
        
        # Confidence interval bounds using empirical residual standard deviation
        z_multiplier = 1.96 if self.confidence_level >= 0.95 else 1.645
        half_width = z_multiplier * self.residual_std
        lower_bounds = current_prices * (1.0 + predicted_returns - half_width)
        upper_bounds = current_prices * (1.0 + predicted_returns + half_width)
        
        return predicted_prices, predicted_returns, probs, lower_bounds, upper_bounds

    def get_feature_importances(self) -> Dict[str, float]:
        """Extract feature importances if available."""
        if hasattr(self.regressor, "feature_importances_"):
            return {
                feat: float(imp)
                for feat, imp in zip(self.feature_names, self.regressor.feature_importances_)
            }
        elif hasattr(self.regressor, "coef_"):
            coefs = np.abs(self.regressor.coef_)
            total = np.sum(coefs) if np.sum(coefs) > 0 else 1.0
            return {
                feat: float(c / total)
                for feat, c in zip(self.feature_names, coefs)
            }
        return {feat: 1.0 / len(self.feature_names) for feat in self.feature_names}
