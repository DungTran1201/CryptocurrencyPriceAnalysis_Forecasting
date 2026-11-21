# Data Plane System Architecture Specification (`TO-BE`)

**Document ID:** `DOC-DP-20-ARCH`  
**Version:** `1.0.0`  
**Status:** `APPROVED_PHASE_1_BASELINE`  
**Binding ADRs:** `ADR-DP-001` through `ADR-DP-007`

---

## 1. Architectural Context & Hardware Envelope (`MEASURED` #6, #14, #15, #16)

- **Target Host Baseline (`MEASURED` #6):** Windows 10 Enterprise (`10.0.19045`), Intel Core i5-10600KF (6 cores / 12 threads, 4.10 GHz), `31.89 GB` physical RAM with **`2.64 GB` available under active desktop workloads**, `78.19 GB` free on `C:\` SSD. **Docker, WSL2, Redis, and PostgreSQL are absent on host.**
- **Existing Broker Footprint (`MEASURED` #6, #16):** `.bin/nats-server.exe v2.15.3` runs natively at `~40–63 MB` WS, with NATS Core pub/sub roundtrip `0.243 ms` avg and JetStream `StorageType.MEMORY` KV `0.231 ms` put / `0.362 ms` get.
- **Analytical Latency Context (`MEASURED` #14, #15):** Cold ephemeral `:memory:` DuckDB scans over 101 Silver Parquet files cost `70.5–117.5 ms` (`#14`), whereas pre-built DuckDB snapshot `dw-v{N}.duckdb` opens in `~52 ms` and queries `GROUP BY` in `12.01 ms` (`#15`) while eliminating multi-process RW/RO lock collisions (`1.43 ms` atomic snapshot publish).
- **Design Mandate (`ADR-DP-001`):** Deliver strict loose coupling, zero silent data loss, and cross-process behavioral parity within `<= 450 MB` (`LITE`) / `<= 950 MB` (`STANDARD`) total platform RSS without introducing Docker/Redis/Temporal.

---

## 2. Three-Plane Logical Architecture & Component Boundaries (`COMP-DP-01..13`)

```
+---------------------------------------------------------------------------------------------------+
| APPLICATION PLANE (Stateless API & Real-Time UI Gateway — FastAPI + React/Vite)                  |
|  - COMP-DP-11 API Gateway: Read-only REST, auth/sanitized mutations, Prometheus /metrics          |
|  - COMP-DP-08 ServingGatewayBridge (Subscriber + WSBroadcastHub) -> /api/v1/ws/market             |
+-------------------------------+----------------------------------------+--------------------------+
                                | NATS Core (serving.*) + NATS KV        | RO Snapshot / SQL Reads
                                | & Workflow SQL Queue                   |
+-------------------------------v----------------------------------------v--------------------------+
| DATA & ORCHESTRATION PLANE                                                                        |
|  [Streaming Path]                                  [Durable Batch / Workflow Path]                |
|  - COMP-DP-01 Ingestor (WS + single-flight heal)   - COMP-DP-09 WorkflowEngine (SQL lease/DAG)    |
|  - COMP-DP-02 BrokerAdapter (NATS JetStream)       - COMP-DP-10 Governance/DQ/Retention           |
|  - COMP-DP-03 StreamProcessor (6-stage post-ACK)   - COMP-DP-06 WarehouseService (Single writer)  |
|  - COMP-DP-13 IncrementalAnalytics (atomic ckpt)                                                  |
|  - COMP-DP-07 HotStateCache (NATS KV + TTLCache)                                                  |
+------------------------------------------------+--------------------------------------------------+
                                                 | Atomic Commits & Immutable Objects
+------------------------------------------------v--------------------------------------------------+
| PERSISTENCE & METADATA PLANE (Single-Node Lakehouse + Warehouse + Operational SQL)                |
|  - COMP-DP-04 LakeStorage + Manifests: Bronze zstd JSONL, Silver Parquet, Gold Parquet + Manifest |
|  - COMP-DP-06 DuckDB Warehouse: dw_staging.duckdb (RW writer) -> snapshots/dw-v{N}.duckdb (RO Pool) |
|  - COMP-DP-05 OperationalDB: SQLite WAL (LITE) / PostgreSQL (STANDARD/EXTENDED optional)          |
+---------------------------------------------------------------------------------------------------+
```

### Component Responsibilities & Strict Ownership

| Component ID | Name | Primary Responsibility | Strict Boundary Invariant |
|---|---|---|---|
| `COMP-DP-01` | **Ingestor** | Connects to Binance WS (`aggTrade`, `kline_1m`) + single-flight REST backfill (`/klines`, `/aggTrades`); normalizes `IFC-DP-001` v1.1; buffers in bounded queue; spills to disk on shutdown timeout; offloads malformed frames to async DLQ. | Never writes directly to Silver/Gold/Warehouse or `WSBroadcastHub`. |
| `COMP-DP-02` | **BrokerAdapter** | Manages `NatsJetStreamBroker` (`MARKET_EVENTS`, `MARKET_DLQ`) and test `InMemoryBroker`; `_connect_lock` + monotonic `_conn_epoch`; profile-bounded storage caps. | Never silently discards un-acked data via bad fallback sizing (`EXTENDED` ladder fixed). |
| `COMP-DP-03` | **StreamProcessor** | Durable pull consumer (`MedallionStreamConsumer`) executing `RECEIVED->VALIDATED->PREPARED->FILES_WRITTEN->SQL_COMMITTED->ACKED` under `_flush_lock`; two-phase `BoundedDedupCache`; post-commit `serving.*` & closed-bar emit. | Never inserts into `_dedup` or triggers inference prior to `SQL_COMMITTED`; never `TERM`s without durable DLQ persistence. |
| `COMP-DP-04` | **LakeStorage + Manifests** | `StorageBackend` (`LocalStorageBackend` / `S3StorageBackend`) + `MedallionStorageManager`: immutable Bronze `zstd` JSONL, immutable Silver/Gold Parquet (`dt=` real partitioning, `taker_buy_*`), `lake_snapshots`, `lake_manifest_files`, `batch_ledger`. | Never mutates existing Parquet files in place; never silently ignores unreadable fragments during merge/compaction. |
| `COMP-DP-05` | **OperationalDB** | SQLAlchemy 2.0 + Alembic schema (`14` existing + `6` new tables); SQLite WAL (`LITE`) / PostgreSQL (`STANDARD`/`EXTENDED`); `ON CONFLICT` candle promotion (`open->closed`); read-only `get_db()` without auto-commit on `GET`. | Single source of transactional state for manifests, checkpoints, workflows, forecasts, and model registry. |
| `COMP-DP-06` | **WarehouseService** | Persistent DuckDB Star Schema (`dim_symbol`, `dim_timeframe`, `dim_date`, `fact_kline_bar`, `fact_risk_daily`, `warehouse_checkpoints`, `mart_*`) built by serialized writer lease -> `CHECKPOINT` -> `close()` -> `dw-v{N}.duckdb` snapshot swap. | Only `WorkflowEngine` writes `data/warehouse/staging/dw_staging.duckdb`; API readers open only published `dw-v{N}.duckdb` with `read_only=True`. |
| `COMP-DP-07` | **HotStateCache** | `HotStateCache` protocol (`IFC-DP-009`) using NATS JetStream KV (`StorageType.MEMORY` `hot_state` & `worker_heartbeats` buckets) + bounded in-process `TTLCache` invalidated by `serving.events.closed_bar`. | Degrades gracefully to SQL/Lake reads if broker KV is unreachable; zero Redis dependency on single-node host. |
| `COMP-DP-08` | **ServingGatewayBridge** | Canonical cross-process bridge over NATS Core (`serving.market.<SYMBOL>`, `serving.events.closed_bar`, `serving.control.*`) + KV (`hot_state`, `worker_heartbeats`) driving `WSBroadcastHub` and control commands identically in `LITE` & `STANDARD`. | In `embedded_in_api=False`, API runs bridge subscriber only (no ingestor/consumer/retention loop). |
| `COMP-DP-09` | **WorkflowEngine** | SQL-backed durable DAG queue (`workflow_runs`, `workflow_tasks`, `workflow_schedules`) in `workers/workflow_worker.py` with active-run mutex, lease/heartbeat, stale-lease reaper, step-level resume, and optional NATS `workflow.wakeup` nudge. | Strictly separate from NATS JetStream; eliminates `FastAPI.BackgroundTasks` and un-leased `sync_worker.py`. |
| `COMP-DP-10` | **Governance / DQ / Retention** | 10-rule SQL + `agg_trade_id` continuity + Parquet parity DQ (`commit=False` option inside flush); manifest-backed catalog (zero `GET` writes); `dt=` + manifest-aware retention with grace-TTL GC. | Never runs DB writes on `GET` endpoints; never uses `st_mtime` or `local_path` as retention truth. |
| `COMP-DP-11` | **API Gateway** | FastAPI REST + `/api/v1/ws/market` + `/metrics`; Pydantic response contracts (`MarketDataResponseSchema` preserved); `require_admin_if_configured` on all mutation routes; sanitized error envelopes. | Zero inline ML training, historical REST sync, or blocking `rglob` on the HTTP event loop. |
| `COMP-DP-12` | **Observability** | Per-process Prometheus metrics (`IFC-DP-010`) aggregated via KV heartbeats/worker metrics; active lag & staleness computation; disk/RAM gauges; structured JSON logging preserving `extra`. | Never freezes freshness/lag gauges silently when stream stalls; never blocks event loop on disk traversal. |
| `COMP-DP-13` | **IncrementalAnalytics** | $O(1)$/rolling per-symbol state (`EMA`, `RSI`, `MACD`, `BB`, `ATR`, `VWAP`, `Vol`, `VaR`, `CVaR`, `MDD`) with atomic `tmp + fsync + os.replace` checkpoints persisting `last_stream_seq` and trade accumulators. | Mathematical parity with batch reference calculations preserved (`tests/test_financial_correctness.py`). |

---

## 3. Process Topology & Resource Allocation (`ADR-DP-001`)

| Dimension | Profile `LITE` (Default Local) | Profile `STANDARD` (Native Multi-Process) | Profile `EXTENDED` (Optional Scale / S3) |
|---|---|---|---|
| **OS Processes (Python + Broker)** | `1` Uvicorn process (`embedded_in_api=True`, running Ingestor, Consumer, Bridge, API, and embedded async `WorkflowWorker` loop) + `1` `nats-server.exe` | `3` Python processes (`api`, `stream_worker`, `workflow_worker`) + `1` `nats-server.exe` *(Docker Compose optional)* | `3` Python processes + NATS + optional Postgres / MinIO / Prometheus / Grafana |
| **Communication Contract** | Same `ServingGatewayBridge` + `HotStateCache` + SQL `WorkflowEngine` over localhost NATS loopback | Identical NATS Core/KV + SQL `WorkflowEngine` across OS processes | Identical contracts (`S3StorageBackend` + Postgres) |
| **Total RAM Ceiling** | `<= 450 MB` RSS (`TARGET_TO_BE_ESTABLISHED` breakdown per proc) | `<= 950 MB` RSS native (`TARGET_TO_BE_ESTABLISHED`) | `<= 2048 MB` *(requires freeing host RAM)* |
| **NATS JetStream Caps** | `max_memory: 64MB`, `max_file: 128MB` (`MARKET_EVENTS` 70%, `MARKET_DLQ` 20%, 10% headroom); `hot_state` 8MB + `worker_heartbeats` 1MB in MEMORY | `max_memory: 128MB`, `max_file: 512MB`; `hot_state` 16MB + `worker_heartbeats` 2MB in MEMORY | `max_memory: 256MB`, `max_file: 1024MB`; `hot_state` 32MB + `worker_heartbeats` 4MB in MEMORY |
| **DuckDB Limits** | `memory_limit='128MB'`, `threads=2` | `memory_limit='256MB'`, `threads=4` | `memory_limit='512MB'`, `threads=4` |
| **Operational DB** | SQLite WAL (`./data/crypto_market.db`) | SQLite WAL (native host) or PostgreSQL 16 (when provisioned) | PostgreSQL 16 (when provisioned) |
| **Host Readiness (`#6`)** | **Verified Host Ready** | **Verified Host Ready (Native)**; Postgres/Docker `UNVERIFIED` | `UNVERIFIED` (Docker/MinIO absent on host) |
