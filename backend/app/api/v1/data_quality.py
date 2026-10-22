"""Data Quality monitoring, rule inspection, and lineage endpoints."""

from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, Query, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db
from backend.app.models.data_quality import DataQualityRun, DataQualityResult
from backend.app.services.data_quality_service import DataQualityService

router = APIRouter(prefix="/data-quality", tags=["Data Quality"])


class RunEvaluationRequest(BaseModel):
    symbol: str = Field(default="BTCUSDT", description="Cryptocurrency symbol")
    timeframe: str = Field(default="1h", description="Candle interval")
    limit: int = Field(default=1000, ge=10, le=5000, description="Number of historical candles to evaluate")


@router.get("/overview", summary="Get data quality scorecard metrics")
async def get_data_quality_overview(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Returns platform-wide data quality pass rates and rule summary statistics."""
    return await DataQualityService.get_overview_metrics(db)


@router.get("/lineage", summary="Retrieve Medallion data lineage DAG")
async def get_lineage(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Returns nodes and edges connecting Bronze, Silver, Gold, Features, and Serving."""
    return await DataQualityService.get_lineage_graph(db)


@router.get("/runs", summary="Query historical data quality evaluation runs")
async def list_data_quality_runs(
    symbol: Optional[str] = Query(None),
    timeframe: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
) -> List[Dict[str, Any]]:
    """Returns historical validation runs with overall pass/fail status."""
    query = select(DataQualityRun).order_by(DataQualityRun.run_timestamp.desc())
    if symbol:
        query = query.where(DataQualityRun.symbol == symbol.upper())
    if timeframe:
        query = query.where(DataQualityRun.timeframe == timeframe.lower())
    if status:
        query = query.where(DataQualityRun.status == status.upper())

    query = query.limit(limit)
    res = await db.execute(query)
    runs = res.scalars().all()

    return [
        {
            "id": r.id,
            "dataset_name": r.dataset_name,
            "symbol": r.symbol,
            "timeframe": r.timeframe,
            "run_timestamp": r.run_timestamp.isoformat(),
            "status": r.status,
            "total_rules_evaluated": r.total_rules_evaluated,
            "rules_passed": r.rules_passed,
            "rules_failed": r.rules_failed,
            "evaluated_row_count": r.evaluated_row_count,
            "duration_ms": r.duration_ms
        }
        for r in runs
    ]


@router.get("/runs/{run_id}", summary="Get detailed rule results for a data quality run")
async def get_run_details(run_id: str, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Retrieves each evaluated rule, failure counts, severity, and violation payload samples."""
    run_res = await db.execute(select(DataQualityRun).where(DataQualityRun.id == run_id))
    run = run_res.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Data quality run not found")

    results_res = await db.execute(
        select(DataQualityResult)
        .where(DataQualityResult.run_id == run_id)
        .order_by(DataQualityResult.rule_id.asc())
    )
    results = results_res.scalars().all()

    return {
        "run": {
            "id": run.id,
            "dataset_name": run.dataset_name,
            "symbol": run.symbol,
            "timeframe": run.timeframe,
            "run_timestamp": run.run_timestamp.isoformat(),
            "status": run.status,
            "total_rules_evaluated": run.total_rules_evaluated,
            "rules_passed": run.rules_passed,
            "rules_failed": run.rules_failed,
            "evaluated_row_count": run.evaluated_row_count,
            "duration_ms": run.duration_ms
        },
        "results": [
            {
                "id": res.id,
                "rule_id": res.rule_id,
                "rule_name": res.rule_name,
                "category": res.category,
                "severity": res.severity,
                "status": res.status,
                "failed_records_count": res.failed_records_count,
                "sample_failures": res.sample_failures,
                "message": res.message
            }
            for res in results
        ]
    }


@router.post("/evaluate", summary="Execute data quality audit on demand")
async def trigger_evaluation(
    req: RunEvaluationRequest,
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Runs the 10 data quality rules on the selected symbol/interval immediately."""
    run = await DataQualityService.evaluate_klines(
        db, symbol=req.symbol, timeframe=req.timeframe, limit=req.limit
    )
    return {
        "run_id": run.id,
        "symbol": run.symbol,
        "timeframe": run.timeframe,
        "status": run.status,
        "rules_passed": run.rules_passed,
        "total_rules": run.total_rules_evaluated,
        "evaluated_row_count": run.evaluated_row_count,
        "duration_ms": run.duration_ms
    }
