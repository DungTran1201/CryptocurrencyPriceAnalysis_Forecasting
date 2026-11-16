# Single-Node Resource Budget & Execution Profiles

**Target Host Baseline:** Intel i5-12400F (6C/12T), 8,035 MB Total RAM (~1,418 MB free physical RAM during dev), 17.09 GB free disk on `C:`.  
**Core Mandate:** Complete Data Platform architecture within strict, measured single-node resource ceilings. Never allocate unbounded memory or silently drop events.

---

## 1. Execution Profiles Overview

| Dimension | Profile A — `LITE` (Default Local) | Profile B — `STANDARD` | Profile C — `EXTENDED` |
|---|---|---|---|
| **Purpose** | Constrained dev/demo on 8 GB host | Full persistent single-node platform | Benchmarks, S3/MinIO, Prometheus + Grafana |
| **Tracked Symbols** | `BTCUSDT`, `ETHUSDT` (max 4 configurable) | `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT` | 4+ configurable symbols |
| **Active Streams** | `aggTrade`, `kline_1m` | `aggTrade`, `kline_1m` | `aggTrade`, `kline_1m` + extended backfill |
| **Message Broker** | Native `nats-server.exe` JetStream (file store capped at 128 MB) | Native or Docker NATS JetStream (file store capped at 512 MB) | Docker NATS JetStream (file store capped at 1 GB) |
| **Operational Metadata DB** | SQLite WAL (`./data/crypto_market.db`) | PostgreSQL 16 Alpine (Docker) or SQLite WAL | PostgreSQL 16 Alpine (Docker) |
| **Analytical / Medallion Store** | Local FS (`data/bronze`, `data/silver`, `data/gold`) + DuckDB | Local FS Parquet + DuckDB | Optional MinIO (S3-compatible) + DuckDB |
| **Monitoring Stack** | In-app `/metrics` + `/api/v1/system/health` + psutil | In-app `/metrics` + structured JSON logs | Optional Prometheus + Grafana containers |
| **Target Total App RAM Budget** | **<= 450 MB** RSS (all platform processes) | **<= 950 MB** RSS (native) / **<= 1.4 GB** (containers) | **<= 2.2 GB** RSS (requires idle host apps closed) |

**Invariant:** Changing profile (`PLATFORM_PROFILE=lite|standard|extended`) adjusts capacity bounds, concurrency, and optional external extensions ONLY. It **never** alters financial formulas, indicator math, data quality rules, or walk-forward ML validation logic.

---

## 2. Configurable Resource Limits Matrix

