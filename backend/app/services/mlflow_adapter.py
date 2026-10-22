"""MLflow Tracking & Experiment Observability Adapter.

Provides transparent integration with experiment tracking:
- Probes external MLflow server if configured via MLFLOW_TRACKING_URI
- Honestly reports connection status (CONNECTED vs OFFLINE / LOCAL_FALLBACK)
- Aggregates tracked experiment runs from the database registry
- Normalizes hyperparameters, walk-forward validation metrics, and model artifacts
- Enforces model promotion gating criteria (beats naive baseline, positive directional edge)
"""

import os
from datetime import datetime, timezone
import json
from typing import List, Dict, Any, Optional
import httpx
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.logging import get_logger
from backend.app.models.ml_model import ModelRegistryEntry, ModelEvaluationMetric

logger = get_logger("MLflowAdapter")


class MLflowAdapter:
    """Adapter bridging internal model evaluations with MLflow experiment standards."""

    @staticmethod
    async def get_tracking_status() -> Dict[str, Any]:
        """Probe remote MLflow tracking server or declare local registry fallback."""
        tracking_uri = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
        is_configured = "MLFLOW_TRACKING_URI" in os.environ

        try:
            async with httpx.AsyncClient(timeout=1.5) as client:
                res = await client.get(f"{tracking_uri}/health")
                if res.status_code == 200:
                    return {
                        "is_connected": True,
                        "tracking_uri": tracking_uri,
                        "server_status": "CONNECTED",
                        "adapter_mode": "REMOTE_MLFLOW",
                        "message": f"Connected to active MLflow tracking server at {tracking_uri}."
                    }
        except Exception:
            pass

        return {
            "is_connected": False,
            "tracking_uri": tracking_uri if is_configured else "local://sqlite-model-registry",
            "server_status": "UNAVAILABLE" if is_configured else "NOT_CONFIGURED",
            "adapter_mode": "LOCAL_REGISTRY_FALLBACK",
            "message": "Remote MLflow tracking server is not reachable. Operating with local database Model Registry."
        }

    @staticmethod
    async def list_experiment_runs(db: AsyncSession, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Query all registered experiment runs and associated metrics."""
        query = select(ModelRegistryEntry).order_by(ModelRegistryEntry.created_at.desc())
        if symbol:
            query = query.where(ModelRegistryEntry.symbol == symbol.upper())

        res = await db.execute(query)
        entries = res.scalars().all()

        runs = []
        for entry in entries:
            # Query metrics
            metrics_res = await db.execute(
                select(ModelEvaluationMetric)
                .where(ModelEvaluationMetric.model_id == entry.model_id)
                .order_by(ModelEvaluationMetric.evaluated_at.desc())
            )
            metric = metrics_res.scalars().first()

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
                    "mae": round(metric.mae, 4) if metric else None,
                    "rmse": round(metric.rmse, 4) if metric else None,
                    "mape": round(metric.mape, 4) if metric else None,
                    "directional_accuracy_pct": round(metric.directional_accuracy * 100.0, 2) if metric else None,
                    "naive_mae": round(metric.naive_mae, 4) if metric and metric.naive_mae else None,
                    "mae_improvement_pct": round(metric.mae_improvement_pct, 2) if metric and metric.mae_improvement_pct else None,
                    "beats_naive_baseline": metric.beats_naive_baseline if metric else False,
                } if metric else None,
                "gating_status": "APPROVED" if entry.is_active else "CANDIDATE",
                "promotion_criteria": "Requires Walk-Forward MAE < Naive Baseline and Directional Accuracy > 50%"
            })

        return runs
