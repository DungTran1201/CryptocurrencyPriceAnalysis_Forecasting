"""Forecast and realization persistence models."""

from datetime import datetime, timezone
import uuid
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    Boolean,
    Index
)
from backend.app.core.database import Base


class ForecastRecord(Base):
    """Immutable record of generated market predictions.
    
    Includes data cutoff time, target prediction timestamp, predicted price,
    directional probability, confidence bounds, and realization tracking.
    """
    __tablename__ = "forecast_records"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    model_id = Column(String(64), nullable=False, index=True)
    model_version = Column(String(32), nullable=False)
    symbol = Column(String(32), nullable=False, index=True)
    timeframe = Column(String(16), nullable=False, index=True)
    horizon_steps = Column(Integer, nullable=False)
    
    data_cutoff_time = Column(DateTime, nullable=False)
    forecast_timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), nullable=False, index=True)
    target_time = Column(DateTime, nullable=False, index=True)
    
    current_price = Column(Float, nullable=False)
    predicted_price = Column(Float, nullable=False)
    predicted_return_pct = Column(Float, nullable=False)
    predicted_direction = Column(String(8), nullable=False)  # "UP", "DOWN", "FLAT"
    direction_probability = Column(Float, nullable=False)    # 0.0 to 1.0 (prob of UP)
    
    lower_bound_price = Column(Float, nullable=True)
    upper_bound_price = Column(Float, nullable=True)
    confidence_level = Column(Float, default=0.95, nullable=False)
    
    # Reconciliation with actual outcome
    status = Column(String(16), default="PENDING", nullable=False)  # PENDING, RECONCILED, EXPIRED
    realized_price = Column(Float, nullable=True)
    realized_direction = Column(String(8), nullable=True)
    absolute_error = Column(Float, nullable=True)
    percentage_error = Column(Float, nullable=True)
    direction_correct = Column(Boolean, nullable=True)
    reconciled_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_forecast_symbol_target", "symbol", "target_time"),
        Index("ix_forecast_status", "status"),
    )
