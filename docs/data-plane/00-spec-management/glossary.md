# Data Plane Technical Glossary

**Document ID:** `DOC-DP-00-GLOSSARY`  
**Version:** `1.0.0`  
**Status:** `APPROVED_PHASE_1_BASELINE`

---

| Term | Authoritative Definition |
|---|---|
| **Active Snapshot** | The single `lake_snapshots` (`status='ACTIVE'`) or `warehouse_snapshots` (`status='ACTIVE'`) version pointer atomically committed in SQL after all underlying Parquet or `.duckdb` files are written and verified. |
| **At-Least-Once Delivery** | Guarantee that NATS JetStream redelivers any unacknowledged message until explicitly `ACK`ed or `TERM`ed, paired with idempotent consumer persistence so zero committed data is lost or duplicated. |
| **Batch Ledger (`batch_ledger`)** | Operational SQL table recording each micro-batch, backfill, compaction, or warehouse build (`batch_id`, `idempotency_key`, state transitions, NATS sequence range, and linked `snapshot_id`). |
| **Bronze Layer** | Append-only, immutable raw event archive stored as `zstd`-compressed JSONL (`*.jsonl.zst`) partitioned by `source/stream/dt/symbol` with a unified envelope across WS and REST sources. |
| **Closed-Candle Promotion** | Idempotent upsert rule allowing an unclosed forming candle (`is_closed=False`) to be updated by newer forming snapshots or finalized (`is_closed=True`), while prohibiting closed bars from ever being overwritten by stale/forming ticks. |
| **Data Lake (`data/bronze`, `data/silver`, `data/gold`)** | Immutable Parquet and compressed JSONL object store governed by SQL Snapshot Manifests behind `StorageBackend` (`LocalStorageBackend` or `S3StorageBackend`). |
| **Data Warehouse (`data/warehouse/`)** | Persistent DuckDB database built as a Star Schema (`dim_*`, `fact_*`, `mart_*`) by a single serialized writer (`WarehouseService`) and served to concurrent readers via immutable versioned snapshots (`snapshots/dw-v{N}.duckdb`). |
| **Dead-Letter Queue (`MARKET_DLQ` / `dead_letter_events`)** | Quarantine destination for permanently malformed events or batches exceeding `nats_max_deliver`; `msg.term()` is permitted **only** after durable persistence to at least one DLQ sink succeeds. |
| **Epistemic Status Tag** | Mandatory qualifier (`OBSERVED`, `MEASURED`, `INFERRED`, `PROPOSED`, `UNVERIFIED`) preventing confusion between AS-IS code reality and TO-BE targets. |
| **Gold Layer** | Materialized analytical marts (`analytics_marts`) and zero-lookahead ML feature vectors (`feature_sets`) partitioned by actual `open_time` UTC date `dt=YYYY-MM-DD` with explicit PyArrow schemas. |
| **Hot State (`hot_state` KV)** | Ephemeral, bounded in-memory NATS JetStream KeyValue bucket (`StorageType.MEMORY`, TTL 300s) storing latest per-symbol live prices, incremental indicators, and latest forecasts for cross-process serving. |
| **Lease / Heartbeat / Reaper** | Cooperative SQL locking protocol for `WorkflowEngine` (`workflow_runs`): a worker atomically claims a job with `lease_owner` + `lease_expires_at`, renews `heartbeat_at` while running, and a reaper reclaims expired leases after crashes. |
| **Micro-Batch State Machine** | Ordered commit lifecycle inside `MedallionStreamConsumer`: `RECEIVED -> VALIDATED -> PREPARED -> FILES_WRITTEN -> SQL_COMMITTED -> ACKED` (or `NAK_RETRY` / `QUARANTINED_DLQ`). |
| **Open-Bar / Closed-Bar** | Candle state flag `is_closed`: `False` while Binance exchange candle window is still forming (`now < close_time`), `True` once finalized. |
| **ServingGatewayBridge** | Canonical cross-process bridge (`COMP-DP-08`) connecting `StreamWorker` / `WorkflowWorker` to FastAPI over NATS Core (`serving.market.*`, `serving.control.*`, `serving.events.closed_bar`) and NATS KV (`hot_state`, `worker_heartbeats`). |
| **Silver Layer** | Validated, deduplicated, OHLC-checked canonical candles and aggregate trades stored as immutable Parquet files referenced by active manifests, synchronized with operational SQL `klines`. |
| **Snapshot Manifest** | SQL-backed inventory (`lake_snapshots` + `lake_manifest_files`) listing the exact active immutable Parquet files, row counts, byte sizes, SHA-256 checksums, and timestamp bounds for a dataset version. |
| **Watermarks (Event / Ingestion / Processing)** | `event_time` = exchange UTC timestamp; `ingestion_time` = connector receipt UTC timestamp; `processing_time` = consumer persistence UTC timestamp; `start/end_watermark` = delta time range processed by a workflow run. |
| **Workflow Engine (`WorkflowEngine`)** | SQL-backed durable DAG scheduler and job runner (`workers/workflow_worker.py`), strictly separate from NATS JetStream event streaming, replacing volatile `FastAPI.BackgroundTasks`. |
