"""Bounded async producer queue with explicit backpressure & retry handling."""

import asyncio
from dataclasses import dataclass, field
import time
from typing import Dict, Any, Optional

from backend.app.core.config import settings
from backend.app.core.logging import get_logger
from backend.app.core.metrics import (
    BACKPRESSURE_EVENTS,
    EVENTS_PUBLISHED,
    PROCESSING_FAILURES,
    QUEUE_DEPTH,
)
from backend.app.streaming.broker import MessageBroker
from backend.app.streaming.telemetry import PipelineTelemetryTracker

logger = get_logger("BoundedProducer")


@dataclass
class QueuedEvent:
    subject: str
    payload: bytes
    msg_id: str
    symbol: str
    stream_label: str
    enqueued_mono: float = field(default_factory=time.perf_counter)


class BoundedEventProducer:
    """Bounded async buffer decoupling WebSocket reads from NATS publishes with backpressure."""

    def __init__(
        self,
        broker: MessageBroker,
        maxsize: Optional[int] = None,
        high_watermark_ratio: Optional[float] = None,
        telemetry: Optional[PipelineTelemetryTracker] = None,
    ):
        self.broker = broker
        self.maxsize = maxsize or settings.resources.stream_queue_maxsize
        self.high_watermark_ratio = high_watermark_ratio or settings.resources.queue_high_watermark_ratio
        self.telemetry = telemetry
        self._queue: asyncio.Queue[QueuedEvent] = asyncio.Queue(maxsize=self.maxsize)
        self._running = False
        self._task: Optional[asyncio.Task] = None

        self.published_count = 0
        self.backpressure_count = 0
        self.publish_error_count = 0
        self.backpressure_active = False
        self._last_bp_log = 0.0

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._drain_loop(), name="bounded_producer_drain")

    async def stop(self, drain_timeout: float = 5.0) -> None:
        self._running = False
        # Wait briefly for queued messages to flush without dropping them
        deadline = time.monotonic() + drain_timeout
        while not self._queue.empty() and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def enqueue(
        self,
        subject: str,
        payload: bytes,
        msg_id: str,
        symbol: str,
        stream_label: str,
    ) -> None:
        """Enqueue event; applies backpressure (awaits drain) instead of dropping events."""
        qsize = self._queue.qsize()
        QUEUE_DEPTH.labels(queue="ingestion_outbound").set(qsize)
        threshold = int(self.maxsize * self.high_watermark_ratio)

        if qsize >= threshold:
            self.backpressure_active = True
            self.backpressure_count += 1
            BACKPRESSURE_EVENTS.labels(stage="ingestion_queue").inc()
            now = time.monotonic()
            if now - self._last_bp_log > 5.0:
                logger.warning(
                    f"Ingestion queue at {qsize}/{self.maxsize} ({qsize / self.maxsize:.0%}). "
                    "Applying backpressure flow control."
                )
                self._last_bp_log = now
        else:
            self.backpressure_active = False

        # Blocking await when queue is full guarantees zero silent event loss
        await self._queue.put(
            QueuedEvent(
                subject=subject,
                payload=payload,
                msg_id=msg_id,
                symbol=symbol,
                stream_label=stream_label,
            )
        )
        QUEUE_DEPTH.labels(queue="ingestion_outbound").set(self._queue.qsize())

    async def _drain_loop(self) -> None:
        backoff = 0.5
        while self._running or not self._queue.empty():
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                QUEUE_DEPTH.labels(queue="ingestion_outbound").set(self._queue.qsize())
                continue

            if self.telemetry:
                self.telemetry.record_stage("bounded_queue", (time.perf_counter() - item.enqueued_mono) * 1000.0)

            published = False
            while not published:
                t_pub0 = time.perf_counter()
                try:
                    if not self.broker.is_connected():
                        await self.broker.connect()
                    await self.broker.publish(
                        subject=item.subject,
                        payload=item.payload,
                        msg_id=item.msg_id,
                    )
                    if self.telemetry:
                        self.telemetry.record_stage("nats_broker", (time.perf_counter() - t_pub0) * 1000.0)
                    self.published_count += 1
                    EVENTS_PUBLISHED.labels(stream=item.stream_label, symbol=item.symbol).inc()
                    published = True
                    backoff = 0.5
                except asyncio.CancelledError:
                    # Re-queue item on cancellation if loop hasn't exited
                    raise
                except Exception as exc:
                    self.publish_error_count += 1
                    if self.telemetry:
                        self.telemetry.record_stage_error("nats_broker")
                    PROCESSING_FAILURES.labels(stage="broker_publish").inc()
                    logger.warning(f"Broker publish error ({exc}); backing off {backoff:.1f}s")
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2.0, 10.0)
                    if not self._running:
                        break
            self._queue.task_done()
            qsize = self._queue.qsize()
            QUEUE_DEPTH.labels(queue="ingestion_outbound").set(qsize)
            if qsize < int(self.maxsize * self.high_watermark_ratio):
                self.backpressure_active = False

    def stats(self) -> Dict[str, Any]:
        qsize = self._queue.qsize()
        return {
            "queue_depth": qsize,
            "queue_maxsize": self.maxsize,
            "occupancy_pct": round((qsize / self.maxsize) * 100.0, 1) if self.maxsize else 0.0,
            "backpressure_active": self.backpressure_active,
            "backpressure_events": self.backpressure_count,
            "published_count": self.published_count,
            "publish_errors": self.publish_error_count,
        }

