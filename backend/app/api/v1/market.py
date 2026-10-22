"""Market and Kline REST API endpoints."""

from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db
from backend.app.core.logging import get_logger
from backend.app.schemas.market import (
    SymbolInfoSchema,
    MarketDataResponseSchema,
    SyncRequestSchema,
    SyncResponseSchema
)
from backend.app.services.market_service import MarketService
from backend.app.services.sync_service import BinanceSyncService

logger = get_logger("MarketAPI")

router = APIRouter(prefix="/market", tags=["Market Data"])
market_service = MarketService()
sync_service = BinanceSyncService()

VALID_TIMEFRAMES = {"1m", "5m", "15m", "1h", "4h", "1d"}


@router.get("/symbols", response_model=List[SymbolInfoSchema])
async def list_symbols(db: AsyncSession = Depends(get_db)):
    """Retrieve all supported cryptocurrency pairs with real-time 24h stats."""
    return await market_service.get_symbols(db)


@router.get("/klines", response_model=MarketDataResponseSchema)
async def get_klines_with_indicators(
    symbol: str = Query("BTCUSDT", description="Crypto pair"),
    timeframe: str = Query("1h", description="Candle interval (1m, 5m, 15m, 1h, 4h, 1d)"),
    limit: int = Query(300, ge=1, le=1000, description="Number of candles"),
    start_time: Optional[datetime] = Query(None, description="Start UTC datetime filter"),
    end_time: Optional[datetime] = Query(None, description="End UTC datetime filter"),
    db: AsyncSession = Depends(get_db)
):
    """Retrieve historical candlestick data enriched with technical indicators."""
    normalized_symbol = symbol.strip().upper()
    if not normalized_symbol or len(normalized_symbol) > 20 or not normalized_symbol.isalnum():
        raise HTTPException(status_code=400, detail=f"Invalid symbol format '{symbol}'")

    if timeframe not in VALID_TIMEFRAMES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported timeframe '{timeframe}'. Valid options: {', '.join(sorted(VALID_TIMEFRAMES))}"
        )

    if start_time and end_time and start_time > end_time:
        raise HTTPException(status_code=400, detail="start_time must be less than or equal to end_time")

    data = await market_service.get_klines_with_indicators(
        db=db,
        symbol=normalized_symbol,
        timeframe=timeframe,
        limit=limit,
        start_time=start_time,
        end_time=end_time
    )
    return data


@router.post("/sync", response_model=SyncResponseSchema)
async def trigger_sync(
    payload: SyncRequestSchema,
    db: AsyncSession = Depends(get_db)
):
    """Trigger manual or incremental synchronization from Binance API."""
    normalized_symbol = payload.symbol.strip().upper()
    if not normalized_symbol or len(normalized_symbol) > 20 or not normalized_symbol.isalnum():
        raise HTTPException(status_code=400, detail=f"Invalid symbol format '{payload.symbol}'")

    if payload.timeframe not in VALID_TIMEFRAMES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported timeframe '{payload.timeframe}'. Valid options: {', '.join(sorted(VALID_TIMEFRAMES))}"
        )

    try:
        result = await sync_service.sync_incremental(
            db=db,
            symbol=normalized_symbol,
            timeframe=payload.timeframe,
            lookback_days_if_empty=payload.lookback_days
        )
        return SyncResponseSchema(
            symbol=normalized_symbol,
            timeframe=payload.timeframe,
            added_candles=result["added_candles"],
            status=result["status"],
            message=f"Successfully synced {result['added_candles']} candles for {normalized_symbol} {payload.timeframe}"
        )
    except ValueError as ve:
        logger.warning(f"Validation error during sync of {normalized_symbol}: {ve}")
        raise HTTPException(status_code=400, detail=f"Sync request invalid: {str(ve)}")
    except Exception as e:
        logger.error(f"Synchronization failed for {normalized_symbol} {payload.timeframe}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Market synchronization encountered an internal server error.")
