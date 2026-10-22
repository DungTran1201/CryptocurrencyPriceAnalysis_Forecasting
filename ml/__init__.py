"""Machine Learning and Forecasting Package."""

from ml.features import extract_features, prepare_supervised_dataset
from ml.baselines import NaivePersistenceBaseline, RollingMeanBaseline
from ml.models import CryptoTimeSeriesModel
from ml.evaluation import calculate_metrics, chronological_split, walk_forward_evaluate
from ml.registry import ModelRegistry

__all__ = [
    "extract_features",
    "prepare_supervised_dataset",
    "NaivePersistenceBaseline",
    "RollingMeanBaseline",
    "CryptoTimeSeriesModel",
    "calculate_metrics",
    "chronological_split",
    "walk_forward_evaluate",
    "ModelRegistry"
]
