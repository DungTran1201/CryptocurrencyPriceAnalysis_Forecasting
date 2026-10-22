"""Exploratory and Quantitative Market Analytics endpoints."""

from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db
from backend.app.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("/returns", summary="Calculate return distributions, moments, and histogram")
async def get_returns_distribution(
    symbol: str = Query("BTCUSDT", description="Crypto symbol"),
    timeframe: str = Query("1h", description="Candlestick interval"),
    limit: int = Query(500, ge=10, le=2000, description="Historical candle sample size"),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Returns parametric & empirical return metrics: mean, std, skewness, kurtosis, VaR, and histogram."""
    return await AnalyticsService.get_returns_distribution(
        db, symbol=symbol, timeframe=timeframe, limit=limit
    )


@router.get("/volatility", summary="Compute multi-window rolling realized volatility")
async def get_rolling_volatility(
    symbol: str = Query("BTCUSDT", description="Crypto symbol"),
    timeframe: str = Query("1h", description="Candlestick interval"),
    limit: int = Query(500, ge=30, le=2000, description="Historical candle sample size"),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Returns annualized rolling volatility series across 7, 14, and 30-period lookback windows."""
    return await AnalyticsService.get_rolling_volatility(
        db, symbol=symbol, timeframe=timeframe, windows=[7, 14, 30], limit=limit
    )


@router.get("/drawdowns", summary="Compute historical drawdown series and maximum drawdown (MDD)")
async def get_drawdowns(
    symbol: str = Query("BTCUSDT", description="Crypto symbol"),
    timeframe: str = Query("1h", description="Candlestick interval"),
    limit: int = Query(500, ge=10, le=2000, description="Historical candle sample size"),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Returns price peak progression, current drawdown, peak/trough dates, and maximum drawdown."""
    return await AnalyticsService.get_drawdowns(
        db, symbol=symbol, timeframe=timeframe, limit=limit
    )


@router.get("/correlations", summary="Compute pairwise Pearson cross-asset correlation matrix")
async def get_correlation_matrix(
    symbols: Optional[str] = Query("BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT", description="Comma-separated symbols"),
    timeframe: str = Query("1h", description="Candle interval"),
    limit: int = Query(300, ge=30, le=1000, description="Lookback bars per asset"),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Calculates Pearson correlation coefficients on aligned timestamp returns for specified symbols."""
    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()] if symbols else ["BTCUSDT", "ETHUSDT"]
    return await AnalyticsService.get_correlation_matrix(
        db, symbols=symbol_list, timeframe=timeframe, limit=limit
    )
