# Monitoring and Alerting Specification

**Document ID:** `DP-SPEC-802`  
**Status:** `PROPOSED_PHASE_1_SPEC`  
**Owner:** `@sre-qa` (`WI-DP-01` / `WI-DP-10`)  
**Satisfies:** `REQ-DP-OBS-01`, `REQ-DP-OBS-02`, `REQ-DP-OBS-03`, `IFC-DP-010`

---

## 1. Current Monitoring Gaps (`#6` Audit Summary)

AS-IS observability (`metrics.py`, `logging.py`, `consumers.py`, `system.py`) fails to surface four critical operational risks:
1. **Silent Staleness / Frozen Lag:** `DATA_FRESHNESS_SECONDS` updates only inside `_handle_message` (`consumers.py:264`) and `CONSUMER_LAG` updates only inside `_consume_loop` (`consumers.py:161`). When Binance WS disconnects or the consumer hangs, both gauges freeze at their last healthy values.
2. **Blind Disk & Host RAM Pressure:** `disk_free_gb` and `host_ram_available_mb` exist only in `/api/v1/system/resources` JSON, absent from Prometheus `/metrics`; `STORAGE_USAGE_BYTES` omits `dlq/`, `models/`, `checkpoints/`, `warehouse/`, and `.db-wal`; zero threshold warnings exist.
3. **Unmetered Batch & Worker Failures:** `PipelineService`, `SyncService`, `sync_worker`, `ModelService`, `ForecastService`, and API `500` handlers do not increment `platform_processing_failures_total`. Silent `except Exception: pass` blocks mask Parquet/catalog failures.
4. **Event-Loop Blocking Telemetry & Split-Brain:** `collect_resource_snapshot()` executes synchronous `Path.rglob("*")` inside async `/metrics` and `/system/resources` handlers (`main.py:100`, `system.py:67`), and decoupled `STANDARD` mode leaves API gauges at `0`.

---

## 2. Target Telemetry & Health Checks (`WI-DP-10`)

1. **Off-Event-Loop Cached Resource Collector (`OBS-03`):**
   - Run `dir_size_bytes` across `bronze`, `silver`, `gold`, `warehouse`, `nats`, `dlq`, `models`, `checkpoints`, `metadata_db`, `metadata_wal` inside `asyncio.to_thread()` with a bounded TTL cache (`10s`), preventing `/metrics` scrapes from blocking HTTP/WS serving.
2. **Active Freshness & Worker Heartbeat Evaluator:**
   - Maintain `last_event_utc` per `(symbol, stream)` and recompute `platform_data_freshness_seconds = max(0, now_utc - last_event_utc)` on every `/metrics` scrape and every `2s` heartbeat tick.
   - Monitor NATS KV `worker_heartbeats` (`ttl=15s`): if `stream_worker` or `workflow_worker` heartbeat is absent in `STANDARD` mode, flag `/api/v1/health` and `/api/v1/system/resources` as `DEGRADED`.
3. **Dependency-Probing `/api/v1/health`:**
   - Execute lightweight `SELECT 1` DB check, broker `is_connected()` check, worker heartbeat check (if `embedded_in_api=False`), and host disk free check (`psutil.disk_usage`).
   - Return HTTP `503` (`status: "unhealthy"`) if operational DB fails; HTTP `200` (`status: "degraded"`) if NATS disconnected, worker heartbeat missing, or disk/RAM warning threshold breached; HTTP `200` (`status: "healthy"`) otherwise.
4. **Structured Logging (`core/logging.py`):**
   - Respect `settings.log_format` (`json` | `text`) and configurable `LOG_LEVEL` (`INFO` default).
   - Enhance `JsonLogFormatter` to include bounded `extra` context fields (`component`, `process_role`, `run_id`, `batch_id`, `symbol`, `error_code`) while scrubbing credentials/secrets.

---

## 3. Alert Rules & Thresholds

All alerts map to `IFC-DP-010` Prometheus metrics and/or `/api/v1/system/resources` + `/api/v1/health` state. Latency/throughput numeric thresholds marked `TARGET_TO_BE_ESTABLISHED` will be locked after Phase 2/3 measurements (`DP-SPEC-102`).

