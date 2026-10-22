"""Pydantic schemas for Market and Kline endpoints."""

from datetime import datetime
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field


class SymbolInfoSchema(BaseModel):
    """Symbol status and 24h ticker summary."""
    symbol: str
    base_asset: str
    quote_asset: str
    current_price: float
    change_24h: float
    high_24h: float
    low_24h: float
    volume_24h: float
    last_synced_at: Optional[datetime] = None


class KlineCandleSchema(BaseModel):
    """Single candlestick schema."""
    open_time: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: str
    is_closed: bool


class MarketDataResponseSchema(BaseModel):
    """Historical candles with technical indicators response."""
    symbol: str
    timeframe: str
    count: int
    candles: List[KlineCandleSchema]
    indicators: Dict[str, List[Optional[float]]] = Field(default_factory=dict)


class SyncRequestSchema(BaseModel):
    """Request payload to trigger market sync."""
    symbol: str = Field(default="BTCUSDT")
    timeframe: str = Field(default="1h")
    lookback_days: int = Field(default=30, ge=1, le=365)


class SyncResponseSchema(BaseModel):
    """Response payload after market sync."""
    symbol: str
    timeframe: str
    added_candles: int
    status: str
    message: str
