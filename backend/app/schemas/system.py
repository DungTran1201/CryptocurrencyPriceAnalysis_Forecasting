"""Pydantic schemas for System Status and Health endpoints."""

from datetime import datetime
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, ConfigDict


class CheckpointSummarySchema(BaseModel):
    """Synchronization status per symbol and timeframe."""
    model_config = ConfigDict(from_attributes=True)

    symbol: str
    timeframe: str
    total_candles: int
    last_close_time: Optional[datetime] = None
    last_sync_status: str
    detected_gaps_count: int
    updated_at: datetime


class SystemStatusResponse(BaseModel):
    """Overall system health and synchronization status."""
    status: str
    version: str
    environment: str
    current_time: str
    database_connected: bool
    total_candles_stored: int
    total_forecasts_generated: int
    total_reconciled_forecasts: int
    active_models_count: int
    checkpoints: List[CheckpointSummarySchema]
