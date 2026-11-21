"""System health, operational monitoring, and resource utilization API endpoints."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
import psutil
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.core.database import get_db
from backend.app.core.logging import get_logger
from backend.app.core.metrics import (
    STAGE_FAILURES_TOTAL,
    collect_resource_snapshot_async,
    update_active_freshness_from_db,
)
from backend.app.models.market import Kline, SyncCheckpoint
from backend.app.models.forecast import ForecastRecord
from backend.app.models.ml_model import ModelRegistryEntry
from backend.app.schemas.system import (
    DependencyCheckSchema,
    HealthStatusSchema,
    ResourceMetricsSchema,
    SystemStatusResponse,
    CheckpointSummarySchema,
)
from backend.app.storage import get_data_root
from backend.app.streaming.runtime import stream_runtime
from backend.app.streaming.telemetry import merge_worker_snapshots

logger = get_logger("SystemAPI")
router = APIRouter(tags=["System Status"])


async def _read_worker_heartbeats_safe() -> Dict[str, Any]:
    """Read worker heartbeats from runtime/HotStateCache if available without failing."""
    hb_getter = getattr(stream_runtime, "get_worker_heartbeats", None)
    if callable(hb_getter):
        try:
            raw = await hb_getter()
            return merge_worker_snapshots(raw)
        except Exception:
            return merge_worker_snapshots(None)
    return merge_worker_snapshots(None)


@router.get("/health", response_model=HealthStatusSchema)
async def health_check(db: AsyncSession = Depends(get_db)):
    """Dependency-probing readiness & liveness probe (DB, disk headroom, broker/workers)."""
    checks: Dict[str, DependencyCheckSchema] = {}
    db_ok = False
    try:
        await db.execute(text("SELECT 1"))
        db_ok = True
        checks["database"] = DependencyCheckSchema(status="OK")
    except Exception:
        STAGE_FAILURES_TOTAL.labels(process="api", stage="health_db").inc()
        checks["database"] = DependencyCheckSchema(status="FAILED", detail="Database connectivity check failed")

    disk_degraded = False
    try:
        data_root = get_data_root()
        du = psutil.disk_usage(str(data_root))
        free_gb = round(du.free / (1024 ** 3), 2)
        if free_gb < 2.0 or du.percent >= 95.0:
            disk_degraded = True
            checks["disk"] = DependencyCheckSchema(status="FAILED", detail=f"Critical disk pressure: {free_gb} GB free")
        elif free_gb < 10.0 or du.percent >= 85.0:
            disk_degraded = True
            checks["disk"] = DependencyCheckSchema(status="DEGRADED", detail=f"Low disk headroom: {free_gb} GB free")
        else:
            checks["disk"] = DependencyCheckSchema(status="OK", detail=f"{free_gb} GB free")
    except Exception:
        disk_degraded = True
        checks["disk"] = DependencyCheckSchema(status="DEGRADED", detail="Disk stat unavailable")

    broker_degraded = False
    if settings.streaming.enabled and settings.app_env != "testing":
        if stream_runtime.broker.is_connected():
            checks["broker"] = DependencyCheckSchema(status="OK")
        else:
            broker_degraded = True
            checks["broker"] = DependencyCheckSchema(status="DEGRADED", detail="Message broker disconnected")
    else:
        checks["broker"] = DependencyCheckSchema(status="SKIPPED", detail="Streaming disabled in current env")

    worker_degraded = False
    if settings.streaming.enabled and not settings.streaming.embedded_in_api and settings.app_env != "testing":
        hb_summary = await _read_worker_heartbeats_safe()
        if hb_summary["status"] == "ALIVE":
            checks["workers"] = DependencyCheckSchema(status="OK", detail=f"{hb_summary['active_workers']} active")
        else:
            worker_degraded = True
            checks["workers"] = DependencyCheckSchema(status="DEGRADED", detail=f"Worker state: {hb_summary['status']}")

    if not db_ok:
        payload = HealthStatusSchema(
            status="unhealthy",
            profile=settings.profile.value,
            timestamp=datetime.now(timezone.utc).isoformat(),
            app_name=settings.app_name,
            version=settings.app_version,
            checks=checks,
        )
        return JSONResponse(status_code=503, content=payload.model_dump())

    overall = "degraded" if (disk_degraded or broker_degraded or worker_degraded) else "healthy"
    return HealthStatusSchema(
        status=overall,
        profile=settings.profile.value,
        timestamp=datetime.now(timezone.utc).isoformat(),
        app_name=settings.app_name,
        version=settings.app_version,
        checks=checks,
    )


@router.get("/system/status", response_model=SystemStatusResponse)
async def system_status(db: AsyncSession = Depends(get_db)):
    """Comprehensive readiness and operational state inspection."""
    db_connected = False
    try:
        await db.execute(text("SELECT 1"))
        db_connected = True
    except Exception:
        STAGE_FAILURES_TOTAL.labels(process="api", stage="system_status_db").inc()
        return SystemStatusResponse(
            status="DEGRADED",
            version=settings.app_version,
            environment=settings.app_env,
            current_time=datetime.now(timezone.utc).isoformat(),
            database_connected=False,
            total_candles_stored=0,
            total_forecasts_generated=0,
            total_reconciled_forecasts=0,
            active_models_count=0,
            checkpoints=[],
        )

    await update_active_freshness_from_db(db)
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
        database_connected=db_connected,
        total_candles_stored=total_candles,
        total_forecasts_generated=total_forecasts,
        total_reconciled_forecasts=total_reconciled,
        active_models_count=active_models,
        checkpoints=[CheckpointSummarySchema.model_validate(cp) for cp in checkpoints],
    )


@router.get(
    "/system/resources",
    response_model=ResourceMetricsSchema,
    summary="Live process RSS, CPU, disk usage, and profile resource limits",
)
async def system_resources(db: AsyncSession = Depends(get_db)) -> ResourceMetricsSchema:
    """Measure actual memory, CPU, disk usage off-event-loop and worker/broker utilization."""
    snap = await collect_resource_snapshot_async(
        data_dir=str(get_data_root()),
        memory_budget_mb=settings.resources.total_memory_mb,
    )
    try:
        await update_active_freshness_from_db(db)
    except Exception:
        pass

    stream_snap = await stream_runtime.status_snapshot()
    hb_summary = await _read_worker_heartbeats_safe()

    embedded = settings.streaming.embedded_in_api
    if embedded:
        stream_summary: Dict[str, Any] = {
            "status": "AVAILABLE",
            "broker_connected": bool(stream_snap["broker"].get("connected", False)),
            "broker_backend": stream_snap["broker"].get("backend"),
            "broker_messages": int(stream_snap["broker"].get("messages", 0)),
            "total_consumer_lag": int(stream_snap["broker"].get("total_consumer_lag", 0)),
            "ws_connected": bool(stream_snap["ingestor"].get("connected", False)),
            "events_received": int(stream_snap["ingestor"].get("received_count", 0)),
            "events_published": int(stream_snap["producer"].get("published_count", 0)),
            "events_consumed": int(stream_snap["consumer"].get("consumed_count", 0)),
            "queue_depth": int(stream_snap["producer"].get("queue_depth", 0)),
            "backpressure_active": bool(stream_snap["producer"].get("backpressure_active", False)),
            "dlq_count": int(stream_snap["consumer"].get("dlq_count", 0)),
        }
    else:
        stream_workers = [
            w for w in hb_summary.get("workers", {}).values()
            if w.get("role") == "stream_worker" and w.get("state") != "STALE"
        ]
        if stream_workers:
            sw_stats = stream_workers[0].get("stream_stats", {})
            stream_summary = {
                "status": "AVAILABLE",
                "broker_connected": bool(stream_snap["broker"].get("connected", False)),
                "broker_backend": stream_snap["broker"].get("backend"),
                "broker_messages": int(stream_snap["broker"].get("messages", 0)),
                "total_consumer_lag": int(stream_snap["broker"].get("total_consumer_lag", 0)),
                "ws_connected": bool(sw_stats.get("ws_connected", False)),
                "events_received": int(sw_stats.get("events_received", 0)),
                "events_published": int(sw_stats.get("events_published", 0)),
                "events_consumed": int(sw_stats.get("events_consumed", 0)),
                "queue_depth": int(sw_stats.get("queue_depth", 0)),
                "backpressure_active": bool(sw_stats.get("backpressure_active", False)),
                "dlq_count": int(sw_stats.get("dlq_count", 0)),
            }
        else:
            stream_summary = {
                "status": hb_summary["status"],  # UNAVAILABLE or STALE — never fake zeros as live
                "broker_connected": bool(stream_snap["broker"].get("connected", False)),
                "broker_backend": stream_snap["broker"].get("backend"),
                "broker_messages": int(stream_snap["broker"].get("messages", 0)),
                "total_consumer_lag": int(stream_snap["broker"].get("total_consumer_lag", 0)),
                "ws_connected": False,
                "events_received": 0,
                "events_published": 0,
                "events_consumed": 0,
                "queue_depth": 0,
                "backpressure_active": False,
                "dlq_count": 0,
            }

    return ResourceMetricsSchema(
        profile=settings.profile.value,
        embedded_in_api=embedded,
        limits={
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
        measured=snap,
        streaming=stream_summary,
        workers=hb_summary,
    )
