# Requirement Traceability Matrix, Work Packages & Acceptance Framework

---

## 1. Requirement Traceability Matrix (RTM)

| Req ID | Acceptance ID | Module / Implementation Target | Verification Test / Evidence |
|---|---|---|---|
| `FR-ING-01`, `FR-ING-05` | `AC-04` | `backend/app/streaming/binance_ws.py` | Unit WS parser/reconnect test + Live Binance WS connection test |
| `FR-ING-02`, `FR-ING-04` | `AC-04`, `AC-14` | `backend/app/services/sync_service.py`, `models/market.py` | `tests/test_data_pipeline.py` (mocked REST + checkpointing + gap fill) |
| `FR-ING-03` | `AC-04`, `AC-06` | `backend/app/schemas/events.py`, `streaming/normalizer.py` | Schema versioning & UTC timestamp tests |
| `FR-STR-01..06` | `AC-05`, `AC-06`, `AC-14` | `backend/app/streaming/broker.py`, `consumers.py`, `dlq` | NATS JetStream publish/pull/ACK/NAK/DLQ/replay/backpressure tests |
| `FR-DAT-01..03` | `AC-07`, `AC-08`, `AC-09` | `backend/app/storage/{base,local,s3,medallion}.py`, `duckdb_engine.py` | Bronze zstd JSONL, Silver Parquet, Gold DuckDB/Parquet integration tests |
| `FR-DAT-04` | `AC-10` | `backend/app/services/data_quality_service.py` | Streaming & batch DQ rule tests (empty, valid, OHLC fail, gap, spike) |
| `FR-DAT-05..07` | `AC-11`, `AC-12` | `backend/app/models/governance.py`, `services/governance_service.py` | Catalog query, persisted lineage DAG, retention pruning tests |
| `FR-ORC-01..03` | `AC-13`, `AC-14` | `backend/app/services/pipeline_service.py`, `workers/orchestrator.py` | Persisted DAG task runs, retry, recovery replay/backfill tests |
| `FR-ANA-01..03` | `AC-15`, `AC-16` | `ml/incremental_analytics.py`, `backend/app/services/analytics_service.py` | Formula tests + stream vs batch reference parity tests across 15 metrics |
| `FR-ML-01..05` | `AC-17` | `ml/{features,models,evaluation,registry,online_features}.py`, `services/{model,forecast}_service.py` | No-lookahead test, walk-forward CV gating, triggered inference, reconciliation tests |
| `FR-APP-01..04` | `AC-18`, `AC-19` | `backend/app/api/v1/*`, `frontend/src/*` | FastAPI REST + WS contract tests, Vitest/node tests, `tsc && vite build`, Live UI check |
| `NFR-RES-01..02` | `AC-01`, `AC-02`, `AC-22`, `AC-23` | `backend/app/core/config.py`, `docs/10-audit/resource-budget.md` | Measured RAM/CPU/disk benchmarks under LITE & STANDARD profiles |
| `NFR-OBS-01` | `AC-20` | `backend/app/core/metrics.py`, `api/v1/system.py` | `/metrics` Prometheus scrape + psutil + NATS lag tests |
| `NFR-DEP-01` | `AC-21`, `AC-24`, `AC-25` | `alembic/`, `docker/docker-compose.yml`, `scripts/` | Alembic upgrade, startup script verification, full live E2E acceptance |

---

## 2. Work Package Breakdown (WBS)

| WP ID | Phase | Work Package | Key Deliverables |
|---|---|---|---|
| **WP-01** | Phase 4 | Foundation, Profiles, Alembic & Storage Abstraction | `.venv`, `nats-server.exe`, `config.py` profiles, `alembic/`, `storage/`, `metrics.py`, `docker-compose.yml` |
| **WP-02** | Phase 5 | Realtime Binance WS Ingestion & NATS Producer | Canonical event schemas, WS connector (`aggTrade`, `kline_1m`), bounded queue, REST backfill integration |
| **WP-03** | Phase 6 | Durable NATS JetStream Consumers, DLQ & Replay | Pull consumers, ACK/NAK, deduplication, backpressure pause/resume, DLQ table/subject, replay CLI/API |
| **WP-04** | Phase 7 | Real Medallion Storage, Catalog, Lineage & Retention | Bronze zstd JSONL, Silver Parquet, Gold DuckDB/Parquet, persisted Catalog & Lineage tables, Retention service |
| **WP-05** | Phase 8 | Financial & Risk Intelligence (Incremental + Batch) | All 15 metrics (incl. ATR, VWAP, CVaR, Covariance), rolling checkpoints, stream/batch parity tests |
| **WP-06** | Phase 9 | ML Online State, Walk-Forward CV & Triggered Inference | Online feature buffer, async/thread training, single-class guard, closed-candle inference trigger, reconciliation |
| **WP-07** | Phase 10 | FastAPI WS Gateway, Catalog/Lineage APIs & UI Upgrade | `/ws/market` coalescing, Catalog/Lineage/Streaming endpoints, Live Market Monitor + fixed UI contracts & build |
| **WP-08** | Phase 11-14 | Benchmarks, Test Suite, Live Acceptance & Final Reports | Full automated suite, LITE/STANDARD benchmarks, Live Binance->UI acceptance, disconnect recovery, final audit docs |

---

## 3. Definition of Ready (DoR) & Definition of Done (DoD)

### Definition of Ready (per Work Package)
- Hardware and resource budget constraints verified.
- Relevant existing contracts (`schemas/`, `models/`, `api/`, `frontend/src/types/`) traced.
- Bounded memory, error-handling, and persistence schemas defined.

### Definition of Done (per Work Package & Overall Platform)
- Code implemented with typed contracts, UTC timestamps, bounded queues, and zero silent drops or fake zeroes.
- Existing + new unit/integration tests pass with mocked external I/O in CI and zero skipped assertions.
- Live external test executed where applicable (Binance WS/REST -> NATS -> Medallion -> DuckDB -> API -> UI).
- Actual memory, CPU, disk, and latency measured and recorded honestly in `docs/10-audit/`.
- All 25 mandatory Acceptance Criteria (`AC-01` through `AC-25`) evaluated with explicit PASS/FAIL/BLOCKED/NOT TESTED evidence.

