"""Durable Stream Consumers: Micro-batch Medallion persistence, Dedup, DLQ, Analytics & Inference."""

import asyncio
from collections import OrderedDict
from datetime import datetime, timezone
import json
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.core.database import AsyncSessionLocal
from backend.app.core.logging import get_logger
from backend.app.core.metrics import (
    CONSUMER_LAG,
    DATA_FRESHNESS_SECONDS,
    DLQ_EVENTS,
    EVENTS_CONSUMED,
    PROCESSING_FAILURES,
    PROCESSING_LATENCY,
)
from backend.app.models.governance import DeadLetterEvent, StreamCheckpoint
from backend.app.models.market import Kline, Symbol, SyncCheckpoint
from backend.app.schemas.events import CanonicalAggTradeEvent, CanonicalKlineEvent
from backend.app.services.data_quality_service import DataQualityService
from backend.app.services.governance_service import GovernanceService
from backend.app.storage import get_data_root
from backend.app.storage.medallion import MedallionStorageManager
from backend.app.streaming.broker import BrokerMessage, MessageBroker, PullSubscription
from backend.app.streaming.telemetry import PipelineTelemetryTracker
from backend.app.streaming.ws_hub import WSBroadcastHub
from ml.incremental_analytics import IncrementalAnalyticsEngine

logger = get_logger("StreamConsumers")


class BoundedDedupCache:
    """Fixed-capacity FIFO/LRU deduplication cache preventing unbounded memory growth."""

    def __init__(self, maxsize: int = 10000):
        self.maxsize = maxsize
        self._items: OrderedDict[str, None] = OrderedDict()

    def seen(self, key: str) -> bool:
        if key in self._items:
            self._items.move_to_end(key)
            return True
        self._items[key] = None
        if len(self._items) > self.maxsize:
            self._items.popitem(last=False)
        return False


