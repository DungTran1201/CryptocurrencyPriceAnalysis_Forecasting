"""Streaming telemetry, JetStream replay, DLQ inspection, and Coalesced WebSocket Gateway."""

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db
from backend.app.core.security import require_admin_if_configured
from backend.app.models.governance import DeadLetterEvent
from backend.app.streaming.runtime import stream_runtime

router = APIRouter(tags=["Streaming & Real-Time"])


class ReplayRequest(BaseModel):
    subject: str = Field(default="market.>")
    start_seq: Optional[int] = Field(default=1, ge=1)
    max_msgs: int = Field(default=100, ge=1, le=500)


@router.get("/streaming/status", summary="Real-time streaming, NATS JetStream, queue & incremental state status")
async def get_streaming_status() -> Dict[str, Any]:
    """Return live broker stats, WS ingestor status, bounded queue occupancy, and incremental state."""
    return await stream_runtime.status_snapshot()


@router.get("/streaming/dlq", summary="List quarantined Dead-Letter Queue events")
async def list_dlq_events(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Inspect failed or malformed events captured in the Dead-Letter ledger."""
    res = await db.execute(
        select(DeadLetterEvent).order_by(DeadLetterEvent.created_at.desc()).limit(limit)
    )
    rows = res.scalars().all()
    return [
        {
            "id": r.id,
            "subject": r.subject,
            "stream_type": r.stream_type,
            "symbol": r.symbol,
            "event_id": r.event_id,
            "error_reason": r.error_reason,
            "delivery_count": r.delivery_count,
            "status": r.status,
            "created_at": r.created_at.isoformat(),
            "replayed_at": r.replayed_at.isoformat() if r.replayed_at else None,
        }
        for r in rows
    ]


@router.post("/streaming/flush", summary="Flush pending micro-batch buffers to Bronze/Silver")
async def flush_streaming_buffer(_auth: None = Depends(require_admin_if_configured)) -> Dict[str, Any]:
    """Flush buffered streaming events into Bronze/Silver storage immediately."""
    return await stream_runtime.consumer.flush_microbatch()


@router.post("/streaming/replay", summary="Replay historical messages from NATS JetStream")
async def replay_stream_messages(
    req: ReplayRequest,
    _auth: None = Depends(require_admin_if_configured),
) -> Dict[str, Any]:
    """Read durable messages from JetStream starting at sequence or beginning."""
    if not stream_runtime.broker.is_connected():
        raise HTTPException(status_code=503, detail="Message broker is currently disconnected.")
    replayed = await stream_runtime.broker.replay_messages(
        subject=req.subject,
        start_seq=req.start_seq,
        max_msgs=req.max_msgs,
    )
    return {
        "subject": req.subject,
        "start_seq": req.start_seq,
        "count": len(replayed),
        "messages": [
            {
                "seq": m["seq"],
                "subject": m["subject"],
                "timestamp": m["timestamp"],
                "payload_preview": m["payload"].decode("utf-8", errors="replace")[:300],
            }
            for m in replayed
        ],
    }


@router.post("/streaming/simulate-disconnect", summary="Trigger controlled WS disconnect to test auto-reconnect")
async def simulate_ws_disconnect(_auth: None = Depends(require_admin_if_configured)) -> Dict[str, Any]:
    """Close active Binance WebSocket so auto-reconnect and REST gap-healing can be verified."""
    await stream_runtime.ingestor.simulate_disconnect_and_recover()
    return {
        "status": "DISCONNECT_TRIGGERED",
        "reconnect_count_before": stream_runtime.ingestor.reconnect_count,
    }


@router.websocket("/ws/market")
async def market_ws_gateway(websocket: WebSocket):
    """Coalesced WebSocket gateway pushing bounded real-time market & analytics snapshots."""
    q = await stream_runtime.ws_hub.register(websocket)
    try:
        while True:
            try:
                text = await asyncio.wait_for(q.get(), timeout=15.0)
                await websocket.send_text(text)
                q.task_done()
            except asyncio.TimeoutError:
                # Lightweight heartbeat frame
                await websocket.send_json({"type": "heartbeat"})
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        stream_runtime.ws_hub.unregister(websocket)

