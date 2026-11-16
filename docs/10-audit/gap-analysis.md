# Phase 2: Existing Architecture Audit & Gap Analysis

**Audit Date:** 2026-11-16  
**Baseline Codebase:** `feat/realtime-data-platform` (from `main` @ `f02164e`)

---

## 1. Documented Architecture vs. Actual Implementation Comparison

| Layer / Capability | Claimed in Existing Docs (`README.md`, `data-flow.md`, `ui-and-docs-audit.md`) | Observed Reality in Source Code | Gap Classification |
|---|---|---|---|
| **Ingestion** | REST kline ingestion + background sync worker | `BinanceSyncService` (REST only); `sync_worker.py` loops every 300s; **no WebSocket real-time ingestion (`aggTrade`, `kline_1m`)**. | **CRITICAL GAP** |
| **Message Broker** | Not present | No message broker (`nats-server` or client) exists. Ingestion writes directly to SQLite/Postgres in request/worker loop. | **CRITICAL GAP** |
| **Stream Processing** | Not present | No durable consumers, acknowledgements, dead-letter queue, backpressure, or replay. | **CRITICAL GAP** |
| **Bronze Storage** | `README.md` claims `raw_market_klines` table & Bronze buffer | **Does not exist.** `PipelineService` (`pipeline_service.py:217`) writes parsed records straight into `klines`. No immutable raw JSONL/Parquet archive. | **CRITICAL GAP** |
| **Silver Storage** | `README.md` claims `validated_market_klines` | `klines` SQL table exists, but no partitioned Parquet Silver layer, and DQ runs *after* `sync_incremental` commits rows into `klines`. | **HIGH GAP** |
| **Gold Storage & OLAP** | `README.md` & `pipeline_service.py:252` claim Gold Marts (`analytical_gold_marts`) | **Placeholder.** `build_gold_marts` only executes `SELECT COUNT(*), MIN, MAX` and logs `"Generated analytical aggregates"` with hardcoded `duration_seconds=0.05`. No DuckDB, no Gold Parquet marts. | **CRITICAL GAP** |
| **Feature Store** | `README.md` claims `ml_feature_sets`; `pipeline_service.py:277` claims 12 features extracted | **Placeholder.** `extract_features` stage does **zero computation**, hardcodes `duration_seconds=0.04`. No online feature state. | **CRITICAL GAP** |
| **Data Catalog** | Partial static metadata in `data_explorer.py` (`DATASETS_METADATA`) | Only 3 hardcoded dicts in Python memory; not persisted, missing Bronze/Gold/Features, missing retention, owner, version, partition specs. | **HIGH GAP** |
| **Data Lineage** | `data_quality_service.py:get_lineage_graph` | Static hardcoded Python array; `serving_forecasts` hardcoded `records: 0` & `status: "HEALTHY"`. Not persisted per run. | **HIGH GAP** |
| **Orchestration** | `PipelineRun` & `PipelineTaskRun` | Persisted tables exist, but `build_gold_marts` & `extract_features` are no-ops, no task retry logic, no scheduled maintenance DAG, no dataset input/output links. | **MEDIUM GAP** |
| **Analytics & Risk** | Returns, Volatility, Drawdowns, Correlations | **Missing CVaR, Covariance Matrix, ATR (in market/analytics), VWAP**, incremental streaming calculators, and batch/stream parity tests. | **MEDIUM GAP** |
| **Machine Learning** | `ml/` modules + `ModelService` + `ForecastService` | Walk-forward CV and registry exist, **but** `train_model_pipeline` blocks FastAPI event loop, `classifier.fit` fails on single-class fold, `ml/registry.py` uses `datetime.utcnow()`, `generate_forecast` silently runs network REST sync on empty DB, and `/models` has N+1 queries. | **MEDIUM GAP** |
| **Backend & WS** | 28 REST endpoints; static Vite build mount | No WebSocket gateway (`/ws`), no `/metrics` Prometheus endpoint, no resource/lag telemetry, missing validation on `/analytics/*`, `Symbol.last_synced_at` never updated by `sync_service.py`. | **HIGH GAP** |
| **Frontend UI** | 9 routed views + orphaned `MarketOverview.tsx` | Clean Binance dark UI, **but** no live streaming WS monitor, hardcoded symbol options in 3 views, `ForecastHistory` swallows errors silently, `MarketOverview.tsx` dead code. | **MEDIUM GAP** |
| **Database Migrations** | Claimed SQLite + Postgres | `Base.metadata.create_all` only; **no Alembic migrations**. | **MEDIUM GAP** |
| **Deployment & Profiles** | `docker/docker-compose.yml` | No `lite`/`standard`/`extended` profiles, no NATS, no resource limits (`mem_limit`), hardcoded credentials, deprecated `version: '3.8'`. | **HIGH GAP** |
| **Legacy Bloat** | `app/` (`llm_core/` SenseiAgent + Streamlit) | Unrelated copy-pasted Japanese RAG code quarantined in `app/llm_core/README.md`, Streamlit dashboard incompatible with FastAPI backend. | **LOW (CLEANUP/ISOLATE)** |

---

## 2. Prior Audit Findings Re-Verification

Re-checking `docs/audit/codebase-audit.md` and `docs/audit/ui-and-docs-audit.md`:
- **P0-KLINES-EMPTY**: Confirmed fixed in `market_service.py:165-171` (`count: 0`).
- **P1-FALSE-ZEROS**: Partially fixed in `market_service.py:76-90`, **but** `sync_service.py` never updates `Symbol.last_synced_at`, breaking the `STALE` status transition in real deployments!
- **P1-N-PLUS-ONE**: Fixed in `market_service.py`, **but still present** in `backend/app/api/v1/models.py:67-73` and `backend/app/services/mlflow_adapter.py:67-74`.
- **UI & Docs Audit**: Overstated test coverage (`test_analytics.py`, `StatusBadge.test.tsx`, Vitest do not exist); current `tests/` has 28 tests that could not execute until `.venv` is provisioned.

---

## 3. Refactoring & Preservation Strategy

1. **Preserve all working capabilities and existing routes** (`/api/v1/market/*`, `/api/v1/forecasts/*`, `/api/v1/models/*`, `/api/v1/pipelines/*`, `/api/v1/data-quality/*`, `/api/v1/data-explorer/*`, `/api/v1/analytics/*`, `/api/v1/system/*`) while fixing their internal bugs and upgrading them to use genuine Medallion/DuckDB/Catalog/Lineage backends.
2. **Keep `app/` quarantined** (never imported by `backend/` or `ml/`); document clearly as deprecated legacy prototype without breaking git history.
3. **Remove/replace placeholder logic** in `PipelineService` and `DataQualityService` with actual Bronze/Silver/Gold/Feature transformations and persisted metadata.
4. **Consolidate orphaned `MarketOverview.tsx`** or evolve it into the **Live Market Monitor** view so zero dead UI code remains.

