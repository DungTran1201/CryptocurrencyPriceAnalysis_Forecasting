"""Pydantic schemas for Model Lab, Registry, and Training endpoints."""

from datetime import datetime
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field, ConfigDict


class ModelTrainRequest(BaseModel):
    """Payload to trigger a training and walk-forward evaluation run."""
    symbol: str = Field(default="BTCUSDT")
    timeframe: str = Field(default="1h")
    horizon_steps: int = Field(default=6, ge=1, le=24)
    model_type: str = Field(default="gradient_boosting")
    n_splits: int = Field(default=4, ge=2, le=10)


class ModelMetricSchema(BaseModel):
    """Evaluation metric summary for a registered model."""
    model_config = ConfigDict(from_attributes=True)

    mae: float
    rmse: float
    mape: float
    directional_accuracy: float
    brier_score: Optional[float] = None
    naive_mae: Optional[float] = None
    mae_improvement_pct: Optional[float] = None
    beats_naive_baseline: bool


class ModelCardSchema(BaseModel):
    """Detailed model card schema."""
    model_config = ConfigDict(from_attributes=True)

    model_id: str
    name: str
    version: str
    model_type: str
    symbol: str
    timeframe: str
    horizon_steps: int
    train_start_time: datetime
    train_end_time: datetime
    train_sample_count: int
    is_active: bool
    created_at: datetime
    metrics: Optional[ModelMetricSchema] = None


class ModelTrainingResultSchema(BaseModel):
    """Response after executing model training and evaluation."""
    model_id: str
    symbol: str
    timeframe: str
    horizon_steps: int
    is_active: bool
    evaluation: Dict[str, Any]
    feature_count: int
    train_samples: int
    feature_importances: Dict[str, float]
