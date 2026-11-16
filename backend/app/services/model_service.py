"""Model training, walk-forward evaluation, and promotion orchestration service."""

import asyncio
from typing import Dict, Any
import pandas as pd
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.core.logging import get_logger
from backend.app.models.market import Kline
from backend.app.services.governance_service import GovernanceService
from backend.app.services.sync_service import BinanceSyncService
from ml.features import prepare_supervised_dataset
from ml.models import CryptoTimeSeriesModel
from ml.evaluation import walk_forward_evaluate
from ml.registry import ModelRegistry

logger = get_logger("ModelService")


class ModelService:
    """Orchestrates resource-bounded CPU training, walk-forward CV, gating, and registration."""

    def __init__(self):
        self.registry = ModelRegistry()
        self.sync_service = BinanceSyncService()

    async def train_model_pipeline(
        self,
        db: AsyncSession,
        symbol: str,
        timeframe: str,
        horizon_steps: int = 6,
        model_type: str = "gradient_boosting",
        n_splits: int = 4,
    ) -> Dict[str, Any]:
        """Execute bounded ML pipeline off the async event loop."""
        symbol = symbol.upper()
        max_rows = settings.resources.ml_max_train_rows

        stmt = (
            select(Kline)
            .where(and_(Kline.symbol == symbol, Kline.timeframe == timeframe))
            .order_by(Kline.open_time.desc())
            .limit(max_rows)
        )
        res = await db.execute(stmt)
        klines = list(reversed(res.scalars().all()))

        if len(klines) < settings.ml.min_training_samples:
            logger.info(f"Insufficient samples ({len(klines)}). Backfilling from Binance for {symbol} {timeframe}...")
            await self.sync_service.sync_incremental(db, symbol, timeframe, lookback_days_if_empty=60)
            res = await db.execute(stmt)
            klines = list(reversed(res.scalars().all()))

        if len(klines) < 100:
            raise ValueError(f"Need at least 100 candles to train. Only {len(klines)} available for {symbol} {timeframe}")

        df = pd.DataFrame([
            {
                "open_time": k.open_time,
                "open": k.open,
                "high": k.high,
                "low": k.low,
                "close": k.close,
                "volume": k.volume,
            }
            for k in klines
        ])

        def _cpu_train_and_eval():
            supervised_df, feature_cols, _ = prepare_supervised_dataset(df, horizon_steps=horizon_steps)
            if len(supervised_df) < 50:
                raise ValueError("Supervised dataset too small after indicator warmup and horizon shifts.")

            eval_results = walk_forward_evaluate(
                df=supervised_df,
                feature_cols=feature_cols,
                horizon_steps=horizon_steps,
                n_splits=n_splits,
                model_type=model_type,
            )

            final_model = CryptoTimeSeriesModel(model_type=model_type, horizon_steps=horizon_steps)
            final_model.fit(
                X_train=supervised_df,
                y_return=supervised_df["target_return"],
                y_direction=supervised_df["target_direction"],
                feature_cols=feature_cols,
            )
            return supervised_df, feature_cols, eval_results, final_model

        supervised_df, feature_cols, eval_results, final_model = await asyncio.to_thread(_cpu_train_and_eval)

        train_start = supervised_df["open_time"].iloc[0].to_pydatetime()
        train_end = supervised_df["open_time"].iloc[-1].to_pydatetime()
        train_count = len(supervised_df)

        entry, is_promoted = await self.registry.register_and_gate_model(
            db=db,
            model=final_model,
            symbol=symbol,
            timeframe=timeframe,
            horizon_steps=horizon_steps,
            train_start=train_start,
            train_end=train_end,
            train_count=train_count,
            eval_results=eval_results,
        )
        await GovernanceService.record_lineage_edge(
            db,
            source_dataset="gold_feature_sets",
            target_dataset="forecast_records",
            transformation=f"train_{model_type}_walk_forward",
            records_in=train_count,
            records_out=1,
            metadata={"model_id": entry.model_id, "is_active": is_promoted},
        )
        await db.commit()

        return {
            "model_id": entry.model_id,
            "symbol": symbol,
            "timeframe": timeframe,
            "horizon_steps": horizon_steps,
            "is_active": is_promoted,
            "evaluation": eval_results,
            "feature_count": len(feature_cols),
            "train_samples": train_count,
            "feature_importances": final_model.get_feature_importances(),
        }
