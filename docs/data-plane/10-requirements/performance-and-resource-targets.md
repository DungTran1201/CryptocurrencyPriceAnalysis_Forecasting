# Performance, Resource Targets, and Metrics Contract (`IFC-DP-010`)

**Document ID:** `DP-SPEC-102`  
**Status:** `PROPOSED_PHASE_1_SPEC`  
**Owner:** `@sre-qa` (`WI-DP-01` / `WI-DP-10`)  
**Satisfies:** `REQ-DP-OBS-01`, `REQ-DP-OBS-02`, `REQ-DP-OBS-03`, `REQ-DP-CFG-01`

---

## 1. Purpose and Hardware Envelope

This specification defines measurable performance baselines, `TARGET_TO_BE_ESTABLISHED` gates, profile resource budgets (`LITE`, `STANDARD`, `EXTENDED`), and the per-process Prometheus exposition contract (`IFC-DP-010`).

Because the authoritative workstation (`DP-SPEC-001`) has **`31.89 GB` total RAM with only `2.64 GB` currently available** (`91.7%` occupied by external desktop workloads) and **`78.19 GB` free SSD on `C:`**, all platform components MUST enforce hard memory bounds, zero unbounded queues, and deterministic disk retention.

---

## 2. Section 8: Baseline vs. `TARGET_TO_BE_ESTABLISHED` Matrix

Every baseline value below is directly `MEASURED` from Phase 1 Step 1/1B (`#6`, `#14`, `#15`, `#16`). Unmeasured metrics are explicitly marked **`UNMEASURED`**, and no target number is fabricated prior to Phase 2/3 benchmark execution (`TARGET_TO_BE_ESTABLISHED`).

| Metric | Phase 1 Baseline (`MEASURED` or `UNMEASURED`) | Target (`TARGET_TO_BE_ESTABLISHED`) | Measurement & Acceptance Protocol (Phase 2/3) |
|---|---|---|---|
| **Backend Pytest Suite** | **`43 passed in 12.86s`** (`16.07s` wall, 0 fail/skip) | `TARGET_TO_BE_ESTABLISHED` (100% pass for non-`live` suite) | `.venv\Scripts\python.exe -m pytest -v -m "not live"` with isolated `tmp_path` (`TEST-ISO`). |
| **Live-NATS Test Skip Count** | **`1`** skips if `:4222` down | `TARGET_TO_BE_ESTABLISHED` (0 skips in local/CI with NATS) | Run `system` marker tests against ephemeral local `nats-server` on random port. |
| **Host Available Physical RAM** | **`2.64 GB` / `31.89 GB`** (external load) | `TARGET_TO_BE_ESTABLISHED` (platform footprint fits <= `450 MB` LITE / `950 MB` STANDARD) | `psutil` RSS summation across `api` + workers + `nats-server` (`>= 3` runs). |
| **Workspace SSD Free Space (`C:`)** | **`78.19 GB`** of `118.52 GB` | `TARGET_TO_BE_ESTABLISHED` (alert before `< 10%` or `< 5 GB` free) | `psutil.disk_usage(data_dir)` exported via `platform_disk_free_bytes` (`IFC-DP-010`). |
| **Atomic File Write Latency (`4 KB`)** | p50 **`0.55 ms`**, p95 **`1.79 ms`**, max `38.54 ms` | `TARGET_TO_BE_ESTABLISHED` | Temp file + `fsync` + `os.replace` micro-benchmark (`n >= 50`). |
| **Cold DuckDB Query (Silver 15m, `9,600` rows)** | **`70.5–117.5 ms`** (`:memory:` Parquet glob) | `TARGET_TO_BE_ESTABLISHED` (Warehouse snapshot target) | Compare `dw-v{N}.duckdb` `read_only=True` query latency vs `:memory:` Parquet glob. |
| **DuckDB Snapshot Swap (`12.5k` rows)** | **`1.43 ms`** publish; **`50.8–53.7 ms`** RO open; **`12.01 ms`** query | `TARGET_TO_BE_ESTABLISHED` | Measure at 10k, 50k, 100k bars in `WarehouseService` benchmark. |
| **NATS JetStream KV (`MEMORY`) Put / Get / Watch** | Put **`0.231 ms`** avg (`0.423 ms` p95); Get **`0.362 ms`** avg (`0.644 ms` p95); Watch **`1.306 ms`** | `TARGET_TO_BE_ESTABLISHED` | Measure under concurrent `StreamWorker` + `API` load. |
| **NATS Core Pub/Sub RTT** | **`0.243 ms`** avg (`0.421 ms` p95) | `TARGET_TO_BE_ESTABLISHED` | `ServingGatewayBridge` tick coalescer -> `WSBroadcastHub` RTT. |
| **NATS Server RSS / Memory** | **`63.25 MB`** WS (`43.2 MB` `/varz` mem) | `TARGET_TO_BE_ESTABLISHED` (stay within profile `nats_max_mem_mb`) | Poll `/varz` during 10-min sustained stream simulation. |
| **Binance REST Ping / Time RTT** | **`71–445 ms`** (external network) | `N/A` (external dependency) | Recorded only under `-m live`; mocked in deterministic tests. |
| **Sustained WS Ingest Throughput (msgs/s)** | **`UNMEASURED`** | `TARGET_TO_BE_ESTABLISHED` | Synthetic local WS replay (`50–500 msgs/s`) into `BinanceWebSocketIngestor`. |
| **E2E Ingest-to-Commit/ACK Latency (p50/p95)** | **`UNMEASURED`** (in-memory tracker only) | `TARGET_TO_BE_ESTABLISHED` | Measure `event ingestion_time` -> SQL `COMMITTED` / JetStream `ACKED`. |
| **Micro-Batch Flush Duration (p95)** | **`UNMEASURED`** | `TARGET_TO_BE_ESTABLISHED` (must stay `< 0.5 * nats_ack_wait_sec`) | `platform_batch_write_latency_seconds` under `bronze_flush_max_records` load. |
| **Peak RSS per Process (`api`, `stream`, `workflow`)** | **`UNMEASURED`** (no app process running) | `TARGET_TO_BE_ESTABLISHED` | Measure per-PID RSS over `30 min` soak and ML training burst (`n >= 3`). |
| **Consumer Lag Recovery Time (msgs/s drain)** | **`UNMEASURED`** | `TARGET_TO_BE_ESTABLISHED` | Queue `5,000` messages while consumer stopped; time drain to `lag = 0`. |
| **Gap Detection & Backfill Throughput (bars/s)** | **`UNMEASURED`** | `TARGET_TO_BE_ESTABLISHED` | Mocked Binance REST backfill across `7d` of `1m` gaps (`~10,080` bars). |
| **`/metrics` & `/system/resources` Latency** | **`UNMEASURED`** (`sync rglob` risk) | `TARGET_TO_BE_ESTABLISHED` | Measure with `>= 5,000` simulated files in `data/`; prove event loop unblocked. |

