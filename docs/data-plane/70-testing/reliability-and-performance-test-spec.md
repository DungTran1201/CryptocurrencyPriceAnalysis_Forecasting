# Reliability, Fault-Injection, and Performance Test Specification

**Document ID:** `DP-SPEC-703`  
**Status:** `PROPOSED_PHASE_1_SPEC`  
**Owner:** `@sre-qa` (`WI-DP-01` / `WI-DP-12`)

---

## 1. Safety Rules for Reliability & Load Execution

1. **Isolated Broker Port:** Every `system` and `fault_injection` test MUST start an ephemeral `.bin/nats-server.exe` bound to dynamically allocated free localhost ports (`client_port`, `http_port`) with `-sd <tmp_path>/nats`. **Never** target or stop port `4222`.
2. **Isolated Data Root:** All lake, warehouse, SQLite, and checkpoint paths MUST point to `tmp_path` (`TEST-ISO`).
3. **Simulated External Streams:** Binance WS and REST MUST be simulated by an in-process localhost `websockets` / HTTP mock server so tests run deterministically offline.

---

## 2. Fault-Injection Matrix (Section 6.4 Scenarios `S1–S14`)

| Scenario ID | TC ID | Defect / `REQ-DP-*` | Fault Injected | Expected System Behavior & Pass/Fail Oracle |
|---|---|---|---|---|
| **S1** | `TC-DP-FI-01` | `ING-01` (D14) | Drop local mock WS connection mid-stream after emitting gaps in `1m` kline and `agg_trade_id`. | `BinanceWebSocketIngestor` reconnects with exponential backoff, triggers single-flight `_safe_gap_heal()`, heals both `1m` klines and `/aggTrades?fromId`, increments `reconnect_count`; zero permanent gap remains (`DQ-GAP-01` & `DQ-TRD-01` pass). |
| **S2** | `TC-DP-FI-02` | `ING-03` (D7) | Stop and restart ephemeral `nats-server` process while `StreamWorker` is actively ingesting. | `NatsJetStreamBroker` preserves single client/epoch transition, producer spills/retries without drop, consumer rebinds pull subscription cleanly; post-recovery consumer lag returns to `0` and all messages are committed once. |
| **S3** | `TC-DP-FI-03` | `ING-02` (D6) | Ephemeral `nats-server` unreachable while `BoundedEventProducer` reaches high watermark and receives `stop(drain_timeout=0.5)`. | Producer activates backpressure metric (`platform_backpressure_events_total`), then spills remaining queued + `in_flight` items to atomic local spool file; on restart with broker up, spooled events drain first with zero data loss. |
| **S4** | `TC-DP-FI-04` | `DEL-02`, `DEL-06` | Terminate (`kill`) consumer worker process mid-flush (`FILES_WRITTEN` before `COMMITTED`, or after `COMMITTED` before `ACKED`). | Un-acked messages remain in JetStream; restarted consumer redelivers, SQL `ON CONFLICT` + immutable lake snapshot manifests absorb duplicates cleanly, `StreamCheckpoint` increments monotonically without double counting. |
| **S5** | `TC-DP-FI-05` | `DEL-02`, `DEL-01` (D2, D3) | Inject SQL `OperationalError` (`database is locked` / failure) during `flush_microbatch()` after Bronze/Silver files write. | Transaction rolls back, `_dedup` cache is NOT mutated, all batch messages are `nak(delay=...)` (zero `ack()`), `platform_processing_failures_total` increments; subsequent redelivery commits cleanly with zero duplicate rows. |
| **S6** | `TC-DP-FI-06` | `OBS-02` | Simulate disk-full condition via monkeypatched `LocalStorageBackend.write_bytes` raising `OSError(ENOSPC, "No space left")` (real small quota impractical on `NTFS`, so real disk-full is marked `NOT RUN`). | Flush aborts before SQL commit, increments storage/processing failure metric, NAKs batch safely without corrupting existing files (`tmp` cleaned up), health reports `DEGRADED`, and critical disk-pressure guard triggers. |
| **S7** | `TC-DP-FI-07` | `LAKE-02`, `DW-03` | Corrupt bytes inside a non-active or candidate Silver Parquet object / staging DuckDB file. | Active manifest validation / DuckDB staging integrity check fails cleanly (`FAILED`), active `lake_snapshots` & `dw-v{N}.duckdb` pointers remain intact on last known good version, API queries continue serving uncorrupted active snapshot. |
| **S8** | `TC-DP-FI-08` | `DEL-06` (D24) | Truncate `analytics_BTCUSDT_1m.json` checkpoint file to invalid JSON before restart. | `IncrementalAnalyticsEngine` logs explicit error, increments failure counter, avoids silent zeroed overwrite of good checkpoint backup/state, and cleanly rebuilds state from latest closed SQL/Silver bars. |
| **S9** | `TC-DP-FI-09` | `ING-04`, `DEL-03` | Inject burst of `50` malformed JSON frames + invalid OHLC geometry (`high < low`) mixed with valid events on mock WS. | Malformed frames route to DLQ (`MARKET_DLQ` + `DeadLetterEvent`) off the WS read loop without stalling valid event throughput; `msg.term()` executes ONLY if DLQ persistence succeeds (test dual-sink failure -> `msg.nak()`). |
| **S10** | `TC-DP-FI-10` | `DEL-04` | Patch `nats_ack_wait_sec = 1s` and inject `1.5s` artificial sleep inside `_write_files` to trigger JetStream redelivery mid-flush. | `_flush_lock` prevents overlapping flushes, post-commit idempotent upsert + monotonic checkpoint prevent double ingestion, and post-commit `ack()` succeeds or safely absorbs stale redeliveries. |
| **S11** | `TC-DP-FI-11` | `ORC-02` (D15) | Kill `WorkflowWorker` process mid-DAG (`validate_silver` `RUNNING` with expired lease). | Stale-lease reaper detects expired `lease_expires_at`, increments `platform_workflow_reaped_tasks_total`, transitions task back to `QUEUED`, and replacement worker completes remaining DAG steps (`build_gold_marts`, `warehouse_build`) with zero duplicate rows. |
| **S12** | `TC-DP-FI-12` | `LAKE-01`, `DW-02`, `DEL-04` (D8, D9) | Trigger concurrent Silver writes (`StreamProcessor` + `WorkflowWorker`), concurrent `POST /streaming/flush`, and concurrent `API` DuckDB `read_only=True` queries during `WarehouseService` build. | Zero `WinError 32` / DuckDB `IOException` on readers, zero corrupted Parquet partitions, exact deterministic row counts across SQL, Lake manifest, and Warehouse `dw-v{N}.duckdb`. |
| **S13** | `TC-DP-FI-13` | `DEL-05` | Pre-load `200` closed-candle events into JetStream before starting `StreamWorker` (`ml_inference_trigger="closed_candle"`). | Closed-candle hook triggers **only after commit** through bounded `Semaphore(1)` / coalesced queue; zero unbounded `asyncio.create_task` storm; latest bar triggers forecast idempotently without duplicate rows. |
| **S14** | `TC-DP-FI-14` | `IFC-DP-001` | Feed future-timestamped klines (`open_time > now + 10m`) and inverted bars (`open_time > close_time`) via WS & REST sync. | `CanonicalKlineEvent` rejects `open_time > close_time` at normalizer boundary -> DLQ; future-timestamped bars are flagged `CRITICAL` by `DQ-FUT-01` and blocked at Silver DQ gate before Gold/Warehouse promotion. |

