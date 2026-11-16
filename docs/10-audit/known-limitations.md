# Known Limitations, Unverified Environments & Future Evolution Paths

This document records verified boundaries, unexecuted optional components, and minor quirks observed during Phase 13–14 validation—without hiding gaps or extrapolating unrun checks.

---

## 1. Execution & Verification Boundaries

| Component / Check | Current Status | Root Cause & Verification Scope |
|---|---|---|
| **Live Chrome DevTools UI Visual Walkthrough (`browser` subagent)** | **BLOCKED** | Chrome DevTools MCP could not attach (`C:\Users\PC\AppData\Local\Google\Chrome\User Data\DevToolsActivePort` missing because remote debugging via `chrome://inspect/#remote-debugging` is disabled on host). **What WAS verified:** `npm test` (5/5), `npm run build` (`tsc && vite build`), live HTTP `GET /` SPA serving, live `/api/v1/ws/market` frames (`snapshot` + `tick_batch`), and HTTP `200` JSON validation across all 28 inspected REST routes. |
| **Docker Compose Runtime (`STANDARD` / `EXTENDED` Containers)** | **NOT RUN (Config Validated Only)** | Docker Desktop was stopped during verification on an 8 GB RAM host (~1.42–1.51 GB free RAM without `.wslconfig` limits). All three profiles (`lite`, `standard`, `extended`) in `docker/docker-compose.yml` exited `0` under `docker compose config --quiet`, and local `nats-server.exe` + Python API ran natively. |
| **PostgreSQL (`asyncpg`) Live Server Execution** | **NOT RUN** | Operational tables, indexes, and Alembic migrations (`af2bd5126950_initial_platform_schema.py`) were executed and tested live on SQLite WAL (`aiosqlite`), and dialect-safe SQLAlchemy models are defined for PostgreSQL, but no live Postgres server was started on host. |
| **Optional MinIO (`S3StorageBackend`) & Prometheus/Grafana Containers** | **NOT RUN** | `S3StorageBackend` storage interface (`backend/app/storage/s3.py`) and Grafana/Prometheus compose services exist, and `/metrics` Prometheus exposition works directly in FastAPI (`146+` lines live), while external container deployment was deferred due to host memory ceiling. |
| **Remote MLflow Tracking Server** | **NOT CONFIGURED (`LOCAL_REGISTRY_FALLBACK`)** | `/api/v1/models/tracking-status` intentionally reports `server_status: "NOT_CONFIGURED"` and operates with the local SQLite/file Model Registry unless `MLFLOW_TRACKING_URI` is explicitly pointed at a live MLflow server. |

---

## 2. Observed Functional & Behavioral Constraints

1. **Conservative ML Promotion Gate on Real Data**:
   - Running `POST /api/v1/models/train` on `665` hourly `BTCUSDT` observations produced `btcusdt_1h_6h_gradient_boosting_20261116_153952` with walk-forward `MAE = 732.48` vs naive persistence `naive_mae = 564.43` (`mae_improvement_pct = -29.77%`, `beats_naive_baseline = false`).
   - Because the promotion rule enforces `>= 1%` MAE improvement over naive baseline across chronological folds, the model remained unpromoted (`is_active = false`), and `POST /api/v1/forecasts/generate` honestly used `baseline_sma_14` instead of forcing an overfitted ML artifact.
2. **Live Forecast Reconciliation Window**:
   - `POST /api/v1/forecasts/reconcile` against the live DB returned `reconciled_count = 0` because the newly generated 6-hour horizon (`target_time = 2026-11-16T21:00:00 UTC`) had not yet matured at verification time. Matured-forecast reconciliation logic is exercised cleanly in automated backend unit tests (`tests/test_ml_pipeline.py`).
3. **`bronze_market_events` Data Explorer Timeframe Filtering**:
   - Querying `/api/v1/data-explorer/preview?dataset=bronze_market_events&symbol=BTCUSDT&timeframe=1h` returns `0` rows because Bronze raw `aggTrade` / REST batch envelopes store `schema_version`, `event_type`, `symbol`, `ingestion_time`, and `event_id` without a uniform `timeframe=1h` top-level partition key. Omitting `timeframe` returns raw Bronze records (`25` rows on page 1).
4. **In-App `ingestor.endpoint` Display Truncation**:
   - `GET /api/v1/streaming/status` reports `"endpoint": "wss:/"` due to simple string formatting of the endpoint summary while still establishing and maintaining active Binance TLS WebSocket sessions cleanly (`ws_connected: true`, `>2,168` events received).
5. **Dual-Process vs Embedded Single-Process Trade-Off in `LITE`**:
   - Running `STREAM_EMBEDDED_IN_API=true` keeps combined Python RSS at `~286–289 MB` on an 8 GB host; decoupled worker mode (`backend/app/workers/stream_worker.py`) adds one additional Python runtime (~100–130 MB RSS) and is best reserved for `STANDARD` deployments or hosts with >2 GB free RAM.
6. **Legacy Quarantine**:
   - Unrelated historical Streamlit/RAG code under `app/` remains isolated from `backend/`, `ml/`, and `frontend/` runtime execution paths per repository history preservation rules.