class MedallionStreamConsumer:
    """Durable JetStream pull consumer implementing micro-batched Bronze/Silver/SQL + Incremental Analytics."""

    def __init__(
        self,
        broker: MessageBroker,
        durable_name: str = "medallion_stream_consumer",
        medallion: Optional[MedallionStorageManager] = None,
        analytics_engine: Optional[IncrementalAnalyticsEngine] = None,
        ws_hub: Optional[WSBroadcastHub] = None,
        on_closed_kline: Optional[Callable[[CanonicalKlineEvent], Awaitable[None]]] = None,
        session_factory: Optional[Callable[[], Any]] = None,
        telemetry: Optional[PipelineTelemetryTracker] = None,
    ):
        self.broker = broker
        self.durable_name = durable_name
        self.medallion = medallion or MedallionStorageManager()
        self.analytics_engine = analytics_engine or IncrementalAnalyticsEngine(
            checkpoint_dir=get_data_root() / settings.storage.checkpoint_subdir,
            max_bars=settings.resources.online_window_max_bars,
        )
        self.ws_hub = ws_hub
        self.on_closed_kline = on_closed_kline
        self._session_factory = session_factory or AsyncSessionLocal
        self.telemetry = telemetry

        self._dedup = BoundedDedupCache(maxsize=max(settings.resources.stream_queue_maxsize * 2, 5000))
        self._sub: Optional[PullSubscription] = None
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # Bounded micro-batch buffers (holds parsed dicts + pending BrokerMessages to ACK after flush)
        self._bronze_buf: Dict[tuple[str, str], List[Dict[str, Any]]] = {}
        self._silver_trades_buf: Dict[str, List[Dict[str, Any]]] = {}
        self._silver_klines_buf: Dict[tuple[str, str], List[Dict[str, Any]]] = {}
        self._pending_ack_msgs: List[BrokerMessage] = []
        self._buffer_bytes = 0
        self._last_flush_ts = time.monotonic()

        self.consumed_count = 0
        self.dedup_skipped_count = 0
        self.flushed_batches_count = 0
        self.dlq_count = 0
        self.last_seq = 0
        self.last_flush_at: Optional[datetime] = None

    async def start(self) -> None:
        if self._running:
            return
        if not self.broker.is_connected():
            await self.broker.connect()
        self._sub = await self.broker.pull_subscribe(subject="market.>", durable=self.durable_name)
        self._running = True
        self._last_flush_ts = time.monotonic()
        self._task = asyncio.create_task(self._consume_loop(), name="medallion_stream_consumer")
        logger.info(f"Started durable consumer '{self.durable_name}'")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        # Flush any buffered records safely before shutdown
        try:
            await self.flush_microbatch()
            self.analytics_engine.save_checkpoints()
        except Exception as exc:
            logger.error(f"Error flushing micro-batch on stop: {exc}")
        if self._sub:
            await self._sub.unsubscribe()
            self._sub = None

    async def process_single_batch(self, batch_size: Optional[int] = None, timeout: float = 0.5) -> int:
        """Pull and stage one batch; exposed for deterministic integration tests."""
        if not self._sub:
            self._sub = await self.broker.pull_subscribe(subject="market.>", durable=self.durable_name)
        msgs = await self._sub.fetch(batch=batch_size or settings.resources.consumer_batch_size, timeout=timeout)
        if not msgs:
            if self._should_flush():
                await self.flush_microbatch()
            return 0

        for msg in msgs:
            await self._handle_message(msg)

        if self._should_flush():
            await self.flush_microbatch()
        return len(msgs)

    async def _consume_loop(self) -> None:
        last_lag_poll = 0.0
        while self._running:
            try:
                await self.process_single_batch(
                    batch_size=settings.resources.consumer_batch_size,
                    timeout=0.5,
                )
                now = time.monotonic()
                if now - last_lag_poll >= 5.0:
                    last_lag_poll = now
                    info = await self.broker.get_stream_info()
                    for c in info.get("consumers", []):
                        CONSUMER_LAG.labels(
                            stream=info.get("stream", "MARKET_EVENTS"),
                            consumer=c["name"],
                        ).set(c.get("lag", 0))
            except asyncio.CancelledError:
                break
            except Exception as exc:
                PROCESSING_FAILURES.labels(stage="stream_consumer").inc()
                logger.error(f"Consumer loop error: {exc}")
                await asyncio.sleep(1.0)

    def _should_flush(self) -> bool:
        total_records = (
            sum(len(v) for v in self._bronze_buf.values())
        )
        if total_records == 0:
            return False
        age = time.monotonic() - self._last_flush_ts
        max_bytes = settings.resources.bronze_buffer_max_mb * 1024 * 1024
        return (
            total_records >= settings.resources.bronze_flush_max_records
            or age >= settings.resources.microbatch_flush_max_age_sec
            or self._buffer_bytes >= max_bytes
        )

    async def _route_to_dlq(self, msg: BrokerMessage, symbol: str, stream_type: str, reason: str) -> None:
        self.dlq_count += 1
        DLQ_EVENTS.labels(stream=stream_type, symbol=symbol, reason="consumer_error").inc()
        try:
            await self.broker.publish(
                subject=f"market.dlq.{stream_type}.{symbol}",
                payload=msg.payload,
                headers={"x-error-reason": reason[:200], "x-orig-subject": msg.subject},
            )
        except Exception as pub_exc:
            logger.warning(f"Failed publishing DLQ message to broker: {pub_exc}")

        try:
            async with self._session_factory() as db:
                db.add(DeadLetterEvent(
                    subject=msg.subject,
                    stream_type=stream_type,
                    symbol=symbol,
                    event_id=msg.headers.get("Nats-Msg-Id"),
                    payload_json=msg.payload.decode("utf-8", errors="replace")[:4000],
                    error_reason=reason[:1000],
                    delivery_count=msg.delivery_count,
                    status="QUARANTINED",
                ))
                await db.commit()
        except Exception as db_exc:
            logger.error(f"Failed recording DeadLetterEvent in DB: {db_exc}")
        await msg.term()

    async def _handle_message(self, msg: BrokerMessage) -> None:
        t0 = time.perf_counter()
        raw_text = msg.payload.decode("utf-8", errors="replace")
        try:
            raw_obj = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            if self.telemetry:
                self.telemetry.record_stage_error("consumer_handle")
            await self._route_to_dlq(msg, "UNKNOWN", "json_decode", f"Invalid JSON: {exc}")
            return

        event_type = raw_obj.get("event_type")
        symbol = str(raw_obj.get("symbol", "UNKNOWN")).upper()
        try:
            if event_type == "aggTrade":
                evt = CanonicalAggTradeEvent.model_validate(raw_obj)
            elif event_type == "kline":
                evt = CanonicalKlineEvent.model_validate(raw_obj)
            else:
                raise ValueError(f"Unknown canonical event_type: {event_type!r}")
        except Exception as exc:
            if self.telemetry:
                self.telemetry.record_stage_error("consumer_handle")
            await self._route_to_dlq(msg, symbol, str(event_type or "unknown"), f"Schema validation: {exc}")
            return

        # Deduplicate repeated delivery of identical event_id
        if self._dedup.seen(evt.event_id):
            self.dedup_skipped_count += 1
            if self.telemetry:
                self.telemetry.record_stage("consumer_handle", (time.perf_counter() - t0) * 1000.0)
            await msg.ack()
            return

        self.consumed_count += 1
        self.last_seq = max(self.last_seq, msg.stream_seq)
        EVENTS_CONSUMED.labels(consumer=self.durable_name, symbol=evt.symbol).inc()

        # Append to Bronze buffer
        self._bronze_buf.setdefault((evt.event_type, evt.symbol), []).append(raw_obj)
        self._buffer_bytes += len(msg.payload)
        self._pending_ack_msgs.append(msg)

        t_cons_done = time.perf_counter()
        if self.telemetry:
            self.telemetry.record_stage("consumer_handle", (t_cons_done - t0) * 1000.0)

        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        freshness_sec = max(0.0, (now_naive - evt.event_time).total_seconds())
        DATA_FRESHNESS_SECONDS.labels(symbol=evt.symbol, stream=evt.event_type).set(freshness_sec)

        # Update real-time incremental analytics state & Silver buffers
        t_ana0 = time.perf_counter()
        if isinstance(evt, CanonicalAggTradeEvent):
            self._silver_trades_buf.setdefault(evt.symbol, []).append(evt.model_dump())
            state = self.analytics_engine.get_or_create(evt.symbol, "1m")
            trade_snap = state.update_trade(evt.price, evt.quantity, evt.trade_time)
            if self.ws_hub:
                self.ws_hub.publish_symbol_update(evt.symbol, {
                    "symbol": evt.symbol,
                    "live_price": trade_snap["live_price"],
                    "live_trade_qty": trade_snap["live_trade_qty"],
                    "live_trade_time": trade_snap["live_trade_time"],
                    "live_trades_count": trade_snap["live_trades_count"],
                    "live_vwap": trade_snap["live_vwap"],
                })
        elif isinstance(evt, CanonicalKlineEvent):
            state = self.analytics_engine.get_or_create(evt.symbol, evt.timeframe)
            if evt.is_closed:
                self._silver_klines_buf.setdefault((evt.symbol, evt.timeframe), []).append(evt.model_dump())
                snap = state.update_closed_bar(
                    open_time=evt.open_time,
                    open_price=evt.open,
                    high=evt.high,
                    low=evt.low,
                    close=evt.close,
                    volume=evt.volume,
                )
                if self.on_closed_kline:
                    asyncio.create_task(self._safe_closed_callback(evt))
            else:
                snap = state.snapshot()

            if self.ws_hub:
                self.ws_hub.publish_symbol_update(evt.symbol, {
                    "symbol": evt.symbol,
                    "live_price": evt.close,
                    "kline_1m": {
                        "open_time": evt.open_time.isoformat(),
                        "open": evt.open,
                        "high": evt.high,
                        "low": evt.low,
                        "close": evt.close,
                        "volume": evt.volume,
                        "is_closed": evt.is_closed,
                    },
                    "analytics": snap,
                })

        t_ana1 = time.perf_counter()
        if self.telemetry:
            self.telemetry.record_stage("incremental_analytics", (t_ana1 - t_ana0) * 1000.0)
            ing_utc = evt.ingestion_time
            done_utc = datetime.now(timezone.utc).replace(tzinfo=None)
            self.telemetry.record_e2e_wall((done_utc - ing_utc).total_seconds() * 1000.0)

        PROCESSING_LATENCY.labels(stage="consumer_handle").observe(time.perf_counter() - t0)

    async def _safe_closed_callback(self, evt: CanonicalKlineEvent) -> None:
        try:
            if self.on_closed_kline:
                await self.on_closed_kline(evt)
        except Exception as exc:
            logger.warning(f"Closed-kline callback failed for {evt.symbol}: {exc}")

    async def flush_microbatch(self) -> Dict[str, Any]:
        """Persist buffered Bronze & Silver micro-batches, update checkpoints, then ACK messages."""
        if not self._pending_ack_msgs and not self._bronze_buf:
            return {"flushed": 0}

        t_fl0 = time.perf_counter()
        bronze_snap = self._bronze_buf
        silver_trades_snap = self._silver_trades_buf
        silver_klines_snap = self._silver_klines_buf
        ack_msgs = self._pending_ack_msgs

        self._bronze_buf = {}
        self._silver_trades_buf = {}
        self._silver_klines_buf = {}
        self._pending_ack_msgs = []
        self._buffer_bytes = 0
        self._last_flush_ts = time.monotonic()

        total_bronze = 0
        total_silver_trades = 0
        total_silver_klines = 0
        try:
            # 1. Write Bronze + Silver Parquet off event loop
            def _write_files():
                nonlocal total_bronze, total_silver_trades, total_silver_klines
                for (stream_type, symbol), rows in bronze_snap.items():
                    res = self.medallion.write_bronze_batch(stream_type, symbol, rows)
                    total_bronze += res["records"]
                for symbol, rows in silver_trades_snap.items():
                    res = self.medallion.write_silver_trades(symbol, rows)
                    total_silver_trades += res["records"]
                for (symbol, tf), rows in silver_klines_snap.items():
                    res = self.medallion.write_silver_klines(symbol, tf, rows)
                    total_silver_klines += res["records"]
                self.analytics_engine.save_checkpoints()

            await asyncio.to_thread(_write_files)

            # 2. Upsert closed candles + checkpoints + lineage into operational SQL DB
            async with self._session_factory() as db:
                now = datetime.now(timezone.utc).replace(tzinfo=None)
                for (symbol, tf), rows in silver_klines_snap.items():
                    await self._upsert_closed_klines_sql(db, symbol, tf, rows, now)
                    await DataQualityService.evaluate_klines(
                        db, symbol=symbol, timeframe=tf, limit=200, check_mode="STREAM"
                    )
                    await GovernanceService.record_lineage_edge(
                        db,
                        source_dataset="bronze_market_events",
                        target_dataset="silver_klines",
                        transformation="stream_microbatch_upsert",
                        records_in=len(rows),
                        records_out=len(rows),
                    )

                for (stream_type, symbol), rows in bronze_snap.items():
                    stmt = select(StreamCheckpoint).where(
                        and_(
                            StreamCheckpoint.consumer_name == self.durable_name,
                            StreamCheckpoint.symbol == symbol,
                            StreamCheckpoint.stream_type == stream_type,
                        )
                    )
                    ckpt = (await db.execute(stmt)).scalar_one_or_none()
                    last_ev_time = max(
                        datetime.fromisoformat(str(r["event_time"]).replace("Z", "+00:00")).replace(tzinfo=None)
                        for r in rows
                    )
                    if ckpt is None:
                        ckpt = StreamCheckpoint(
                            consumer_name=self.durable_name,
                            subject=f"market.{stream_type}.{symbol}",
                            symbol=symbol,
                            stream_type=stream_type,
                            last_event_time=last_ev_time,
                            last_stream_seq=self.last_seq,
                            processed_count=len(rows),
                            error_count=self.dlq_count,
                            status="ACTIVE",
                            updated_at=now,
                        )
                        db.add(ckpt)
                    else:
                        ckpt.last_event_time = last_ev_time
                        ckpt.last_stream_seq = max(ckpt.last_stream_seq, self.last_seq)
                        ckpt.processed_count += len(rows)
                        ckpt.error_count = self.dlq_count
                        ckpt.updated_at = now
                await db.commit()

            # 3. Explicitly ACK only AFTER durable storage & DB commit succeed
            for m in ack_msgs:
                await m.ack()

            self.flushed_batches_count += 1
            self.last_flush_at = datetime.now(timezone.utc).replace(tzinfo=None)
            flush_ms = (time.perf_counter() - t_fl0) * 1000.0
            if self.telemetry:
                self.telemetry.record_stage("medallion_flush", flush_ms)
            return {
                "flushed": len(ack_msgs),
                "bronze_records": total_bronze,
                "silver_trades": total_silver_trades,
                "silver_klines": total_silver_klines,
                "flush_duration_ms": round(flush_ms, 3),
            }
        except Exception as exc:
            if self.telemetry:
                self.telemetry.record_stage_error("medallion_flush")
            PROCESSING_FAILURES.labels(stage="microbatch_flush").inc()
            logger.error(f"Micro-batch flush failed ({exc}); NAKing {len(ack_msgs)} messages for redelivery")
            for m in ack_msgs:
                if m.delivery_count >= settings.streaming.nats_max_deliver:
                    await self._route_to_dlq(m, "BATCH", "flush", f"Max deliveries after flush error: {exc}")
                else:
                    await m.nak(delay=2.0)
            raise

    async def _upsert_closed_klines_sql(
        self,
        db: AsyncSession,
        symbol: str,
        timeframe: str,
        rows: List[Dict[str, Any]],
        now: datetime,
    ) -> None:
        if not rows:
            return
        open_times = []
        for r in rows:
            ot = r["open_time"]
            if isinstance(ot, str):
                ot = datetime.fromisoformat(ot.replace("Z", "+00:00")).replace(tzinfo=None)
            open_times.append(ot)

        existing_stmt = select(Kline.open_time).where(
            and_(Kline.symbol == symbol, Kline.timeframe == timeframe, Kline.open_time.in_(open_times))
        )
        existing_ots = set((await db.execute(existing_stmt)).scalars().all())
        new_klines = []
        for r, ot in zip(rows, open_times):
            if ot in existing_ots:
                continue
            existing_ots.add(ot)
            ct = r["close_time"]
            if isinstance(ct, str):
                ct = datetime.fromisoformat(ct.replace("Z", "+00:00")).replace(tzinfo=None)
            new_klines.append(Kline(
                symbol=symbol,
                timeframe=timeframe,
                open_time=ot,
                close_time=ct,
                open=float(r["open"]),
                high=float(r["high"]),
                low=float(r["low"]),
                close=float(r["close"]),
                volume=float(r["volume"]),
                quote_asset_volume=r.get("quote_asset_volume"),
                number_of_trades=r.get("number_of_trades"),
                taker_buy_base_asset_volume=r.get("taker_buy_base_asset_volume"),
                taker_buy_quote_asset_volume=r.get("taker_buy_quote_asset_volume"),
                is_closed=bool(r.get("is_closed", True)),
            ))
        if new_klines:
            db.add_all(new_klines)

        sym_obj = (await db.execute(select(Symbol).where(Symbol.symbol == symbol))).scalar_one_or_none()
        if sym_obj:
            sym_obj.last_synced_at = now

    def stats(self) -> Dict[str, Any]:
        return {
            "durable_name": self.durable_name,
            "consumed_count": self.consumed_count,
            "dedup_skipped_count": self.dedup_skipped_count,
            "flushed_batches_count": self.flushed_batches_count,
            "dlq_count": self.dlq_count,
            "last_seq": self.last_seq,
            "pending_buffer_records": sum(len(v) for v in self._bronze_buf.values()),
            "last_flush_at": self.last_flush_at.isoformat() if self.last_flush_at else None,
        }
