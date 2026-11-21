# ADR-DP-006: Durable SQL-Backed Workflow Orchestrator (Separate from NATS JetStream)

- **Status:** Accepted (Phase 1 Baseline)
- **Date:** 2026-11-17
- **Replaces:** `FastAPI.BackgroundTasks` (`api/v1/pipelines.py:135`) and un-leased `sync_worker.py` loop (`workers/sync_worker.py:44-53`)
- **Linked Requirements:** `REQ-DP-ORC-01..04`, `REQ-DP-DW-02`
- **Linked Components:** `COMP-DP-09`, `COMP-DP-06`, `COMP-DP-11`

---

## 1. Context & Observed Evidence (`OBSERVED` `#6`, `#7`, `#8`, `#9`)
1. **Volatile `FastAPI.BackgroundTasks` (`pipelines.py:26-46, 135-146`):** `POST /api/v1/pipelines/trigger` (`sync_mode=false`) spawns in-memory tasks inside FastAPI, returns no `run_id`, lacks per-`(symbol, timeframe)` mutual exclusion, has no lease/heartbeat, and orphans `PipelineRun` rows permanently in `status="RUNNING"` on restart.
2. **Task & Retry Bugs (`pipeline_service.py:240-252, 396-420`):** Only Task 1 retries (reusing `db` after exceptions without `await db.rollback()`), Task 4 (`extract_features`) is an empty stub, and no step-level checkpoint/resume exists.
3. **Ad-Hoc Un-Leased Background Loops:** `workers/sync_worker.py` is an unscheduled `sleep(300)` daemon omitted from `run.bat`/`docker-compose.yml`; `runtime.py:181` runs `enforce_retention` via `cycle % 600` in memory.
4. **Inline Heavy Request Blocking (`models.py:100`, `market.py:70`):** `POST /models/train` runs ML walk-forward training inline on the HTTP request handler (`AGENTS.md` Rule 7 violation).
5. **External Orchestrator Constraints (`MEASURED` `#6`):** Prefect, Temporal, and Celery+Redis are not installed (`requirements.txt`), and Docker/WSL2/Redis are absent on a host with `2.64 GB` free RAM.

## 2. Options Considered
1. **Option A — Deploy Temporal or Prefect Server:** Rejected; violates single-node RAM/dependency budgets (`#6`, `AGENTS.md` Rule 10) and requires external runtime infrastructure not present on host.
2. **Option B — Execute Batch Workflows Inside NATS JetStream Consumers:** Rejected; NATS JetStream targets low-latency ordered event streams (`AckWait=30s`), whereas ETL/Warehouse builds/ML training can run tens of seconds to minutes, require `(workflow, symbol, timeframe)` mutual exclusion locks, cron scheduling, and persistent DAG task resume state.
3. **Option C — Lightweight SQL-Backed Durable Job/DAG Queue + Lease/Reaper Worker (`PROPOSED`):** Reuse SQLite WAL / PostgreSQL with atomic lease claiming, heartbeats, stale-lease reaper, and `workflow_schedules`.

## 4. Decision
Adopt **Option C** (`WorkflowEngine` — `backend/app/services/workflow_service.py` + `backend/app/workers/workflow_worker.py`):
1. **Durable Tables (`IFC-DP-007`):**
   - `workflow_runs`: `id`, `workflow_type`, `symbol`, `timeframe`, `idempotency_key` (enforcing single active `QUEUED|RUNNING|RETRY_WAIT` run per scope), `status` (`QUEUED`, `RUNNING`, `RETRY_WAIT`, `SUCCESS`, `FAILED`, `CANCELLED`), `lease_owner`, `lease_token`, `lease_expires_at`, `heartbeat_at`, `attempt`, `max_attempts`, `next_run_at`, `params_json`, sanitized `error_code`/`error_summary`.
   - `workflow_tasks`: step-level status (`PENDING`, `RUNNING`, `SUCCESS`, `FAILED`, `SKIPPED`) allowing **step-level resume** (skipping already-`SUCCESS` steps on crash recovery).
   - `workflow_schedules`: persisted interval/cron definitions (`GAP_HEAL`, `GOLD_AND_WAREHOUSE_REFRESH`, `PARQUET_COMPACTION`, `FORECAST_RECONCILIATION`, `RETENTION_ENFORCE`).
2. **Execution & Crash Recovery Semantics:**
   - `POST /api/v1/pipelines/trigger` and `POST /api/v1/models/train` (async mode) insert a `QUEUED` `workflow_runs` record inside SQL, optionally emit a best-effort NATS `workflow.wakeup` nudge for `<5 ms` wakeup, and **immediately return `run_id`**—completely removing `FastAPI.BackgroundTasks`.
   - `WorkflowWorker` claims due jobs atomically (`BEGIN IMMEDIATE` on SQLite / `FOR UPDATE SKIP LOCKED` on Postgres), renews heartbeats (`heartbeat_at`, `lease_expires_at`), and offloads CPU work (`DuckDB`, `PyArrow`, `scikit-learn`) via `asyncio.to_thread`.
   - **Stale-Lease Reaper:** On startup and periodically, transitions expired `RUNNING` jobs (`lease_expires_at < now_utc`) to `RETRY_WAIT` (exponential backoff if `attempt < max_attempts`) or `FAILED`.
   - In `LITE`, `WorkflowWorker` runs as a clean supervised async loop inside the single `uvicorn` process; in `STANDARD`, it runs as dedicated Process 3 (`python -m backend.app.workers.workflow_worker`). `workers/sync_worker.py` becomes a thin backward-compatible shim delegating to `WorkflowService`.

## 5. Consequences
- **Positive:** Zero orphaned `RUNNING` jobs across crashes, deterministic single-flight locking for DuckDB Warehouse writes (`ADR-DP-004`) & gap healing, auditable history, and zero new infrastructure daemons.
- **Negative / Mitigation:** Polling latency of `~1–2s` if a `workflow.wakeup` NATS nudge is missed; fully acceptable for batch DAGs and ML jobs while keeping SQL 100% authoritative.
