# Final Resource Usage Report (`LITE` Profile Live & `STANDARD` Code Benchmarks)

**Constraint Baseline:** Windows 10 workstation with **8,035.1 MB** total RAM (~1,418–1,507 MB available physical RAM during active development) and **16.21–17.09 GB** free space on `C:`.

---

## 1. Live Memory & CPU Consumption vs Budget (`LITE` Profile)

Telemetry captured via `GET /api/v1/system/resources` and Windows `Get-Process` while NATS JetStream (`task-349`) and FastAPI + embedded Binance WebSocket streaming (`task-350`) ran live:

| Process / Component | Budgeted Cap (`LITE`) | Measured Idle / Steady RSS | Measured Burst / Peak RSS | Status |
|---|---:|---:|---:|---|
| **FastAPI + Uvicorn Worker (`python.exe` PID `800` + `uvicorn.exe` PID `14356`)** | `<= 380 MB` *(portion of 450 MB)* | `267.98–269.51 MB` (`59.9%` of total 450 MB API budget telemetry) | `289.43 MB` (`286.0` worker + `3.43` supervisor under active streaming + pipelines) | **PASS** |
| **NATS JetStream Broker (`nats-server.exe` PID `3284`)** | `<= 64 MB` mem store (`<= 128 MB` file store) | `22.6 MB` *(fresh start)* | `51.8 MB` RSS *(after `> 2,167` persisted JetStream events)* | **PASS** |
| **Total Live Platform Processes** | **`<= 450 MB` total RSS** | **`~292.1 MB`** (`64.9%` of budget) | **`341.23 MB`** (`75.8%` of budget) | **PASS** |
| **FastAPI Worker CPU %** | Single-node safe ceiling | `4.1%` *(steady live WS stream)* | `26.0%` *(during backfill / ML training burst)* | **PASS** |
| **DuckDB Analytical Engine** | `128MB` hard limit / `2` threads (`LITE`) | Embedded lazily per query | Enforced via `SET memory_limit='128MB'` | **PASS** |
| **Producer Queue Occupancy** | `1000` max events (`80%` high watermark) | `0.0%` (`queue_depth: 0`) | Transient burst with bounded await (no drops) | **PASS** |
| **Host Available Physical RAM** | Must avoid host OOM/thrashing | `1,507.2 MB` free (`81.2%` host used) | `1,485.1 MB` free during load | **PASS** |

---

## 2. Live On-Disk Storage Footprint by Layer

Measured across `data/` after real-time Binance `aggTrade` + `kline_1m` ingestion (`> 2,168` streaming events), two `720`-bar `1h` + `1,440`-bar `1m` historical syncs, Silver/Gold materialization, and model training:

| Storage Layer | Format & Location | File Count | Measured Disk Size | Configured Cap (`LITE`) | Utilization |
|---|---|---:|---:|---:|---|
| **Bronze Raw Events** | `zstd` compressed JSONL (`data/bronze/**/*.jsonl.zst`) | `302` files *(290s-period live stream batches + REST)* | `0.605 MB` | `256 MB` / `3 days` | `0.24%` |
| **Silver Validated Parquet** | Columnar Parquet (`data/silver/**/*.parquet`) | `72` files | `0.900 MB` | `256 MB` / `14 days` | `0.35%` |
| **Gold Analytical & Feature Marts** | DuckDB-backed Parquet (`data/gold/**/*.parquet`) | `4` files | `0.513 MB` | `256 MB` / `30 days` | `0.20%` |
| **NATS JetStream Store** | JetStream file store (`data/nats/`) | `13` files | `5.084 MB` | `128 MB` | `3.97%` |
| **SQLite WAL Operational DB** | SQLite WAL (`data/crypto_market.db`) | `1` db (`+WAL/SHM`) | `1.793 MB` | Local disk bounded | Minimal |
| **Total Active Data Footprint** | **All persisted data + broker stores** | **`392` files** | **`8.895 MB`** | **`896+ MB`** | **`< 1%`** |

---

## 3. Adaptive Profile Validation Scope

- **`LITE` Profile**: Executed **both** synthetic benchmarks (`rss_end_mb = 226.69 MB`) and full live end-to-end streaming + REST + ML execution (`341.23 MB` combined NATS + API peak RSS).
- **`STANDARD` Profile**: Executed synthetic process benchmarks (`rss_start_mb = 225.84 MB`, `rss_end_mb = 233.07 MB` vs `950 MB` native cap). Docker container Compose runtime (`postgres:16-alpine` + `nats`) passed configuration validation (`docker compose config --quiet`), but container execution was **NOT RUN** live due to stopped Docker Desktop and low free host RAM (`~1.4–1.5 GB`).
- **`EXTENDED` Profile**: Optional MinIO, Prometheus, and Grafana services are configured in `docker/docker-compose.yml` (`--profile extended` syntax validated), and in-app `/metrics` Prometheus exposition was verified (`146+` metric lines). Containerized MinIO/Prometheus/Grafana instances were **NOT RUN** live.

