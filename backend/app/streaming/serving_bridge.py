"""Canonical Serving Gateway Bridge over NATS Core & JetStream KV (ADR-DP-007, IFC-DP-002).

Eliminates process split-brain between StreamWorker and FastAPI by:
- Publishing coalesced market updates over NATS Core `serving.market.<SYMBOL>`
- Subscribing in FastAPI and dispatching directly to `WSBroadcastHub`
- Providing NATS Core request-reply control responders for flush & simulated disconnect
- Tracking distributed worker heartbeats with NATS KV TTL auto-expiration
"""

import asyncio
from datetime import datetime, timezone
import json
import time
from typing import Any, Callable, Dict, List, Optional

from backend.app.core.config import settings
from backend.app.core.logging import get_logger
from backend.app.streaming.broker import MessageBroker
from backend.app.streaming.hot_state import HotStateCache
from backend.app.streaming.ws_hub import WSBroadcastHub

logger = get_logger("ServingBridge")


class ServingGatewayBridge:
    """Decoupled bridge connecting StreamWorker, WorkflowWorker, and FastAPI serving processes."""

    def __init__(
        self,
        broker: MessageBroker,
        ws_hub: Optional[WSBroadcastHub] = None,
        hot_state: Optional[HotStateCache] = None,
    ):
        self.broker = broker
        self.ws_hub = ws_hub
        self.hot_state = hot_state or HotStateCache()
        self._subs: List[Any] = []
        self._running = False
        self._heartbeats: Dict[str, Dict[str, Any]] = {}

    async def start_api_subscriber(self) -> None:
        """Called inside FastAPI process lifespan to receive live ticks & heartbeats."""
        if self._running:
            return
        self._running = True

        if hasattr(self.broker, "_nc") and self.broker._nc is not None:
            nc = self.broker._nc

            async def _on_market_msg(msg):
                try:
                    payload = json.loads(msg.data.decode("utf-8"))
                    symbol = payload.get("symbol") or msg.subject.split(".")[-1]
                    # Cache in local hot state
                    await self.hot_state.put_json(f"market.snapshot.{symbol}", payload)
                    # Forward to browser WebSocket hub
                    if self.ws_hub:
                        await self.ws_hub.publish_symbol_update(symbol, payload)
                except Exception as exc:
                    logger.debug("Error processing bridge market msg: %s", exc)

            async def _on_closed_bar(msg):
                try:
                    payload = json.loads(msg.data.decode("utf-8"))
                    symbol = payload.get("symbol")
                    self.hot_state.invalidate_local(f"market.snapshot.{symbol}" if symbol else None)
                except Exception as exc:
                    logger.debug("Error processing bridge closed bar msg: %s", exc)

            async def _on_heartbeat(msg):
                try:
                    data = json.loads(msg.data.decode("utf-8"))
                    wid = data.get("worker_id")
                    if wid:
                        self._heartbeats[wid] = data
                except Exception:
                    pass

            try:
                sub1 = await nc.subscribe("serving.market.*", cb=_on_market_msg)
                sub2 = await nc.subscribe("serving.events.closed_bar", cb=_on_closed_bar)
                sub3 = await nc.subscribe("serving.system.heartbeat", cb=_on_heartbeat)
                self._subs.extend([sub1, sub2, sub3])
                logger.info("ServingGatewayBridge API subscribers registered on NATS Core")
            except Exception as exc:
                logger.warning("Could not register bridge subscribers on NATS: %s", exc)

    async def start_worker_responders(
        self,
        flush_callback: Optional[Callable[[], Any]] = None,
        disconnect_callback: Optional[Callable[[], Any]] = None,
    ) -> None:
        """Called inside StreamWorker process to expose request-reply control handlers."""
        if hasattr(self.broker, "_nc") and self.broker._nc is not None:
            nc = self.broker._nc

            async def _on_flush_req(msg):
                try:
                    res = {}
                    if flush_callback:
                        if asyncio.iscoroutinefunction(flush_callback):
                            res = await flush_callback()
                        else:
                            res = flush_callback()
                    reply_data = json.dumps({"status": "SUCCESS", "result": res}).encode("utf-8")
                    await nc.publish(msg.reply, reply_data)
                except Exception as exc:
                    reply_data = json.dumps({"status": "ERROR", "error": str(exc)}).encode("utf-8")
                    await nc.publish(msg.reply, reply_data)

            async def _on_disconnect_req(msg):
                try:
                    res = {}
                    if disconnect_callback:
                        if asyncio.iscoroutinefunction(disconnect_callback):
                            res = await disconnect_callback()
                        else:
                            res = disconnect_callback()
                    reply_data = json.dumps({"status": "SUCCESS", "result": res}).encode("utf-8")
                    await nc.publish(msg.reply, reply_data)
                except Exception as exc:
                    reply_data = json.dumps({"status": "ERROR", "error": str(exc)}).encode("utf-8")
                    await nc.publish(msg.reply, reply_data)

            try:
                sub_fl = await nc.subscribe("serving.control.flush", cb=_on_flush_req)
                sub_dc = await nc.subscribe("serving.control.simulate_disconnect", cb=_on_disconnect_req)
                self._subs.extend([sub_fl, sub_dc])
                logger.info("ServingGatewayBridge worker control responders registered on NATS Core")
            except Exception as exc:
                logger.warning("Could not register worker control responders on NATS: %s", exc)

    async def publish_market_snapshot(self, symbol: str, data: Dict[str, Any]) -> None:
        """Publish updated symbol/indicator snapshot to NATS Core and hot state."""
        symbol = symbol.upper()
        await self.hot_state.put_json(f"market.snapshot.{symbol}", data)

        if hasattr(self.broker, "_nc") and self.broker._nc is not None:
            try:
                payload = json.dumps(data).encode("utf-8")
                await self.broker._nc.publish(f"serving.market.{symbol}", payload)
            except Exception as exc:
                logger.debug("Failed publishing serving.market.%s: %s", symbol, exc)

    async def publish_closed_bar(self, symbol: str, data: Dict[str, Any]) -> None:
        """Broadcast closed bar completion event."""
        symbol = symbol.upper()
        if hasattr(self.broker, "_nc") and self.broker._nc is not None:
            try:
                payload = json.dumps(data).encode("utf-8")
                await self.broker._nc.publish("serving.events.closed_bar", payload)
            except Exception as exc:
                logger.debug("Failed publishing serving.events.closed_bar: %s", exc)

    async def publish_heartbeat(self, role: str, worker_id: str, data: Dict[str, Any]) -> None:
        """Publish worker health & telemetry heartbeat."""
        payload = {
            "role": role,
            "worker_id": worker_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **data,
        }
        self._heartbeats[worker_id] = payload
        if hasattr(self.broker, "_nc") and self.broker._nc is not None:
            try:
                raw = json.dumps(payload).encode("utf-8")
                await self.broker._nc.publish("serving.system.heartbeat", raw)
            except Exception:
                pass

    async def request_flush(self, timeout: float = 5.0) -> Dict[str, Any]:
        """Send RPC request to active stream worker to trigger micro-batch flush."""
        if hasattr(self.broker, "_nc") and self.broker._nc is not None:
            nc = self.broker._nc
            try:
                msg = await nc.request("serving.control.flush", b"{}", timeout=timeout)
                return json.loads(msg.data.decode("utf-8"))
            except Exception as exc:
                return {"status": "UNAVAILABLE", "error": f"Stream worker did not respond: {exc}"}
        return {"status": "UNAVAILABLE", "error": "NATS broker not connected"}

    async def request_simulate_disconnect(self, timeout: float = 5.0) -> Dict[str, Any]:
        """Send RPC request to active stream worker to simulate WebSocket reconnect."""
        if hasattr(self.broker, "_nc") and self.broker._nc is not None:
            nc = self.broker._nc
            try:
                msg = await nc.request("serving.control.simulate_disconnect", b"{}", timeout=timeout)
                return json.loads(msg.data.decode("utf-8"))
            except Exception as exc:
                return {"status": "UNAVAILABLE", "error": f"Stream worker did not respond: {exc}"}
        return {"status": "UNAVAILABLE", "error": "NATS broker not connected"}

    def get_worker_heartbeats(self) -> List[Dict[str, Any]]:
        """Return cached heartbeats filtered by TTL (within last 30s)."""
        now = datetime.now(timezone.utc)
        active = []
        for wid, hb in list(self._heartbeats.items()):
            try:
                ts_str = hb.get("timestamp")
                if ts_str:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if (now - ts).total_seconds() <= 30.0:
                        active.append(hb)
                    else:
                        del self._heartbeats[wid]
            except Exception:
                pass
        return active

    async def stop(self) -> None:
        """Unsubscribe all bridge listeners and reset state."""
        self._running = False
        for sub in self._subs:
            try:
                await sub.unsubscribe()
            except Exception:
                pass
        self._subs.clear()
