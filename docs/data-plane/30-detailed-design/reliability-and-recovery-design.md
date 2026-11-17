# Reliability, Delivery Guarantees, and Recovery Design

- **Document ID:** `DD-DP-REL-001`
- **Status:** `PROPOSED` (Specification Baseline v1.0)
- **Owner:** `@stream-orch` (Phase 1 Step 2)
- **Traceability:**
  - Requirements: `REQ-DP-DEL-01`, `REQ-DP-DEL-02`, `REQ-DP-DEL-03`, `REQ-DP-DEL-04`, `REQ-DP-DEL-05`, `REQ-DP-DEL-06`
  - Components: `COMP-DP-03` (StreamProcessor), `COMP-DP-10` (Governance/DQ), `COMP-DP-13` (IncrementalAnalytics)
  - ADRs: `ADR-DP-002`, `ADR-DP-003`, `ADR-DP-007`
  - Interfaces: `IFC-DP-001`, `IFC-DP-002`, `IFC-DP-003`, `IFC-DP-005`
  - Phase 2 Work Items: `WI-DP-02`, `WI-DP-04`, `WI-DP-08`

---

## 1. Purpose and Delivery Semantics

The Data Plane guarantees **at-least-once broker delivery combined with idempotent multi-layer persistence and strictly post-commit broker acknowledgment**. No market event may be acknowledged (`ACK`) or deduplicated (`BoundedDedupCache`) before its Bronze raw archival, Silver Parquet/Manifest update, and SQL operational commit all succeed.

---

## 2. AS-IS Reliability Defects (`[OBSERVED]`)

