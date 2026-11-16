"""Model Lab, Registry, and Training REST API endpoints."""

from typing import Dict, List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db
from backend.app.core.logging import get_logger
from backend.app.core.security import require_admin_if_configured, validate_symbol, validate_timeframe
from backend.app.models.ml_model import ModelRegistryEntry, ModelEvaluationMetric
from backend.app.schemas.ml_model import (
    ModelCardSchema,
    ModelMetricSchema,
    ModelTrainRequest,
    ModelTrainingResultSchema,
)
from backend.app.services.model_service import ModelService
from backend.app.services.mlflow_adapter import MLflowAdapter

logger = get_logger("ModelLabAPI")

router = APIRouter(prefix="/models", tags=["Model Lab"])
model_service = ModelService()


@router.get("/tracking-status", summary="Check MLflow tracking server connection and fallback mode")
async def get_tracking_status() -> dict:
    """Return status of external MLflow tracking connection or local database fallback."""
    return await MLflowAdapter.get_tracking_status()


@router.get("/experiments", summary="List experiment runs with hyperparameters and validation metrics")
async def list_experiments(
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    db: AsyncSession = Depends(get_db),
) -> list:
    """Provide experiment run tracking view adhering to MLflow standard entities."""
    return await MLflowAdapter.list_experiment_runs(db, symbol=symbol)


@router.get("", response_model=List[ModelCardSchema])
async def list_models(
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    timeframe: Optional[str] = Query(None, description="Filter by timeframe"),
    is_active: Optional[bool] = Query(None, description="Filter active models"),
    db: AsyncSession = Depends(get_db),
):
    """List all registered models with batched evaluation metrics (zero N+1 queries)."""
    query = select(ModelRegistryEntry)
    filters = []
    if symbol:
        filters.append(ModelRegistryEntry.symbol == symbol.upper())
    if timeframe:
        filters.append(ModelRegistryEntry.timeframe == timeframe)
    if is_active is not None:
        filters.append(ModelRegistryEntry.is_active == is_active)

    if filters:
        query = query.where(and_(*filters))

    query = query.order_by(ModelRegistryEntry.created_at.desc())
    entries = list((await db.execute(query)).scalars().all())
    if not entries:
        return []

    model_ids = [e.model_id for e in entries]
    m_res = await db.execute(
        select(ModelEvaluationMetric)
        .where(ModelEvaluationMetric.model_id.in_(model_ids))
        .order_by(ModelEvaluationMetric.evaluated_at.desc())
    )
    metrics_by_id: Dict[str, ModelEvaluationMetric] = {}
    for m in m_res.scalars().all():
        metrics_by_id.setdefault(m.model_id, m)

    model_cards = []
    for entry in entries:
        metric = metrics_by_id.get(entry.model_id)
        model_cards.append(ModelCardSchema(
            model_id=entry.model_id,
            name=entry.name,
            version=entry.version,
            model_type=entry.model_type,
            symbol=entry.symbol,
            timeframe=entry.timeframe,
            horizon_steps=entry.horizon_steps,
            train_start_time=entry.train_start_time,
            train_end_time=entry.train_end_time,
            train_sample_count=entry.train_sample_count,
            is_active=entry.is_active,
            created_at=entry.created_at,
            metrics=ModelMetricSchema.model_validate(metric) if metric else None,
        ))

    return model_cards


@router.post("/train", response_model=ModelTrainingResultSchema)
async def train_model(
    payload: ModelTrainRequest,
    db: AsyncSession = Depends(get_db),
    _auth: None = Depends(require_admin_if_configured),
):
    """Trigger a CPU-bounded training and walk-forward cross validation pipeline with gating."""
    sym = validate_symbol(payload.symbol)
    tf = validate_timeframe(payload.timeframe)
    if payload.model_type not in {"gradient_boosting", "ridge"}:
        raise HTTPException(status_code=400, detail="Unsupported model_type. Valid options: gradient_boosting, ridge")

    try:
        result = await model_service.train_model_pipeline(
            db=db,
            symbol=sym,
            timeframe=tf,
            horizon_steps=payload.horizon_steps,
            model_type=payload.model_type,
            n_splits=payload.n_splits,
        )
        return ModelTrainingResultSchema(**result)
    except ValueError as ve:
        logger.warning(f"Validation error during model training: {ve}")
        raise HTTPException(status_code=400, detail=f"Training parameters invalid: {str(ve)}")
    except Exception as e:
        logger.error(f"Training pipeline failed for {sym} {tf}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Model training pipeline encountered an internal server error.")
