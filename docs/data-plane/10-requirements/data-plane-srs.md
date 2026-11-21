# Data Plane Software Requirements Specification (`REQ-DP-*`)

**Document ID:** `DOC-DP-10-SRS`  
**Version:** `1.0.0`  
**Status:** `APPROVED_PHASE_1_BASELINE`  
**Upstream Audit Basis:** `#6`, `#7`, `#8`, `#9`, `#14`, `#15`, `#16`

---

## 1. Scope Classification: Mandatory vs. Aspirational / Optional

| Classification | Scope | Host Verification Basis (`#6`) |
|---|---|---|
| **Mandatory (Phase 2 Core)** | All 33 `REQ-DP-*` items below running natively on Windows (`LITE` embedded loopback & `STANDARD` multi-process with SQLite WAL, `.bin/nats-server.exe`, local Medallion Parquet lake, persistent DuckDB snapshots, NATS KV hot state, SQL durable workflows). | `.venv` Python `3.14.10`, `duckdb 2.0.0`, `nats-server.exe v2.15.3`, `78.19 GB` free SSD, `2.64 GB` free host RAM (`MEASURED` `#6`). |
| **Aspirational / Optional (`EXTENDED` / Future Multi-Node)** | Live PostgreSQL 16 server, MinIO S3 object storage (`S3StorageBackend` live runtime), Docker Compose multi-container runtime, optional Redis adapter for multi-replica API scale-out, and Prometheus/Grafana containers. | PostgreSQL, Docker, Redis NOT FOUND on host; WSL2 unavailable (`OBSERVED` `#6`). Contracts & migrations remain Postgres/S3-ready (`REQ-DP-CFG-01`, `REQ-DP-LAKE-05`), while live container execution stays explicitly optional/unverified until provisioned. |

---

## 2. Ingestion & Broker Requirements (`REQ-DP-ING-*`)

