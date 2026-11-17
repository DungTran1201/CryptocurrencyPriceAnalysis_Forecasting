"""Forecast generation and audit history REST API endpoints."""

from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select, and_, func, desc, cast, Float
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db
from backend.app.core.security import require_admin_if_configured
from backend.app.models.forecast import ForecastRecord
from backend.app.schemas.forecast import (
    ForecastGenerateRequest,
    ForecastRecordSchema,
    ForecastHistoryResponse
)
from backend.app.services.forecast_service import ForecastService

from backend.app.core.logging import get_logger

logger = get_logger("ForecastAPI")

router = APIRouter(prefix="/forecasts", tags=["Forecasts"])
forecast_service = ForecastService()


@router.post("/generate", response_model=ForecastRecordSchema)
async def generate_forecast(
    payload: ForecastGenerateRequest,
    db: AsyncSession = Depends(get_db),
    _auth: None = Depends(require_admin_if_configured),
):
    """Generate a model inference forecast and save an immutable forecast record."""
    try:
        record = await forecast_service.generate_forecast(
            db=db,
            symbol=payload.symbol,
            timeframe=payload.timeframe,
            horizon_steps=payload.horizon_steps
        )
        return record
    except ValueError as ve:
        logger.warning(f"Validation error during forecast generation: {ve}")
        raise HTTPException(status_code=400, detail="Inference request invalid: check input parameters or dataset sufficiency.")
    except Exception as e:
        logger.error(f"Inference failed for {payload.symbol} {payload.timeframe}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Forecast inference encountered an internal server error.")


@router.get("", response_model=ForecastHistoryResponse)
async def list_forecasts(
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    timeframe: Optional[str] = Query(None, description="Filter by timeframe"),
    status: Optional[str] = Query(None, description="Filter by status (PENDING, RECONCILED)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db)
):
    """List historical forecast records with paginated audit ledger and aggregate accuracy statistics."""
    query = select(ForecastRecord)
    filters = []
    if symbol:
        filters.append(ForecastRecord.symbol == symbol.upper())
    if timeframe:
        filters.append(ForecastRecord.timeframe == timeframe)
    if status:
        filters.append(ForecastRecord.status == status.upper())

    if filters:
        query = query.where(and_(*filters))

    # Total count
    count_stmt = select(func.count()).select_from(query.subquery())
    total_count = (await db.execute(count_stmt)).scalar() or 0

    # Paginated records
    offset = (page - 1) * page_size
    records_stmt = query.order_by(ForecastRecord.forecast_timestamp.desc()).offset(offset).limit(page_size)
    records = (await db.execute(records_stmt)).scalars().all()

    # Aggregate statistics on reconciled forecasts
    stats_query = select(
        func.count(ForecastRecord.id),
        func.avg(cast(ForecastRecord.direction_correct, Float)),
        func.avg(ForecastRecord.percentage_error)
    ).where(ForecastRecord.status == "RECONCILED")
    if symbol:
        stats_query = stats_query.where(ForecastRecord.symbol == symbol.upper())

    reconciled_res = await db.execute(stats_query)
    rec_count, avg_hit, avg_mpe = reconciled_res.one()

    hit_rate = (avg_hit * 100.0) if avg_hit is not None else 0.0
    mpe = avg_mpe if avg_mpe is not None else 0.0

    return ForecastHistoryResponse(
        total_count=total_count,
        reconciled_count=rec_count or 0,
        direction_hit_rate_pct=round(hit_rate, 2),
        mean_percentage_error=round(mpe, 2),
        records=records
    )


@router.post("/reconcile")
async def trigger_reconciliation(
    db: AsyncSession = Depends(get_db),
    _auth: None = Depends(require_admin_if_configured),
):
    """Trigger realization check for mature pending forecasts against actual realized candles."""
    count = await forecast_service.reconcile_pending_forecasts(db)
    return {"status": "SUCCESS", "reconciled_count": count}
