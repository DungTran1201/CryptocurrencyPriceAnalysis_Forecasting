"""Binance Public WebSocket Connector with bounded queue, reconnection & REST gap-heal."""

import asyncio
from datetime import datetime, timezone
import json
import random
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional
import websockets

from backend.app.core.config import settings
from backend.app.core.database import AsyncSessionLocal
from backend.app.core.logging import get_logger
from backend.app.core.metrics import DLQ_EVENTS, EVENTS_RECEIVED, PROCESSING_FAILURES
from backend.app.models.governance import DeadLetterEvent
from backend.app.streaming.normalizer import (
    NormalizationError,
    normalize_binance_ws_payload,
    subject_for_event,
)
from backend.app.streaming.producer import BoundedEventProducer
from backend.app.streaming.telemetry import PipelineTelemetryTracker

logger = get_logger("BinanceWSIngestor")


def build_combined_stream_url(
    base_url: str,
    symbols: List[str],
    streams: List[str],
) -> str:
    """Build Binance combined stream URL e.g. /stream?streams=btcusdt@aggTrade/btcusdt@kline_1m."""
    parts = []
    for sym in symbols:
        s_low = sym.strip().lower()
        for st in streams:
            parts.append(f"{s_low}@{st}")
    stream_path = "/".join(parts)
    return f"{base_url.rstrip('/')}/stream?streams={stream_path}"


