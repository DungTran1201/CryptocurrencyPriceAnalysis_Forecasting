"""Exploratory and Quantitative Market Analytics endpoints."""

from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db
from backend.app.core.security import validate_symbol, validate_timeframe
from backend.app.services.analytics_service import AnalyticsService
from backend.app.streaming.runtime import stream_runtime

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("/returns", summary="Calculate return distributions, moments, VaR/CVaR, ATR, VWAP, and histogram")
async def get_returns_distribution(
    symbol: str = Query("BTCUSDT", description="Crypto symbol"),
    timeframe: str = Query("1h", description="Candlestick interval"),
    limit: int = Query(500, ge=10, le=2000, description="Historical candle sample size"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Return parametric & empirical return metrics: mean, std, skew, kurtosis, VaR, CVaR, ATR, VWAP, histogram."""
    sym = validate_symbol(symbol)
    tf = validate_timeframe(timeframe)
    return await AnalyticsService.get_returns_distribution(db, symbol=sym, timeframe=tf, limit=limit)


@router.get("/volatility", summary="Compute multi-window rolling realized volatility")
async def get_rolling_volatility(
    symbol: str = Query("BTCUSDT", description="Crypto symbol"),
    timeframe: str = Query("1h", description="Candlestick interval"),
    limit: int = Query(500, ge=30, le=2000, description="Historical candle sample size"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Return annualized rolling volatility series across 7, 14, and 30-period lookback windows."""
    sym = validate_symbol(symbol)
    tf = validate_timeframe(timeframe)
    return await AnalyticsService.get_rolling_volatility(
        db, symbol=sym, timeframe=tf, windows=[7, 14, 30], limit=limit
    )


@router.get("/drawdowns", summary="Compute historical drawdown series and maximum drawdown (MDD)")
async def get_drawdowns(
    symbol: str = Query("BTCUSDT", description="Crypto symbol"),
    timeframe: str = Query("1h", description="Candlestick interval"),
    limit: int = Query(500, ge=10, le=2000, description="Historical candle sample size"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Return price peak progression, current drawdown, peak/trough dates, and maximum drawdown."""
    sym = validate_symbol(symbol)
    tf = validate_timeframe(timeframe)
    return await AnalyticsService.get_drawdowns(db, symbol=sym, timeframe=tf, limit=limit)


@router.get("/correlations", summary="Compute pairwise Pearson correlation & covariance matrices")
async def get_correlation_matrix(
    symbols: Optional[str] = Query("BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT", description="Comma-separated symbols"),
    timeframe: str = Query("1h", description="Candle interval"),
    limit: int = Query(300, ge=30, le=1000, description="Lookback bars per asset"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Calculate Pearson correlation coefficients and sample covariance on aligned returns."""
    tf = validate_timeframe(timeframe)
    symbol_list = [validate_symbol(s) for s in symbols.split(",") if s.strip()] if symbols else ["BTCUSDT", "ETHUSDT"]
    return await AnalyticsService.get_correlation_matrix(
        db, symbols=symbol_list[:10], timeframe=tf, limit=limit
    )


@router.get("/incremental", summary="Inspect real-time per-symbol incremental streaming analytics state")
async def get_incremental_snapshots() -> Dict[str, Any]:
    """Return current in-memory O(1) rolling technical & risk analytics per active stream symbol."""
    return {
        "snapshots": stream_runtime.analytics_engine.all_snapshots(),
    }
