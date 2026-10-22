"""Market and Kline REST API endpoints."""

from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, Query, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db
from backend.app.schemas.market import (
    SymbolInfoSchema,
    MarketDataResponseSchema,
    SyncRequestSchema,
    SyncResponseSchema
)
from backend.app.services.market_service import MarketService
from backend.app.services.sync_service import BinanceSyncService

router = APIRouter(prefix="/market", tags=["Market Data"])
market_service = MarketService()
sync_service = BinanceSyncService()


@router.get("/symbols", response_model=List[SymbolInfoSchema])
async def list_symbols(db: AsyncSession = Depends(get_db)):
    """Retrieve all supported cryptocurrency pairs with real-time 24h stats."""
    return await market_service.get_symbols(db)


@router.get("/klines", response_model=MarketDataResponseSchema)
async def get_klines_with_indicators(
    symbol: str = Query("BTCUSDT", description="Crypto pair"),
    timeframe: str = Query("1h", description="Candle interval (1m, 5m, 15m, 1h, 4h, 1d)"),
    limit: int = Query(300, ge=10, le=1000, description="Number of candles"),
    start_time: Optional[datetime] = Query(None, description="Start UTC datetime filter"),
    end_time: Optional[datetime] = Query(None, description="End UTC datetime filter"),
    db: AsyncSession = Depends(get_db)
):
    """Retrieve historical candlestick data enriched with technical indicators."""
    data = await market_service.get_klines_with_indicators(
        db=db,
        symbol=symbol,
        timeframe=timeframe,
        limit=limit,
        start_time=start_time,
        end_time=end_time
    )
    return data


@router.post("/sync", response_model=SyncResponseSchema)
async def trigger_sync(
    payload: SyncRequestSchema,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """Trigger manual or incremental synchronization from Binance API."""
    try:
        result = await sync_service.sync_incremental(
            db=db,
            symbol=payload.symbol,
            timeframe=payload.timeframe,
            lookback_days_if_empty=payload.lookback_days
        )
        return SyncResponseSchema(
            symbol=payload.symbol,
            timeframe=payload.timeframe,
            added_candles=result["added_candles"],
            status=result["status"],
            message=f"Successfully synced {result['added_candles']} candles for {payload.symbol} {payload.timeframe}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Synchronization failed: {str(e)}")
