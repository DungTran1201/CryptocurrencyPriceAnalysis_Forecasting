"""Model Lab, Registry, and Training REST API endpoints."""

from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db
from backend.app.models.ml_model import ModelRegistryEntry, ModelEvaluationMetric
from backend.app.schemas.ml_model import (
    ModelCardSchema,
    ModelMetricSchema,
    ModelTrainRequest,
    ModelTrainingResultSchema
)
from backend.app.services.model_service import ModelService

router = APIRouter(prefix="/models", tags=["Model Lab"])
model_service = ModelService()


@router.get("", response_model=List[ModelCardSchema])
async def list_models(
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    timeframe: Optional[str] = Query(None, description="Filter by timeframe"),
    is_active: Optional[bool] = Query(None, description="Filter active models"),
    db: AsyncSession = Depends(get_db)
):
    """List all registered models with their training metadata and evaluation metrics."""
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
    res = await db.execute(query)
    entries = res.scalars().all()

    model_cards = []
    for entry in entries:
        # Fetch corresponding evaluation metric
        m_stmt = select(ModelEvaluationMetric).where(
            ModelEvaluationMetric.model_id == entry.model_id
        ).limit(1)
        m_res = await db.execute(m_stmt)
        metric = m_res.scalar_one_or_none()

        card = ModelCardSchema(
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
            metrics=ModelMetricSchema.model_validate(metric) if metric else None
        )
        model_cards.append(card)

    return model_cards


@router.post("/train", response_model=ModelTrainingResultSchema)
async def train_model(
    payload: ModelTrainRequest,
    db: AsyncSession = Depends(get_db)
):
    """Trigger a full training and walk-forward cross validation pipeline with gating."""
    try:
        result = await model_service.train_model_pipeline(
            db=db,
            symbol=payload.symbol,
            timeframe=payload.timeframe,
            horizon_steps=payload.horizon_steps,
            model_type=payload.model_type,
            n_splits=payload.n_splits
        )
        return ModelTrainingResultSchema(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Training pipeline failed: {str(e)}")
