"""Market analytics service: Candles, Technical Indicators, and Aggregation."""

from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import numpy as np
import pandas as pd
from sqlalchemy import select, and_, func
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.market import Symbol, Kline, SyncCheckpoint
from ml.features import compute_sma, compute_ema, compute_rsi, compute_bollinger_bands, compute_macd


class MarketService:
    """Provides market candlestick querying, indicator computation, and symbol statistics."""

    async def get_symbols(self, db: AsyncSession) -> List[Dict[str, Any]]:
        """List all active symbols with their latest sync status and 24h price summary.
        
        Uses a batched window query to fetch the last 24 1h candles for all symbols at once,
        preventing N+1 database queries.
        """
        stmt = select(Symbol).where(Symbol.is_active == True)
        res = await db.execute(stmt)
        symbols = res.scalars().all()
        if not symbols:
            return []

        active_symbols = [s.symbol for s in symbols]

        # Batch load up to 24 most recent 1h candles per symbol using window function
        rn_col = func.row_number().over(
            partition_by=Kline.symbol,
            order_by=Kline.open_time.desc()
        ).label("rn")

        ranked_subquery = select(
            Kline.id,
            Kline.symbol,
            Kline.timeframe,
            Kline.open_time,
            Kline.close_time,
            Kline.open,
            Kline.high,
            Kline.low,
            Kline.close,
            Kline.volume,
            Kline.is_closed,
            rn_col
        ).where(
            and_(
                Kline.symbol.in_(active_symbols),
                Kline.timeframe == "1h"
            )
        ).subquery()

        kline_alias = aliased(Kline, ranked_subquery)
        batch_stmt = select(kline_alias).where(
            ranked_subquery.c.rn <= 24
        ).order_by(kline_alias.symbol, kline_alias.open_time.asc())

        k_res = await db.execute(batch_stmt)
        all_klines = k_res.scalars().all()

        klines_by_sym: Dict[str, List[Kline]] = {s.symbol: [] for s in symbols}
        for k in all_klines:
            klines_by_sym[k.symbol].append(k)

        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        symbol_list = []
        for s in symbols:
            klines = klines_by_sym.get(s.symbol, [])
            candle_count = len(klines)

            if not klines:
                symbol_list.append({
                    "symbol": s.symbol,
                    "base_asset": s.base_asset,
                    "quote_asset": s.quote_asset,
                    "current_price": None,
                    "change_24h": None,
                    "high_24h": None,
                    "low_24h": None,
                    "volume_24h": None,
                    "candle_count_24h": 0,
                    "has_full_24h": False,
                    "data_status": "UNAVAILABLE",
                    "last_synced_at": s.last_synced_at
                })
            else:
                current_price = klines[-1].close
                price_reference = klines[0].open
                change_24h = ((current_price - price_reference) / price_reference * 100.0) if price_reference > 0 else 0.0
                high_24h = max([k.high for k in klines])
                low_24h = min([k.low for k in klines])
                volume_24h = sum([k.volume for k in klines])
                has_full_24h = (candle_count >= 24)

                # Determine freshness / status
                is_stale = False
                if s.last_synced_at:
                    if (now_utc - s.last_synced_at).total_seconds() > 7200:  # > 2 hours
                        is_stale = True

                if is_stale:
                    status = "STALE"
                elif has_full_24h:
                    status = "SYNCHRONIZED"
                else:
                    status = "PARTIAL"

                symbol_list.append({
                    "symbol": s.symbol,
                    "base_asset": s.base_asset,
                    "quote_asset": s.quote_asset,
                    "current_price": round(current_price, 2),
                    "change_24h": round(change_24h, 2),
                    "high_24h": round(high_24h, 2),
                    "low_24h": round(low_24h, 2),
                    "volume_24h": round(volume_24h, 2),
                    "candle_count_24h": candle_count,
                    "has_full_24h": has_full_24h,
                    "data_status": status,
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
            return {
                "symbol": symbol,
                "timeframe": timeframe,
                "count": 0,
                "candles": [],
                "indicators": {}
            }

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
        n_candles = len(close_series)

        indicators: Dict[str, Any] = {}

        # 1. SMAs
        for p in sma_periods:
            if n_candles >= p:
                sma_vals = compute_sma(close_series, p)
                indicators[f"SMA_{p}"] = [None if np.isnan(v) else round(v, 2) for v in sma_vals]
            else:
                indicators[f"SMA_{p}"] = [None] * n_candles

        # 2. EMAs
        for p in ema_periods:
            if n_candles >= p:
                ema_vals = compute_ema(close_series, p)
                indicators[f"EMA_{p}"] = [None if np.isnan(v) else round(v, 2) for v in ema_vals]
            else:
                indicators[f"EMA_{p}"] = [None] * n_candles

        # 3. Bollinger Bands
        if include_bollinger:
            if n_candles >= 20:
                mid, up, low, pct_b = compute_bollinger_bands(close_series, window=20, num_std=2.0)
                indicators["BOLL_MID"] = [None if np.isnan(v) else round(v, 2) for v in mid]
                indicators["BOLL_UPPER"] = [None if np.isnan(v) else round(v, 2) for v in up]
                indicators["BOLL_LOWER"] = [None if np.isnan(v) else round(v, 2) for v in low]
            else:
                indicators["BOLL_MID"] = [None] * n_candles
                indicators["BOLL_UPPER"] = [None] * n_candles
                indicators["BOLL_LOWER"] = [None] * n_candles

        # 4. RSI
        if include_rsi:
            if n_candles >= 14:
                rsi_vals = compute_rsi(close_series, window=14)
                indicators["RSI_14"] = [None if np.isnan(v) else round(v, 2) for v in rsi_vals]
            else:
                indicators["RSI_14"] = [None] * n_candles

        # 5. MACD
        if include_macd:
            if n_candles >= 26:
                m_line, s_line, h_line = compute_macd(close_series)
                indicators["MACD_LINE"] = [None if np.isnan(v) else round(v, 2) for v in m_line]
                indicators["MACD_SIGNAL"] = [None if np.isnan(v) else round(v, 2) for v in s_line]
                indicators["MACD_HIST"] = [None if np.isnan(v) else round(v, 2) for v in h_line]
            else:
                indicators["MACD_LINE"] = [None] * n_candles
                indicators["MACD_SIGNAL"] = [None] * n_candles
                indicators["MACD_HIST"] = [None] * n_candles

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "count": len(df),
            "candles": df.to_dict(orient="records"),
            "indicators": indicators
        }