| Defect | Location | Failure Impact |
|---|---|---|
| Pre-commit `BoundedDedupCache` data loss | `consumers.py:242-247` | `self._dedup.seen(evt.event_id)` inserts the ID on pull; when `flush_microbatch()` fails and NAKs (`line 445`), redelivery hits `seen() == True` and immediately calls `msg.ack()`, silently losing uncommitted data |
| Mid-loop DQ `db.commit()` | `consumers.py:373` -> `data_quality_service.py:76, 331` | Commits first symbol's `Kline`s and `DataQualityRun` inside the flush loop before remaining symbols, lineage, and `StreamCheckpoint` commit |
| Post-SQL-commit ACK error misroutes to DLQ | `consumers.py:421-445` | If `m.ack()` fails on message `k`, `except Exception` NAKs/DLQs/TERMs ALL `ack_msgs` (including already-ACK'd and already-SQL-committed items) |
| Unconditional `msg.term()` in `_route_to_dlq` | `consumers.py:186-213` | Swallows NATS DLQ and DB `DeadLetterEvent` write failures and still calls `await msg.term()`, destroying unquarantined messages |
| Unsynchronized concurrent `flush_microbatch` | `consumers.py:330` vs `streaming.py:61` | `POST /streaming/flush` can run concurrently with `_consume_loop`, racing on Silver Parquet and analytics checkpoint files |
| `stop()` cancels active flush mid-flight | `consumers.py:112-129, 341-345` | `self._task.cancel()` interrupts an in-progress flush after buffers were cleared; `CancelledError` bypasses `except Exception` (no `nak()`), and `stop()`'s final flush sees empty buffers |
| Pre-commit closed-candle inference race | `consumers.py:293-294` -> `runtime.py:120-149` -> `forecast_service.py:165-187` | Untracked `create_task(_safe_closed_callback)` runs before `flush_microbatch()` persists the closed candle to SQL, evaluating against stale `t-1` candles |
| Non-atomic & non-idempotent analytics state | `ml/incremental_analytics.py:91-113, 385-394` | `save_checkpoints()` uses non-atomic `write_text()`; `update_trade()` double-counts `live_trades_count` and `live_vwap_*` upon post-restart redelivery |
| Write-only `StreamCheckpoint` & no DLQ replay | `consumers.py:385-417`; `models/governance.py:75` | `StreamCheckpoint` is never read at startup for recovery/monotonic guarding; `DeadLetterEvent.status="REPLAYED"` has no replay path |

---

## 3. TO-BE Micro-Batch Durability State Machine (`ADR-DP-002`)

Every micro-batch (`batch_id = uuid4()`) executes under a strict state progression:

`RECEIVED -> VALIDATED -> PREPARED -> FILES_WRITTEN -> SQL_COMMITTED -> ACKED`

With deterministic failure transitions:
- `RECEIVED` or `VALIDATED` failure (malformed JSON / schema violation) -> `QUARANTINED_DLQ`
- `PREPARED` cache hit (already durably committed) -> `ACK_DUP`
- `FILES_WRITTEN` or `SQL_COMMITTED` failure -> `NAK_RETRY` (or `QUARANTINED_DLQ` if `delivery_count >= nats_max_deliver`)
- `ACKED` partial failure (after `SQL_COMMITTED`) -> `NAK_RETRY` **only on remaining un-acked messages** (never `QUARANTINED_DLQ` or `TERM`)

### 3.1 State-by-State Behavioral Contract

#### State 1: `RECEIVED`
- `_consume_loop` verifies `self._sub_epoch == self.broker.conn_epoch` (`REQ-DP-ING-03`) and pulls up to `consumer_batch_size` messages (`timeout=0.5s`).
- No in-memory dedup state, SQL state, or file state is modified during `RECEIVED`.

#### State 2: `VALIDATED` (or `QUARANTINED_DLQ`)
- Decode UTF-8 JSON and validate `CanonicalAggTradeEvent` or `CanonicalKlineEvent` (`IFC-DP-001`).
- On `JSONDecodeError` or `ValidationError` (poison pill):
  - Enter `QUARANTINED_DLQ`:
    1. Attempt publish to NATS DLQ stream `market.dlq.{stream_type}.{symbol}` with headers `x-error-reason`, `x-orig-subject`, `x-orig-seq`.
    2. Attempt SQL commit of `DeadLetterEvent(status="QUARANTINED", ...)` in an isolated short session.
    3. **Safety Gate (`REQ-DP-DEL-03`)**: Call `await msg.term()` **ONLY IF at least one durable DLQ sink (NATS DLQ publish OR DB `DeadLetterEvent` commit) succeeded**. If BOTH fail, log `ERROR`, increment `PROCESSING_FAILURES.labels(stage="dlq_write")`, and call `await msg.nak(delay=5.0)` so the message is never silently discarded.

#### State 3: `PREPARED` (`REQ-DP-DEL-01`)
- **Two-Phase `BoundedDedupCache`**:
  - `BoundedDedupCache.contains(event_id: str) -> bool`: pure read-only lookup (moves key to MRU tail if present, **never inserts**).
  - `BoundedDedupCache.commit_keys(keys: Iterable[str]) -> None`: inserts keys into LRU **only after `SQL_COMMITTED`**.
- During message staging:
  - If `self._dedup.contains(evt.event_id)` is `True`: the event was already committed in an earlier batch -> transition to `ACK_DUP` (`await msg.ack()`).
  - Track `self._batch_seen_ids: Set[str]` for the active uncommitted batch:
    - If `evt.event_id in self._batch_seen_ids`: append `msg` to `self._pending_ack_msgs` (so it will be ACK'd together when the batch reaches `SQL_COMMITTED`), and skip adding duplicate rows to Bronze/Silver buffers.
    - Else: add `evt.event_id` to `self._batch_seen_ids` and `self._staged_event_ids`, stage payload in `_bronze_buf` / `_silver_trades_buf` / `_silver_klines_buf`, and append `msg` to `_pending_ack_msgs`.
- Update in-memory live price/VWAP preview (`IncrementalSymbolState`) ONLY on non-duplicate staged events, tracking `staged_closed_klines` separately for post-commit callbacks.

#### State 4: `FILES_WRITTEN` (`REQ-DP-DEL-04`, `REQ-DP-LAKE-01`)
- Acquire `self._flush_lock: asyncio.Lock` before snapshotting `_bronze_buf`, `_silver_*_buf`, `_pending_ack_msgs`, `_staged_event_ids`, and `_batch_seen_ids`.
- Execute disk I/O via `await asyncio.to_thread(_write_files)` using immutable batch objects:
  1. **Bronze**: Write immutable `part-{ts}-{batch_id}.jsonl.zst` with unified envelope (`schema_version`, `event_id`, `event_type`, `source`, `symbol`, `timeframe`, `event_time`, `ingestion_time`, `payload`).
  2. **Silver**: Write immutable Parquet micro-batch object(s) (`part-{dt}-{batch_id}.parquet`) with explicit `SILVER_KLINE_SCHEMA` (including `taker_buy_*`) or `SILVER_TRADE_SCHEMA` (no destructive read-modify-overwrite of active partitions; compaction runs asynchronously via `WorkflowWorker`!).
  3. **Analytics Checkpoint**: Write `analytics_{sym}_{tf}.json` atomically (`tmp_path` + `flush` + `fsync` + `os.replace`) (`REQ-DP-DEL-06`).
- If `_write_files` raises any `Exception`: jump to `NAK_RETRY` (do NOT touch SQL or `_dedup`). Any orphaned uncommitted Parquet files are never added to `lake_snapshots` and are cleaned by manifest GC after grace TTL.

#### State 5: `SQL_COMMITTED` (`REQ-DP-DEL-02`, `REQ-DP-DEL-04`, `REQ-DP-DEL-05`)
- Open one isolated `async with self._session_factory() as db:` transaction:
  1. **SQL `Kline` Upsert**: Execute dialect-native `INSERT ... ON CONFLICT (symbol, timeframe, open_time) DO UPDATE` promoting `is_closed=False -> True` (`REQ-DP-KLN-01`) for all closed klines in batch.
  2. **Batch & Snapshot Manifest Registration**: Persist `batch_ledger` (`idempotency_key = f"{durable_name}:{batch_seq_range}"` or batch hash) + append new immutable file entries into a new `ACTIVE` `lake_snapshots` / `lake_manifest_files` snapshot (under manifest writer rule per `DD-DP-LAKE`).
  3. **Lineage & Monotonic `StreamCheckpoint`**:
     - Record `DataLineageEdge`.
     - Upsert `StreamCheckpoint`: compare `batch_max_seq` against `ckpt.last_stream_seq`. Only increment `ckpt.processed_count` by records with `stream_seq > ckpt.last_stream_seq` (`last_stream_seq = max(ckpt.last_stream_seq, batch_max_seq)`), preventing post-restart double counting! Also persist latest `agg_trade_id` per symbol in `ckpt.state_json` for restart/reconnect gap heal (`REQ-DP-ING-01`).
  4. **No Mid-Loop `db.commit()` (`REQ-DP-DEL-04`)**:
     - `DataQualityService.evaluate_klines(..., commit=False)` MUST NOT call `await db.commit()` internally when `commit=False` (or lightweight stream DQ is flushed in the same transaction / offloaded to a post-commit workflow task).
  5. Execute **one single `await db.commit()`** committing all SQL changes atomically.
- **On SQL Exception**: Execute `await db.rollback()`, keep `_dedup` unchanged, transition to `NAK_RETRY` (or `QUARANTINED_DLQ` if `delivery_count >= nats_max_deliver`).
- **Post-Commit Hooks (Executed ONLY AFTER `await db.commit()` returns)**:
  1. `self._dedup.commit_keys(committed_event_ids)` (`REQ-DP-DEL-01`).
  2. `self.last_seq = max(self.last_seq, batch_max_seq)`.
  3. Update `HotStateCache` (`hot_state` KV) & emit `serving.market.*` via `ServingGatewayBridge`.
  4. **Closed-Candle Inference Ordering (`REQ-DP-DEL-05`)**: For each closed kline in `committed_closed_klines`, either publish `serving.events.closed_bar` or enqueue into a bounded in-consumer inference queue (`maxsize=32`, drained sequentially by a tracked worker task / `asyncio.Semaphore(1)`), guaranteeing `ForecastService.try_triggered_forecast()` reads the freshly committed SQL `Kline` row and never spawns unbounded concurrent tasks.

#### State 6: `ACKED`
- Iterate `ack_msgs` using index tracking:
  ```python
  for idx, m in enumerate(ack_msgs):
      await m.ack()
  ```
- **Post-Commit ACK Failure Handling (`REQ-DP-DEL-02`)**:
  - If `m.ack()` raises at index `k`:
    - Log `WARNING` and increment `PROCESSING_FAILURES.labels(stage="broker_ack")`.
    - Best-effort `await m.nak(delay=2.0)` **ONLY on `ack_msgs[k:]`** (catching transport errors cleanly).
    - **NEVER** route `ack_msgs` to `_route_to_dlq` or call `m.term()` once `SQL_COMMITTED` succeeded.
    - When JetStream redelivers `ack_msgs[k:]`: if same process, `BoundedDedupCache.contains()` immediately ACKs safely; if restarted (cold cache), SQL `Kline` upsert, `batch_ledger` idempotency check, and monotonic `StreamCheckpoint.last_stream_seq` prevent duplicate SQL counts or corrupt state.

---

## 4. Shutdown Safety & DLQ Replay

### 4.1 Cancellation-Safe `MedallionStreamConsumer.stop()` (`REQ-DP-DEL-02`)
1. Set `self._running = False` and notify `_consume_loop` to stop pulling new batches.
2. Await `self._task` up to `graceful_stop_timeout = 10.0s` so any active `flush_microbatch()` finishes normally (only call `self._task.cancel()` on hard timeout).
3. Inside `flush_microbatch()`, capture `BaseException` (including `asyncio.CancelledError`) before `SQL_COMMITTED`: if cancelled mid-flush before SQL commit, execute best-effort `nak()` on `ack_msgs` (without touching `_dedup`) before re-raising `CancelledError`.
4. Once `_consume_loop` exits, execute `await self.flush_microbatch()` under `_flush_lock`, await bounded closed-candle callback drain, and atomically save `analytics_engine.save_checkpoints()`.

### 4.2 Incremental Analytics State Idempotency (`REQ-DP-DEL-06`)
- Extend `IncrementalSymbolState.to_checkpoint()` (`ml/incremental_analytics.py:302-328`) to persist `last_agg_trade_id: Optional[int]`, `live_price`, `live_trades_count`, `live_vwap_pv`, `live_vwap_vol`.
- Guard `IncrementalSymbolState.update_trade(price, qty, trade_time, agg_trade_id=...)` with monotonic `if agg_trade_id is not None and self.last_agg_trade_id is not None and agg_trade_id <= self.last_agg_trade_id: return snapshot`, ensuring zero double-counting of `live_trades_count` or `live_vwap` across redeliveries or restarts.
- Atomic checkpoint persistence: write `.tmp` -> `flush` -> `fsync` -> `os.replace`. On corrupt JSON load, log `ERROR`, increment `PROCESSING_FAILURES.labels(stage="analytics_checkpoint")`, and rebuild rolling state from recent Silver/SQL closed bars rather than silently resetting to empty.

### 4.3 Quarantined DLQ Replay Workflow (`DeadLetterEvent`)
- Implement `POST /api/v1/streaming/dlq/{dlq_id}/replay` (and batch replay) via `StreamProcessor` / `WorkflowService`:
  - Loads `DeadLetterEvent` (`status == "QUARANTINED"`), validates/repairs payload against `IFC-DP-001`, republishes to NATS subject (`market.aggtrade.*` / `market.kline.*`) or marks `IGNORED`, and atomically updates `DeadLetterEvent.status = "REPLAYED"` and `replayed_at = now_utc`.
