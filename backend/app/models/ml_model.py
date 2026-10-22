"""Model Registry and Evaluation tracking models."""

from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    Boolean,
    Text,
    ForeignKey
)
from backend.app.core.database import Base


class ModelRegistryEntry(Base):
    """Registered time-series model metadata and gating status."""
    __tablename__ = "model_registry"

    model_id = Column(String(64), primary_key=True)
    name = Column(String(64), nullable=False)
    version = Column(String(32), nullable=False)
    model_type = Column(String(32), nullable=False)  # baseline_naive, baseline_sma, gradient_boosting, ridge
    symbol = Column(String(32), nullable=False, index=True)
    timeframe = Column(String(16), nullable=False, index=True)
    horizon_steps = Column(Integer, nullable=False)
    
    feature_names = Column(Text, nullable=False)  # JSON-encoded list of features
    hyperparameters = Column(Text, nullable=False)  # JSON-encoded dict
    
    train_start_time = Column(DateTime, nullable=False)
    train_end_time = Column(DateTime, nullable=False)
    train_sample_count = Column(Integer, nullable=False)
    
    is_active = Column(Boolean, default=False, nullable=False)
    artifact_path = Column(String(256), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), nullable=False)


class ModelEvaluationMetric(Base):
    """Walk-forward and validation metrics for registered models."""
    __tablename__ = "model_evaluation_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_id = Column(String(64), ForeignKey("model_registry.model_id", ondelete="CASCADE"), nullable=False, index=True)
    split_type = Column(String(32), nullable=False)  # "walk_forward", "out_of_sample_test", "validation"
    
    mae = Column(Float, nullable=False)
    rmse = Column(Float, nullable=False)
    mape = Column(Float, nullable=False)
    directional_accuracy = Column(Float, nullable=False)
    brier_score = Column(Float, nullable=True)
    
    naive_mae = Column(Float, nullable=True)
    mae_improvement_pct = Column(Float, nullable=True)
    beats_naive_baseline = Column(Boolean, default=False, nullable=False)
    
    evaluated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), nullable=False)
