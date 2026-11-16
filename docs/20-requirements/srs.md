# Software Requirements Specification (SRS)

**Project:** Resource-Efficient Real-Time Financial Data Intelligence Platform  
**Target Profiles:** `LITE`, `STANDARD`, `EXTENDED`  
**Constraint Baseline:** Single-node personal workstation (8 GB RAM / ~1.4 GB free RAM during dev, 6C/12T CPU, 17.09 GB free disk on `C:`).

---

## 1. Functional Requirements (FR)

### 1.1 Data Ingestion & Streaming (`FR-ING`)
- **FR-ING-01:** Connect to Binance public WebSocket streams (`aggTrade` and `kline_1m`) for configurable symbols (`BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT` default).
- **FR-ING-02:** Support Binance public REST historical backfill and gap healing (`data-api.binance.vision` primary, `api.binance.com` fallback) with exponential backoff + jitter.
- **FR-ING-03:** Normalize raw exchange events into versioned canonical schemas (`schema_version="1.0.0"`) with explicit `event_time`, `ingestion_time`, `processing_time`, UTC normalization, and `is_closed` distinction.
- **FR-ING-04:** Persist ingestion checkpoints (`symbol`, `stream_type`, `timeframe`, `last_event_time`, `last_sequence_id`) so restarts resume without gap loss or duplication.
- **FR-ING-05:** Auto-reconnect WebSocket streams on disconnect/network interruption with bounded backoff and live status reporting.

### 1.2 Message Broker & Stream Processing (`FR-STR`)
- **FR-STR-01:** Publish normalized canonical events to durable **NATS JetStream** subjects (`market.aggtrade.<symbol>`, `market.kline.<timeframe>.<symbol>`).
- **FR-STR-02:** Run bounded, durable pull consumers for: (a) Bronze archival, (b) Silver validation & Parquet persistence, (c) Incremental Analytics & Feature State, and (d) Coalesced Serving Broadcast.
- **FR-STR-03:** Enforce explicit `ACK` only after durable processing/commit, `NAK` with backoff on transient failure, and Dead-Letter Queue (`market.dlq.*`) persistence after `max_deliver`.
- **FR-STR-04:** Enforce strict idempotency on `(symbol, timeframe, open_time)` for klines and `(symbol, agg_trade_id)` for trades.
- **FR-STR-05:** Support deterministic JetStream replay by sequence/time window for recovery and historical recomputation.
- **FR-STR-06:** Enforce bounded queues and backpressure without silent event dropping.

### 1.3 Medallion Storage, Catalog, Lineage & Governance (`FR-DAT`)
- **FR-DAT-01:** **Bronze Layer** — Persist immutable raw event payloads (with ingestion timestamp & source metadata) in `zstd`-compressed JSONL micro-batches via `StorageBackend` abstraction.
- **FR-DAT-02:** **Silver Layer** — Validate, normalize, and deduplicate events; persist partitioned Apache Parquet (`source=binance/event_type=.../dt=YYYY-MM-DD/symbol=...`) and transactional SQLite/Postgres metadata/klines.
- **FR-DAT-03:** **Gold Layer** — Materialize analytical Parquet marts (`gold_returns`, `gold_volatility_risk`, `gold_drawdowns`, `gold_correlations`, `gold_features`) and query lazily via **DuckDB** (`memory_limit` bounded).
- **FR-DAT-04:** **Data Quality** — Run both streaming per-batch validation and batch 10+ rule suites (Completeness, Schema, Uniqueness, Monotonic Ordering, Interval Gaps, OHLC Geometry, Non-Negative Volume, Future Timestamps, Outlier Spikes, Freshness SLA), persisting runs/results.
- **FR-DAT-05:** **Data Catalog** — Persist queryable catalog metadata (`dataset_name`, `layer`, `schema_json`, `data_type`, `source`, `partition_spec`, `row_count`, `storage_location`, `owner`, `retention_policy`, `version`, `updated_at`).
- **FR-DAT-06:** **Data Lineage** — Persist queryable run-level provenance edges tracing `Source -> Ingestion -> Broker -> Bronze -> Silver -> Gold -> Features -> ML -> Serving`.
- **FR-DAT-07:** **Governance & Retention** — Enforce schema versioning, dataset naming conventions, automated retention pruning by age & disk ceiling, and audit trail logging.

### 1.4 Orchestration & Recovery (`FR-ORC`)
- **FR-ORC-01:** Provide lightweight persisted DAG/task runner tracking workflows, task dependencies, execution status (`PENDING/RUNNING/SUCCESS/FAILED`), start/end times, duration, rows processed, retries, input/output datasets, and error messages.
- **FR-ORC-02:** Provide periodic scheduled maintenance (backfill/gap heal, Gold compaction/materialization, retention pruning, forecast reconciliation).
- **FR-ORC-03:** Support CLI/API recovery actions: REST backfill, broker replay, consumer restart, and historical Gold/Feature recomputation.

