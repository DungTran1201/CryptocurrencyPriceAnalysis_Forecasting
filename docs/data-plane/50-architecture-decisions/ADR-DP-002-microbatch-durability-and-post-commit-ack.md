# ADR-DP-002: Micro-Batch Durability State Machine & Post-Commit Acknowledgment

- **Status:** Accepted (Phase 1 Baseline)
- **Date:** 2026-11-17
- **Supersedes:** Pre-commit dedup/flush semantics in `docs/40-adr/ADR-004-incremental-streaming-and-microbatch-semantics.md`
- **Linked Requirements:** `REQ-DP-ING-01..04`, `REQ-DP-DEL-01..06`
- **Linked Components:** `COMP-DP-01`, `COMP-DP-02`, `COMP-DP-03`, `COMP-DP-13`

---

## 1. Context & Observed Evidence (`OBSERVED` `#8`, `#9`)
1. **Pre-Commit Dedup Data Loss (`consumers.py:242-247`):** `MedallionStreamConsumer._handle_message()` calls `self._dedup.seen(evt.event_id)` on message pull *before* buffering, Parquet/Bronze writes, or SQL commit. If `flush_microbatch()` fails and `NAK`s the batch (`consumers.py:445`), JetStream redelivers ~2s later and `_handle_message` treats the uncommitted events as duplicates and calls `await msg.ack()`, permanently losing data.
2. **Mid-Loop Commit & Post-Commit ACK Bug (`consumers.py:373, 421-445`):** `DataQualityService.evaluate_klines` calls `await db.commit()` mid-loop (`data_quality_service.py:76,331`), committing partial symbols before `StreamCheckpoint` updates. If `m.ack()` fails after SQL commit (`421-422`), `except Exception` attempts `nak()`/`_route_to_dlq` -> `m.term()`, potentially quarantining already-committed events.
3. **Flush Concurrency & Pre-Commit Inference (`consumers.py:293-294, 330`):** `flush_microbatch()` lacks an `asyncio.Lock` against `POST /streaming/flush`, and spawns untracked `asyncio.create_task` for closed-bar ML inference *before* the closed candle is committed to SQL.
4. **Silent DLQ Drop (`consumers.py:186-213`):** `_route_to_dlq` calls `await msg.term()` unconditionally even if both NATS DLQ publish and SQL `DeadLetterEvent` fail.
5. **Producer & Broker Gaps (`producer.py:62-75,155`, `broker.py:178-198`, `binance_ws.py:98-144`):** `producer.stop()` breaks publish retries and drops queued/in-flight items; `broker.connect()` overwrites `_nc`/`_js` without closing prior handles, orphaning `_sub`; `binance_ws.py` stalls WS reads on inline `_record_malformed` DB writes and omits `aggTrade` gap healing.

## 2. Options Considered
1. **Option A — Per-Message Synchronous Persistence & ACK:** Rejected; writing Parquet and committing SQLite WAL per `aggTrade` tick causes severe write amplification and violates single-node CPU/I/O bounds (`ADR-004`).
2. **Option B — Fire-and-Forget Async Flush with Immediate ACK:** Rejected; violates zero silent data loss (`AGENTS.md` / `REQ-DP-DEL-*`).
3. **Option C — Six-Stage Transactional Micro-Batch State Machine + Two-Phase Dedup + Producer Spill (`PROPOSED`):** Keep bounded micro-batching while gating every irreversible state transition on durable persistence.

## 3. Decision
Adopt **Option C**:
1. **Six-Stage Micro-Batch Lifecycle (Serialized under `self._flush_lock = asyncio.Lock()`):**
   - `RECEIVED` -> `VALIDATED` (schema v1.1 `open_time <= close_time` + timeframe allowlist; invalid -> `QUARANTINED_DLQ`, calling `msg.term()` **only if** NATS `MARKET_DLQ` OR SQL `DeadLetterEvent` commit succeeds, else `msg.nak(delay=5.0)`).
   - `PREPARED`: Read-only `self._dedup.contains(event_id)` check (safe because `_dedup` holds *only* committed IDs). Intra-batch duplicates stage their `BrokerMessage` handles to await batch commit.
   - `FILES_WRITTEN`: Off-loop `asyncio.to_thread` writes **immutable** Bronze `zstd` JSONL + immutable Silver Parquet objects + atomic `analytics_{sym}_{tf}.json` (`tmp + fsync + os.replace`).
   - `SQL_COMMITTED`: Single atomic DB transaction commits `Kline` (`ON CONFLICT` promotion), `DataQualityService(..., commit=False)`, `batch_ledger`, `lake_snapshots`, `DataLineageEdge`, `SyncCheckpoint`, and monotonic `StreamCheckpoint` (only counting `stream_seq > ckpt.last_stream_seq`).
   - **Post-Commit Side Effects (strictly after `await db.commit()`):** Call `self._dedup.commit_keys(committed_ids)`, emit `serving.events.closed_bar` / `serving.market.<SYMBOL>`, and trigger closed-bar ML inference via bounded `asyncio.Semaphore(1)`.
   - `ACKED`: Iterate `ack_msgs`; if `m.ack()` raises, `nak(delay=2.0)` only un-acked subset — **never** `DLQ` or `TERM` committed messages.
2. **Ingestion & Reconnect Resilience:**
   - `BoundedEventProducer` retains `in_flight` through `drain_timeout`, spilling `in_flight` + remaining queue to atomic `data/dlq/producer_spool.jsonl` on timeout/cancel and draining spool first on startup.
   - `NatsJetStreamBroker` serializes `connect()` under `_connect_lock`, preserves live/reconnecting `_nc`, and bumps `_conn_epoch` on fresh connect so `MedallionStreamConsumer` re-binds `_sub`.
   - `BinanceWebSocketIngestor` queues malformed frames off the WS receive loop and triggers single-flight REST backfill for both `1m` klines and `/api/v3/aggTrades?fromId`.

## 4. Consequences
- **Positive:** Eliminates silent data loss across flush failures, shutdowns, NATS restarts, and malformed bursts while preserving high micro-batch throughput.
- **Negative / Mitigation:** Requires `batch_ledger` & monotonic `StreamCheckpoint` updates to guarantee idempotency if a crash occurs between `SQL_COMMITTED` and `ACKED`; verified explicitly via fault-injection tests (`TC-DP-002..008`, `TC-DP-FI-02..09`).
