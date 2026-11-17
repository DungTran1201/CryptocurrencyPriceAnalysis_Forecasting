# Ingestion and Streaming Detailed Design

- **Document ID:** `DD-DP-ING-001`
- **Status:** `PROPOSED` (Specification Baseline v1.0)
- **Owner:** `@stream-orch` (Phase 1 Step 2)
- **Traceability:**
  - Requirements: `REQ-DP-ING-01`, `REQ-DP-ING-02`, `REQ-DP-ING-03`, `REQ-DP-ING-04`, `REQ-DP-SRV-01`
  - Components: `COMP-DP-01` (Ingestor), `COMP-DP-02` (BrokerAdapter), `COMP-DP-08` (ServingGatewayBridge)
  - ADRs: `ADR-DP-001`, `ADR-DP-002`, `ADR-DP-007`
  - Interfaces: `IFC-DP-001`, `IFC-DP-002`, `IFC-DP-003`
  - Phase 2 Work Items: `WI-DP-03`, `WI-DP-08`, `WI-DP-11`

---

## 1. Purpose and Scope

This document defines the target detailed design for real-time market ingestion, canonical normalization, bounded-memory outbound buffering, NATS JetStream broker connectivity, and disconnect recovery in the Data Plane. It addresses every AS-IS ingestion and broker defect identified during the Phase 1 audit (`#8`, `#16`).

---

## 2. AS-IS Ingestion & Broker Gaps (`[OBSERVED]`)

| Defect Area | Observed AS-IS Evidence | Operational Failure Mode | Target Requirement |
|---|---|---|---|
| Reconnect gap heal omits `aggTrade` & races | `binance_ws.py:143-144` fires untracked `create_task(_safe_gap_heal)`; `runtime.py:109-118` only calls `sync_incremental` + `fill_gaps` for `"1m"`; `_safe_gap_heal` (`binance_ws.py:213-218`) swallows REST failures | Missed `aggTrade` ticks during any disconnect/restart are lost forever; overlapping reconnects race on SQL `klines` and Silver Parquet | `REQ-DP-ING-01` |
| Producer shutdown/cancel loses queued events | `producer.py:46` uses volatile `asyncio.Queue`; line `155` breaks out of publish retry on `not self._running` and calls `task_done()` (`line 157`); `CancelledError` (`lines 144-146`) drops in-flight item | In-memory buffer (up to 1,000–10,000 events) is silently discarded if NATS is down or slow during `stop(drain_timeout=5.0)` | `REQ-DP-ING-02` |
| NATS reconnect orphans consumer handle | `broker.py:178-198` overwrites `self._nc`/`self._js` when `not self._nc.is_connected` without closing old handle; `consumers.py:133-170` never re-binds `self._sub` | Concurrent `producer`/`runtime` calls to `connect()` leak connections and trap `MedallionStreamConsumer` in an infinite `fetch` error loop | `REQ-DP-ING-03` |
| Malformed DLQ DB write stalls WS loop | `binance_ws.py:98-115, 158, 172` awaits `AsyncSessionLocal()` inline inside `async for raw_frame in ws` | A burst of malformed frames or slow SQLite locks pauses WebSocket frame consumption | `REQ-DP-ING-04` |
| Clean close backoff stagnation | `binance_ws.py:189-195` sleeps `min(backoff, ...)` without updating backoff on repeated clean remote closes | Rapid reconnect churn if server cleanly closes socket repeatedly | `REQ-DP-ING-01` |
| Stream storage fallback cliff | `broker.py:232-249` falls back `[max_b, 32MB, 8MB, 2MB, 512KB]` on `"insufficient storage"` | EXTENDED (`max_b=768MB`) against `docker/nats/nats.conf:8` (`512MB`) silently drops straight to `32MB` | `IFC-DP-003` |
| Subject/timeframe validation gaps | `normalizer.py:58` accepts arbitrary `k["i"]`; `events.py:66-77` omits `open_time <= close_time`; `ReplayRequest.subject` (`streaming.py:20`) unvalidated | Unsupported intervals or invalid NATS subjects pass normalization or raise unhandled HTTP 500 on `/streaming/replay` | `IFC-DP-001`, `IFC-DP-002` |

---

## 3. TO-BE Component Design

### 3.1 Binance Public WebSocket Ingestor (`COMP-DP-01`, `binance_ws.py`)

