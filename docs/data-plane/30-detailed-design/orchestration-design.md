# Durable Workflow Orchestration Design

- **Document ID:** `DD-DP-ORC-001`
- **Status:** `PROPOSED` (Specification Baseline v1.0)
- **Owner:** `@stream-orch` (Phase 1 Step 2)
- **Traceability:**
  - Requirements: `REQ-DP-ORC-01`, `REQ-DP-ORC-02`, `REQ-DP-ORC-03`, `REQ-DP-ORC-04`, `REQ-DP-DW-02`
  - Components: `COMP-DP-09` (WorkflowEngine), `COMP-DP-06` (WarehouseService), `COMP-DP-10` (Governance/DQ), `COMP-DP-11` (API Gateway)
  - ADRs: `ADR-DP-001`, `ADR-DP-004`, `ADR-DP-006`
  - Interfaces: `IFC-DP-002`, `IFC-DP-007`, `IFC-DP-011`
  - Phase 2 Work Items: `WI-DP-05`, `WI-DP-07`, `WI-DP-11`, `WI-DP-13`

---

## 1. Purpose and Separation from NATS JetStream

NATS JetStream (`MARKET_EVENTS` / `MARKET_DLQ`) is built for low-latency, ordered streaming event delivery (`AckWait=30s`). Long-running batch DAGs—historical backfill, `aggTrades` healing, Silver compaction, Gold Parquet materialization, DuckDB Warehouse builds (`REQ-DP-DW-02`), ML walk-forward training (`REQ-DP-ORC-04`), forecast reconciliation, and retention sweeps—require mutual exclusion locks, multi-minute leases, cron schedules, and step-level resume.

This document specifies the **SQL-Backed Durable Workflow Orchestrator (`COMP-DP-09`)**, completely eliminating `FastAPI.BackgroundTasks` (`pipelines.py:135-146`), the un-leased `sync_worker.py` `sleep(300)` loop (`sync_worker.py:44-53`), and `runtime.py`'s `cycle % 600` retention timer (`runtime.py:181-182`).

---

## 2. AS-IS Orchestration Defects (`[OBSERVED]`)

