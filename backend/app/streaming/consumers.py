"""Durable Stream Consumers: Micro-batch Medallion persistence, Dedup, DLQ, Analytics & Inference."""

import asyncio
from collections import OrderedDict
from datetime import datetime, timezone
import hashlib
import json
import time
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional
import uuid
from sqlalchemy import select, and_, func
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
from backend.app.models.lake import BatchLedger
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
    """Fixed-capacity FIFO/LRU deduplication cache supporting two-phase post-commit insertion."""

    def __init__(self, maxsize: int = 10000):
        self.maxsize = maxsize
        self._items: OrderedDict[str, None] = OrderedDict()

    def contains(self, key: str) -> bool:
        """Read-only membership check; moves existing key to MRU end without inserting."""
        if key in self._items:
            self._items.move_to_end(key)
            return True
        return False

    def add(self, key: str) -> None:
        """Insert a single committed key into the bounded LRU cache."""
        if key in self._items:
            self._items.move_to_end(key)
            return
        self._items[key] = None
        while len(self._items) > self.maxsize:
            self._items.popitem(last=False)

    def commit_keys(self, keys: Iterable[str]) -> None:
        """Insert a batch of keys ONLY after durable file + SQL persistence commits (REQ-DP-DEL-01)."""
        for k in keys:
            if k:
                self.add(k)

    def seen(self, key: str) -> bool:
        """Legacy helper checking and inserting immediately."""
        if self.contains(key):
            return True
        self.add(key)
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
        self._sub_epoch: int = -1
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._flush_lock = asyncio.Lock()

        # Bounded micro-batch buffers (holds parsed dicts + pending BrokerMessages to ACK after flush)
        self._bronze_buf: Dict[tuple[str, str], List[Dict[str, Any]]] = {}
        self._silver_trades_buf: Dict[str, List[Dict[str, Any]]] = {}
        self._silver_klines_buf: Dict[tuple[str, str], List[Dict[str, Any]]] = {}
        self._pending_ack_msgs: List[BrokerMessage] = []
        self._batch_seen_ids: set[str] = set()
        self._staged_event_ids: List[str] = []
        self._staged_closed_klines: List[CanonicalKlineEvent] = []
        self._buffer_bytes = 0
        self._last_flush_ts = time.monotonic()

        # Bounded post-commit closed-candle callback concurrency
        self._closed_kline_sem = asyncio.Semaphore(1)
        self._closed_kline_tasks: set[asyncio.Task] = set()

        self.consumed_count = 0
        self.dedup_skipped_count = 0
        self.flushed_batches_count = 0
        self.dlq_count = 0
        self.last_seq = 0
        self.last_flush_at: Optional[datetime] = None
        self.last_batch_state: str = "IDLE"

    async def _ensure_subscription(self) -> PullSubscription:
        broker_epoch = int(getattr(self.broker, "conn_epoch", 0))
        if self._sub is None or self._sub_epoch != broker_epoch:
            if self._sub is not None:
                try:
                    await self._sub.unsubscribe()
                except Exception:
                    pass
            if not self.broker.is_connected():
                await self.broker.connect()
                broker_epoch = int(getattr(self.broker, "conn_epoch", 0))
            self._sub = await self.broker.pull_subscribe(subject="market.>", durable=self.durable_name)
            self._sub_epoch = broker_epoch
        return self._sub

    async def start(self) -> None:
        if self._running:
            return
        if not self.broker.is_connected():
            await self.broker.connect()
        await self._ensure_subscription()
        self._running = True
        self._last_flush_ts = time.monotonic()
        self._task = asyncio.create_task(self._consume_loop(), name="medallion_stream_consumer")
        logger.info(f"Started durable consumer '{self.durable_name}'")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=5.0)
            except (asyncio.TimeoutError, Exception):
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
            self._task = None

        # Flush any buffered records safely under _flush_lock before shutdown
        try:
            await self.flush_microbatch()
            if self._closed_kline_tasks:
                await asyncio.gather(*list(self._closed_kline_tasks), return_exceptions=True)
            self.analytics_engine.save_checkpoints()
        except Exception as exc:
            logger.error(f"Error flushing micro-batch on stop: {exc}")
        if self._sub:
            await self._sub.unsubscribe()
            self._sub = None

    async def process_single_batch(self, batch_size: Optional[int] = None, timeout: float = 0.5) -> int:
        """Pull and stage one batch; exposed for deterministic integration tests."""
        sub = await self._ensure_subscription()
        try:
            msgs = await sub.fetch(batch=batch_size or settings.resources.consumer_batch_size, timeout=timeout)
        except Exception:
            # Force subscription re-bind on next poll if connection reset
            self._sub = None
            raise

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
        total_records = sum(len(v) for v in self._bronze_buf.values())
        if total_records == 0 and not self._pending_ack_msgs:
            return False
        age = time.monotonic() - self._last_flush_ts
        max_bytes = settings.resources.bronze_buffer_max_mb * 1024 * 1024
        return (
            total_records >= settings.resources.bronze_flush_max_records
            or age >= settings.resources.microbatch_flush_max_age_sec
            or self._buffer_bytes >= max_bytes
        )

    async def _route_to_dlq(self, msg: BrokerMessage, symbol: str, stream_type: str, reason: str) -> None:
        """Quarantine poison/exhausted message; TERM only if at least one durable DLQ sink succeeds (REQ-DP-DEL-03)."""
        self.dlq_count += 1
        DLQ_EVENTS.labels(stream=stream_type, symbol=symbol, reason="consumer_error").inc()
        broker_dlq_ok = False
        db_dlq_ok = False

        try:
            await self.broker.publish(
                subject=f"market.dlq.{stream_type}.{symbol}",
                payload=msg.payload,
                headers={"x-error-reason": reason[:200], "x-orig-subject": msg.subject},
            )
            broker_dlq_ok = True
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
            db_dlq_ok = True
        except Exception as db_exc:
            logger.error(f"Failed recording DeadLetterEvent in DB: {db_exc}")

        if broker_dlq_ok or db_dlq_ok:
            self.last_batch_state = "QUARANTINED_DLQ"
            await msg.term()
        else:
            self.last_batch_state = "NAK_RETRY"
            PROCESSING_FAILURES.labels(stage="dlq_persistence").inc()
            logger.error(
                f"Both broker and DB DLQ sinks failed for {msg.subject} (seq={msg.stream_seq}); "
                "NAKing instead of TERM to prevent silent data loss."
            )
            try:
                await msg.nak(delay=5.0)
            except Exception:
                pass

    async def _handle_message(self, msg: BrokerMessage) -> None:
        t0 = time.perf_counter()
        self.last_batch_state = "RECEIVED"
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

        self.last_batch_state = "VALIDATED"

        # 1. Check already-committed deduplication cache (read-only! Never inserts pre-commit)
        if self._dedup.contains(evt.event_id):
            self.dedup_skipped_count += 1
            if self.telemetry:
                self.telemetry.record_stage("consumer_handle", (time.perf_counter() - t0) * 1000.0)
            await msg.ack()
            return

        # 2. Check intra-batch duplicate (waits for batch commit before ACK)
        if evt.event_id in self._batch_seen_ids:
            self.dedup_skipped_count += 1
            self._pending_ack_msgs.append(msg)
            if self.telemetry:
                self.telemetry.record_stage("consumer_handle", (time.perf_counter() - t0) * 1000.0)
            return

        self.last_batch_state = "PREPARED"
        self._batch_seen_ids.add(evt.event_id)
        self._staged_event_ids.append(evt.event_id)
        self.consumed_count += 1
        EVENTS_CONSUMED.labels(consumer=self.durable_name, symbol=evt.symbol).inc()

        # Attach broker stream_seq for monotonic StreamCheckpoint accounting
        staged_raw = dict(raw_obj)
        staged_raw["_stream_seq"] = msg.stream_seq
        self._bronze_buf.setdefault((evt.event_type, evt.symbol), []).append(staged_raw)
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
            trade_snap = state.update_trade(
                evt.price,
                evt.quantity,
                evt.trade_time,
                agg_trade_id=evt.agg_trade_id,
            )
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
                # Stage closed kline to fire callback ONLY AFTER SQL commit (REQ-DP-DEL-05)
                self._staged_closed_klines.append(evt)
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

    def _schedule_closed_callback(self, evt: CanonicalKlineEvent) -> None:
        if not self.on_closed_kline:
            return
        max_q = settings.serving.closed_bar_inference_queue_max
        if len(self._closed_kline_tasks) >= max_q:
            logger.warning(f"Closed-kline callback queue full ({max_q}); skipping duplicate trigger for {evt.symbol}")
            return
        task = asyncio.create_task(self._safe_closed_callback(evt))
        self._closed_kline_tasks.add(task)
        task.add_done_callback(self._closed_kline_tasks.discard)

    async def _safe_closed_callback(self, evt: CanonicalKlineEvent) -> None:
        async with self._closed_kline_sem:
            try:
                if self.on_closed_kline:
                    await self.on_closed_kline(evt)
            except Exception as exc:
                logger.warning(f"Closed-kline callback failed for {evt.symbol}: {exc}")

    async def flush_microbatch(self) -> Dict[str, Any]:
        """Persist buffered Bronze & Silver micro-batches, commit SQL atomically, then ACK messages."""
        async with self._flush_lock:
            if not self._pending_ack_msgs and not self._bronze_buf:
                return {"flushed": 0, "state": self.last_batch_state}

            t_fl0 = time.perf_counter()
            bronze_snap = self._bronze_buf
            silver_trades_snap = self._silver_trades_buf
            silver_klines_snap = self._silver_klines_buf
            ack_msgs = self._pending_ack_msgs
            staged_event_ids = self._staged_event_ids
            closed_klines_snap = self._staged_closed_klines

            self._bronze_buf = {}
            self._silver_trades_buf = {}
            self._silver_klines_buf = {}
            self._pending_ack_msgs = []
            self._batch_seen_ids = set()
            self._staged_event_ids = []
            self._staged_closed_klines = []
            self._buffer_bytes = 0
            self._last_flush_ts = time.monotonic()

            seq_vals = [m.stream_seq for m in ack_msgs if m.stream_seq > 0]
            min_seq = min(seq_vals) if seq_vals else 0
            max_seq = max(seq_vals) if seq_vals else 0
            keys_digest = hashlib.sha256("|".join(sorted(staged_event_ids)).encode("utf-8")).hexdigest()[:16]
            idempotency_key = f"{self.durable_name}:{min_seq}:{max_seq}:{keys_digest}"

            total_bronze = 0
            total_silver_trades = 0
            total_silver_klines = 0
            sql_committed = False

            try:
                # 1. Write Bronze + Silver Parquet + atomic analytics checkpoints off event loop
                def _write_files():
                    nonlocal total_bronze, total_silver_trades, total_silver_klines
                    for (stream_type, symbol), rows in bronze_snap.items():
                        clean_rows = [{k: v for k, v in r.items() if k != "_stream_seq"} for r in rows]
                        res = self.medallion.write_bronze_batch(stream_type, symbol, clean_rows)
                        total_bronze += res["records"]
                    for symbol, rows in silver_trades_snap.items():
                        res = self.medallion.write_silver_trades(symbol, rows)
                        total_silver_trades += res["records"]
                    for (symbol, tf), rows in silver_klines_snap.items():
                        res = self.medallion.write_silver_klines(symbol, tf, rows)
                        total_silver_klines += res["records"]
                    self.analytics_engine.save_checkpoints()

                await asyncio.to_thread(_write_files)
                self.last_batch_state = "FILES_WRITTEN"

                # 2. Single atomic SQL transaction: Klines (open->closed promotion) + DQ (commit=False) + Lineage + BatchLedger + StreamCheckpoint
                async with self._session_factory() as db:
                    now = datetime.now(timezone.utc).replace(tzinfo=None)

                    existing_ledger = (
                        await db.execute(select(BatchLedger).where(BatchLedger.idempotency_key == idempotency_key))
                    ).scalar_one_or_none()

                    if existing_ledger is None:
                        ledger_entry = BatchLedger(
                            batch_id=str(uuid.uuid4()),
                            batch_type="STREAM_MICROBATCH",
                            producer_name=self.durable_name,
                            symbol=next(iter(silver_trades_snap.keys()), None)
                            or (next(iter(silver_klines_snap.keys()))[0] if silver_klines_snap else None),
                            timeframe=next(iter(silver_klines_snap.keys()))[1] if silver_klines_snap else "1m",
                            idempotency_key=idempotency_key,
                            status="COMMITTED",
                            nats_seq_start=min_seq,
                            nats_seq_end=max_seq,
                            records_received=len(ack_msgs),
                            records_written=len(staged_event_ids),
                            records_rejected=0,
                            staged_keys_json=json.dumps(staged_event_ids[:100]),
                            created_at=now,
                            committed_at=now,
                        )
                        db.add(ledger_entry)

                    for (symbol, tf), rows in silver_klines_snap.items():
                        await self._upsert_closed_klines_sql(db, symbol, tf, rows, now)
                        await DataQualityService.evaluate_klines(
                            db, symbol=symbol, timeframe=tf, limit=200, check_mode="STREAM", commit=False
                        )
                        await GovernanceService.record_lineage_edge(
                            db,
                            source_dataset="bronze_market_events",
                            target_dataset="silver_klines",
                            transformation="stream_microbatch_upsert",
                            records_in=len(rows),
                            records_out=len(rows),
                        )

                    for symbol, t_rows in silver_trades_snap.items():
                        await DataQualityService.evaluate_agg_trades(
                            db, symbol=symbol, trades=t_rows, check_mode="STREAM", commit=False
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
                        row_seqs = [int(r.get("_stream_seq") or 0) for r in rows]
                        max_row_seq = max(row_seqs) if row_seqs else max_seq

                        state_meta = None
                        if stream_type == "aggTrade":
                            max_aid = max(int(r.get("agg_trade_id", 0)) for r in rows)
                            state_meta = json.dumps({"last_agg_trade_id": max_aid})

                        if ckpt is None:
                            ckpt = StreamCheckpoint(
                                consumer_name=self.durable_name,
                                subject=f"market.{stream_type}.{symbol}",
                                symbol=symbol,
                                stream_type=stream_type,
                                last_event_time=last_ev_time,
                                last_stream_seq=max(max_row_seq, max_seq),
                                processed_count=len(rows),
                                error_count=self.dlq_count,
                                status="ACTIVE",
                                state_json=state_meta,
                                updated_at=now,
                            )
                            db.add(ckpt)
                        else:
                            prev_seq = int(ckpt.last_stream_seq or 0)
                            # Monotonic sequence guard prevents double-counting after restart redelivery
                            if existing_ledger is not None:
                                new_count = 0
                            else:
                                new_count = sum(
                                    1 for s in row_seqs if s == 0 or s > prev_seq
                                )
                            ckpt.last_event_time = max(ckpt.last_event_time, last_ev_time) if ckpt.last_event_time else last_ev_time
                            ckpt.last_stream_seq = max(prev_seq, max_row_seq, max_seq)
                            ckpt.processed_count = int(ckpt.processed_count or 0) + new_count
                            ckpt.error_count = self.dlq_count
                            if state_meta:
                                ckpt.state_json = state_meta
                            ckpt.updated_at = now

                    await db.commit()
                    sql_committed = True
                    self.last_batch_state = "COMMITTED"

                # 3. Post-commit hooks: mark dedup cache & dispatch closed-candle callbacks
                self._dedup.commit_keys(staged_event_ids)
                self.last_seq = max(self.last_seq, max_seq)
                for closed_evt in closed_klines_snap:
                    self._schedule_closed_callback(closed_evt)

                # 4. Explicitly ACK only AFTER durable storage & DB commit succeed
                acked_idx = 0
                try:
                    for idx, m in enumerate(ack_msgs):
                        acked_idx = idx
                        await m.ack()
                    self.last_batch_state = "ACKED"
                except Exception as ack_exc:
                    # SQL ALREADY COMMITTED: never route committed messages to DLQ or term()
                    self.last_batch_state = "NAK_POST_COMMIT"
                    PROCESSING_FAILURES.labels(stage="broker_ack").inc()
                    logger.warning(
                        f"Post-commit ACK failed at message {acked_idx}/{len(ack_msgs)} ({ack_exc}); "
                        "NAKing remaining un-acked messages without DLQ quarantine."
                    )
                    for m in ack_msgs[acked_idx:]:
                        try:
                            await m.nak(delay=2.0)
                        except Exception:
                            pass

                self.flushed_batches_count += 1
                self.last_flush_at = datetime.now(timezone.utc).replace(tzinfo=None)
                flush_ms = (time.perf_counter() - t_fl0) * 1000.0
                if self.telemetry:
                    self.telemetry.record_stage("medallion_flush", flush_ms)
                return {
                    "flushed": len(ack_msgs),
                    "state": self.last_batch_state,
                    "bronze_records": total_bronze,
                    "silver_trades": total_silver_trades,
                    "silver_klines": total_silver_klines,
                    "flush_duration_ms": round(flush_ms, 3),
                }
            except BaseException as exc:
                if self.telemetry:
                    self.telemetry.record_stage_error("medallion_flush")
                PROCESSING_FAILURES.labels(stage="microbatch_flush").inc()
                logger.error(f"Micro-batch flush failed before commit ({exc}); NAKing {len(ack_msgs)} messages for redelivery")
                is_cancel = isinstance(exc, asyncio.CancelledError)
                for m in ack_msgs:
                    try:
                        if not is_cancel and m.delivery_count >= settings.streaming.nats_max_deliver:
                            await self._route_to_dlq(m, "BATCH", "flush", f"Max deliveries after flush error: {type(exc).__name__}")
                        else:
                            self.last_batch_state = "NAK_RETRY"
                            await m.nak(delay=2.0)
                    except Exception:
                        pass
                raise

    async def _upsert_closed_klines_sql(
        self,
        db: AsyncSession,
        symbol: str,
        timeframe: str,
        rows: List[Dict[str, Any]],
        now: datetime,
    ) -> None:
        """Upsert klines with open->closed promotion and SyncCheckpoint synchronization (REQ-DP-KLN-01)."""
        if not rows:
            return

        dedup_by_ot: Dict[datetime, Dict[str, Any]] = {}
        for r in rows:
            ot = r["open_time"]
            if isinstance(ot, str):
                ot = datetime.fromisoformat(ot.replace("Z", "+00:00")).replace(tzinfo=None)
            prev = dedup_by_ot.get(ot)
            if prev is None or (not prev.get("is_closed", True) and bool(r.get("is_closed", True))):
                dedup_by_ot[ot] = r
            elif bool(prev.get("is_closed", True)) == bool(r.get("is_closed", True)):
                dedup_by_ot[ot] = r

        open_times = sorted(dedup_by_ot.keys())
        existing_stmt = select(Kline).where(
            and_(Kline.symbol == symbol, Kline.timeframe == timeframe, Kline.open_time.in_(open_times))
        )
        existing_rows = (await db.execute(existing_stmt)).scalars().all()
        existing_by_ot: Dict[datetime, Kline] = {k.open_time: k for k in existing_rows}

        new_klines = []
        for ot in open_times:
            r = dedup_by_ot[ot]
            ct = r["close_time"]
            if isinstance(ct, str):
                ct = datetime.fromisoformat(ct.replace("Z", "+00:00")).replace(tzinfo=None)
            incoming_closed = bool(r.get("is_closed", True))

            if ot in existing_by_ot:
                ek = existing_by_ot[ot]
                # Promote open -> closed, or update forming bar if newer; never downgrade closed -> open
                if (not ek.is_closed and incoming_closed) or (not ek.is_closed and not incoming_closed and ct >= ek.close_time):
                    ek.close_time = ct
                    ek.open = float(r["open"])
                    ek.high = float(r["high"])
                    ek.low = float(r["low"])
                    ek.close = float(r["close"])
                    ek.volume = float(r["volume"])
                    ek.quote_asset_volume = r.get("quote_asset_volume")
                    ek.number_of_trades = r.get("number_of_trades")
                    ek.taker_buy_base_asset_volume = r.get("taker_buy_base_asset_volume")
                    ek.taker_buy_quote_asset_volume = r.get("taker_buy_quote_asset_volume")
                    ek.is_closed = incoming_closed
            else:
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
                    is_closed=incoming_closed,
                ))

        if new_klines:
            db.add_all(new_klines)
        await db.flush()

        sym_obj = (await db.execute(select(Symbol).where(Symbol.symbol == symbol))).scalar_one_or_none()
        if sym_obj:
            sym_obj.last_synced_at = now

        # Keep SyncCheckpoint synchronized with stream kline persistence
        stats_res = await db.execute(
            select(func.count(Kline.id), func.min(Kline.open_time), func.max(Kline.open_time), func.max(Kline.close_time)).where(
                and_(Kline.symbol == symbol, Kline.timeframe == timeframe)
            )
        )
        total_cnt, min_open, max_open, max_close = stats_res.one()
        sync_cp = (
            await db.execute(
                select(SyncCheckpoint).where(and_(SyncCheckpoint.symbol == symbol, SyncCheckpoint.timeframe == timeframe))
            )
        ).scalar_one_or_none()
        if sync_cp is None:
            db.add(SyncCheckpoint(
                symbol=symbol,
                timeframe=timeframe,
                first_open_time=min_open,
                last_open_time=max_open,
                last_close_time=max_close,
                total_candles=int(total_cnt or 0),
                last_sync_status="SUCCESS",
                completeness_status="VERIFIED" if total_cnt else "UNPOPULATED",
                detected_gaps_count=0,
                updated_at=now,
            ))
        else:
            if min_open and (sync_cp.first_open_time is None or min_open < sync_cp.first_open_time):
                sync_cp.first_open_time = min_open
            if max_open:
                sync_cp.last_open_time = max_open
            if max_close:
                sync_cp.last_close_time = max_close
            sync_cp.total_candles = int(total_cnt or 0)
            sync_cp.last_sync_status = "SUCCESS"
            sync_cp.updated_at = now

    def stats(self) -> Dict[str, Any]:
        return {
            "durable_name": self.durable_name,
            "consumed_count": self.consumed_count,
            "dedup_skipped_count": self.dedup_skipped_count,
            "flushed_batches_count": self.flushed_batches_count,
            "dlq_count": self.dlq_count,
            "last_seq": self.last_seq,
            "last_batch_state": self.last_batch_state,
            "pending_buffer_records": sum(len(v) for v in self._bronze_buf.values()),
            "last_flush_at": self.last_flush_at.isoformat() if self.last_flush_at else None,
        }
