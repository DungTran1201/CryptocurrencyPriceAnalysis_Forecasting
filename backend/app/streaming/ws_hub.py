"""Coalesced, resource-bounded WebSocket Broadcast Hub for UI live streaming."""

import asyncio
import json
import time
from typing import Any, Dict, Set
from fastapi import WebSocket

from backend.app.core.config import settings
from backend.app.core.logging import get_logger

logger = get_logger("WSBroadcastHub")


class WSBroadcastHub:
    """Coalesces high-frequency market/analytics updates before pushing to browser clients."""

    def __init__(self, coalesce_interval_ms: int | None = None):
        self.coalesce_interval_sec = (coalesce_interval_ms or settings.resources.ws_coalesce_interval_ms) / 1000.0
        self._clients: Dict[WebSocket, asyncio.Queue] = {}
        self._pending_symbols: Dict[str, Dict[str, Any]] = {}
        self._pending_system: Dict[str, Any] = {}
        self._dirty = False
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._flush_loop(), name="ws_coalesce_flush")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        for ws in list(self._clients.keys()):
            try:
                await ws.close()
            except Exception:
                pass
        self._clients.clear()

    async def register(self, websocket: WebSocket) -> asyncio.Queue:
        await websocket.accept()
        q: asyncio.Queue = asyncio.Queue(maxsize=16)
        self._clients[websocket] = q
        # Immediately push current coalesced snapshot on connect
        if self._pending_symbols:
            await self._enqueue_client(q, json.dumps({
                "type": "snapshot",
                "symbols": self._pending_symbols,
                "stream_status": self._pending_system,
            }))
        return q

    def unregister(self, websocket: WebSocket) -> None:
        self._clients.pop(websocket, None)

    def publish_symbol_update(self, symbol: str, payload: Dict[str, Any]) -> None:
        """Merge latest symbol state into coalescing buffer (non-blocking)."""
        sym = symbol.upper()
        existing = self._pending_symbols.get(sym, {})
        existing.update(payload)
        self._pending_symbols[sym] = existing
        self._dirty = True

    def publish_system_status(self, status_payload: Dict[str, Any]) -> None:
        self._pending_system = dict(status_payload)
        self._dirty = True

    async def _enqueue_client(self, q: asyncio.Queue, text: str) -> None:
        if q.full():
            # Evict oldest unconsumed snapshot in favor of fresher state (bounded client buffer)
            try:
                q.get_nowait()
                q.task_done()
            except asyncio.QueueEmpty:
                pass
        try:
            q.put_nowait(text)
        except asyncio.QueueFull:
            pass

    async def _flush_loop(self) -> None:
        while self._running:
            await asyncio.sleep(self.coalesce_interval_sec)
            if not self._dirty or not self._clients:
                continue
            self._dirty = False
            msg = json.dumps({
                "type": "tick_batch",
                "ts_ms": int(time.time() * 1000),
                "symbols": self._pending_symbols,
                "stream_status": self._pending_system,
            }, default=str)
            for q in list(self._clients.values()):
                await self._enqueue_client(q, msg)

    @property
    def client_count(self) -> int:
        return len(self._clients)

