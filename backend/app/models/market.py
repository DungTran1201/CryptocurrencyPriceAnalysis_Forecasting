"""Market data models: Symbols, Kline candlesticks, and Sync Checkpoints."""

from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    Boolean,
    UniqueConstraint,
    Index
)
from backend.app.core.database import Base


class Symbol(Base):
    """Registered cryptocurrency trading symbols."""
    __tablename__ = "symbols"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(32), unique=True, nullable=False, index=True)
    base_asset = Column(String(16), nullable=False)
    quote_asset = Column(String(16), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), nullable=False)
    last_synced_at = Column(DateTime, nullable=True)


class Kline(Base):
    """OHLCV market candlestick records.
    
    Contains unique constraint on (symbol, timeframe, open_time) to
    enforce idempotency and prevent duplicate records.
    """
    __tablename__ = "klines"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(32), nullable=False, index=True)
    timeframe = Column(String(16), nullable=False, index=True)
    open_time = Column(DateTime, nullable=False, index=True)
    close_time = Column(DateTime, nullable=False)
    
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)
    
    quote_asset_volume = Column(Float, nullable=True)
    number_of_trades = Column(Integer, nullable=True)
    taker_buy_base_asset_volume = Column(Float, nullable=True)
    taker_buy_quote_asset_volume = Column(Float, nullable=True)
    
    is_closed = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "open_time", name="uq_symbol_tf_opentime"),
        Index("ix_kline_lookup", "symbol", "timeframe", "open_time"),
    )


class SyncCheckpoint(Base):
    """Checkpoints for incremental sync and gap tracking."""
    __tablename__ = "sync_checkpoints"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(32), nullable=False)
    timeframe = Column(String(16), nullable=False)
    last_open_time = Column(DateTime, nullable=True)
    last_close_time = Column(DateTime, nullable=True)
    total_candles = Column(Integer, default=0, nullable=False)
    last_sync_status = Column(String(32), default="IDLE", nullable=False)
    last_error = Column(String(512), nullable=True)
    detected_gaps_count = Column(Integer, default=0, nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None), nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", name="uq_checkpoint_symbol_tf"),
    )
