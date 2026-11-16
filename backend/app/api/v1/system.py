"""System health, operational monitoring, and resource utilization API endpoints."""

from datetime import datetime, timezone
from typing import Any, Dict
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.core.database import get_db
from backend.app.core.metrics import collect_resource_snapshot
from backend.app.models.market import Kline, SyncCheckpoint
from backend.app.models.forecast import ForecastRecord
from backend.app.models.ml_model import ModelRegistryEntry
from backend.app.schemas.system import SystemStatusResponse, CheckpointSummarySchema
from backend.app.storage import get_data_root
from backend.app.streaming.runtime import stream_runtime

router = APIRouter(tags=["System Status"])


@router.get("/health")
async def health_check():
    """Liveness probe."""
    return {
        "status": "healthy",
        "profile": settings.profile.value,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "app_name": settings.app_name,
        "version": settings.app_version,
    }


@router.get("/system/status", response_model=SystemStatusResponse)
async def system_status(db: AsyncSession = Depends(get_db)):
    """Comprehensive readiness and operational state inspection."""
    total_candles = (await db.execute(select(func.count(Kline.id)))).scalar() or 0
    total_forecasts = (await db.execute(select(func.count(ForecastRecord.id)))).scalar() or 0
    total_reconciled = (
        await db.execute(select(func.count(ForecastRecord.id)).where(ForecastRecord.status == "RECONCILED"))
    ).scalar() or 0
    active_models = (
        await db.execute(select(func.count(ModelRegistryEntry.model_id)).where(ModelRegistryEntry.is_active == True))
    ).scalar() or 0

    checkpoints = (
        await db.execute(select(SyncCheckpoint).order_by(SyncCheckpoint.symbol.asc()))
    ).scalars().all()

    return SystemStatusResponse(
        status="OPERATIONAL",
        version=settings.app_version,
        environment=settings.app_env,
        current_time=datetime.now(timezone.utc).isoformat(),
        database_connected=True,
        total_candles_stored=total_candles,
        total_forecasts_generated=total_forecasts,
        total_reconciled_forecasts=total_reconciled,
        active_models_count=active_models,
        checkpoints=[CheckpointSummarySchema.model_validate(cp) for cp in checkpoints],
    )


@router.get("/system/resources", summary="Live process RSS, CPU, disk usage, and profile resource limits")
async def system_resources() -> Dict[str, Any]:
    """Measure actual memory, CPU, disk usage, and broker/queue utilization."""
    snap = collect_resource_snapshot(
        data_dir=str(get_data_root()),
        memory_budget_mb=settings.resources.total_memory_mb,
    )
    stream_snap = await stream_runtime.status_snapshot()
    return {
        "profile": settings.profile.value,
        "limits": {
            "total_memory_mb": settings.resources.total_memory_mb,
            "worker_concurrency": settings.resources.worker_concurrency,
            "stream_queue_maxsize": settings.resources.stream_queue_maxsize,
            "consumer_batch_size": settings.resources.consumer_batch_size,
            "bronze_flush_max_records": settings.resources.bronze_flush_max_records,
            "microbatch_flush_max_age_sec": settings.resources.microbatch_flush_max_age_sec,
            "duckdb_memory_limit": settings.resources.duckdb_memory_limit,
            "duckdb_threads": settings.resources.duckdb_threads,
            "ml_max_train_rows": settings.resources.ml_max_train_rows,
            "ws_coalesce_interval_ms": settings.resources.ws_coalesce_interval_ms,
        },
        "measured": snap,
        "streaming": {
            "broker_connected": stream_snap["broker"].get("connected", False),
            "broker_backend": stream_snap["broker"].get("backend"),
            "broker_messages": stream_snap["broker"].get("messages", 0),
            "total_consumer_lag": stream_snap["broker"].get("total_consumer_lag", 0),
            "ws_connected": stream_snap["ingestor"].get("connected", False),
            "events_received": stream_snap["ingestor"].get("received_count", 0),
            "events_published": stream_snap["producer"].get("published_count", 0),
            "events_consumed": stream_snap["consumer"].get("consumed_count", 0),
            "queue_depth": stream_snap["producer"].get("queue_depth", 0),
            "backpressure_active": stream_snap["producer"].get("backpressure_active", False),
            "dlq_count": stream_snap["consumer"].get("dlq_count", 0),
        },
    }
