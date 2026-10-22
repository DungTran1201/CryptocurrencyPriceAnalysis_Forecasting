"""Model Registry and Evaluation Gating Controller.

Manages model versioning, artifact persistence, evaluation gates, and activation.
"""

from datetime import datetime
import json
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
import joblib
from sqlalchemy import select, and_, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.core.logging import get_logger
from backend.app.models.ml_model import ModelRegistryEntry, ModelEvaluationMetric
from ml.models import CryptoTimeSeriesModel

logger = get_logger("ModelRegistry")


class ModelRegistry:
    """Handles model artifact lifecycle, versioning, and promotion gates."""

    def __init__(self, storage_dir: Optional[str] = None):
        self.storage_dir = Path(storage_dir or settings.ml.model_storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def generate_model_id(
        self,
        symbol: str,
        timeframe: str,
        horizon_steps: int,
        model_type: str
    ) -> str:
        """Create deterministic model identifier with timestamp."""
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        return f"{symbol.lower()}_{timeframe}_{horizon_steps}h_{model_type}_{ts}"

    def save_artifact(self, model: CryptoTimeSeriesModel, model_id: str) -> str:
        """Persist fitted model pipeline to disk."""
        filepath = self.storage_dir / f"{model_id}.joblib"
        joblib.dump(model, filepath)
        return str(filepath)

    def load_artifact(self, artifact_path: str) -> CryptoTimeSeriesModel:
        """Load fitted model pipeline from disk."""
        p = Path(artifact_path)
        if not p.exists():
            raise FileNotFoundError(f"Model artifact not found: {artifact_path}")
        return joblib.load(p)

    async def register_and_gate_model(
        self,
        db: AsyncSession,
        model: CryptoTimeSeriesModel,
        symbol: str,
        timeframe: str,
        horizon_steps: int,
        train_start: datetime,
        train_end: datetime,
        train_count: int,
        eval_results: Dict[str, Any]
    ) -> Tuple[ModelRegistryEntry, bool]:
        """Apply evaluation gates and register model in database."""
        symbol = symbol.upper()
        model_id = self.generate_model_id(symbol, timeframe, horizon_steps, model.model_type)
        artifact_path = self.save_artifact(model, model_id)

        candidate_metrics = eval_results["candidate"]
        naive_metrics = eval_results["naive_baseline"]
        improvement = eval_results.get("mae_improvement_pct", 0.0)

        # Evaluation Gates:
        # 1. Candidate MAE strictly better than Naive Baseline
        # 2. Improvement margin meets threshold (e.g. >= 1%)
        # 3. Directional accuracy >= threshold (e.g. >= 50%)
        passes_mae_gate = eval_results.get("beats_naive", False)
        passes_margin_gate = improvement >= (settings.ml.activation_margin_threshold * 100.0)
        passes_dir_gate = candidate_metrics["directional_accuracy"] >= settings.ml.min_direction_accuracy

        is_promoted = passes_mae_gate and passes_margin_gate and passes_dir_gate

        if is_promoted:
            # Deactivate previous active model for this symbol/timeframe/horizon
            deact_stmt = update(ModelRegistryEntry).where(
                and_(
                    ModelRegistryEntry.symbol == symbol,
                    ModelRegistryEntry.timeframe == timeframe,
                    ModelRegistryEntry.horizon_steps == horizon_steps,
                    ModelRegistryEntry.is_active == True
                )
            ).values(is_active=False)
            await db.execute(deact_stmt)
            logger.info(f"Model {model_id} passed all gates! Promoted to ACTIVE.")
        else:
            logger.warning(
                f"Model {model_id} failed gates (MAE: {passes_mae_gate}, Margin: {passes_margin_gate}, "
                f"Dir: {passes_dir_gate}). Registered as inactive candidate."
            )

        # Create registry entry
        entry = ModelRegistryEntry(
            model_id=model_id,
            name=f"{symbol} {model.model_type.title()} {horizon_steps}h",
            version=model.version,
            model_type=model.model_type,
            symbol=symbol,
            timeframe=timeframe,
            horizon_steps=horizon_steps,
            feature_names=json.dumps(model.feature_names),
            hyperparameters=json.dumps({"horizon_steps": horizon_steps, "confidence_level": model.confidence_level}),
            train_start_time=train_start,
            train_end_time=train_end,
            train_sample_count=train_count,
            is_active=is_promoted,
            artifact_path=artifact_path,
            created_at=datetime.utcnow()
        )
        db.add(entry)
        await db.flush()

        # Record evaluation metrics
        metric = ModelEvaluationMetric(
            model_id=model_id,
            split_type="walk_forward",
            mae=candidate_metrics["mae"],
            rmse=candidate_metrics["rmse"],
            mape=candidate_metrics["mape"],
            directional_accuracy=candidate_metrics["directional_accuracy"],
            brier_score=candidate_metrics["brier_score"],
            naive_mae=naive_metrics["mae"],
            mae_improvement_pct=improvement,
            beats_naive_baseline=passes_mae_gate,
            evaluated_at=datetime.utcnow()
        )
        db.add(metric)
        await db.commit()

        return entry, is_promoted

    async def get_active_model(
        self,
        db: AsyncSession,
        symbol: str,
        timeframe: str,
        horizon_steps: int
    ) -> Optional[Tuple[ModelRegistryEntry, CryptoTimeSeriesModel]]:
        """Retrieve the currently active production model."""
        stmt = select(ModelRegistryEntry).where(
            and_(
                ModelRegistryEntry.symbol == symbol.upper(),
                ModelRegistryEntry.timeframe == timeframe,
                ModelRegistryEntry.horizon_steps == horizon_steps,
                ModelRegistryEntry.is_active == True
            )
        ).order_by(ModelRegistryEntry.created_at.desc())
        res = await db.execute(stmt)
        entry = res.scalar_one_or_none()

        if not entry or not entry.artifact_path:
            return None

        model = self.load_artifact(entry.artifact_path)
        return entry, model