1. **Combined Stream Connection & Backoff (`REQ-DP-ING-01`)**:
   - Alternates primary (`wss://data-stream.binance.vision:9443`) and fallback (`wss://stream.binance.com:9443`) combined streams (`/stream?streams=...`) with `open_timeout=10`, `ping_interval=20`, `ping_timeout=20`, `max_queue=64` (`binance_ws.py:130-136`).
   - Both clean remote closes (`binance_ws.py:189-195`) and exceptions (`lines 198-208`) advance exponential backoff (`reconnect_min_sec * 2^k` + jitter up to `reconnect_max_sec`), resetting `backoff` only after receiving at least one valid frame or sustaining connection beyond a stability threshold (e.g., `5.0s`).
2. **Non-Blocking Malformed-Frame Quarantine (`REQ-DP-ING-04`)**:
   - `async for raw_frame in ws:` MUST NOT open `AsyncSessionLocal()` inline.
   - Instead, JSON decode errors (`json.JSONDecodeError`) and `NormalizationError` events are pushed onto a bounded non-blocking quarantine queue (`_malformed_q: asyncio.Queue(maxsize=256)`).
   - If `_malformed_q` is full, emit a rate-limited warning and increment `DLQ_EVENTS` + `PROCESSING_FAILURES` without blocking valid market frames.
   - A dedicated background drainer task (started/stopped cleanly in `start()`/`stop()`) persists queued malformed frames to `market.dlq.ws_ingest.UNKNOWN` and `dead_letter_events`, or persists safely via `producer` DLQ route.
3. **Single-Flight Post-Reconnect & Startup Gap Healing (`REQ-DP-ING-01`)**:
   - Maintain a tracked `_gap_heal_task: Optional[asyncio.Task]` and `asyncio.Lock` (or enqueue a durable workflow job on `WorkflowService`!).
   - On reconnect (`reconnect_count > 0`) AND on initial ingestor startup (when prior watermarks exist in `sync_checkpoints` / `stream_checkpoints`), trigger a **single-flight coalesced gap heal**:
     - If a gap-heal task is already running, mark `_heal_pending = True` rather than spawning overlapping tasks; when the active pass finishes, run one more pass if `_heal_pending` is set.
     - On `stop()`, cancel and await `_gap_heal_task` cleanly.
   - **What Gap Heal Covers (`1m` Klines + `aggTrades`)**:
     - **1m Klines**: Invoke `BinanceSyncService.sync_incremental(db, symbol, "1m")` + `fill_gaps(db, symbol, "1m")` using unified open-to-closed SQL+Silver upsert rules (`REQ-DP-KLN-01`).
     - **`aggTrades` (`REST /api/v3/aggTrades`)**: Read the latest persisted `agg_trade_id` watermark per tracked symbol from `stream_checkpoints.state_json` (or `agg_trades` manifest metadata), and backfill bounded windows via `GET /api/v3/aggTrades?symbol={SYM}&fromId={last_id + 1}&limit=1000` (capped per pass by `streaming.aggtrade_backfill_max_batches` to respect Binance rate limits and memory budgets).
     - Backfilled `aggTrade` batches are either published with deterministic `event_id = aggTrade:{SYM}:{agg_trade_id}` (`source="binance_rest_backfill"`) or persisted directly through `MedallionStorageManager` + manifest ledger under the workflow writer lease.
     - Failed gap-heal attempts increment `PROCESSING_FAILURES.labels(stage="gap_heal")` and schedule a persistent retry via `WorkflowService` (`RETRY_WAIT`) rather than silently dropping the error.

### 3.2 Canonical Normalizer & Schema Validation (`normalizer.py`, `schemas/events.py`, `IFC-DP-001`)

- **Schema v1.1.0 Additions**:
  - `CanonicalKlineEvent` validates `timeframe in VALID_STREAM_TIMEFRAMES` (`{"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"}`), and enforces `open_time <= close_time` (`events.py:66-77`).
  - Both `CanonicalAggTradeEvent` and `CanonicalKlineEvent` enforce `math.isfinite` on all numeric float fields (`price`, `quantity`, `open`, `high`, `low`, `close`, `volume`), preventing `NaN`/`Inf` payloads from poisoning JSON serialization or Parquet/SQL.
  - Normalize `source` explicitly (`binance_ws` vs `binance_rest_backfill`) while preserving deterministic `event_id`:
    - `aggTrade:{SYMBOL}:{agg_trade_id}`
    - `kline:{SYMBOL}:{timeframe}:{open_ms}:closed` or `kline:{SYMBOL}:{timeframe}:{open_ms}:tick:{event_ms}`

### 3.3 Bounded Event Producer & Shutdown Spill (`COMP-DP-01`, `producer.py`)