> **Rule for Setting Targets:** Concrete SLA numbers replace `TARGET_TO_BE_ESTABLISHED` only after Phase 2 (`WI-DP-10` / `WI-DP-12`) collects `>= 3` reproducible benchmark runs in isolated temp storage on this host.

---

## 3. Adaptive Execution Profile Resource Budgets

| Budget Parameter | `LITE` (Single-Process + NATS) | `STANDARD` (3-Process Native / Docker) | `EXTENDED` (Multi-Process + Optional S3) |
|---|---|---|---|
| **Python App Processes (`max_python_procs`)** | `1` (`api` w/ embedded stream + workflow runtime) | `3` (`api`, `stream_worker`, `workflow_worker`) | Up to `4` |
| **Total Memory Budget (`total_memory_mb`)** | `450 MB` (`TARGET_TO_BE_ESTABLISHED`) | `950 MB` (`TARGET_TO_BE_ESTABLISHED`) | `2048 MB` (requires closing heavy external host apps) |
| **Stream Queue Max (`stream_queue_maxsize`)** | `1,000` (HW `80%`) | `5,000` (HW `80%`) | `10,000` (HW `80%`) |
| **Consumer Batch / Flush Max** | `50` / `250` recs / `5.0s` | `200` / `1,000` recs / `5.0s` | `500` / `2,000` recs / `10.0s` |
| **DuckDB Memory / Threads** | `128 MB` / `2` threads | `256 MB` / `4` threads | `512 MB` / `4` threads |
| **NATS JetStream Mem / File Store** | `64 MB` / `128 MB` (`8 MB` KV `MEMORY`) | `128 MB` / `512 MB` (`16 MB` KV `MEMORY`) | `256 MB` / `1024 MB` (`32 MB` KV `MEMORY`) |
| **Lake Retention (Bronze / Silver / Gold)** | `3d / 14d / 30d`, `256 MB` each | `7d / 30d / 90d`, `1024 MB` each | `30d / 90d / 180d`, `4096 MB` each |
| **ML Max Train Rows (`ml_max_train_rows`)** | `2,000` (offloaded to `WorkflowWorker`) | `5,000` (offloaded to `WorkflowWorker`) | `20,000` (offloaded to `WorkflowWorker`) |
| **Warehouse Snapshot Retention (`retain_snapshots` / `reader_grace_ttl_sec`)** | `3` snapshots (`dw-v{N}.duckdb`) / `60s` grace | `3` snapshots / `60s` grace | `5` snapshots / `60s` grace (config override up to `120s`) |

