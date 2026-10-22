"""Forecast generation, persistence, and realization reconciliation service."""

from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
import pandas as pd
from sqlalchemy import select, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.core.logging import get_logger
from backend.app.models.market import Kline
from backend.app.models.forecast import ForecastRecord
from backend.app.services.sync_service import BinanceSyncService, get_interval_delta
from ml.features import extract_features
from ml.baselines import NaivePersistenceBaseline, RollingMeanBaseline
from ml.registry import ModelRegistry

logger = get_logger("ForecastService")


class ForecastService:
    """Manages forecast generation, persistence, and realization audit logs."""

    def __init__(self):
        self.registry = ModelRegistry()
        self.sync_service = BinanceSyncService()

    async def get_recent_candles_df(
        self,
        db: AsyncSession,
        symbol: str,
        timeframe: str,
        limit: int = 150
    ) -> pd.DataFrame:
        """Fetch recent candles as a clean DataFrame sorted chronologically."""
        stmt = select(Kline).where(
            and_(
                Kline.symbol == symbol.upper(),
                Kline.timeframe == timeframe
            )
        ).order_by(Kline.open_time.desc()).limit(limit)
        
        res = await db.execute(stmt)
        klines = res.scalars().all()

        if not klines:
            # Sync fresh batch from Binance if database is empty
            logger.info(f"Database empty for {symbol} {timeframe}. Triggering instant seed fetch...")
            await self.sync_service.sync_incremental(db, symbol, timeframe, lookback_days_if_empty=15)
            res = await db.execute(stmt)
            klines = res.scalars().all()

        if not klines:
            raise ValueError(f"Insufficient candle history available for {symbol} {timeframe}")

        # Reverse to chronological order (oldest to newest)
        klines = list(reversed(klines))

        records = [
            {
                "open_time": k.open_time,
                "open": k.open,
                "high": k.high,
                "low": k.low,
                "close": k.close,
                "volume": k.volume
            }
            for k in klines
        ]
        return pd.DataFrame(records)

    async def generate_forecast(
        self,
        db: AsyncSession,
        symbol: str,
        timeframe: str,
        horizon_steps: int = 6
    ) -> ForecastRecord:
        """Generate a production forecast and persist immutable record to database."""
        symbol = symbol.upper()
        df = await self.get_recent_candles_df(db, symbol, timeframe, limit=120)
        
        cutoff_candle = df.iloc[-1]
        cutoff_time = cutoff_candle["open_time"]
        current_price = float(cutoff_candle["close"])
        
        # Calculate target time: cutoff_time + (horizon_steps * interval_delta)
        delta = get_interval_delta(timeframe)
        target_time = cutoff_time + (delta * horizon_steps)

        # Check for active registered model
        active_pair = await self.registry.get_active_model(db, symbol, timeframe, horizon_steps)

        if active_pair:
            model_entry, model = active_pair
            model_id = model_entry.model_id
            model_ver = model_entry.version
            
            features_df = extract_features(df)
            pred_prices, pred_returns, probs, lower_bounds, upper_bounds = model.predict(features_df)
            
            pred_price = float(pred_prices[-1])
            pred_return = float(pred_returns[-1])
            prob_up = float(probs[-1])
            lower_b = float(lower_bounds[-1])
            upper_b = float(upper_bounds[-1])
        else:
            # High-reliability fallback: Rolling Mean Baseline
            baseline = RollingMeanBaseline(window=14)
            pred_prices, pred_returns, probs = baseline.predict(df)
            
            model_id = "baseline_sma_14"
            model_ver = "1.0.0"
            pred_price = float(pred_prices[-1])
            pred_return = float(pred_returns[-1])
            prob_up = float(probs[-1])
            
            # Simple bounds based on recent ATR
            half_width = current_price * 0.02
            lower_b = pred_price - half_width
            upper_b = pred_price + half_width

        # Direction determination
        if abs(pred_return) < 0.001:
            direction = "FLAT"
        elif pred_return > 0:
            direction = "UP"
        else:
            direction = "DOWN"

        # Persist immutable forecast record
        forecast = ForecastRecord(
            model_id=model_id,
            model_version=model_ver,
            symbol=symbol,
            timeframe=timeframe,
            horizon_steps=horizon_steps,
            data_cutoff_time=cutoff_time,
            forecast_timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
            target_time=target_time,
            current_price=current_price,
            predicted_price=round(pred_price, 4),
            predicted_return_pct=round(pred_return * 100.0, 4),
            predicted_direction=direction,
            direction_probability=round(prob_up, 4),
            lower_bound_price=round(lower_b, 4),
            upper_bound_price=round(upper_b, 4),
            confidence_level=0.95,
            status="PENDING"
        )
        db.add(forecast)
        await db.commit()
        await db.refresh(forecast)

        logger.info(
            f"Forecast created: {symbol} {timeframe} target {target_time} | "
            f"Current: {current_price} -> Pred: {pred_price:.2f} ({direction}, P={prob_up:.2f})"
        )
        return forecast

    async def reconcile_pending_forecasts(self, db: AsyncSession) -> int:
        """Audit and reconcile pending forecasts whose target time has elapsed."""
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        
        # Query pending forecasts where target_time <= now_utc
        stmt = select(ForecastRecord).where(
            and_(
                ForecastRecord.status == "PENDING",
                ForecastRecord.target_time <= now_utc
            )
        )
        res = await db.execute(stmt)
        pending_list = res.scalars().all()

        reconciled_count = 0
        for f in pending_list:
            # Look for candle matching target_time
            candle_stmt = select(Kline).where(
                and_(
                    Kline.symbol == f.symbol,
                    Kline.timeframe == f.timeframe,
                    Kline.open_time >= f.target_time
                )
            ).order_by(Kline.open_time.asc()).limit(1)
            c_res = await db.execute(candle_stmt)
            realized_candle = c_res.scalar_one_or_none()

            if realized_candle:
                actual_price = realized_candle.close
                abs_err = abs(actual_price - f.predicted_price)
                pct_err = (abs_err / actual_price) * 100.0 if actual_price > 0 else 0.0

                actual_change = actual_price - f.current_price
                if abs(actual_change / f.current_price) < 0.001:
                    realized_dir = "FLAT"
                elif actual_change > 0:
                    realized_dir = "UP"
                else:
                    realized_dir = "DOWN"

                # Check if direction prediction was correct
                dir_correct = (f.predicted_direction == realized_dir)

                f.realized_price = round(actual_price, 4)
                f.realized_direction = realized_dir
                f.absolute_error = round(abs_err, 4)
                f.percentage_error = round(pct_err, 4)
                f.direction_correct = dir_correct
                f.status = "RECONCILED"
                f.reconciled_at = datetime.now(timezone.utc).replace(tzinfo=None)
                reconciled_count += 1

        if reconciled_count > 0:
            await db.commit()
            logger.info(f"Reconciled {reconciled_count} mature forecasts.")

        return reconciled_count