class BinanceWebSocketIngestor:
    """Connects to Binance public WS streams and pushes canonical events to BoundedEventProducer."""

    def __init__(
        self,
        producer: BoundedEventProducer,
        symbols: Optional[List[str]] = None,
        streams: Optional[List[str]] = None,
        on_reconnect_gap_heal: Optional[Callable[[], Awaitable[None]]] = None,
        telemetry: Optional[PipelineTelemetryTracker] = None,
    ):
        self.producer = producer
        self.symbols = [s.upper() for s in (symbols or settings.streaming.symbols)]
        self.streams = list(streams or settings.streaming.streams)
        self.on_reconnect_gap_heal = on_reconnect_gap_heal
        self.telemetry = telemetry

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._ws: Any = None

        self.connected = False
        self.active_endpoint: Optional[str] = None
        self.received_count = 0
        self.malformed_count = 0
        self.reconnect_count = 0
        self.last_event_time: Optional[datetime] = None
        self.last_error: Optional[str] = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name="binance_ws_ingestor")

    async def stop(self) -> None:
        self._running = False
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self.connected = False

    async def simulate_disconnect_and_recover(self) -> None:
        """Close active WebSocket intentionally to verify reconnection & gap-heal recovery."""
        if self._ws is not None:
            await self._ws.close()

    async def _record_malformed(self, raw_text: str, reason: str) -> None:
        self.malformed_count += 1
        DLQ_EVENTS.labels(stream="ws_ingest", symbol="UNKNOWN", reason="normalization").inc()
        try:
            async with AsyncSessionLocal() as db:
                db.add(DeadLetterEvent(
                    subject="market.dlq.ingest",
                    stream_type="ws_ingest",
                    symbol="UNKNOWN",
                    event_id=None,
                    payload_json=raw_text[:4000],
                    error_reason=reason[:1000],
                    delivery_count=1,
                    status="QUARANTINED",
                ))
                await db.commit()
        except Exception as exc:
            logger.error(f"Failed to persist malformed WS DLQ record: {exc}")

    async def _run_loop(self) -> None:
        urls = [
            build_combined_stream_url(settings.streaming.binance_ws_base_url, self.symbols, self.streams),
            build_combined_stream_url(settings.streaming.binance_ws_fallback_url, self.symbols, self.streams),
        ]
        backoff = settings.streaming.reconnect_min_sec
        attempt = 0

        while self._running:
            url = urls[attempt % len(urls)]
            attempt += 1
            try:
                logger.info(f"Connecting to Binance WS ({len(self.symbols)} symbols, streams={self.streams})...")
                async with websockets.connect(
                    url,
                    open_timeout=10,
                    ping_interval=20,
                    ping_timeout=20,
                    max_queue=64,
                ) as ws:
                    self._ws = ws
                    self.connected = True
                    self.active_endpoint = url.split("/stream?")[0]
                    self.last_error = None
                    backoff = settings.streaming.reconnect_min_sec

                    if self.reconnect_count > 0 and self.on_reconnect_gap_heal:
                        asyncio.create_task(self._safe_gap_heal())

                    logger.info(f"Connected to Binance WS at {self.active_endpoint}")

                    async for raw_frame in ws:
                        if not self._running:
                            break
                        t_rx0 = time.perf_counter()
                        ing_ts = datetime.now(timezone.utc).replace(tzinfo=None)
                        try:
                            raw_dict = json.loads(raw_frame)
                        except json.JSONDecodeError as json_exc:
                            if self.telemetry:
                                self.telemetry.record_stage_error("ws_ingest")
                            await self._record_malformed(str(raw_frame), str(json_exc))
                            continue
                        t_rx1 = time.perf_counter()
                        if self.telemetry:
                            self.telemetry.record_stage("ws_ingest", (t_rx1 - t_rx0) * 1000.0)

                        t_norm0 = time.perf_counter()
                        try:
                            event = normalize_binance_ws_payload(raw_dict, ingestion_time=ing_ts)
                            subject = subject_for_event(event)
                            payload_bytes = event.model_dump_json().encode("utf-8")
                        except NormalizationError as norm_exc:
                            if self.telemetry:
                                self.telemetry.record_stage_error("normalize")
                            await self._record_malformed(str(raw_frame), str(norm_exc))
                            continue
                        t_norm1 = time.perf_counter()
                        if self.telemetry:
                            self.telemetry.record_stage("normalize", (t_norm1 - t_norm0) * 1000.0)

                        self.received_count += 1
                        self.last_event_time = ing_ts
                        EVENTS_RECEIVED.labels(stream=event.event_type, symbol=event.symbol).inc()

                        await self.producer.enqueue(
                            subject=subject,
                            payload=payload_bytes,
                            msg_id=event.event_id,
                            symbol=event.symbol,
                            stream_label=event.event_type,
                        )
                # Loop ended cleanly (e.g. remote/simulated WS close frame)
                if self._running:
                    self.connected = False
                    self._ws = None
                    self.reconnect_count += 1
                    logger.warning("Binance WS closed cleanly; scheduling reconnect...")
                    await asyncio.sleep(min(backoff, settings.streaming.reconnect_max_sec))
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.connected = False
                self._ws = None
                self.reconnect_count += 1
                self.last_error = str(exc)
                PROCESSING_FAILURES.labels(stage="binance_ws").inc()
                jitter = random.uniform(0.1, 0.7)
                sleep_sec = min(backoff + jitter, settings.streaming.reconnect_max_sec)
                logger.warning(f"Binance WS disconnected ({exc}); reconnecting in {sleep_sec:.1f}s...")
                await asyncio.sleep(sleep_sec)
                backoff = min(backoff * 2.0, settings.streaming.reconnect_max_sec)
            finally:
                self.connected = False
                self._ws = None

    async def _safe_gap_heal(self) -> None:
        try:
            if self.on_reconnect_gap_heal:
                await self.on_reconnect_gap_heal()
        except Exception as exc:
            logger.warning(f"Post-reconnect REST gap heal failed: {exc}")

    def stats(self) -> Dict[str, Any]:
        return {
            "connected": self.connected,
            "endpoint": self.active_endpoint,
            "symbols": self.symbols,
            "streams": self.streams,
            "received_count": self.received_count,
            "malformed_count": self.malformed_count,
            "reconnect_count": self.reconnect_count,
            "last_event_time": self.last_event_time.isoformat() if self.last_event_time else None,
            "last_error": self.last_error,
        }