---

## 4. `IFC-DP-010`: Per-Process Prometheus Metrics & Label Contract

### 4.1 Multi-Process Metrics Topology
In `LITE` (`embedded_in_api=True`), the API process hosts ingestion and consumption, so `GET /metrics` sees streaming + API metrics directly. In `STANDARD`/`EXTENDED` (`embedded_in_api=False`), **`stream_worker` and `workflow_worker` run in separate OS processes**, each with its own Python `CollectorRegistry`.

To eliminate split-brain (`#7`):
1. Every Python process (`api`, `stream_worker`, `workflow_worker`) instantiates its metrics with a `process_role` label (`api` | `stream_worker` | `workflow_worker`) and exposes an optional lightweight localhost Prometheus HTTP server (configurable `METRICS_PORT`: `api` on `:8000/metrics`, `stream_worker` on `:9101/metrics`, `workflow_worker` on `:9102/metrics`, disabled when `0`).
2. Every `2s`, `stream_worker` and `workflow_worker` also publish their latest `ProcessTelemetrySnapshot` (RSS, CPU, queue depth, lag, freshness, failure counters, stage timings) to NATS KV `worker_heartbeats` (`ttl=15s`).
3. `GET /api/v1/system/resources` and `GET /api/v1/streaming/status` read `worker_heartbeats` from KV so the API UI always reflects live worker resource and pipeline state, never zeros.
4. `collect_resource_snapshot()` (`OBS-03`) MUST run directory `stat`/`rglob` off the asyncio event loop (`asyncio.to_thread`) with a cached snapshot (`TTL >= 10s`) so concurrent `/metrics` scrapes never stall HTTP/WS serving.

### 4.2 Canonical Metric Registry (`IFC-DP-010`)

Cardinality rule: **Never** place unbounded values (`run_id`, `event_id`, `error_message`, raw timestamps) in Prometheus labels. Allowed bounded labels: `process_role`, `stream`, `symbol` (allowlisted pairs), `layer`, `stage`, `consumer`, `rule_id`, `status`, `reason`, `queue`.

