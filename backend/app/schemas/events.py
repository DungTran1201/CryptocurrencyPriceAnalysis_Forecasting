"""Canonical versioned event schemas for streaming & Medallion ingestion."""

from datetime import datetime, timezone
from typing import Literal, Optional, Union
from pydantic import BaseModel, Field, model_validator

CANONICAL_EVENT_SCHEMA_VERSION = "1.0.0"


def ensure_utc_naive(dt: datetime) -> datetime:
    """Normalize datetime to UTC naive representation matching ORM models."""
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


class CanonicalAggTradeEvent(BaseModel):
    """Canonical normalized aggregate trade event."""
    schema_version: str = Field(default=CANONICAL_EVENT_SCHEMA_VERSION)
    event_id: str
    event_type: Literal["aggTrade"] = "aggTrade"
    source: str = "binance_ws"
    symbol: str
    agg_trade_id: int = Field(ge=0)
    price: float = Field(gt=0.0)
    quantity: float = Field(ge=0.0)
    quote_quantity: float = Field(ge=0.0)
    is_buyer_maker: bool
    event_time: datetime
    trade_time: datetime
    ingestion_time: datetime

    @model_validator(mode="after")
    def _normalize_dates(self) -> "CanonicalAggTradeEvent":
        self.symbol = self.symbol.upper()
        self.event_time = ensure_utc_naive(self.event_time)
        self.trade_time = ensure_utc_naive(self.trade_time)
        self.ingestion_time = ensure_utc_naive(self.ingestion_time)
        return self


VALID_TIMEFRAMES = {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w"}


class CanonicalKlineEvent(BaseModel):
    """Canonical normalized candlestick bar event (forming or closed)."""
    schema_version: str = Field(default=CANONICAL_EVENT_SCHEMA_VERSION)
    event_id: str
    event_type: Literal["kline"] = "kline"
    source: str = "binance_ws"
    symbol: str
    timeframe: str
    open_time: datetime
    close_time: datetime
    open: float = Field(gt=0.0)
    high: float = Field(gt=0.0)
    low: float = Field(gt=0.0)
    close: float = Field(gt=0.0)
    volume: float = Field(ge=0.0)
    quote_asset_volume: Optional[float] = Field(default=None, ge=0.0)
    number_of_trades: Optional[int] = Field(default=None, ge=0)
    taker_buy_base_asset_volume: Optional[float] = Field(default=None, ge=0.0)
    taker_buy_quote_asset_volume: Optional[float] = Field(default=None, ge=0.0)
    is_closed: bool
    event_time: datetime
    ingestion_time: datetime

    @model_validator(mode="after")
    def _validate_ohlc(self) -> "CanonicalKlineEvent":
        self.symbol = self.symbol.upper()
        self.timeframe = self.timeframe.lower()
        if self.timeframe not in VALID_TIMEFRAMES:
            raise ValueError(f"Unsupported timeframe: {self.timeframe!r}")
        self.open_time = ensure_utc_naive(self.open_time)
        self.close_time = ensure_utc_naive(self.close_time)
        if self.open_time > self.close_time:
            raise ValueError("open_time must not exceed close_time")
        self.event_time = ensure_utc_naive(self.event_time)
        self.ingestion_time = ensure_utc_naive(self.ingestion_time)
        if self.high < self.low or self.high < self.open or self.high < self.close:
            raise ValueError("OHLC geometry invalid: high must bound low, open, and close")
        if self.low > self.open or self.low > self.close:
            raise ValueError("OHLC geometry invalid: low must not exceed open or close")
        return self


CanonicalMarketEvent = Union[CanonicalAggTradeEvent, CanonicalKlineEvent]

