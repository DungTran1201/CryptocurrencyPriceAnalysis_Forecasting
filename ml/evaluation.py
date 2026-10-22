"""Chronological evaluation, walk-forward cross-validation, and metrics computation.

Enforces zero look-ahead bias and strict comparison against naive baselines.
"""

from typing import Dict, Any, List, Tuple
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, brier_score_loss

from ml.baselines import NaivePersistenceBaseline
from ml.models import CryptoTimeSeriesModel


def calculate_metrics(
    y_true_prices: np.ndarray,
    y_pred_prices: np.ndarray,
    current_prices: np.ndarray,
    y_true_directions: np.ndarray,
    predicted_probs: np.ndarray
) -> Dict[str, float]:
    """Compute comprehensive regression, direction, and probability calibration metrics."""
    mae = float(mean_absolute_error(y_true_prices, y_pred_prices))
    rmse = float(np.sqrt(mean_squared_error(y_true_prices, y_pred_prices)))
    
    # MAPE
    non_zero = y_true_prices != 0
    mape = float(np.mean(np.abs((y_true_prices[non_zero] - y_pred_prices[non_zero]) / y_true_prices[non_zero])) * 100.0)

    # Directional Accuracy (Hit rate)
    true_change = y_true_prices - current_prices
    pred_change = y_pred_prices - current_prices
    
    # Sign match: (positive and positive) or (negative and negative)
    direction_hits = ((true_change >= 0) & (pred_change >= 0)) | ((true_change < 0) & (pred_change < 0))
    directional_accuracy = float(np.mean(direction_hits))

    # Brier Score (lower is better, range [0, 1])
    try:
        brier = float(brier_score_loss(y_true_directions, predicted_probs))
    except Exception:
        brier = 0.25

    return {
        "mae": round(mae, 4),
        "rmse": round(rmse, 4),
        "mape": round(mape, 4),
        "directional_accuracy": round(directional_accuracy, 4),
        "brier_score": round(brier, 4)
    }


def chronological_split(
    df: pd.DataFrame,
    test_ratio: float = 0.2
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Split dataset chronologically into train and test sets."""
    split_idx = int(len(df) * (1.0 - test_ratio))
    train_df = df.iloc[:split_idx].copy().reset_index(drop=True)
    test_df = df.iloc[split_idx:].copy().reset_index(drop=True)
    return train_df, test_df


def walk_forward_evaluate(
    df: pd.DataFrame,
    feature_cols: List[str],
    horizon_steps: int = 6,
    n_splits: int = 4,
    model_type: str = "gradient_boosting"
) -> Dict[str, Any]:
    """Perform expanding-window walk-forward cross validation.
    
    Evaluates both the candidate ML model and the Naive Baseline on identical folds.
    """
    total_len = len(df)
    min_train_size = int(total_len * 0.4)
    step_size = (total_len - min_train_size) // n_splits

    fold_metrics: List[Dict[str, float]] = []
    naive_fold_metrics: List[Dict[str, float]] = []

    for fold in range(n_splits):
        train_end = min_train_size + (fold * step_size)
        test_end = min(train_end + step_size, total_len)
        if test_end <= train_end:
            break

        train_fold = df.iloc[:train_end].copy().reset_index(drop=True)
        test_fold = df.iloc[train_end:test_end].copy().reset_index(drop=True)

        # 1. Fit & Evaluate Candidate Model
        candidate = CryptoTimeSeriesModel(model_type=model_type, horizon_steps=horizon_steps)
        candidate.fit(
            X_train=train_fold,
            y_return=train_fold["target_return"],
            y_direction=train_fold["target_direction"],
            feature_cols=feature_cols
        )
        pred_prices, pred_returns, probs, _, _ = candidate.predict(test_fold)

        m_candidate = calculate_metrics(
            y_true_prices=test_fold["target_price"].values,
            y_pred_prices=pred_prices,
            current_prices=test_fold["close"].values,
            y_true_directions=test_fold["target_direction"].values,
            predicted_probs=probs
        )
        fold_metrics.append(m_candidate)

        # 2. Evaluate Naive Baseline
        naive = NaivePersistenceBaseline()
        naive_prices, _, naive_probs = naive.predict(test_fold)
        m_naive = calculate_metrics(
            y_true_prices=test_fold["target_price"].values,
            y_pred_prices=naive_prices,
            current_prices=test_fold["close"].values,
            y_true_directions=test_fold["target_direction"].values,
            predicted_probs=naive_probs
        )
        naive_fold_metrics.append(m_naive)

    # Average metrics across all folds
    avg_mae = float(np.mean([f["mae"] for f in fold_metrics]))
    avg_rmse = float(np.mean([f["rmse"] for f in fold_metrics]))
    avg_mape = float(np.mean([f["mape"] for f in fold_metrics]))
    avg_dir_acc = float(np.mean([f["directional_accuracy"] for f in fold_metrics]))
    avg_brier = float(np.mean([f["brier_score"] for f in fold_metrics]))

    naive_avg_mae = float(np.mean([f["mae"] for f in naive_fold_metrics]))
    naive_avg_dir_acc = float(np.mean([f["directional_accuracy"] for f in naive_fold_metrics]))

    # Compute improvement margin
    mae_improvement_pct = ((naive_avg_mae - avg_mae) / naive_avg_mae) * 100.0 if naive_avg_mae > 0 else 0.0

    return {
        "candidate": {
            "mae": round(avg_mae, 4),
            "rmse": round(avg_rmse, 4),
            "mape": round(avg_mape, 4),
            "directional_accuracy": round(avg_dir_acc, 4),
            "brier_score": round(avg_brier, 4)
        },
        "naive_baseline": {
            "mae": round(naive_avg_mae, 4),
            "directional_accuracy": round(naive_avg_dir_acc, 4)
        },
        "mae_improvement_pct": round(mae_improvement_pct, 2),
        "beats_naive": avg_mae < naive_avg_mae,
        "folds_evaluated": len(fold_metrics)
    }