| Resource Parameter | Config Key | `LITE` | `STANDARD` | `EXTENDED` |
|---|---|---|---|---|
| **Process Count (Python)** | `RESOURCE_MAX_PYTHON_PROCS` | `2` (API+Gateway+Consumer, Ingestor/Worker or embedded tasks) | `3` (API, Ingestor, Stream Consumer/Scheduler) | `3–4` |
| **Total App Memory Soft Limit (MB)** | `RESOURCE_TOTAL_MEMORY_MB` | `450` | `950` | `2048` |
| **NATS JetStream Max Memory (MB)** | `NATS_MAX_MEM_MB` | `64` | `128` | `256` |
| **NATS JetStream Max File Store (MB)** | `NATS_MAX_FILE_MB` | `128` | `512` | `1024` |
| **DuckDB Memory Limit** | `DUCKDB_MEMORY_LIMIT` | `128MB` | `256MB` | `512MB` |
| **DuckDB Threads** | `DUCKDB_THREADS` | `2` | `4` | `4` |
| **PostgreSQL Shared Buffers / Cap** | `POSTGRES_MEM_LIMIT_MB` | N/A (SQLite) | `256` | `384` |
| **Worker Async Concurrency** | `WORKER_CONCURRENCY` | `2` | `4` | `6` |
| **Bounded In-Memory Event Queue** | `STREAM_QUEUE_MAXSIZE` | `1000` events | `5000` events | `10000` events |
| **Consumer Pull Batch Size** | `CONSUMER_BATCH_SIZE` | `50` | `200` | `500` |
| **Bronze Micro-Batch Max Records** | `BRONZE_FLUSH_MAX_RECORDS` | `250` | `1000` | `2000` |
| **Bronze/Silver Flush Max Age (sec)** | `MICROBATCH_FLUSH_MAX_AGE_SEC` | `5.0` | `5.0` | `10.0` |
| **Bronze Buffer Memory Cap (MB)** | `BRONZE_BUFFER_MAX_MB` | `16` | `32` | `64` |
| **DB Pool Size / Max Overflow** | `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `5` / `5` (NullPool/WAL for SQLite) | `5` / `10` | `10` / `15` |
| **Online Rolling State Window** | `ONLINE_WINDOW_MAX_BARS` | `300` bars/symbol | `500` bars/symbol | `1000` bars/symbol |
| **ML Max Training Rows** | `ML_MAX_TRAIN_ROWS` | `2000` | `5000` | `20000` |
| **ML Inference Trigger Mode** | `ML_INFERENCE_TRIGGER` | `closed_candle_or_api` | `closed_candle_or_api` | `closed_candle_or_api` |
| **Bronze Disk Retention (Days / MB)** | `RETENTION_BRONZE_DAYS` / `MAX_MB` | `3` days / `256 MB` | `7` days / `1024 MB` | `30` days / `4096 MB` |
| **Silver Disk Retention (Days / MB)** | `RETENTION_SILVER_DAYS` / `MAX_MB` | `14` days / `256 MB` | `30` days / `1024 MB` | `90` days / `4096 MB` |
| **Gold Disk Retention (Days / MB)** | `RETENTION_GOLD_DAYS` / `MAX_MB` | `30` days / `256 MB` | `90` days / `1024 MB` | `180` days / `4096 MB` |
| **Frontend WS Push Interval (ms)** | `WS_COALESCE_INTERVAL_MS` | `500` | `250` | `250` |
| **Frontend Client Ring Buffer** | `UI_STREAM_BUFFER_MAX` | `200` points | `300` points | `500` points |

---

## 3. Bounded Queues, Backpressure & Flow-Control Policy

No unbounded queues (`asyncio.Queue(maxsize=0)` or unlimited lists) are permitted anywhere in ingestion, stream consumers, micro-batchers, or WebSocket broadcasting.

1. **Producer-to-Broker Path:**
   - Normalized events enter a bounded `asyncio.Queue(maxsize=STREAM_QUEUE_MAXSIZE)`.
   - When occupancy reaches **80% high watermark**, a backpressure metric (`backpressure_events_total`) increments, structured warning is logged, and the WebSocket reader pauses/throttles frame reads (`await queue.put(...)` awaits downstream drain rather than dropping events!).
   - If the broker (`NATS JetStream`) is temporarily unreachable, events remain in a bounded local spill-buffer / retry loop with exponential backoff; if disk spill limit is exceeded, ingestion pauses cleanly and surfaces `DEGRADED/BACKPRESSURE` in `/api/v1/system/health` rather than silently discarding events.
2. **Broker-to-Consumer Path:**
   - NATS JetStream durable pull consumers fetch bounded batches (`batch=CONSUMER_BATCH_SIZE`) with explicit `AckWait` and `MaxAckPending`.
   - Consumers only send `msg.ack()` **after** Bronze/Silver/Gold/SQL metadata writes commit or after routing unrecoverable malformed payloads to the Dead-Letter Subject (`market.dlq.*`) and persisting a DLQ record.
   - Failed transient writes execute `msg.nak(delay=...)` up to `max_deliver`, then route to DLQ — zero silent loss.
3. **Micro-Batch Persistence Policy:**
   - Flush triggers when **any** threshold hits first: `len(buffer) >= BRONZE_FLUSH_MAX_RECORDS`, `age >= MICROBATCH_FLUSH_MAX_AGE_SEC`, or `buffer_bytes >= BRONZE_BUFFER_MAX_MB * 1024 * 1024` (or graceful shutdown).
   - Prevents per-tick database transactions and prevents thousands of tiny Parquet files; background compaction merges small partitions into daily compacted Parquet files.
4. **API & Frontend Backpressure:**
   - FastAPI REST routes enforce `limit <= 1000` (klines) and `limit <= 5000` (CSV export) and query Parquet/DuckDB lazily with predicate pushdown.
   - WebSocket gateway coalesces latest ticker/candle/analytics updates per `(symbol, stream)` over `WS_COALESCE_INTERVAL_MS` (default 250–500 ms) into bounded per-client send queues; slow WebSocket clients receive coalesced snapshots instead of growing server RAM.

