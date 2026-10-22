"""Pydantic schemas for Forecast generation and history."""

from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


class ForecastGenerateRequest(BaseModel):
    """Parameters for running inference and generating a forecast."""
    symbol: str = Field(default="BTCUSDT")
    timeframe: str = Field(default="1h")
    horizon_steps: int = Field(default=6, ge=1, le=48)


class ForecastRecordSchema(BaseModel):
    """Full forecast record schema with realization fields."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    model_id: str
    model_version: str
    symbol: str
    timeframe: str
    horizon_steps: int
    data_cutoff_time: datetime
    forecast_timestamp: datetime
    target_time: datetime
    current_price: float
    predicted_price: float
    predicted_return_pct: float
    predicted_direction: str
    direction_probability: float
    lower_bound_price: Optional[float] = None
    upper_bound_price: Optional[float] = None
    confidence_level: float
    status: str
    realized_price: Optional[float] = None
    realized_direction: Optional[str] = None
    absolute_error: Optional[float] = None
    percentage_error: Optional[float] = None
    direction_correct: Optional[bool] = None
    reconciled_at: Optional[datetime] = None


class ForecastHistoryResponse(BaseModel):
    """Paginated forecast records with overall audit metrics."""
    total_count: int
    reconciled_count: int
    direction_hit_rate_pct: float
    mean_percentage_error: float
    records: List[ForecastRecordSchema]
