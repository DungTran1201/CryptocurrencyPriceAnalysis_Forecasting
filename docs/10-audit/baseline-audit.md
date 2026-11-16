# Baseline Repository Audit

**Audit Date:** 2026-11-16  
**Repository:** `https://github.com/DungTran1201/CryptocurrencyPriceAnalysis_Forecasting`  
**Baseline Commit (`main`):** `f02164e1cac081343520517687ef9aa2b4057168`  
**Working Branch Created:** `feat/realtime-data-platform`  

---

## 1. Git & Workspace State

- `git status --short` on `main`: clean working tree (no uncommitted edits).
- Recent commit history:
  - `f02164e` — `feat: add institutional Binance design system, core frontend UI components, and architecture documentation`
  - `681e6d7` — `feat: implement enterprise data platform with pipelines, quality monitoring, analytics, and frontend views`
  - `843c107` — `feat: initialize project structure with FastAPI backend, React frontend, and agent workflows`
  - `e52053c` — `feat: add forecast history view, sync worker, and frontend dependencies`
  - `75ddcf6` — `Chatbot Agent first build,setup`
- Workspace directories present at baseline:
  - `.agent/` — rules, skills, agents, workflows
  - `.github/workflows/ci.yml` — backend pytest + frontend `npm run build`
  - `app/` — legacy Streamlit + quarantined `llm_core/` ("SenseiAgent" unrelated Japanese RAG artifacts)
  - `backend/app/` — FastAPI app, SQLAlchemy models (5 modules), Pydantic schemas (4 modules), API v1 routers (8 routers), services (8 modules), `workers/sync_worker.py`
  - `ml/` — `features.py`, `baselines.py`, `models.py`, `evaluation.py`, `registry.py`
  - `frontend/` — React 18 + TypeScript 5.6 + Vite 6 + Lucide React; 10 view files (`MarketOverview.tsx` orphaned; 9 routed in `App.tsx`)
  - `docker/` — `Dockerfile.backend`, `Dockerfile.frontend`, `docker-compose.yml`, `nginx.conf`
  - `docs/` — `architecture/data-flow.md`, `audit/{codebase-audit,current-state,ui-and-docs-audit}.md`, `design/`, `screenshots/`
  - `tests/` — 4 test files (`test_api_contract.py` [11 tests], `test_data_pipeline.py` [5 tests], `test_data_platform.py` [8 tests], `test_ml_pipeline.py` [4 tests] = **28 tests total**)

---

## 2. Baseline Verification Execution Results

| Check | Command | Exit Code | Result |
|---|---|---|---|
| Backend pytest | `py -3.12 -m pytest tests/ -v` | `1` | **FAILED at collection:** `tests/conftest.py:6: ModuleNotFoundError: No module named 'pytest_asyncio'` (no `.venv` created; `aiosqlite`, `pandas`, `pyarrow`, `asyncpg` also absent from Python 3.12 global site-packages) |
| Frontend unit tests | `npm test` (in `frontend/`) | `0` | **PASSED:** 5/5 tests in `src/utils/formatters.test.ts` via Node 24 `node --test` |
| Frontend typecheck & build | `npm run build` (`tsc && vite build`) | `1` | **FAILED:** `'tsc' is not recognized` (`frontend/node_modules` not installed) |
| Live Docker Compose | `docker ps -a` | `1` | **UNAVAILABLE:** Docker Desktop daemon not running |

---

## 3. Baseline Dependency Audit (`requirements.txt` & `frontend/package.json`)

- `requirements.txt` contains 19 packages (`fastapi`, `uvicorn`, `pydantic`, `pydantic-settings`, `sqlalchemy`, `aiosqlite`, `greenlet`, `asyncpg`, `pyyaml`, `requests`, `httpx`, `pandas`, `numpy`, `scikit-learn`, `joblib`, `scipy`, `pyarrow`, `pytest`, `pytest-asyncio`).
- Missing dependencies required for target Data Platform capabilities:
  - `nats-py` (NATS JetStream async client)
  - `duckdb` (in-process OLAP analytical engine over Parquet)
  - `websockets` (Binance public WebSocket stream ingestion)
  - `alembic` (schema migrations for SQLite & PostgreSQL)
  - `zstandard` (low-overhead Bronze payload compression)
  - `psutil` (host/process CPU, RAM, and disk observability)
  - `prometheus-client` (lightweight `/metrics` exposition)
- `frontend/package.json`: clean minimal footprint (`react`, `react-dom`, `lucide-react`, `typescript`, `vite`, `@vitejs/plugin-react`).

---

## 4. Truthfulness Audit of Existing Documentation

Inspection of existing docs against actual source code revealed concrete discrepancies:
1. `docs/audit/ui-and-docs-audit.md` cites nonexistent test filenames (`tests/test_analytics.py`, `tests/test_data_quality.py`, `src/components/StatusBadge.test.tsx`) and Vitest runner; the actual repository uses `tests/test_data_platform.py`, `tests/test_api_contract.py`, `tests/test_data_pipeline.py`, `tests/test_ml_pipeline.py` and Node's built-in `node --test`.
2. `README.md` architecture diagram and prose claim database tables `raw_market_klines`, `validated_market_klines`, `analytical_gold_marts`, and `ml_feature_sets`; none of these exist in `backend/app/models/`.
3. `README.md` PowerShell examples for `POST /api/v1/market/sync` and `POST /api/v1/pipelines/trigger` pass parameters as URL query strings (`?symbol=BTCUSDT...`), whereas the FastAPI handlers require JSON request bodies (`SyncRequestSchema`, `TriggerPipelineRequest`).
4. `PipelineService.execute_medallion_pipeline` logs completion of `build_gold_marts` and `extract_features` with hardcoded durations (`0.05s`, `0.04s`) without transforming or persisting Gold datasets or feature tables.