| Metric Name | Type | Labels | Owner Process(es) | Purpose / Change vs. AS-IS |
|---|---|---|---|---|
| `platform_events_received_total` | Counter | `stream`, `symbol` | `api` (LITE), `stream_worker` | Existing; WS frames normalized & accepted. |
| `platform_events_published_total` | Counter | `stream`, `symbol` | `api` (LITE), `stream_worker` | Existing; events published to NATS. |
| `platform_events_consumed_total` | Counter | `consumer`, `symbol` | `api` (LITE), `stream_worker` | Existing; durable consumer reads. |
| `platform_events_persisted_total` | Counter | `layer`, `symbol` | All writers | Existing; add `warehouse` layer value. |
| `platform_dlq_events_total` | Counter | `stream`, `symbol`, `reason` | `stream_worker` / `api` | Existing; malformed or max-deliver quarantined items. |
| `platform_backpressure_events_total` | Counter | `stage` | `stream_worker` / `api` | Existing; bounded queue high-watermark hits. |
| `platform_processing_failures_total` | Counter | `process_role`, `stage` | **All processes** | **Upgraded:** Instrument `pipeline`, `sync_service`, `workflow_task`, `warehouse_build`, `model_train`, `api_5xx`, `ws_gap_heal` (previously streaming-only). |
| `platform_dq_failures_total` | Counter | `rule_id`, `symbol` | `stream_worker`, `workflow_worker` | Existing + new `DQ-TRD-01` (`aggTrade` continuity). |
| `platform_queue_depth` | Gauge | `queue` | `stream_worker` / `api` | Existing (`ingestion_outbound`, plus `closed_bar_trigger`). |
| `platform_consumer_lag_msgs` | Gauge | `stream`, `consumer` | `stream_worker` / `api` | Existing; set stale/alerted if heartbeat expires. |
| `platform_data_freshness_seconds` | Gauge | `symbol`, `stream` | `stream_worker` / `api` | **Upgraded:** Actively computed on scrape/tick as `now - last_event_time` so staleness rises monotonically during WS stalls instead of freezing. |
| `platform_data_gaps_detected_total` | Counter | `symbol`, `timeframe`, `gap_type` | `workflow_worker`, `stream_worker` | **NEW:** Tracks leading, interior, trailing, and `agg_trade_id` gaps detected. |
| `platform_processing_latency_seconds` | Histogram | `stage` | All processes | Existing; expand to batch workflow steps & DuckDB queries. |
| `platform_batch_write_latency_seconds` | Histogram | `layer` | All writers | Existing (`bronze`, `silver`, `gold`, `warehouse`). |
| `platform_workflow_runs_total` | Counter | `pipeline_name`, `status` | `workflow_worker` | **NEW:** Tracks `SUCCESS`, `FAILED`, `REAPED`, `CANCELLED` durable runs. |
| `platform_workflow_reaped_tasks_total` | Counter | `task_name` | `workflow_worker` | **NEW:** Tracks stale leases recovered by the reaper. |
| `platform_process_rss_bytes` | Gauge | `process_role` | **All processes** | **Upgraded:** Differentiate `api`, `stream_worker`, `workflow_worker`. |
| `platform_process_cpu_percent` | Gauge | `process_role` | **All processes** | **Upgraded:** Per-process CPU gauge. |
| `platform_host_ram_available_bytes` | Gauge | *(none)* | `api` | **NEW:** Exposes host free RAM to Prometheus (preventing blind OOM under external host load). |
| `platform_host_ram_used_percent` | Gauge | *(none)* | `api` | **NEW:** Exposes host RAM occupancy %. |
| `platform_disk_free_bytes` | Gauge | `mount` | `api` | **NEW:** Exposes free disk space on `DATA_DIR` volume (`C:` = `78.19 GB`). |
| `platform_disk_used_percent` | Gauge | `mount` | `api` | **NEW:** Exposes volume utilization %. |
| `platform_storage_bytes` | Gauge | `layer` | `api` | **Upgraded:** Add `dlq`, `models`, `checkpoints`, `warehouse`, `metadata_wal` alongside `bronze`, `silver`, `gold`, `nats`, `metadata_db`. |

---

## 5. Resource Throttling & Graceful Degradation Rules

1. **Ingestion Backpressure (`COMP-DP-01`):** When `BoundedEventProducer._queue.qsize() >= 0.80 * stream_queue_maxsize`, set `backpressure_active = True`, increment `platform_backpressure_events_total`, and block `enqueue()` via `asyncio.Queue.put()` (never silently drop events).
2. **Memory Pressure Guard (`COMP-DP-09` / `COMP-DP-12`):**
   - If `process_rss_mb > 0.85 * total_memory_mb` **OR** `host_ram_available_mb < 512`:
     - `WorkflowWorker` defers non-critical `MODEL_TRAIN` and `PARQUET_COMPACTION` jobs (`status = QUEUED`, logged as `RESOURCE_THROTTLED`) while continuing critical `GAP_HEAL` and `RETENTION_ENFORCE` tasks.
     - `MedallionStreamConsumer` triggers immediate `flush_microbatch()` to release Python dict buffers.
3. **Disk Pressure Guard (`COMP-DP-10` / `COMP-DP-12`):**
   - **Warning (`disk_free_gb < 10.0` or `disk_used_pct >= 85%`):** Emit structured `WARNING` log, flag `/api/v1/health` as `DEGRADED`, trigger immediate scheduled `RETENTION_ENFORCE` job (`GovernanceService.enforce_retention` + warehouse old snapshot GC).
   - **Critical (`disk_free_gb < 2.0` or `disk_used_pct >= 95%`):** Pause new ML artifact writes and non-essential Bronze REST archival; keep operational SQL checkpoints and NATS DLQ intact; return `503` on non-essential compute endpoints (`POST /models/train`).
4. **DuckDB Contention Guard (`COMP-DP-06`):** Single serialized writer acquires SQL lease (`warehouse_build` task) with explicit `memory_limit` (`128MB` LITE / `256MB` STANDARD / `512MB` EXTENDED); API readers open immutable `dw-v{N}.duckdb` with `read_only=True` and bounded connection lifetimes.