| Defect | Location | Impact |
|---|---|---|
| Volatile `BackgroundTasks` & missing `run_id` | `pipelines.py:26-46, 134-146` | Queued runs vanish on crash; active runs remain stuck in `status="RUNNING"` permanently (`pipeline_service.py:48-50`); caller receives no `run_id` |
| Zero concurrency mutex | `pipelines.py:135`, `pipeline_service.py:165` | Duplicate triggers for `(symbol, timeframe)` run concurrently, racing on SQL `klines`, Silver Parquet, and Gold Parquet |
| No step retry/resume or rollback | `pipeline_service.py:240-252, 286-420` | Only Task 1 retries (without `db.rollback()`); Tasks 2–4 have zero retry; failed runs cannot resume from last succeeded step |
| Heavy ML/sync/DAG inline in HTTP handlers | `models.py:100-126`, `pipelines.py:118-133`, `market.py:70-98` | HTTP clients block on walk-forward ML training (`AGENTS.md` Rule #7 violation) and REST sync loops |
| `sync_worker.py` omitted & un-leased | `sync_worker.py:1-61`, `run.bat`, `docker-compose.yml` | Not launched by `run.bat` or Compose; omits `fill_gaps()`; no leader lease or signal handler |
| Windows signal handling ignored | `stream_worker.py:24-27` | `loop.add_signal_handler` raises `NotImplementedError` on Windows, leaving `SIGTERM` without graceful shutdown |

---

## 3. Persistent SQL State Model (`IFC-DP-007`)

Workflow persistence extends `pipeline_runs` / `pipeline_task_runs` (or introduces unified `workflow_runs`, `workflow_tasks`, `workflow_schedules` tables in `WI-DP-05`) with explicit lease and schedule state:

1. **`workflow_runs`**:
   - Identity & Routing: `id (UUID PK)`, `workflow_type` (`MEDALLION_DAG`, `MARKET_SYNC`, `GAP_HEAL`, `PARQUET_COMPACT`, `WAREHOUSE_BUILD`, `ML_TRAIN`, `FORECAST_RECONCILE`, `RETENTION_ENFORCE`), `symbol`, `timeframe`, `trigger_type` (`MANUAL`, `SCHEDULED`, `RECONNECT`, `RETRY`), `idempotency_key` (enforces single active `QUEUED|RUNNING|RETRY_WAIT` run per `(workflow_type, symbol, timeframe)` via partial unique index / transactional check).
   - Lifecycle: `status` (`QUEUED`, `RUNNING`, `RETRY_WAIT`, `SUCCESS`, `FAILED`, `CANCELLED`), `priority (int)`, `attempt (int)`, `max_attempts (int)`, `next_run_at (DateTime)`.
   - **Lease & Heartbeat**: `lease_owner (String(64)?)`, `lease_token (String(36)?)`, `lease_expires_at (DateTime?)`, `heartbeat_at (DateTime?)`.
   - Watermarks & Sanitized Error: `params_json`, `result_json`, `error_code (String(64)?)`, `error_summary (String(512)?)` (safe public summary; full diagnostics logged server-side only, `REQ-DP-SEC-02`), `started_at`, `completed_at`, `duration_seconds`, `created_at`.
2. **`workflow_tasks`** (Child DAG Steps):
   - `id`, `run_id (FK CASCADE)`, `task_name`, `sequence_order`, `depends_on`, `status` (`PENDING`, `RUNNING`, `SUCCESS`, `FAILED`, `SKIPPED`), `attempt`, `max_attempts`, `checkpoint_json` (step cursor/resume state), `records_processed`, `started_at`, `completed_at`, `duration_seconds`, `error_code`, `error_summary`.
3. **`workflow_schedules`**:
   - `schedule_id (PK)`, `workflow_type`, `symbol`, `timeframe`, `interval_seconds`, `enabled (bool)`, `params_json`, `last_run_id`, `last_triggered_at`, `next_trigger_at`, `updated_at`.
   - Default seeded schedules replace `sync_worker.py` (`300s` sync + gap-heal + reconcile), `runtime.py` (`600s` retention + warehouse incremental build + Silver trade compaction).

---

## 4. Lease, Heartbeat, Stale-Lease Reaper, and Step Resume (`REQ-DP-ORC-01..03`)

### 4.1 Atomic Job Claim & Mutual Exclusion (`REQ-DP-ORC-01`)
- `POST /api/v1/pipelines/trigger` (and `POST /api/v1/models/train`, `POST /api/v1/market/sync`) validates inputs (`validate_symbol`, `validate_timeframe`), writes a `QUEUED` `workflow_runs` row inside the request transaction, optionally publishes a fire-and-forget NATS `workflow.wakeup` nudge, and returns HTTP `202 Accepted` immediately with `{run_id, status: "QUEUED", deduplicated: bool}`.
- If an active run with the same active `(workflow_type, symbol, timeframe)` lock already exists (`QUEUED` or `RUNNING`), the API returns that existing `run_id` (`deduplicated: true`) rather than spawning racing duplicates.
- **Claim Protocol (`WorkflowWorker`)**:
  - Polls every `workflow.poll_interval_sec` (`2.0s`) or wakes immediately on NATS `workflow.wakeup`.
  - Atomically claims the highest-priority due job (`status IN ('QUEUED', 'RETRY_WAIT') AND next_run_at <= now_utc`) via:
    - PostgreSQL: `SELECT ... FOR UPDATE SKIP LOCKED` + `UPDATE ... SET status='RUNNING', lease_owner=..., lease_token=..., lease_expires_at=now+lease_ttl`.
    - SQLite: single conditional `UPDATE workflow_runs SET status='RUNNING', lease_owner=..., lease_token=..., lease_expires_at=... WHERE id = (SELECT id FROM workflow_runs WHERE ... LIMIT 1) AND status IN ('QUEUED', 'RETRY_WAIT')` checking `rowcount == 1`.

### 4.2 Heartbeat & Stale-Lease Reaper (`REQ-DP-ORC-02`)
- **Heartbeat Renewal**: While a task executes, a background lease-renewer task updates `heartbeat_at = now_utc` and `lease_expires_at = now_utc + lease_ttl_sec` (default `60s`, renewed every `15s`), fenced by `WHERE id = :run_id AND lease_token = :token AND status = 'RUNNING'`. If renewal sees `rowcount == 0` (lease stolen/cancelled), execution aborts cleanly via cancellation token.
- **Stale-Lease Reaper**: Runs at `WorkflowWorker` startup and every `workflow.reaper_interval_sec` (`15s`):
  - Queries `workflow_runs WHERE status = 'RUNNING' AND lease_expires_at < now_utc`.
  - Also transitions any orphaned `workflow_tasks WHERE status = 'RUNNING'` under that run to `PENDING` (for safe idempotent re-execution).
  - If `run.attempt < run.max_attempts`: transitions run to `RETRY_WAIT` with exponential backoff (`min(10 * 2^attempt, 300)`s), clearing `lease_owner`/`lease_token`.
  - Else: marks run `FAILED` (`error_code="LEASE_EXPIRED_MAX_RETRIES"`) so `running_runs` never stays inflated after crashes.

### 4.3 Step-Level Idempotent Resume (`REQ-DP-ORC-02`)
- When `WorkflowWorker` starts or resumes a `workflow_runs` record:
  - Loads existing `workflow_tasks` ordered by `sequence_order`.
  - Tasks already in `status == 'SUCCESS'` are **skipped** (preserving their `records_processed` and outputs!).
  - Tasks in `PENDING` or reset from crashed `RUNNING` execute sequentially inside clean per-step transactions (`await db.rollback()` before any retry!).
  - `extract_features` (`pipeline_service.py:396-420`) becomes a genuine, standalone step consuming the latest `ACTIVE` Silver snapshot (no longer a stub duplicating Task 3).
  - **Serialized DuckDB Warehouse Lock (`REQ-DP-DW-02`)**: `WAREHOUSE_BUILD` jobs acquire an explicit SQL/workflow exclusive lease (`workflow_type='WAREHOUSE_BUILD'`, global key `global`), guaranteeing only one writer ever mutates `dw_staging.duckdb` before atomic `dw-v{N}.duckdb` snapshot swap.

---

## 5. Resource-Aware Throttling & Windows Signal Handling

### 5.1 Host Memory & Concurrency Guardrails (`[MEASURED]` #6)
- Host measurements show only `2.64 GB` free RAM under external host load, and LITE caps total Python RSS at `450 MB`.
- `WorkflowWorker` enforces:
  - `workflow.max_concurrent_jobs`: `1` in `LITE`, `2` in `STANDARD`, `3` in `EXTENDED` (excluding `WAREHOUSE_BUILD` and `ML_TRAIN`, which are mutually capped at `1` active CPU-heavy job at a time).
  - Before claiming `ML_TRAIN` or `WAREHOUSE_BUILD`, check process RSS vs `resources.total_memory_mb` (and `psutil.virtual_memory().available`): if memory utilization exceeds `90%` (`HIGH_MEMORY_PRESSURE`), defer non-urgent `SCHEDULED` jobs (`next_run_at = now + 30s`) while still allowing critical `GAP_HEAL` / `FORECAST_RECONCILE` runs, logging a `WARNING` metric.
  - CPU-heavy Pandas/DuckDB/Scikit-learn stages execute via `asyncio.to_thread` (or bounded worker threadpool) so the asyncio heartbeat loop never starves and misses lease renewal!

### 5.2 Cross-Platform Windows Graceful Shutdown (`stream_worker.py` & `workflow_worker.py`)
- Because Windows `asyncio` event loops raise `NotImplementedError` on `loop.add_signal_handler` (`stream_worker.py:24-27`), both `stream_worker.py` and `workflow_worker.py` register standard `signal.signal(signal.SIGINT, ...)` / `signal.signal(signal.SIGTERM, ...)` (and `SIGBREAK` on Windows) calling `loop.call_soon_threadsafe(stop_event.set)`!
- On shutdown signal:
  1. `WorkflowWorker` stops claiming new jobs.
  2. Active job receives graceful cancellation / waits up to `graceful_shutdown_sec = 15.0s` to finish current atomic step.
  3. Any job still mid-step releases its lease cleanly (`status='RETRY_WAIT', next_run_at=now_utc`) instead of waiting for lease expiration.

### 5.3 Deployment Topology Parity (`LITE` vs `STANDARD` / `EXTENDED`)
- **LITE (`run.bat lite`)**: Can run `WorkflowWorker` either as an explicit lightweight coroutine loop inside the single `LITE` runtime OR as a dedicated second Python process (`max_python_procs: 2` in `config.py:25` already budgets 2 Python processes for LITE!). Running `uvicorn` (with embedded `StreamRuntime`) + `workflow_worker` stays within `max_python_procs=2` and isolates ML/DuckDB bursts cleanly from HTTP/WS serving.
- **STANDARD / EXTENDED (`run.bat standard|extended`)**: Launches `uvicorn` (API), `python -m backend.app.workers.stream_worker`, and `python -m backend.app.workers.workflow_worker` (`sync_worker.py` becomes a backward-compatible CLI shim delegating to `workflow_worker`).
