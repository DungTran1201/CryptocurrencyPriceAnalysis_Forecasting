# Rollback and Troubleshooting Playbook

**Document ID:** `DP-SPEC-804`  
**Status:** `PROPOSED_PHASE_1_SPEC`  
**Owner:** `@sre-qa` (`WI-DP-01`)

---

## 1. Safe Rollback Procedures

### 1.1 Warehouse Snapshot Rollback (`dw-v{N}.duckdb` -> `dw-v{N-1}.duckdb`)
Because `WarehouseService` retains `N = 3` (or `5` EXTENDED) immutable snapshots:
1. Pause or wait for `warehouse_build` job in `WorkflowWorker` to become idle.
2. Update `warehouse_snapshots` active pointer (or `LATEST` pointer file) back to `dw-v{N-1}.duckdb`.
3. API readers immediately open `dw-v{N-1}.duckdb` (`read_only=True`) on next query without schema migration or downtime.

### 1.2 Data Lake Snapshot Rollback (`lake_snapshots`)
1. Identify last healthy `snapshot_id` (`status = 'SUPERSEDED'`) for affected `dataset_id` in `lake_snapshots`.
2. Flip `ACTIVE` snapshot pointer atomically back to prior `snapshot_id` (marking bad snapshot `FAILED` / `EXPIRED`) before GC TTL removes old Parquet objects (`LAKE-02`, `LAKE-03`).

### 1.3 Schema & Application Code Rollback
- **Database Migrations (`Alembic`):** Always take an online SQLite backup (`DP-SPEC-803` Section 2) **before** applying `alembic upgrade head`. If a Phase 2 migration must revert, stop API + workers, run `.\.venv\Scripts\alembic.exe downgrade <prior_rev>` (e.g., `af2bd5126950`), or restore the pre-upgrade `.db` backup if destructive DDL occurred.
- **Process Topology Rollback (`STANDARD` -> `LITE`):** If host RAM drops below safe levels for 3 Python processes, stop `stream_worker` and `workflow_worker`, set `PLATFORM_PROFILE=lite` and `STREAM_EMBEDDED_IN_API=true`, and restart via `run.bat lite`.
- **Cache Rollback (`HotStateCache`):** If NATS JetStream KV experiences memory pressure, `HotStateCache` falls back transparently to bounded in-process `TTLCache` + operational SQL/Lake queries.

---

## 2. Troubleshooting Matrix (`OBSERVED` & Known Failure Modes)

| Symptom | Probable Root Cause | Diagnostic Steps | Resolution |
|---|---|---|---|
| **API `GET /streaming/status` & `/metrics` return zeros while `stream_worker` is running** | AS-IS split-brain when `STREAM_EMBEDDED_IN_API=false` (`#7`), or expired `worker_heartbeats` KV TTL (`15s`). | Check `PLATFORM_PROFILE` & `STREAM_EMBEDDED_IN_API`; check `stream_worker` process alive; query `http://127.0.0.1:8222/jsz`. | In AS-IS: run `lite` profile (`embedded_in_api=true`). In TO-BE (`WI-DP-08`): verify `stream_worker` heartbeat in KV and `ServingGatewayBridge` NATS connection. |
| **DuckDB `IOException` / `WinError 32: file used by another process`** | Reader attempted to open `dw_staging.duckdb` directly while writer held `read_write` lock (`#15`). | Check DuckDB connection path in traceback/logs. | Ensure readers **only** open immutable `snapshots/dw-v{N}.duckdb` via `read_only=True`, never staging `.duckdb`. |
| **NATS `ServerError 10047: insufficient storage resources available`** | Attempting to allocate `StorageType.FILE` KV or oversized stream against LITE `128 MB` file cap (`121.6 MB` reserved by `MARKET_EVENTS` + `MARKET_DLQ`, `#16`). | Query `http://127.0.0.1:8222/jsz` -> check `reserved_storage` vs `config.max_storage`. | Use `StorageType.MEMORY` for `hot_state` and `worker_heartbeats` KV buckets; match `nats-local.conf` limits to profile (`start_nats.ps1`). |
| **SQL `klines` shows `is_closed = 0` while Silver Parquet shows `is_closed = True`** | AS-IS `save_klines_idempotent` / `_upsert_closed_klines_sql` skips existing `open_time` without open->closed promotion (`#9`). | Query SQL `SELECT * FROM klines WHERE is_closed = 0` and compare vs Silver Parquet. | Apply `WI-DP-04` (`ON CONFLICT DO UPDATE` promotion) and run gap-heal / force reconcile for affected bars. |
| **Pipeline stuck in `RUNNING` indefinitely after restart** | AS-IS `FastAPI.BackgroundTasks` died on process restart (`#7`, `#8`) or `WorkflowWorker` died mid-lease. | Query `pipeline_runs` / `workflow_runs` where `status = 'RUNNING'` and check `updated_at` / `lease_expires_at`. | In AS-IS: mark stale run failed manually or restart recovery. In TO-BE (`WI-DP-07`): `WorkflowWorker` stale-lease reaper auto-requeues expired leases. |
| **Consumer lag grows & `platform_batch_write_latency_seconds` spikes** | Slow Silver Parquet compaction / DuckDB memory spill / SQLite WAL lock contention or host RAM thrashing (`2.64 GB` free host RAM). | Check `/api/v1/system/resources` (`host_ram_available_mb`, `process_rss_mb`), `/api/v1/streaming/status` `pipeline_flow.totals.bottleneck_node_id`. | Close heavy external host apps if RAM `< 1 GB`; verify `LITE` batch caps (`50`/`250`); confirm `run_retention` is not competing heavily. |
| **`setup.bat` fails on `node` / `npm` or `git` not found** | Host has Node (`C:\Program Files\nodejs\`) & Git (`C:\Program Files\Git\cmd\`) installed outside default shell `PATH` (`#6`). | Run `where node; where git` in terminal. | Prepend `C:\Program Files\nodejs;C:\Program Files\Git\cmd` to session `PATH`. |
| **`nats-server` port `4222` busy or stale PID** | Previous `nats-server.exe` still running (e.g., PID `12080` observed at baseline) or orphaned `data/nats/nats.pid`. | `Get-NetTCPConnection -LocalPort 4222 -State Listen`; inspect `http://127.0.0.1:8222/varz`. | Reuse if healthy & matching profile limits; else stop gracefully (`nats-server.exe --signal quit` or `scripts\stop_nats.ps1`) and restart. |