### 1.5 Financial & Risk Intelligence (`FR-ANA`)
- **FR-ANA-01:** Implement incremental rolling calculators (per-symbol state with persisted checkpoints) and independent vectorized batch reference calculators for: Simple Returns, Log Returns, SMA, EMA, RSI (Wilder/SMA), MACD, Bollinger Bands, ATR, VWAP, Rolling Realized Volatility, Historical VaR (95%/99%), CVaR / Expected Shortfall (95%/99%), Maximum Drawdown, Pairwise Correlation, and Covariance Matrix.
- **FR-ANA-02:** Verify mathematical parity between incremental stream updates and batch reference computations within tight floating-point tolerance.
- **FR-ANA-03:** Handle late or corrected closed candles by updating affected state or triggering bounded recomputation.

### 1.6 Machine Learning (`FR-ML`)
- **FR-ML-01:** Generate offline feature datasets and maintain online rolling feature state using strictly chronological zero-lookahead logic.
- **FR-ML-02:** Support CPU-friendly models (`Ridge`, `LogisticRegression`, `HistGradientBoosting`, `NaivePersistenceBaseline`, `RollingMeanBaseline`) with bounded `ML_MAX_TRAIN_ROWS`.
- **FR-ML-03:** Enforce chronological expanding walk-forward cross-validation and naive-baseline gating (`MAE < naive_MAE` by margin and directional threshold) before promotion in Model Registry.
- **FR-ML-04:** Execute ML training strictly offline / background worker (never blocking FastAPI event loop); execute realtime inference only on closed-candle triggers or explicit API requests.
- **FR-ML-05:** Persist immutable forecast records (`ForecastRecord`) and reconcile mature forecasts against actual closed candles.

### 1.7 Application & Presentation (`FR-APP`)
- **FR-APP-01:** Expose typed FastAPI REST endpoints (`/api/v1/*`) covering Market, Streaming, Pipelines, Medallion/Catalog/Lineage, Data Quality, Data Explorer, Financial & Risk Analytics, Forecasts, Models, System Health, and `/metrics`.
- **FR-APP-02:** Expose a WebSocket Gateway (`/api/v1/ws/market`) pushing coalesced, bounded updates (ticker, latest kline, incremental indicators, stream metrics) without per-tick flooding.
- **FR-APP-03:** Provide a cohesive React + TypeScript UI covering: Data Operations Overview, Live Market Monitor, Data Explorer (Catalog & Preview & Export), Data Quality & Lineage, Pipeline Observatory, Financial & Risk Analytics, Prediction Studio, Forecast History, Model Lab, and System Health.
- **FR-APP-04:** Never coerce missing/unavailable/stale values to `$0.00` or `0.0%`; render explicit loading, empty, stale, backpressure, and error states with retry actions.

---

## 2. Non-Functional, Resource & Operational Requirements

- **NFR-RES-01 (RAM Ceiling):** `LITE` profile total platform RAM <= 450 MB; `STANDARD` native <= 950 MB.
- **NFR-RES-02 (Bounded Buffers):** Every async queue and micro-batch buffer enforces explicit `maxsize` / `max_bytes` / `max_age`.
- **NFR-RES-03 (Storage Efficiency):** Parquet Snappy/Zstd compression for Silver/Gold; Zstd JSONL for Bronze; automated retention pruning protecting `C:` free disk space.
- **NFR-PERF-01 (No Event-Loop Blocking):** CPU-intensive Pandas/DuckDB/Scikit-learn work offloaded via `asyncio.to_thread` or dedicated worker process.
- **NFR-REL-01 (Idempotency & Recovery):** Replaying identical JetStream sequences or re-running REST backfills yields zero duplicate records.
- **NFR-SEC-01 (Input & Error Hygiene):** Strict allowlist validation on symbol/timeframe/dataset/limits; zero raw stack traces, filesystem paths, or secrets returned to HTTP/WS clients; security headers enabled.
- **NFR-OBS-01 (Observability):** Structured JSON/key-value logging, Prometheus `/metrics`, `psutil` process CPU/RAM/disk telemetry, NATS stream/consumer lag, freshness timestamps, and DQ pass rates.
- **NFR-DEP-01 (Reproducible Startup):** Clean single-command native scripts for `LITE`/`STANDARD` + `docker-compose.yml` with `lite`, `standard`, `extended` profiles and Alembic schema migrations.