1. **Bounded Memory & Upstream Backpressure**:
   - `_queue: asyncio.Queue[QueuedEvent]` bounded by `resources.stream_queue_maxsize` (`1000` LITE / `5000` STANDARD / `10000` EXTENDED) plus an optional soft byte ceiling (`resources.bronze_buffer_max_mb`).
   - `enqueue()` sets `backpressure_active = True` at `queue_high_watermark_ratio` (`0.80`) and awaits `self._queue.put(...)`, propagating real backpressure to the WS reader (`REQ-DP-ING-02`).
2. **Startup Spool Replay & Graceful Shutdown Drain (`REQ-DP-ING-02`)**:
   - **Fix for `producer.py:155` Silent Drop**: Remove `if not self._running: break` inside `except Exception:`. While `not self._queue.empty()` and `time.monotonic() < shutdown_deadline`, `_drain_loop` continues retrying broker publish with bounded exponential backoff (`0.2s .. 2.0s`).
   - **In-Flight Tracking**: Hold `item = await self._queue.get()` in `self._in_flight: Optional[QueuedEvent]` until `broker.publish(...)` succeeds and `self._queue.task_done()` completes.
   - **Bounded Local Spill on Timeout / Cancel**: If `stop(drain_timeout)` expires or `_drain_loop` receives `CancelledError` while `self._in_flight` is non-None or `not self._queue.empty()`:
     - Collect `[self._in_flight]` + all remaining items drained via `get_nowait()`, and write them atomically (`.tmp` + `fsync` + `os.replace`) as base64/JSON lines to `{data_dir}/{dlq_subdir}/producer_spool.jsonl` (capped at `resources.producer_spool_max_mb`, e.g., `16 MB`).
     - On next `BoundedEventProducer.start()`, read and republish `producer_spool.jsonl` to JetStream before releasing normal queue flow (deleting the spool file only after all spooled events publish cleanly).
     - Increment `PROCESSING_FAILURES.labels(stage="producer_spool")` if disk spill itself fails so zero silent drops occur.

### 3.4 NATS JetStream Broker Adapter (`COMP-DP-02`, `broker.py`, `IFC-DP-003`)

1. **Reconnect Safety & Connection Epoch (`REQ-DP-ING-03`)**:
   - Protect `connect()` with `self._connect_lock = asyncio.Lock()`.
   - **Rule**: If `self._nc is not None and not self._nc.is_closed`:
     - If `self._nc.is_connected`: return immediately.
     - If temporarily reconnecting (`not self._nc.is_connected` and `not self._nc.is_closed`): wait up to `connect_timeout` for `nats-py`'s built-in reconnect loop (`max_reconnect_attempts=-1, reconnect_time_wait=2`) rather than blindly overwriting `self._nc`!
   - Only create a new `nats.connect(...)` if `self._nc is None or self._nc.is_closed`. Before replacing, ensure any stale handle is closed, then increment `self._conn_epoch += 1`.
   - Expose `@property def conn_epoch(self) -> int` on `MessageBroker`.
   - `MedallionStreamConsumer._consume_loop` checks `self._sub_epoch != self.broker.conn_epoch` (and catches `ConnectionClosedError` / invalid sub errors) to cleanly unsubscribe and re-bind `await self.broker.pull_subscribe(...)`.
2. **Stream Limits, Retention & Corrected Storage Fallback Ladder (`IFC-DP-003`)**:
   - `MARKET_EVENTS` (`RetentionPolicy.LIMITS`, `StorageType.FILE`, `DiscardPolicy.OLD` configurable per profile, `duplicate_window=nats_dedup_window_sec`, `max_age=retention_bronze_days * 86400`).
   - Reserve `main_max_bytes = 70%` and `dlq_max_bytes = 20%` (leaving 10% headroom for JetStream metadata / temporary probes; note KV buckets use `StorageType.MEMORY` per `#16`).
   - Replace coarse fallback `[max_b, 32MB, 8MB, 2MB, 512KB]` with proportional percentage steps `[1.0, 0.85, 0.70, 0.50, 0.25]` of `max_b` down to `max(4MB, ...)` so an EXTENDED/512MB server cap degrades smoothly (e.g., `~358MB`) rather than collapsing to `32MB`.
   - Log a `CRITICAL`/`WARNING` metric event whenever fallback sizing activates.
3. **Consumer Migration Safety**:
   - On `pull_subscribe`, inspect existing `consumer_info` first if present; if immutable fields (`ack_wait`, `max_deliver`, `ack_policy`) match, reuse existing durable consumer without error; if configuration changed intentionally across upgrades, log and apply controlled consumer recreation or surface explicit config-mismatch alert.
4. **`InMemoryBroker` Parity (`broker.py:441-564`)**:
   - Track `ack_wait` delivery timestamps in `InMemoryBroker` so unit/integration tests can exercise `ack_wait` expiration redelivery deterministically in addition to explicit `nak()`.