### `REQ-DP-ING-01` — Single-Flight WS Reconnect Gap Healing (`1m` Klines + `aggTrades`)
- **Tier:** Mandatory
- **Context [`OBSERVED` #8, #9]:** `BinanceWebSocketIngestor._run_loop` (`binance_ws.py:143-144`) spawns untracked `_safe_gap_heal()` tasks on reconnect that only heal `1m` klines (`runtime.py:109-118`), permanently losing missed `aggTrade` ticks and risking concurrent races on rapid reconnects.
- **Requirement:** On WebSocket reconnect (and bounded startup catch-up), the ingestor/sync path SHALL run a single-flight guarded backfill healing both `1m` klines and missed `aggTrade` ticks via bounded Binance REST `/api/v3/aggTrades?fromId=...` pagination, retrying transient HTTP/network failures without crashing the WS loop.
- **Acceptance Criteria:**
  1. Concurrent reconnect signals collapse into at most one active heal execution per `(symbol, stream_type)`.
  2. Mocked WS disconnect + reconnect heals both missing `1m` candles and missing `aggTrade` IDs into Silver & SQL idempotently (`TC-DP-014`, `TC-DP-FI-01`).

### `REQ-DP-ING-02` — Zero-Loss Producer Shutdown & Spill
- **Tier:** Mandatory
- **Context [`OBSERVED` #8]:** `BoundedEventProducer.stop(drain_timeout=5.0)` (`producer.py:62-75, 155`) breaks retry loops on shutdown and discards `in_flight` + queued events upon cancellation.
- **Requirement:** `BoundedEventProducer` SHALL retain its active `in_flight` event during publish retries until `drain_timeout` expires, and on timeout or cancellation SHALL atomically spill `in_flight` plus all remaining `_queue` items to a bounded disk spool (`data/dlq/producer_spool.jsonl`) and drain the spool first on next startup.
- **Acceptance Criteria:** Simulated broker outage during `producer.stop()` yields 0 lost events across restart (`TC-DP-006`, `TC-DP-FI-03`).

### `REQ-DP-ING-03` — Lock-Safe NATS Reconnect Without Orphaned Subscriptions
- **Tier:** Mandatory
- **Context [`OBSERVED` #8]:** `NatsJetStreamBroker.connect` (`broker.py:178-198`) overwrites `_nc`/`_js` when reconnecting without closing prior handles, orphaning `MedallionStreamConsumer._sub` (`consumers.py:133-170`) while `runtime.py:159` skips re-subscribing.
- **Requirement:** `NatsJetStreamBroker.connect()` SHALL serialize under an `asyncio.Lock`, preserve healthy/auto-reconnecting `_nc` instances (`not is_closed`), and increment a monotonic `conn_epoch` whenever a fresh client is created; `MedallionStreamConsumer` SHALL detect `sub_epoch != broker.conn_epoch` or closed-sub errors and re-bind `pull_subscribe`.
- **Acceptance Criteria:** Killing and restarting `nats-server` mid-stream restores consumer lag to `0` automatically without manual intervention (`TC-DP-007`, `TC-DP-FI-02`).

### `REQ-DP-ING-04` — Non-Blocking Malformed Payload Quarantine
- **Tier:** Mandatory
- **Context [`OBSERVED` #8]:** `_record_malformed` (`binance_ws.py:98-115`) opens `AsyncSessionLocal()` inline inside `async for raw_frame in ws`, stalling WS frame reads on SQLite writes.
- **Requirement:** Malformed WS frames SHALL be queued to a bounded async DLQ writer / NATS DLQ path without blocking the `async for raw_frame in ws` receive loop; canonical schema `CanonicalKlineEvent` (`IFC-DP-001`) SHALL enforce `open_time <= close_time` and `timeframe` allowlist validation.
- **Acceptance Criteria:** A burst of malformed frames records DLQ entries without stalling valid WS frames (`TC-DP-FI-09`, `TC-DP-FI-14`).

---

## 3. Stream Delivery & Processing Requirements (`REQ-DP-DEL-*`)

### `REQ-DP-DEL-01` — Post-Commit Deduplication Gate
- **Tier:** Mandatory
- **Context [`OBSERVED` #8]:** `consumers.py:242-247` inserts `event_id` into `BoundedDedupCache` immediately upon message pull, causing redeliveries after a failed flush to skip and `ACK` uncommitted data.
- **Requirement:** `BoundedDedupCache` SHALL expose read-only `contains(key)` and post-commit `commit_keys(keys)`. Keys SHALL ONLY be inserted into `BoundedDedupCache` after durable file writes and `await db.commit()` succeed. Intra-batch duplicates SHALL stage their `BrokerMessage` handles to wait for batch commit before `ACK`.
- **Acceptance Criteria:** Failed flush -> `NAK` -> redelivery persists all events exactly once (`TC-DP-002`, `TC-DP-FI-05`).

### `REQ-DP-DEL-02` — Transactional Micro-Batch Ordering & Post-Commit ACK Safety
- **Tier:** Mandatory
- **Context [`OBSERVED` #8]:** If `m.ack()` fails after SQL commit (`consumers.py:421-422`), `except Exception` NAKs/DLQs/TERMs already-committed messages (`441-445`).
- **Requirement:** Consumer flush SHALL execute strictly in order: `RECEIVED -> VALIDATED -> PREPARED -> FILES_WRITTEN -> SQL_COMMITTED -> ACKED`. If `ACK` fails after `SQL_COMMITTED`, the consumer SHALL log and best-effort `NAK` only the un-acknowledged subset and SHALL NEVER route committed messages to `MARKET_DLQ` or `TERM`.
- **Acceptance Criteria:** Injected SQL failures trigger `NAK` with zero `ACK`s; injected `ACK` failures post-commit never trigger `TERM`/DLQ and idempotently absorb redeliveries (`TC-DP-003`, `TC-DP-004`, `TC-DP-FI-04`, `TC-DP-FI-05`).

### `REQ-DP-DEL-03` — Durable DLQ Guarantee Before `TERM`
- **Tier:** Mandatory
- **Context [`OBSERVED` #8]:** `_route_to_dlq` (`consumers.py:186-213`) calls `msg.term()` unconditionally even when both NATS DLQ publish and DB `DeadLetterEvent` commit fail.
- **Requirement:** `_route_to_dlq` SHALL call `msg.term()` ONLY if at least one durable DLQ sink (`MARKET_DLQ` stream publish OR SQL `dead_letter_events` commit) succeeds; if both fail, it SHALL call `msg.nak(delay=5.0)`.
- **Acceptance Criteria:** Dual DLQ sink failure results in `NAK` rather than `TERM` (`TC-DP-FI-09`).

### `REQ-DP-DEL-04` — Flush Serialization & Atomic SQL Transactions
- **Tier:** Mandatory
- **Context [`OBSERVED` #8, #9]:** `flush_microbatch()` lacks an `asyncio.Lock` against `/streaming/flush`, and calls `DataQualityService.evaluate_klines()` which commits mid-loop (`data_quality_service.py:76, 331`) before `StreamCheckpoint` updates.
- **Requirement:** `MedallionStreamConsumer.flush_microbatch()` SHALL serialize under `self._flush_lock`, handle graceful stop without dropping cleared staging buffers (`except BaseException`), and execute all SQL writes (`Kline` upsert, `DataQualityService(..., commit=False)`, `batch_ledger`, `lake_snapshots`, `DataLineageEdge`, monotonic `StreamCheckpoint`) inside a single atomic transaction.
- **Acceptance Criteria:** Concurrent `flush_microbatch` and `/streaming/flush` calls produce zero duplicate/corrupt artifacts; mid-flush failure rolls back SQL cleanly (`TC-DP-005`, `TC-DP-008`, `TC-DP-FI-10`, `TC-DP-FI-12`).

### `REQ-DP-DEL-05` — Post-Commit Closed-Bar Inference Ordering
- **Tier:** Mandatory
- **Context [`OBSERVED` #8]:** `consumers.py:293-294` triggers `_safe_closed_callback(evt)` via `asyncio.create_task` before `flush_microbatch()` commits the closing candle to SQL.
- **Requirement:** Closed-candle inference and `serving.events.closed_bar` emission SHALL execute strictly AFTER `SQL_COMMITTED`, gated by a bounded `asyncio.Semaphore(1)` (or `WorkflowEngine` trigger) so `ForecastService` always sees the newly closed candle.
- **Acceptance Criteria:** Triggered inference reads the closed candle just committed in the batch (`TC-DP-028`, `TC-DP-FI-13`).

### `REQ-DP-DEL-06` — Atomic Incremental Analytics Checkpoints & Idempotent Replay
- **Tier:** Mandatory
- **Context [`OBSERVED` #8, #9]:** `IncrementalAnalyticsEngine.save_checkpoints()` (`ml/incremental_analytics.py:385-394`) uses non-atomic `write_text()` and omits `live_trades_count` / `live_vwap_*` / `last_stream_seq`.
- **Requirement:** Analytics checkpoints SHALL be written atomically (`tmp + fsync + os.replace`) and persist `last_stream_seq` and live trade accumulator fields so redeliveries after restart remain idempotent.
- **Acceptance Criteria:** Simulated crash during checkpoint write leaves prior valid checkpoint intact; redelivery does not double-count `live_trades_count` (`TC-DP-024`, `TC-DP-FI-04`, `TC-DP-FI-08`).

---

## 4. Data Lake, Manifests & Kline Unification Requirements (`REQ-DP-LAKE-*`, `REQ-DP-KLN-*`)

### `REQ-DP-LAKE-01` — Immutable Parquet Object Storage
- **Tier:** Mandatory
- **Context [`OBSERVED` #8, #9]:** `write_silver_klines` (`medallion.py:179-205`) overwrites `part-{dt_key}.parquet` in place and silently skips corrupt files (`188-189, 275-276`), causing lost updates under concurrent writers.
- **Requirement:** All Bronze, Silver, and Gold writes SHALL create new immutable run/batch-stamped object keys (`part-{dt}-{batch_id}.parquet`), never mutating existing Parquet files in place or discarding unreadable files silently.
- **Acceptance Criteria:** Concurrent Silver writes create distinct immutable objects resolved cleanly via manifests with zero lost rows (`TC-DP-009`, `TC-DP-FI-12`).

### `REQ-DP-LAKE-02` — SQL-Backed Snapshot Manifests & Batch Ledger
- **Tier:** Mandatory
- **Context [`OBSERVED` #7, #9]:** Data Lake has no manifests, snapshots, or batch transaction tracking; `DataCatalogEntry.version` is static `"1.0.0"`.
- **Requirement:** Lake commits SHALL record a `batch_ledger` entry, create a `lake_snapshots` (`STAGING -> ACTIVE`) record with `lake_manifest_files` (checksum, row count, byte size, min/max timestamps), and atomically flip the `ACTIVE` snapshot pointer inside the committing SQL transaction. Readers SHALL resolve files exclusively from the `ACTIVE` snapshot manifest.
- **Acceptance Criteria:** Crash between Parquet write and SQL commit leaves the previous `ACTIVE` snapshot untouched and uncorrupted (`TC-DP-009`, `TC-DP-FI-07`).

### `REQ-DP-LAKE-03` — Safe Compaction & Deferred Grace-TTL Garbage Collection
- **Tier:** Mandatory
- **Context [`OBSERVED` #9]:** Immediate deletion of superseded files risks `FileNotFoundError` for concurrent DuckDB/PyArrow readers.
- **Requirement:** Compaction workflows SHALL merge small Silver/trade fragments into a new compacted Parquet file, atomically commit a new `ACTIVE` `lake_snapshots` pointer, mark prior files `SUPERSEDED`, and delete orphaned physical objects ONLY after a configurable grace TTL (`>= 60s`).
- **Acceptance Criteria:** Concurrent reader querying old snapshot succeeds while compaction swaps to compacted snapshot (`TC-DP-FI-07`, `TC-DP-FI-12`).

### `REQ-DP-LAKE-04` — Real Date-Partitioned Gold Materialization
- **Tier:** Mandatory
- **Context [`OBSERVED` #9]:** `materialize_gold_marts` (`medallion.py:367-375`) writes entire multi-day history into `dt={max_open_time}`, causing duplicates when `read_gold_dataset` globs across days (`418`).
- **Requirement:** Gold `analytics_marts` and `feature_sets` SHALL be partitioned by each row's actual UTC `open_time` date `dt=YYYY-MM-DD`, indexed via `lake_snapshots`, returning zero duplicate `(symbol, timeframe, open_time)` rows across consecutive days.
- **Acceptance Criteria:** Materializing Gold across two UTC days returns exact deduplicated row counts (`TC-DP-011`).

### `REQ-DP-LAKE-05` — Manifest-Driven Governance & Safe Retention (`S3`-Compatible)
- **Tier:** Mandatory (`LocalStorageBackend`); Optional Runtime (`S3StorageBackend` `UNVERIFIED` live)
- **Context [`OBSERVED` #9]:** `GovernanceService.list_catalog` (`governance_service.py:282`) mutates DB on `GET` and caps Gold counts at `5000`; `enforce_retention` (`458-520`) uses `st_mtime`, breaks on S3 (`local_path`), and ignores manifests.
- **Requirement:** `GET /governance/catalog`, `/data-explorer/datasets`, and `/data-quality/lineage` SHALL be purely read-only (deriving counts from `ACTIVE` `lake_snapshots` with `BigInteger` columns). Retention SHALL evaluate partition `dt=` age and snapshot byte budgets using `StorageBackend` metadata (`list_keys`/`stat`/SQL `lake_manifest_files`, without `local_path`), protecting `ACTIVE` Gold/Silver snapshots needed by Warehouse checkpoints.
- **Acceptance Criteria:** `GET /governance/catalog` performs zero SQL writes; retention deletes only expired/unreferenced partitions using `dt=`, never active snapshots (`TC-DP-001`, `TC-DP-018`).

### `REQ-DP-LAKE-06` — Explicit Arrow Schemas & Unified Bronze Envelopes
- **Tier:** Mandatory
- **Context [`OBSERVED` #9]:** `SILVER_KLINE_SCHEMA` omits `taker_buy_*` fields present in SQL `Kline`; Gold relies on Pandas inference (`large_string`); WS vs REST Bronze schemas diverge.
- **Requirement:** Bronze WS and REST records SHALL share a unified canonical envelope (`schema_version`, `event_id`, `event_type`, `source`, `symbol`, `timeframe`, `event_time`, `ingestion_time`, `payload`). Silver Parquet SHALL include `taker_buy_base_asset_volume` and `taker_buy_quote_asset_volume`. Gold Parquet SHALL enforce explicit `GOLD_ANALYTICS_SCHEMA` and `GOLD_FEATURE_SCHEMA` (`pa.string()`).
- **Acceptance Criteria:** Schema validation verifies Arrow schema parity across Bronze, Silver, Gold, and SQL (`TC-DP-009`, `TC-DP-010`, `TC-DP-FI-14`).

### `REQ-DP-KLN-01` — Unified SQL & Silver Open-to-Closed Promotion + Accurate `SyncCheckpoint`
- **Tier:** Mandatory
- **Context [`OBSERVED` #9]:** Disk inspection proved `BTCUSDT 1m` and `ETHUSDT 1m` (`05:43`) have `is_closed=0` in SQL vs `is_closed=True` in Silver Parquet because `save_klines_idempotent` / `_upsert_closed_klines_sql` skip existing keys and `sync_incremental` advances cursor past unclosed bars.
- **Requirement:** Both SQL (`ON CONFLICT(symbol, timeframe, open_time) DO UPDATE`) and Silver Lake upsert SHALL enforce identical state transitions: `open->closed` promotes all OHLCV + trade fields and `is_closed=True`; `open->open` updates only on newer `close_time`/higher `volume`; `closed->open` is a no-op. `sync_incremental` SHALL resume from `min(open_time where is_closed=False)` if present, and both `SyncService` and `MedallionStreamConsumer` SHALL update `SyncCheckpoint` (`last_open_time`, `last_close_time`, `last_sync_status`) transactionally.
- **Acceptance Criteria:** Open bar followed by closed bar promotes cleanly in both SQL and Silver Parquet (`TC-DP-010`, `TC-DP-012`, `TC-DP-013`).

---

## 5. Persistent Data Warehouse Requirements (`REQ-DP-DW-*`)

### `REQ-DP-DW-01` — Persistent DuckDB Star Schema Warehouse
- **Tier:** Mandatory
- **Context [`MEASURED` #14]:** Ephemeral `:memory:` DuckDB cold queries over 101 Silver Parquet files cost `70.5–117.5 ms` per call; Star Schema analytical marts do not exist.
- **Requirement:** The platform SHALL maintain a persistent DuckDB Warehouse (`data/warehouse/`) implementing Star Schema tables (`dim_symbol`, `dim_timeframe`, `dim_date`, `fact_kline_bar`, `fact_risk_daily`, `warehouse_checkpoints`) and mart views (`mart_market_overview`, `mart_risk_summary`, `mart_data_completeness`), populated incrementally from `ACTIVE` Silver/Gold manifests, and used by analytical queries (`AnalyticsService` / `DataExplorer`).
- **Acceptance Criteria:** Incremental ETL builds Star Schema dimensions, facts, and marts matching Silver/Gold data (`TC-DP-026`, `TC-DP-PERF-03`).

### `REQ-DP-DW-02` — Single Serialized Warehouse Writer
- **Tier:** Mandatory
- **Context [`MEASURED` #15]:** Cross-process or multi-connection RW writes on DuckDB 2.0.0 Windows raise `IOException` / `ConnectionException`.
- **Requirement:** All mutations to `data/warehouse/staging/dw_staging.duckdb` SHALL be serialized through a single `WarehouseService` writer lease inside `WorkflowEngine` (`workflow_worker` or single-process `LITE` coordinator), executing `CHECKPOINT` and closing the RW handle before publishing.
- **Acceptance Criteria:** Overlapping warehouse build triggers serialize cleanly via workflow lock without DuckDB lock errors (`TC-DP-026`, `TC-DP-FI-12`).

### `REQ-DP-DW-03` — Immutable Versioned Warehouse Snapshots for Concurrent Readers
- **Tier:** Mandatory
- **Context [`MEASURED` #15]:** Holding RW on `dw_staging.duckdb` blocks `read_only=True` readers (`IOException`), whereas publishing `staging -> CHECKPOINT -> close -> copyfile+os.replace -> dw-v{N}.duckdb` succeeded in `1.43 ms` with concurrent `read_only=True` readers (`12.01 ms` query).
- **Requirement:** After `CHECKPOINT` + `close()`, `WarehouseService` SHALL publish an immutable `snapshots/dw-v{N}.duckdb`, update the `warehouse_snapshots` SQL pointer atomically (`status='ACTIVE'`), and retain `WarehouseSettings.retain_snapshots = 3 / 3 / 5` (`N=3` for `LITE`) + `reader_grace_ttl_sec >= 60` before GC. API readers SHALL open only the latest published `dw-v{N}.duckdb` with `read_only=True` (bounded by `duckdb_memory_limit` & `duckdb_threads`).
- **Acceptance Criteria:** Concurrent API readers query `dw-v{N}` simultaneously while writer updates `dw_staging.duckdb` and publishes `dw-v{N+1}` without errors (`TC-DP-026`, `TC-DP-FI-07`, `TC-DP-PERF-03`).

---

## 6. Hot State, Orchestration, Serving Bridge & Observability (`REQ-DP-HOT-*`, `REQ-DP-ORC-*`, `REQ-DP-SRV-*`, `REQ-DP-OBS-*`)

### `REQ-DP-HOT-01` — `HotStateCache` on NATS JetStream KV (`StorageType.MEMORY`) + In-Process `TTLCache`
- **Tier:** Mandatory (NATS KV + `TTLCache`); Optional/Future (Redis adapter)
- **Context [`MEASURED` #6, #16]:** Host lacks Redis, Docker, and WSL2 (`2.64 GB` free RAM). `StorageType.FILE` KV failed under LITE `128 MB` cap (`121.6 MB` reserved), whereas `StorageType.MEMORY` KV passed (`0.23 ms` put, `0.36 ms` get, TTL verified).
- **Requirement:** Define `HotStateCache` (`IFC-DP-009`) backed by NATS JetStream KV (`StorageType.MEMORY` buckets `hot_state` and `worker_heartbeats` within `nats_max_mem_mb`) paired with a bounded in-process `TTLCache` (`<= 10 MB`, invalidated on `serving.events.closed_bar`). Redis SHALL NOT be required or claimed active on this single-node host.
- **Acceptance Criteria:** Cross-process reads hit `hot_state` KV; cache invalidates on closed bar; degraded fallback to SQL/Lake works if NATS is temporarily down (`TC-DP-017`, `TC-DP-027`).

### `REQ-DP-ORC-01` — Durable SQL Job Queue (`workflow_runs`) With Active-Run Mutex
- **Tier:** Mandatory
- **Requirement:** Replace `FastAPI.BackgroundTasks` in `POST /api/v1/pipelines/trigger` (`pipelines.py:135`) with durable `workflow_runs` persistence returning `run_id` and `status="QUEUED"` immediately (`HTTP 202`), enforcing active-run mutual exclusion (`idempotency_key` per `(workflow_type, symbol, timeframe)`).
- **Acceptance Criteria:** Triggering duplicate concurrent pipelines returns existing active `run_id` or `409`/deduplicated status rather than corrupting shared state (`TC-DP-015`, `TC-DP-029`).

### `REQ-DP-ORC-02` — Lease, Heartbeat, Stale-Lease Reaper & Step-Level Resume
- **Tier:** Mandatory
- **Requirement:** `workers/workflow_worker.py` SHALL acquire `workflow_runs` via atomic SQL lease (`lease_owner`, `lease_token`, `lease_expires_at`), renew `heartbeat_at`, checkpoint `workflow_tasks`, skip already-`SUCCESS` tasks on retry, and run a startup + periodic stale-lease reaper moving expired `RUNNING` jobs to `RETRY_WAIT` or `FAILED`.
- **Acceptance Criteria:** Killing the worker mid-DAG causes the reaper to reclaim and resume the run to `SUCCESS` without re-executing completed tasks (`TC-DP-015`, `TC-DP-016`, `TC-DP-FI-11`).

### `REQ-DP-ORC-03` — Persisted Schedules Replacing `sync_worker.py` & `cycle % 600`
- **Tier:** Mandatory
- **Requirement:** Replace ad-hoc `sync_worker.py` `sleep(300)` and `runtime.py:181` `cycle % 600` with persisted `workflow_schedules` rows (`GAP_HEAL`, `GOLD_AND_WAREHOUSE_REFRESH`, `PARQUET_COMPACTION`, `FORECAST_RECONCILIATION`, `RETENTION_ENFORCE`) firing via `WorkflowEngine` (`sync_worker.py` kept as thin shim invoking `WorkflowService`).
- **Acceptance Criteria:** Due schedules enqueue durable `workflow_runs` with single-flight protection (`TC-DP-015`, `TC-DP-PERF-05`).

### `REQ-DP-ORC-04` — Non-Blocking API Request Handlers
- **Tier:** Mandatory (`AGENTS.md` Rule 7)
- **Requirement:** `POST /api/v1/models/train` SHALL enqueue a durable `WorkflowEngine` job (or run in worker pool when explicitly requested with bounded test mode) instead of executing training inline on the HTTP request thread/session; `GET` routes SHALL NOT trigger network syncs or DB writes.
- **Acceptance Criteria:** `POST /models/train` returns job/run status cleanly without blocking API health probes (`TC-DP-018`, `TC-DP-029`).

### `REQ-DP-SRV-01` — Canonical `ServingGatewayBridge` Across `LITE` & `STANDARD`
- **Tier:** Mandatory
- **Context [`OBSERVED` #7, #8]:** `embedded_in_api=False` causes split-brain zeros across `/streaming/status`, `/streaming/flush`, `/streaming/simulate-disconnect`, `/ws/market`, `/analytics/incremental`, and `/system/resources`.
- **Requirement:** Implement `ServingGatewayBridge` (`COMP-DP-08`) over NATS Core (`serving.market.*`, `serving.control.*`, `serving.events.closed_bar`) and NATS KV (`hot_state`, `worker_heartbeats`) used identically in both `LITE` (loopback) and `STANDARD` (multi-process). When `embedded_in_api=False`, FastAPI SHALL NOT instantiate local ingestor/consumer/retention tasks.
- **Acceptance Criteria:** With `stream_worker` running in a separate OS process, `WS /ws/market`, `GET /streaming/status`, `GET /analytics/incremental`, `POST /streaming/flush`, and `POST /streaming/simulate-disconnect` operate identically to `LITE` (`TC-DP-017`, `TC-DP-PERF-05`).

### `REQ-DP-OBS-01`, `REQ-DP-OBS-02`, `REQ-DP-OBS-03` — Multi-Process Observability & Event-Loop Protection
- **Tier:** Mandatory
- **Requirement:**
  - `REQ-DP-OBS-01`: Aggregate per-worker Prometheus metrics (`IFC-DP-010`) and compute active freshness/lag staleness at scrape time (`now - last_event_time`) so stalled streams do not freeze metrics.
  - `REQ-DP-OBS-02`: Export host available RAM, disk free space, worker heartbeat status, and batch/ML/workflow failure counters to `/metrics`.
  - `REQ-DP-OBS-03`: Replace synchronous `Path.rglob("*")` inside async `/metrics` and `/system/resources` (`metrics.py:120-156`) with off-event-loop `asyncio.to_thread` cached snapshots or manifest byte totals, including `dlq/`, `models/`, `checkpoints/`, `warehouse/`, and `.db-wal`.
- **Acceptance Criteria:** `/metrics` reports active staleness on simulated stall, exports disk/RAM gauges, and completes without blocking the event loop (`TC-DP-021`, `TC-DP-022`, `TC-DP-023`, `TC-DP-FI-06`, `TC-DP-PERF-04`).

---

## 7. Security, Test Isolation & Configuration (`REQ-DP-SEC-*`, `REQ-DP-CFG-*`)

### `REQ-DP-SEC-01` — Complete Admin Authentication Coverage
- **Tier:** Mandatory
- **Requirement:** Apply `Depends(require_admin_if_configured)` to all mutating operational endpoints including `POST /api/v1/forecasts/generate`, `POST /api/v1/forecasts/reconcile`, and `POST /api/v1/data-quality/evaluate` (closing gaps noted in `#6`), plus rate/size bounds on workflow/replay payloads.
- **Acceptance Criteria:** When `ADMIN_API_TOKEN` is set, unauthenticated requests to all mutation endpoints return `401` (`TC-DP-019`).

### `REQ-DP-SEC-02` — Sanitized Errors & Zero Leakage
- **Tier:** Mandatory (`AGENTS.md` Rule 8)
- **Requirement:** Never expose raw `str(exc)`, stack traces, filesystem paths, or connection strings via HTTP `detail`, `PipelineRun.error_message` public API responses (`pipelines.py:87`), or `get_stream_info()` (`broker.py:360`). Map internal errors to stable `error_code` + safe summary; log full tracebacks server-side only.
- **Acceptance Criteria:** Injected broker/SQL/validation failures return sanitized messages with zero paths or stack traces (`TC-DP-020`).

### `REQ-DP-SEC-03` — Mandatory Test Isolation (`TEST-ISO`)
- **Tier:** Mandatory (Prerequisite for Phase 2)
- **Context [`OBSERVED` #6]:** `tests/test_api_and_security.py:68-73` runs retention against live `./data/`.
- **Requirement:** `tests/conftest.py` SHALL provide an autouse session/function isolation guard redirecting `DATA_DIR`, checkpoint dirs, warehouse dirs, and SQLite DBs to `tmp_path` and asserting repo `./data/` remains untouched; `system` tests MUST use a non-default NATS port and temp `store_dir`.
- **Acceptance Criteria:** Running full pytest suite leaves repo `./data/` files and mtimes 100% unchanged (`TC-DP-001`).

### `REQ-DP-CFG-01` — Unified Configuration, Dependency Pinning & Deployment Scripts
- **Tier:** Mandatory
- **Requirement:** Unify `config.yaml`, `.env`, and `Settings.load()` (`IFC-DP-011`) so `data.streams`, `data.api.*`, `ml.*`, `BINANCE_API_URL`, `BINANCE_FALLBACK_URL`, `BINANCE_WS_URL`, and `DATA_DIR` resolve deterministically; pin `requirements.txt` bounds and include `psycopg[binary]>=3.2.0,<4.0` with `postgresql+psycopg://` URI normalization for PostgreSQL sync/Alembic compatibility; fix `docker/nats/nats.conf`, `Dockerfile.backend`, and `run.bat standard` multi-process worker launch.
- **Acceptance Criteria:** Settings unit tests verify full precedence (`env > config.yaml > profile defaults`); `alembic upgrade head` & `run.bat --check` pass (`TC-DP-025`, `TC-DP-PERF-01`, `TC-DP-PERF-05`).
