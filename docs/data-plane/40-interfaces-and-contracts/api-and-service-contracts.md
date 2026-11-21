# API and Service Contracts

- **Document ID:** `IFC-DP-007` (with API Boundary Rules)
- **Status:** `PROPOSED` (Specification Baseline v1.0)
- **Owner:** `@stream-orch` (Phase 1 Step 2)
- **Traceability:**
  - Requirements: `REQ-DP-ORC-01`, `REQ-DP-ORC-04`, `REQ-DP-SRV-01`, `REQ-DP-SEC-01`, `REQ-DP-SEC-02`, `REQ-DP-OBS-03`
  - Components: `COMP-DP-08` (ServingGatewayBridge), `COMP-DP-09` (WorkflowEngine), `COMP-DP-11` (API Gateway)
  - ADRs: `ADR-DP-001`, `ADR-DP-006`, `ADR-DP-007`
  - Phase 2 Work Items: `WI-DP-07`, `WI-DP-08`, `WI-DP-09`, `WI-DP-10`, `WI-DP-13`

---

## 1. Purpose and Normative Boundary Rules

All HTTP/WebSocket endpoints under `/api/v1` and `/metrics` serve as a **stateless read and control gateway** (`ADR-DP-001`). The API process MUST obey these boundary invariants:

1. **Mandatory Typed Pydantic Contracts**: Replace untyped `Dict[str, Any]` / `List[Dict[str, Any]]` returns on `/system/resources`, `/streaming/*`, `/pipelines/*`, `/data-explorer/*`, `/data-quality/*`, `/governance/*`, and `/analytics/*` with explicit Pydantic response schemas (`AGENTS.md` Rule #3).
2. **Preserve `MarketDataResponseSchema` Contract**: `GET /api/v1/market/klines` MUST always return `MarketDataResponseSchema(symbol, timeframe, count, candles, indicators)` (`backend/app/schemas/market.py:36-42`), returning `count=0, candles=[], indicators={}` when empty (`AGENTS.md`).
3. **Non-Blocking Event Loop (`REQ-DP-ORC-04`, `REQ-DP-OBS-03`)**:
   - Never run heavy model training, full REST backfill, or multi-step ETL inline inside HTTP request handlers (`POST /models/train`, `POST /pipelines/trigger`, `POST /market/sync` must enqueue durable jobs in `workflow_runs` or run explicitly bounded async I/O).
   - Never run synchronous `Path.rglob("*")` (`collect_resource_snapshot`), DuckDB scans, or PyArrow reads directly on the event loop; offload CPU/FS work via `asyncio.to_thread(...)` or read precomputed manifests/heartbeats.
   - **Zero DB Writes on `GET`**: `GET /data-explorer/datasets`, `GET /governance/catalog`, and `GET /data-quality/lineage` MUST NOT call `GovernanceService.sync_catalog_entries(db)` + `await db.commit()` (`governance_service.py:276-282`); `get_db()` (`database.py:107`) MUST NOT unconditionally commit on read requests.
4. **Sanitized Error Contracts (`REQ-DP-SEC-02`)**:
   - Public HTTP error responses and persisted public `error_summary` fields MUST NOT expose raw `str(exc)`, stack traces, file paths, SQL, or credentials (remediating `pipelines.py:87, 100`, `broker.py:360`, `market.py:95`, `forecast.py:41`, `models.py:123`).
   - Return structured error payloads `{error_code, message, correlation_id}` and log full details server-side.
5. **Input & Datetime Validation (`REQ-DP-SEC-01`)**:
   - Every endpoint accepting `symbol` or `timeframe` MUST call `validate_symbol` and `validate_timeframe` (`core/security.py:13-30`) — fixing gaps in `market.py:45-53`, `data_explorer.py:145, 284`, and `data_quality.py:122`.
   - Normalize `start_time` and `end_time` query parameters (`market.py:40-41`) via `ensure_utc_naive()` before comparing against UTC-naive ORM `DateTime` columns (`asyncpg` compatibility) and enforce `start_time <= end_time`.
   - Enforce `require_admin_if_configured` on **all** mutation routes, adding it to `POST /forecasts/generate`, `POST /forecasts/reconcile`, `POST /data-quality/evaluate`, `POST /streaming/dlq/{id}/replay`, and `POST /pipelines/runs/{id}/cancel` (`REQ-DP-SEC-01`).

---

## 2. Durable Workflow REST Contracts (`IFC-DP-007`)

Replaces `pipelines.py:26-46, 106-146` (`FastAPI.BackgroundTasks` with no `run_id`).

### 2.1 Trigger & Enqueue Endpoints (`202 Accepted`)

| Endpoint | Method | Request Schema | Response Schema | Behavior |
|---|---|---|---|---|
| `/api/v1/pipelines/trigger` | `POST` | `TriggerPipelineRequest(symbol, timeframe, trigger_type, lookback_days, skip_network_ingest)` | `WorkflowEnqueuedResponse(run_id, workflow_type, symbol, timeframe, status, deduplicated, created_at)` | Inserts `QUEUED` `workflow_runs` + child `workflow_tasks`, emits NATS `workflow.wakeup`, returns `run_id` immediately. Deduplicates active `(MEDALLION_DAG, symbol, timeframe)` runs (`deduplicated=True`). (`sync_mode` query removed or strictly restricted to test/CLI). |
| `/api/v1/models/train` | `POST` | `ModelTrainRequest` | `WorkflowEnqueuedResponse` (or `202` job status) | Enqueues `ML_TRAIN` workflow job (`WorkflowWorker` executes off API process, `REQ-DP-ORC-04`). |
| `/api/v1/market/sync` | `POST` | `SyncRequestSchema` | `WorkflowEnqueuedResponse` (or bounded async sync with `run_id`) | Enqueues `MARKET_SYNC` (or executes bounded incremental sync under workflow lock when `mode=inline` is explicitly enabled). |
| `/api/v1/pipelines/runs/{run_id}/cancel` | `POST` | None (Admin protected) | `WorkflowRunSummarySchema` | Cancels `QUEUED` immediately or signals active worker lease revocation (`CANCELLED`). |
| `/api/v1/pipelines/runs/{run_id}/retry` | `POST` | None (Admin protected) | `WorkflowEnqueuedResponse` | Resets `FAILED` run to `QUEUED` resuming from first non-`SUCCESS` `workflow_tasks` step. |

### 2.2 Workflow Query & Schedule Endpoints

- `GET /api/v1/pipelines/overview` -> `PipelineOverviewSchema`: `{total_runs, queued_runs, running_runs, retry_wait_runs, succeeded_runs, failed_runs, success_rate_pct, total_rows_read, total_rows_inserted, avg_duration_seconds, latest_successful_run_at, latest_error_code, latest_error_summary}`.
- `GET /api/v1/pipelines/runs` -> `List[WorkflowRunSummarySchema]`: includes `id, workflow_type, symbol, timeframe, status, attempt, max_attempts, lease_owner, heartbeat_at, next_run_at, error_code, error_summary, started_at, completed_at, duration_seconds`.
- `GET /api/v1/pipelines/runs/{run_id}` -> `WorkflowRunDetailSchema`: includes `tasks: List[WorkflowTaskSchema]` with `checkpoint_json`, `attempt`, `error_code`, `error_summary`.
- `GET /api/v1/pipelines/schedules` -> `List[WorkflowScheduleSchema]`: exposes persisted `workflow_schedules` (sync, gap-heal, warehouse build, retention).

---

## 3. Streaming & Serving Bridge REST/WS Contracts (`REQ-DP-SRV-01`)

All endpoints behave identically in `LITE` (`embedded_in_api=True`) and `STANDARD`/`EXTENDED` (`embedded_in_api=False`) by reading from `HotStateCache` (`IFC-DP-004`/`009`) and dispatching control via NATS `serving.control.*` (`IFC-DP-002`):

| Endpoint | Method | Typed Response | Source & Degraded Behavior |
|---|---|---|---|
| `/api/v1/streaming/status` | `GET` | `StreamingStatusSchema` | Reads `hot_state` (`stream.status.latest`) + `worker_heartbeats` + live `broker.get_stream_info()`. If no active `stream_worker` heartbeat exists within `15s`, sets `worker_status="UNAVAILABLE"` instead of returning fake local `0` counts. |
| `/api/v1/streaming/flush` | `POST` | `FlushResultSchema` | Sends NATS request-reply to `serving.control.flush` (`timeout=5.0s`). Returns `503` with safe message if no `StreamWorker` responds. |
| `/api/v1/streaming/simulate-disconnect` | `POST` | `DisconnectTriggerSchema` | Sends NATS request-reply to `serving.control.simulate_disconnect` (`timeout=5.0s`). Returns `503` if ingestor inactive. |
| `/api/v1/streaming/replay` | `POST` | `ReplayResponseSchema` | Validates `ReplayRequest.subject` against `^market\.(aggtrade|kline|dlq)\.[A-Za-z0-9_.*>]+$`. Catches NATS errors -> safe `502`/`503`. |
| `/api/v1/streaming/dlq/{dlq_id}/replay` | `POST` | `DlqReplayResponseSchema` | Admin-protected; validates `DeadLetterEvent` payload, republishes to NATS stream, transitions DB status `QUARANTINED -> REPLAYED` + `replayed_at`. |
| `/api/v1/analytics/incremental` | `GET` | `IncrementalAnalyticsResponseSchema` | Reads `hot_state` `analytics.inc.*` keys (`L1 -> L2 KV`); falls back to checkpoint JSON on KV miss with `freshness_status`. |
| `/api/v1/ws/market` | `WS` | JSON (`snapshot`, `tick_batch`, `heartbeat`, `broker_degraded`) | Fed by `ServingGatewayBridge` subscribing to NATS `serving.market.*` and `serving.system.status` into `WSBroadcastHub` (`maxsize=16` bounded per-client queue). |

---

## 4. Health, System, and Explorer Boundary Fixes

1. **`GET /api/v1/health` (`system.py:22-31`)**: Probes SQL `SELECT 1`, broker connectivity, and active worker heartbeat ages from `worker_heartbeats` KV; returns `status: "healthy" | "degraded"` with structured dependency booleans (never raw exception text).
2. **`GET /api/v1/system/status` (`system.py:34-61`)**: Removes hardcoded `database_connected=True`; wraps DB query failures into explicit degraded/503 status.
3. **`GET /api/v1/system/resources` (`system.py:64-100`)**: Returns `SystemResourcesSchema` aggregating per-process heartbeats (`api`, `stream_worker`, `workflow_worker`) from `worker_heartbeats` KV + cached storage stats (never blocking the event loop with synchronous `rglob`).
4. **`GET /api/v1/data-explorer/preview` & `/export` (`data_explorer.py:145-336`)**:
   - Validate `symbol` and `timeframe`; apply filters BEFORE pagination/limit so `total_rows` and `total_pages` are accurate; honor `timeframe` on Gold CSV exports (`data_explorer.py:311-319` currently ignores it); query Gold/Silver via `ACTIVE` snapshot manifests + offloaded DuckDB (`asyncio.to_thread`).
