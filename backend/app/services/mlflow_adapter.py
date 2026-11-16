"""MLflow Tracking & Experiment Observability Adapter."""

import json
from typing import List, Dict, Any, Optional
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.core.logging import get_logger
from backend.app.models.ml_model import ModelRegistryEntry, ModelEvaluationMetric

logger = get_logger("MLflowAdapter")


class MLflowAdapter:
    """Adapter bridging internal model evaluations with MLflow experiment standards."""

    @staticmethod
    async def get_tracking_status() -> Dict[str, Any]:
        """Probe remote MLflow tracking server or declare local registry fallback."""
        configured_uri = settings.mlflow_tracking_uri
        tracking_uri = configured_uri or "http://localhost:5000"
        is_configured = bool(configured_uri)

        if is_configured:
            try:
                async with httpx.AsyncClient(timeout=1.5) as client:
                    res = await client.get(f"{tracking_uri.rstrip('/')}/health")
                    if res.status_code == 200:
                        return {
                            "is_connected": True,
                            "tracking_uri": tracking_uri,
                            "server_status": "CONNECTED",
                            "adapter_mode": "REMOTE_MLFLOW",
                            "message": f"Connected to active MLflow tracking server at {tracking_uri}.",
                        }
            except Exception:
                pass

        return {
            "is_connected": False,
            "tracking_uri": tracking_uri if is_configured else "local://sqlite-model-registry",
            "server_status": "UNAVAILABLE" if is_configured else "NOT_CONFIGURED",
            "adapter_mode": "LOCAL_REGISTRY_FALLBACK",
            "message": "Operating with local database Model Registry (external MLflow optional).",
        }

    @staticmethod
    async def list_experiment_runs(db: AsyncSession, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Query all registered experiment runs and batched metrics without N+1 SQL calls."""
        query = select(ModelRegistryEntry).order_by(ModelRegistryEntry.created_at.desc())
        if symbol:
            query = query.where(ModelRegistryEntry.symbol == symbol.upper())

        entries = list((await db.execute(query)).scalars().all())
        if not entries:
            return []

        model_ids = [e.model_id for e in entries]
        metrics_res = await db.execute(
            select(ModelEvaluationMetric)
            .where(ModelEvaluationMetric.model_id.in_(model_ids))
            .order_by(ModelEvaluationMetric.evaluated_at.desc())
        )
        metrics_by_id: Dict[str, ModelEvaluationMetric] = {}
        for m in metrics_res.scalars().all():
            metrics_by_id.setdefault(m.model_id, m)

        runs = []
        for entry in entries:
            metric = metrics_by_id.get(entry.model_id)
            params = {}
            if entry.hyperparameters:
                try:
                    params = json.loads(entry.hyperparameters)
                except Exception:
                    params = {}

            runs.append({
                "run_id": entry.model_id,
                "model_name": entry.name,
                "version": entry.version,
                "model_type": entry.model_type,
                "symbol": entry.symbol,
                "timeframe": entry.timeframe,
                "horizon_steps": entry.horizon_steps,
                "is_active": entry.is_active,
                "train_sample_count": entry.train_sample_count,
                "train_start_time": entry.train_start_time.isoformat() if entry.train_start_time else None,
                "train_end_time": entry.train_end_time.isoformat() if entry.train_end_time else None,
                "created_at": entry.created_at.isoformat() if entry.created_at else None,
                "hyperparameters": params,
                "metrics": {
                    "mae": round(metric.mae, 4),
                    "rmse": round(metric.rmse, 4),
                    "mape": round(metric.mape, 4),
                    "directional_accuracy_pct": round(metric.directional_accuracy * 100.0, 2),
                    "naive_mae": round(metric.naive_mae, 4) if metric.naive_mae is not None else None,
                    "mae_improvement_pct": round(metric.mae_improvement_pct, 2) if metric.mae_improvement_pct is not None else None,
                    "beats_naive_baseline": metric.beats_naive_baseline,
                } if metric else None,
                "gating_status": "APPROVED" if entry.is_active else "CANDIDATE",
                "promotion_criteria": "Requires Walk-Forward MAE < Naive Baseline and Directional Accuracy > 50%",
            })

        return runs