---

## 3. Performance, Load, Recovery, and Stress Suites (`TC-DP-PERF-*`)

All performance tests populate Section 8 `TARGET_TO_BE_ESTABLISHED` baselines (`DP-SPEC-102`) using `>= 3` repetitions in `tmp_path` on this host:

| Perf ID | Suite Type | Workload Configuration | Metrics Recorded (`>= 3` runs) |
|---|---|---|---|
| **`TC-DP-PERF-01`** | **Sustained Load & Throughput** | Mock WS emits `200 msgs/s` (`aggTrade` + `kline_1m`) across 4 symbols for `120s` into `StreamWorker` + ephemeral NATS + `API`. | Sustained ingest rate (`msgs/s`), E2E ingest-to-ACK p50/p95 (`ms`), flush duration p95 (`ms`), API/Stream/NATS peak RSS (`MB`), zero dropped events. |
| **`TC-DP-PERF-02`** | **Recovery & Lag Drain Drill** | Stop `StreamWorker` while producer publishes `5,000` events into JetStream; start `StreamWorker` and time drain to `lag == 0`. | Drain throughput (`msgs/s`), total recovery time (`s`), peak queue occupancy (`%`), duplicate count (`must == 0`). |
| **`TC-DP-PERF-03`** | **Warehouse Snapshot & Query Scaling** | Load `50,000` kline bars across 4 symbols / 3 timeframes into staging DuckDB -> snapshot swap -> run `20` concurrent API reads (`read_only=True`). | Warehouse build time (`ms`), snapshot copy/swap time (`ms`), RO query p50/p95 (`ms`), peak process RSS (`MB`). |
| **`TC-DP-PERF-04`** | **Observability & Export Stress** | Populate `tmp_path` lake with `5,000` files; scrape `/metrics` and `/system/resources` while serving `50` concurrent `/health` + `/market/klines` requests. | `/metrics` latency (`ms`), `/health` p95 latency (`ms`), event-loop block check (`< 50 ms` jitter). |
| **`TC-DP-PERF-05`** | **End-to-End Production Simulation (LITE & STANDARD)** | Full 3-process `STANDARD` simulation (`api` + `stream_worker` + `workflow_worker` + `nats-server`) over `10 minutes` combining live mock WS, REST gap heal, Gold/Warehouse build, retention, and UI WS client subscriber. | Total combined RSS (`MB` vs host free RAM budget), CPU (`%`), zero unhandled exceptions, zero stuck `RUNNING` tasks, `WS /ws/market` steady updates. |
