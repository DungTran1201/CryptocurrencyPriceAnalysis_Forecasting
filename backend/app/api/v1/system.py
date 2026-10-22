"""System health and operational monitoring API endpoints."""

from datetime import datetime
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.core.database import get_db
from backend.app.models.market import Kline, SyncCheckpoint
from backend.app.models.forecast import ForecastRecord
from backend.app.models.ml_model import ModelRegistryEntry
from backend.app.schemas.system import SystemStatusResponse, CheckpointSummarySchema

router = APIRouter(tags=["System Status"])


@router.get("/health")
async def health_check():
    """Liveness probe."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "app_name": settings.app_name,
        "version": settings.app_version
    }


@router.get("/system/status", response_model=SystemStatusResponse)
async def system_status(db: AsyncSession = Depends(get_db)):
    """Comprehensive readiness and operational state inspection."""
    # Check total candles
    kline_count_stmt = select(func.count(Kline.id))
    total_candles = (await db.execute(kline_count_stmt)).scalar() or 0

    # Check forecast counts
    fc_count_stmt = select(func.count(ForecastRecord.id))
    total_forecasts = (await db.execute(fc_count_stmt)).scalar() or 0

    rec_count_stmt = select(func.count(ForecastRecord.id)).where(ForecastRecord.status == "RECONCILED")
    total_reconciled = (await db.execute(rec_count_stmt)).scalar() or 0

    # Active models count
    mod_count_stmt = select(func.count(ModelRegistryEntry.model_id)).where(ModelRegistryEntry.is_active == True)
    active_models = (await db.execute(mod_count_stmt)).scalar() or 0

    # Checkpoints
    cp_stmt = select(SyncCheckpoint).order_by(SyncCheckpoint.symbol.asc())
    cp_res = await db.execute(cp_stmt)
    checkpoints = cp_res.scalars().all()

    return SystemStatusResponse(
        status="OPERATIONAL",
        version=settings.app_version,
        environment=settings.app_env,
        current_time=datetime.utcnow().isoformat(),
        database_connected=True,
        total_candles_stored=total_candles,
        total_forecasts_generated=total_forecasts,
        total_reconciled_forecasts=total_reconciled,
        active_models_count=active_models,
        checkpoints=[CheckpointSummarySchema.model_validate(cp) for cp in checkpoints]
    )
