"""Market & Exploratory Analytics Service.

Implements institutional quantitative analytics on real market records:
- Log and simple return distributions with parametric & empirical statistics:
  mean, median, standard deviation, skewness, kurtosis, Value-at-Risk (95%, 99%)
- Binned return frequency distributions for histograms
- Multi-window rolling realized volatility (annualized)
- Cumulative drawdown series, peak-to-trough duration, and maximum drawdown (MDD)
- Pairwise Pearson cross-asset correlation matrix for aligned return series
"""

from datetime import datetime, timezone
import math
from typing import List, Dict, Any, Optional
import numpy as np
from scipy import stats
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.logging import get_logger
from backend.app.models.market import Kline

logger = get_logger("AnalyticsService")

# Periods per year for annualizing volatility
PERIODS_PER_YEAR = {
    "1m": 365 * 24 * 60,
    "5m": 365 * 24 * 12,
    "15m": 365 * 24 * 4,
    "30m": 365 * 24 * 2,
    "1h": 365 * 24,
    "2h": 365 * 12,
    "4h": 365 * 6,
    "1d": 365,
    "1w": 52
}


class AnalyticsService:
    """Service for computing descriptive and quantitative statistics from historical candles."""

    @staticmethod
    async def get_returns_distribution(
        db: AsyncSession,
        symbol: str,
        timeframe: str,
        limit: int = 500
    ) -> Dict[str, Any]:
        """Compute return distribution metrics and histogram frequencies from stored candles."""
        symbol = symbol.upper()
        stmt = (
            select(Kline)
            .where(and_(Kline.symbol == symbol, Kline.timeframe == timeframe))
            .order_by(Kline.open_time.desc())
            .limit(limit)
        )
        res = await db.execute(stmt)
        klines = list(reversed(res.scalars().all()))

        if len(klines) < 3:
            return {
                "symbol": symbol,
                "timeframe": timeframe,
                "count": len(klines),
                "has_sufficient_data": False,
                "message": "Insufficient historical candles to compute return distributions (minimum 3 required)."
            }

        closes = np.array([k.close for k in klines], dtype=np.float64)
        simple_returns = (closes[1:] - closes[:-1]) / closes[:-1]
        log_returns = np.log(closes[1:] / closes[:-1])

        # Remove inf/nan if any
        valid_mask = np.isfinite(simple_returns)
        simple_returns = simple_returns[valid_mask]
        log_returns = log_returns[valid_mask]

        if len(simple_returns) < 3:
            return {
                "symbol": symbol,
                "timeframe": timeframe,
                "count": len(simple_returns),
                "has_sufficient_data": False,
                "message": "Insufficient valid return observations."
            }

        # Distribution metrics
        mean_ret = float(np.mean(simple_returns))
        median_ret = float(np.median(simple_returns))
        std_ret = float(np.std(simple_returns, ddof=1))
        var_ret = float(np.var(simple_returns, ddof=1))
        skew_ret = float(stats.skew(simple_returns))
        kurt_ret = float(stats.kurtosis(simple_returns))  # Fisher's kurtosis (normal == 0)

        p25 = float(np.percentile(simple_returns, 25))
        p75 = float(np.percentile(simple_returns, 75))
        min_ret = float(np.min(simple_returns))
        max_ret = float(np.max(simple_returns))

        # Value at Risk (Historical empirical)
        var_95 = float(np.percentile(simple_returns, 5))
        var_99 = float(np.percentile(simple_returns, 1))

        # Histogram generation (25 bins)
        hist_counts, bin_edges = np.histogram(simple_returns, bins=25)
        bins_data = []
        for i in range(len(hist_counts)):
            center = (bin_edges[i] + bin_edges[i + 1]) / 2.0
            bins_data.append({
                "bin_start": round(float(bin_edges[i]) * 100, 3),
                "bin_end": round(float(bin_edges[i + 1]) * 100, 3),
                "bin_center": round(float(center) * 100, 3),
                "count": int(hist_counts[i])
            })

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "count": len(simple_returns),
            "has_sufficient_data": True,
            "start_time": klines[0].open_time.isoformat(),
            "end_time": klines[-1].open_time.isoformat(),
            "metrics": {
                "mean_pct": round(mean_ret * 100.0, 4),
                "median_pct": round(median_ret * 100.0, 4),
                "std_pct": round(std_ret * 100.0, 4),
                "variance_pct": round(var_ret * 100.0, 6),
                "skewness": round(skew_ret, 3),
                "kurtosis": round(kurt_ret, 3),
                "min_pct": round(min_ret * 100.0, 3),
                "max_pct": round(max_ret * 100.0, 3),
                "p25_pct": round(p25 * 100.0, 3),
                "p75_pct": round(p75 * 100.0, 3),
                "var_95_pct": round(var_95 * 100.0, 3),
                "var_99_pct": round(var_99 * 100.0, 3),
            },
            "histogram": bins_data
        }

    @staticmethod
    async def get_rolling_volatility(
        db: AsyncSession,
        symbol: str,
        timeframe: str,
        windows: List[int] = [7, 14, 30],
        limit: int = 500
    ) -> Dict[str, Any]:
        """Compute rolling realized volatility across multiple lookback windows."""
        symbol = symbol.upper()
        stmt = (
            select(Kline)
            .where(and_(Kline.symbol == symbol, Kline.timeframe == timeframe))
            .order_by(Kline.open_time.desc())
            .limit(limit)
        )
        res = await db.execute(stmt)
        klines = list(reversed(res.scalars().all()))

        if len(klines) < max(windows) + 2:
            return {
                "symbol": symbol,
                "timeframe": timeframe,
                "has_sufficient_data": False,
                "series": []
            }

        closes = np.array([k.close for k in klines], dtype=np.float64)
        returns = (closes[1:] - closes[:-1]) / closes[:-1]
        dates = [k.open_time.isoformat() for k in klines[1:]]

        annualize_factor = math.sqrt(PERIODS_PER_YEAR.get(timeframe.lower(), 365 * 24))

        series = []
        max_win = max(windows)
        for i in range(max_win, len(returns)):
            point: Dict[str, Any] = {"timestamp": dates[i]}
            for w in windows:
                win_slice = returns[i - w:i]
                std_w = np.std(win_slice, ddof=1)
                annualized_vol = std_w * annualize_factor * 100.0
                point[f"vol_{w}"] = round(float(annualized_vol), 2)
            series.append(point)

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "has_sufficient_data": True,
            "windows": windows,
            "current_annualized_vol": series[-1] if series else None,
            "series": series
        }

    @staticmethod
    async def get_drawdowns(
        db: AsyncSession,
        symbol: str,
        timeframe: str,
        limit: int = 500
    ) -> Dict[str, Any]:
        """Compute cumulative peak, drawdown percentage series, and max drawdown (MDD)."""
        symbol = symbol.upper()
        stmt = (
            select(Kline)
            .where(and_(Kline.symbol == symbol, Kline.timeframe == timeframe))
            .order_by(Kline.open_time.desc())
            .limit(limit)
        )
        res = await db.execute(stmt)
        klines = list(reversed(res.scalars().all()))

        if len(klines) < 2:
            return {
                "symbol": symbol,
                "timeframe": timeframe,
                "has_sufficient_data": False,
                "series": []
            }

        closes = [k.close for k in klines]
        dates = [k.open_time.isoformat() for k in klines]

        peak = closes[0]
        peak_date = dates[0]
        max_dd = 0.0
        max_dd_peak_date = dates[0]
        max_dd_trough_date = dates[0]

        series = []
        for i in range(len(closes)):
            price = closes[i]
            if price > peak:
                peak = price
                peak_date = dates[i]

            dd = (price - peak) / peak if peak > 0 else 0.0
            dd_pct = dd * 100.0

            if dd < max_dd:
                max_dd = dd
                max_dd_peak_date = peak_date
                max_dd_trough_date = dates[i]

            series.append({
                "timestamp": dates[i],
                "price": price,
                "peak": round(peak, 2),
                "drawdown_pct": round(dd_pct, 2)
            })

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "has_sufficient_data": True,
            "max_drawdown_pct": round(max_dd * 100.0, 2),
            "max_drawdown_peak_date": max_dd_peak_date,
            "max_drawdown_trough_date": max_dd_trough_date,
            "current_drawdown_pct": series[-1]["drawdown_pct"] if series else 0.0,
            "series": series
        }

    @staticmethod
    async def get_correlation_matrix(
        db: AsyncSession,
        symbols: Optional[List[str]] = None,
        timeframe: str = "1h",
        limit: int = 300
    ) -> Dict[str, Any]:
        """Compute pairwise Pearson correlation matrix for aligned returns across symbols."""
        if not symbols:
            symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]

        symbol_returns: Dict[str, Dict[datetime, float]] = {}

        for sym in symbols:
            stmt = (
                select(Kline.open_time, Kline.close)
                .where(and_(Kline.symbol == sym.upper(), Kline.timeframe == timeframe))
                .order_by(Kline.open_time.desc())
                .limit(limit)
            )
            res = await db.execute(stmt)
            rows = list(reversed(res.all()))
            if len(rows) > 1:
                ret_dict = {}
                for i in range(1, len(rows)):
                    prev_c = rows[i - 1][1]
                    curr_c = rows[i][1]
                    if prev_c > 0:
                        ret_dict[rows[i][0]] = (curr_c - prev_c) / prev_c
                symbol_returns[sym.upper()] = ret_dict

        available_symbols = [s for s in symbols if s in symbol_returns and len(symbol_returns[s]) > 10]

        if len(available_symbols) < 2:
            return {
                "symbols": symbols,
                "available_symbols": available_symbols,
                "has_sufficient_data": False,
                "message": "Need at least 2 symbols with > 10 stored candles to calculate correlation matrix.",
                "matrix": []
            }

        # Find intersecting timestamps
        common_times = set.intersection(*(set(symbol_returns[s].keys()) for s in available_symbols))
        sorted_times = sorted(list(common_times))

        if len(sorted_times) < 10:
            return {
                "symbols": available_symbols,
                "available_symbols": available_symbols,
                "has_sufficient_data": False,
                "message": f"Only {len(sorted_times)} overlapping timestamps found (minimum 10 required).",
                "matrix": []
            }

        # Build data vectors
        vectors = []
        for s in available_symbols:
            vec = [symbol_returns[s][t] for t in sorted_times]
            vectors.append(vec)

        corr_matrix = np.corrcoef(vectors)

        formatted_matrix = []
        for i, s1 in enumerate(available_symbols):
            row = {"symbol": s1}
            for j, s2 in enumerate(available_symbols):
                coef = corr_matrix[i, j]
                row[s2] = round(float(coef), 3) if not np.isnan(coef) else 0.0
            formatted_matrix.append(row)

        return {
            "symbols": available_symbols,
            "timeframe": timeframe,
            "observations_count": len(sorted_times),
            "has_sufficient_data": True,
            "matrix": formatted_matrix
        }
