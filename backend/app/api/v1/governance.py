"""Data Catalog, Governance, Checkpoints, and Retention Management endpoints."""

import asyncio
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db
from backend.app.core.security import require_admin_if_configured
from backend.app.models.governance import StreamCheckpoint
from backend.app.services.governance_service import GovernanceService

router = APIRouter(prefix="/governance", tags=["Data Governance & Catalog"])


@router.get("/catalog", summary="Query persistent Medallion Data Catalog")
async def get_data_catalog(
    layer: Optional[str] = Query(None, description="Filter by layer: SOURCE, BRONZE, SILVER, GOLD, FEATURES, SERVING"),
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Return persistent catalog metadata with schemas, row counts, byte sizes, and retention policies."""
    return await GovernanceService.list_catalog(db, layer=layer)


@router.get("/checkpoints", summary="Inspect durable stream consumer checkpoints")
async def get_stream_checkpoints(db: AsyncSession = Depends(get_db)) -> List[Dict[str, Any]]:
    """List durable consumer offsets, processed counts, and error counts."""
    res = await db.execute(select(StreamCheckpoint).order_by(StreamCheckpoint.updated_at.desc()))
    rows = res.scalars().all()
    return [
        {
            "id": r.id,
            "consumer_name": r.consumer_name,
            "subject": r.subject,
            "symbol": r.symbol,
            "stream_type": r.stream_type,
            "last_event_time": r.last_event_time.isoformat() if r.last_event_time else None,
            "last_stream_seq": r.last_stream_seq,
            "processed_count": r.processed_count,
            "error_count": r.error_count,
            "status": r.status,
            "updated_at": r.updated_at.isoformat(),
        }
        for r in rows
    ]


@router.post("/retention/run", summary="Enforce configured Bronze/Silver/Gold disk retention policies")
async def run_retention_cleanup(_auth: None = Depends(require_admin_if_configured)) -> Dict[str, Any]:
    """Prune expired or over-budget Medallion files according to profile retention policy."""
    return await asyncio.to_thread(GovernanceService.enforce_retention)