| Alert ID | Condition / Signal | Severity | Trigger / Threshold | Automated / Operator Action |
|---|---|---|---|---|
| **ALT-01: Stream Stall / Data Staleness** | `platform_data_freshness_seconds{stream="kline"}` rises continuously or `ingestor.connected == false` | **WARN** / **CRIT** | WARN `> 120s`; CRIT `> 300s` (or `> 3 * timeframe`) | Inspect `BinanceWebSocketIngestor` reconnect state, run `/api/v1/streaming/status`, verify Binance REST/WS reachability, trigger `1m` + `aggTrade` gap heal. |
| **ALT-02: Consumer Lag Growth** | `increase(platform_consumer_lag_msgs[5m]) > 0` or lag sustained above `bronze_flush_max_records * 2` | **WARN** / **CRIT** | WARN `lag > 500` for `2m`; CRIT `lag > 2,000` or rising for `5m` | Check `stream_worker` heartbeat, flush duration histogram (`platform_batch_write_latency_seconds`), and SQLite lock contention. |
| **ALT-03: Disk Pressure** | `platform_disk_free_bytes` drops or `platform_disk_used_percent` rises | **WARN** / **CRIT** | WARN `< 10 GB` free or `>= 85%` used; CRIT `< 2 GB` free or `>= 95%` used | Immediately run `GovernanceService.enforce_retention()` + Warehouse old snapshot GC; at CRIT, pause non-essential ML training & REST archival (`503`). |
| **ALT-04: Host RAM / Process RSS Pressure** | `platform_host_ram_available_bytes` low or `platform_process_rss_bytes` exceeds profile budget | **WARN** / **CRIT** | WARN `host_free < 1024 MB` or `RSS > 0.85 * budget`; CRIT `host_free < 512 MB` | `WorkflowWorker` defers `MODEL_TRAIN` & `COMPACTION`; `StreamProcessor` flushes micro-batch immediately; operator checks external host apps (`2.64 GB` baseline free!). |
| **ALT-05: Stage Processing Failures** | `rate(platform_processing_failures_total[5m]) > 0` | **WARN** / **CRIT** | Any failure in `microbatch_flush`, `warehouse_build`, `workflow_task`, or `api_5xx` | Inspect structured logs by `process_role` + `stage` + `error_code`; check `workflow_runs` and `batch_ledger`. |
| **ALT-06: Data Gaps / DQ Critical Failure** | `increase(platform_data_gaps_detected_total[15m]) > 0` or `platform_dq_failures_total{rule_id=~"DQ-SCH.*\|DQ-NUL.*\|DQ-REL.*\|DQ-TRD.*"}` | **WARN** / **CRIT** | Gap detected unhealed after 1 retry; any `CRITICAL` DQ failure | Halt promotion to Gold/Warehouse for affected `(symbol, timeframe)`; inspect `data_quality_results` and trigger bounded gap-heal workflow. |
| **ALT-07: DLQ Growth** | `increase(platform_dlq_events_total[5m]) > 0` or `MARKET_DLQ` message count rises | **WARN** | `>= 5` DLQ events in `5m` (or any `reason="flush"` / `"consumer_error"`) | Query `GET /api/v1/streaming/dlq` (authenticated); identify schema drift vs malformed Binance payloads vs poison message. |
| **ALT-08: Stale Lease Reaper Activity** | `increase(platform_workflow_reaped_tasks_total[15m]) > 0` | **WARN** / **CRIT** | `>= 1` reaped task (worker crash/hang); CRIT if same `run_id` reaped `>= 3` times | Inspect dead `workflow_worker` logs/OOM events; inspect task idempotency state before manual retry. |
| **ALT-09: Worker Heartbeat Missing** | `worker_heartbeats` KV key expired in `STANDARD` / `EXTENDED` mode | **CRIT** | Missing `> 15s` (KV TTL) | Restart missing `stream_worker` or `workflow_worker`; API reports `DEGRADED`. |
