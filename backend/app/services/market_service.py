"""Market analytics service: Candles, Technical Indicators, and Aggregation."""

from datetime import datetime
from typing import List, Dict, Any, Optional
import numpy as np
import pandas as pd
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.market import Symbol, Kline, SyncCheckpoint
from ml.features import compute_sma, compute_ema, compute_rsi, compute_bollinger_bands, compute_macd


class MarketService:
    """Provides market candlestick querying, indicator computation, and symbol statistics."""

    async def get_symbols(self, db: AsyncSession) -> List[Dict[str, Any]]:
        """List all active symbols with their latest sync status and 24h price summary."""
        # Query default registered symbols
        stmt = select(Symbol).where(Symbol.is_active == True)
        res = await db.execute(stmt)
        symbols = res.scalars().all()

        symbol_list = []
        for s in symbols:
            # Get latest 24h stats from Kline table
            latest_kline_stmt = select(Kline).where(
                and_(Kline.symbol == s.symbol, Kline.timeframe == "1h")
            ).order_by(Kline.open_time.desc()).limit(24)
            k_res = await db.execute(latest_kline_stmt)
            klines = list(reversed(k_res.scalars().all()))

            current_price = klines[-1].close if klines else 0.0
            price_24h_ago = klines[0].open if len(klines) >= 24 else (klines[0].open if klines else current_price)
            change_24h = ((current_price - price_24h_ago) / price_24h_ago * 100.0) if price_24h_ago > 0 else 0.0
            high_24h = max([k.high for k in klines]) if klines else current_price
            low_24h = min([k.low for k in klines]) if klines else current_price
            volume_24h = sum([k.volume for k in klines]) if klines else 0.0

            symbol_list.append({
                "symbol": s.symbol,
                "base_asset": s.base_asset,
                "quote_asset": s.quote_asset,
                "current_price": round(current_price, 2),
                "change_24h": round(change_24h, 2),
                "high_24h": round(high_24h, 2),
                "low_24h": round(low_24h, 2),
                "volume_24h": round(volume_24h, 2),
                "last_synced_at": s.last_synced_at
            })
        return symbol_list

    async def get_klines_with_indicators(
        self,
        db: AsyncSession,
        symbol: str,
        timeframe: str,
        limit: int = 300,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        sma_periods: Optional[List[int]] = None,
        ema_periods: Optional[List[int]] = None,
        include_bollinger: bool = True,
        include_rsi: bool = True,
        include_macd: bool = True
    ) -> Dict[str, Any]:
        """Fetch historical candles and attach requested technical indicators."""
        symbol = symbol.upper()
        sma_periods = sma_periods or [7, 25, 99]
        ema_periods = ema_periods or [12, 26]

        query = select(Kline).where(
            and_(
                Kline.symbol == symbol,
                Kline.timeframe == timeframe
            )
        )
        if start_time:
            query = query.where(Kline.open_time >= start_time)
        if end_time:
            query = query.where(Kline.open_time <= end_time)

        query = query.order_by(Kline.open_time.desc()).limit(limit)
        res = await db.execute(query)
        klines = list(reversed(res.scalars().all()))

        if not klines:
            return {"symbol": symbol, "timeframe": timeframe, "candles": [], "indicators": {}}

        df = pd.DataFrame([
            {
                "open_time": k.open_time.isoformat(),
                "open": k.open,
                "high": k.high,
                "low": k.low,
                "close": k.close,
                "volume": k.volume,
                "close_time": k.close_time.isoformat(),
                "is_closed": k.is_closed
            }
            for k in klines
        ])
        close_series = pd.Series([k.close for k in klines])

        indicators: Dict[str, Any] = {}

        # 1. SMAs
        for p in sma_periods:
            if len(close_series) >= p:
                sma_vals = compute_sma(close_series, p)
                indicators[f"SMA_{p}"] = [None if np.isnan(v) else round(v, 2) for v in sma_vals]

        # 2. EMAs
        for p in ema_periods:
            if len(close_series) >= p:
                ema_vals = compute_ema(close_series, p)
                indicators[f"EMA_{p}"] = [None if np.isnan(v) else round(v, 2) for v in ema_vals]

        # 3. Bollinger Bands
        if include_bollinger and len(close_series) >= 20:
            mid, up, low, pct_b = compute_bollinger_bands(close_series, window=20, num_std=2.0)
            indicators["BOLL_MID"] = [None if np.isnan(v) else round(v, 2) for v in mid]
            indicators["BOLL_UPPER"] = [None if np.isnan(v) else round(v, 2) for v in up]
            indicators["BOLL_LOWER"] = [None if np.isnan(v) else round(v, 2) for v in low]

        # 4. RSI
        if include_rsi and len(close_series) >= 14:
            rsi_vals = compute_rsi(close_series, window=14)
            indicators["RSI_14"] = [None if np.isnan(v) else round(v, 2) for v in rsi_vals]

        # 5. MACD
        if include_macd and len(close_series) >= 26:
            m_line, s_line, h_line = compute_macd(close_series)
            indicators["MACD_LINE"] = [None if np.isnan(v) else round(v, 2) for v in m_line]
            indicators["MACD_SIGNAL"] = [None if np.isnan(v) else round(v, 2) for v in s_line]
            indicators["MACD_HIST"] = [None if np.isnan(v) else round(v, 2) for v in h_line]

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "count": len(df),
            "candles": df.to_dict(orient="records"),
            "indicators": indicators
        }
