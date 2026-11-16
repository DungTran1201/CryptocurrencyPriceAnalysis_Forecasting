"""Pipeline orchestration, recomputation, and task execution endpoints."""

from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, Query, HTTPException, status, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db, AsyncSessionLocal
from backend.app.core.logging import get_logger
from backend.app.core.security import require_admin_if_configured, validate_symbol, validate_timeframe
from backend.app.services.pipeline_service import PipelineService

router = APIRouter(prefix="/pipelines", tags=["Pipelines"])
logger = get_logger("PipelineRouter")


class TriggerPipelineRequest(BaseModel):
    """Payload to trigger an asynchronous Medallion data pipeline run."""
    symbol: str = Field(default="BTCUSDT", description="Trading pair symbol")
    timeframe: str = Field(default="1h", description="Candle timeframe (e.g. 1h, 15m, 1d)")
    trigger_type: str = Field(default="MANUAL", description="Trigger mechanism (MANUAL, SCHEDULED, RETRY, BACKFILL)")
    lookback_days: int = Field(default=30, ge=1, le=180, description="Lookback window if initial seed")
    skip_network_ingest: bool = Field(default=False, description="If true, recompute Silver/Gold/Features from stored candles")


async def run_pipeline_background(
    symbol: str,
    timeframe: str,
    trigger_type: str,
    lookback_days: int,
    skip_network_ingest: bool = False,
):
    """Background task executor for pipeline execution with an isolated DB session."""
    async with AsyncSessionLocal() as db:
        try:
            await PipelineService.execute_medallion_pipeline(
                db,
                symbol=symbol,
                timeframe=timeframe,
                trigger_type=trigger_type,
                lookback_days=lookback_days,
                skip_network_ingest=skip_network_ingest,
            )
        except Exception as e:
            logger.error(f"Background pipeline failed for {symbol}: {e}")


@router.get("/overview", summary="Retrieve aggregated pipeline operational metrics")
async def get_pipeline_overview(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Provide high-level pipeline KPIs: total runs, success rate, running tasks, throughput."""
    return await PipelineService.get_overview_stats(db)


@router.get("/runs", summary="Query historical pipeline runs")
async def list_pipeline_runs(
    status: Optional[str] = Query(None, description="Filter by status (RUNNING, SUCCESS, FAILED)"),
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    timeframe: Optional[str] = Query(None, description="Filter by timeframe"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Return paginated pipeline runs with execution metadata and statistics."""
    runs = await PipelineService.list_runs(
        db, status=status, symbol=symbol, timeframe=timeframe, limit=limit, offset=offset
    )
    return [
        {
            "id": r.id,
            "pipeline_name": r.pipeline_name,
            "workflow_version": r.workflow_version,
            "symbol": r.symbol,
            "timeframe": r.timeframe,
            "status": r.status,
            "trigger_type": r.trigger_type,
            "retry_count": r.retry_count,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "duration_seconds": r.duration_seconds,
            "rows_read": r.rows_read,
            "rows_inserted": r.rows_inserted,
            "rows_updated": r.rows_updated,
            "rows_rejected": r.rows_rejected,
            "gaps_detected": r.gaps_detected,
            "start_watermark": r.start_watermark.isoformat() if r.start_watermark else None,
            "end_watermark": r.end_watermark.isoformat() if r.end_watermark else None,
            "error_message": r.error_message,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in runs
    ]


@router.get("/runs/{run_id}", summary="Get detailed task breakdown for a pipeline run")
async def get_pipeline_run_details(
    run_id: str,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Return run metadata and logs for each task stage."""
    run = await PipelineService.get_run_details(db, run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline run not found")
    return run


@router.post("/trigger", summary="Trigger a Medallion pipeline run")
async def trigger_pipeline(
    req: TriggerPipelineRequest,
    background_tasks: BackgroundTasks,
    sync_mode: bool = Query(False, description="If true, execute synchronously; otherwise run in background"),
    db: AsyncSession = Depends(get_db),
    _auth: None = Depends(require_admin_if_configured),
) -> Dict[str, Any]:
    """Initiate an end-to-end Medallion pipeline run (Ingest -> Validate -> Gold Marts -> Features)."""
    sym = validate_symbol(req.symbol)
    tf = validate_timeframe(req.timeframe)

    if sync_mode:
        run = await PipelineService.execute_medallion_pipeline(
            db,
            symbol=sym,
            timeframe=tf,
            trigger_type=req.trigger_type,
            lookback_days=req.lookback_days,
            skip_network_ingest=req.skip_network_ingest,
        )
        return {
            "status": "COMPLETED",
            "run_id": run.id,
            "pipeline_status": run.status,
            "duration_seconds": run.duration_seconds,
            "rows_inserted": run.rows_inserted,
        }
    else:
        background_tasks.add_task(
            run_pipeline_background,
            sym,
            tf,
            req.trigger_type,
            req.lookback_days,
            req.skip_network_ingest,
        )
        return {
            "status": "QUEUED",
            "message": f"Pipeline dispatched for {sym} ({tf}).",
        }
