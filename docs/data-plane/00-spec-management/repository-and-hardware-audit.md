# Repository and Hardware Audit Baseline

**Document ID:** `DP-SPEC-001`  
**Status:** `APPROVED_PHASE_1_BASELINE`  
**Owner:** `@sre-qa` (`WI-DP-01`)  
**Evidence Epoch:** Commit `95496ac` (`feat/realtime-data-platform`), audited `2026-11-17`

---

## 1. Purpose and Scope

This document establishes the single authoritative, verified hardware, host-toolchain, runtime-footprint, test-suite, and AS-IS component baseline for `CryptocurrencyPriceAnalysis_Forecasting`. Every claim is tagged with its evidence level:

- **`MEASURED`**: Directly executed and recorded via tool output on this workstation during Phase 1 Step 1 / Step 1B.
- **`OBSERVED`**: Directly read from repository source files, configuration, or `data/` artifacts.
- **`INFERRED`**: Derived from observed code/config without live execution (e.g., PostgreSQL container behavior).
- **`UNVERIFIED`**: Could not be empirically proven on this host (e.g., WSL2 distro availability, real disk-full behavior).

---

## 2. Authoritative Host Hardware Baseline

All host measurements were captured via PowerShell CIM/WMI (`Win32_OperatingSystem`, `Win32_Processor`, `Win32_LogicalDisk`, `Win32_DiskDrive`, `Get-Volume`) and `.venv\Scripts\python.exe` (`psutil 7.2.2`, `platform`) on `2026-11-17`.

| Subsystem | Value (`MEASURED`) | Operational Constraint & Design Implication |
|---|---|---|
| **Operating System** | Microsoft Windows 10 Enterprise, Version `10.0.19045`, Build `19045`, 64-bit (`Windows-10-10.0.19045-SP0`) | Windows file-locking semantics (`WinError 32`) strictly apply to DuckDB (`ADR-DP-004`) and SQLite WAL; POSIX `loop.add_signal_handler` raises `NotImplementedError` (`stream_worker.py:24-27`). |
| **CPU** | `Intel(R) Core(TM) i5-10600KF CPU @ 4.10GHz`, 6 physical cores, 12 logical processors, MaxClockSpeed `4104 MHz` | Ample CPU concurrency for bounded `DuckDB` threads (`2–4`) and CPU-only `scikit-learn`; avoid multi-process contention under memory load. |
| **Physical RAM** | Total `33,443,456 KB` (`31.89 GB` via `psutil`); Available `2.64 GB` (`91.7%` used; `FreePhysicalMemory = 3,283,872 KB`) | **Primary runtime constraint:** External workstation processes (`DeltaForceClient-Win64-Shipping` PID `6320` = `9,871.3 MB` WS, `chrome` top 2 = `1,726.1 MB`, `Antigravity IDE` top 3 = `1,091.1 MB`, `agy` = `358.9 MB`) leave only **~2.64 GB** physical RAM free. Swap: `16.0 GB` total, `1.39 GB` used. |
| **Workspace Drive (`C:\`)** | `System`, `NTFS`, Fixed, Healthy: `118.52 GB` total, **`78.19 GB` free** (`psutil` / `Get-Volume`; `78.22 GB` via `Win32_LogicalDisk`) | Sufficient space for bounded Lake/Warehouse snapshots and NATS JetStream, but requires manifest-driven retention and disk-pressure monitoring (`REQ-DP-OBS-02`). |
| **Physical Disk** | `\\.\PHYSICALDRIVE0`, `vDiskBus Disk` (`Generic Physical Disk`), `MediaType = SSD`, `BusType = ATA`, `119.01 GB`, `Healthy` | Fast atomic `tmp + fsync + os.replace` writes (`0.55 ms` p50). |
| **Other Logical Volumes** | `A:` (`19.98 GB` / `17.49 GB` free), `B:` (`19.98 GB` / `19.88 GB` free), `E:` (`1863.02 GB` / `595.32 GB` free), `G:` (`1863.02 GB` / `541.13 GB` free) | Backing hardware `UNVERIFIED` (`Get-PhysicalDisk`/`Win32_DiskDrive` enumerated only `PHYSICALDRIVE0`); workspace and `./data/` reside on `C:`. |

---

## 3. Host Toolchain, Git State, and Running Services

### 3.1 Python Virtual Environment & Package Drift (`MEASURED` / `OBSERVED`)
- **Executable:** `C:\Users\Administrator\Projects\CryptocurrencyPriceAnalysis_Forecasting\.venv\Scripts\python.exe`
- **Version:** `Python 3.14.10`
- **Key Installed Packages (`pip list`):** `fastapi 0.163.1`, `uvicorn 0.54.0`, `pydantic 2.14.3`, `pydantic-settings 2.16.3`, `SQLAlchemy 2.1.9`, `alembic 1.20.1`, `aiosqlite 0.22.1`, `asyncpg 0.32.0`, `duckdb 2.0.0`, `nats-py 2.16.0`, `websockets 17.4`, `httpx 0.28.1`, `pandas 3.1.1`, `numpy 2.5.5`, `pyarrow 26.0.1`, `scikit-learn 1.9.1`, `scipy 1.18.1`, `zstandard 0.25.0`, `orjson 3.13.0`, `psutil 7.2.2`, `prometheus_client 0.26.0`, `opentelemetry-api 1.45.2`, `pytest 9.2.0`, `pytest-asyncio 1.5.0`.
- **CI & Dependency Drift (`OBSERVED`):**
  - `requirements.txt:1-27` specifies unpinned `>=` lower bounds with no lockfile, causing local Python `3.14.10` package versions (`FastAPI 0.163.1`, `DuckDB 2.0.0`, `PyArrow 26.0.1`, `SQLAlchemy 2.1.9`, `Pandas 3.1.1`) to drift above CI (`python-version: '3.12'` in `.github/workflows/ci.yml:20`).
  - `requirements.txt` includes `asyncpg>=0.29.0` for async PostgreSQL, but **omits a synchronous PostgreSQL driver** (`psycopg[binary]`), breaking `alembic upgrade head` (`alembic/env.py:19,43`) and `sync_engine` (`backend/app/core/database.py:85`) in `STANDARD`/`EXTENDED` PostgreSQL mode (`INFERRED`).

### 3.2 Host Binaries & External Daemon Availability (`OBSERVED` / `MEASURED`)

| Tool / Daemon | Host Status (`MEASURED`) | Exact Path / Version / Notes |
|---|---|---|
| **Git** | Installed (not on default `PATH`) | `C:\Program Files\Git\cmd\git.exe` (`git version 2.56.1.windows.1`). `.git/HEAD` -> `ref: refs/heads/feat/realtime-data-platform`; HEAD `95496ac`; clean working tree. |
| **NATS Server** | Installed & **Running** | `.bin\nats-server.exe` (`v2.15.3`). PID `12080`, WS `63.25 MB` (`/varz mem=43,229,184 B`), ports `::4222` & `::8222`, cmdline `-js -c data\nats\nats-local.conf -P data\nats\nats.pid`. |
| **Node.js / npm** | Installed (not on default `PATH`) | `C:\Program Files\nodejs\node.exe` (`v26.13.1`), `npm.cmd` (`11.20.0`). `frontend/node_modules` and `frontend/dist` exist. |
| **Docker** | **NOT FOUND** | Absent from `PATH` and `C:\Program Files\Docker\Docker\Docker Desktop.exe`. |
| **Redis** | **NOT FOUND** | `redis-server`, `redis-cli`, and `C:\Program Files\Redis` absent. |
| **PostgreSQL** | **NOT FOUND** | `C:\Program Files\PostgreSQL` absent; no `postgres` process running. |
| **WSL2** | **UNVERIFIED / Unavailable** | `C:\windows\system32\wsl.exe` exists, but `wsl --status` and `wsl --list --verbose` emit legacy usage help only (no configured WSL2 distro). |
| **App Processes** | **Not running** | No `uvicorn`, Python worker, or Node processes active at baseline. |

### 3.3 Live NATS JetStream & On-Disk `data/` Footprint (`MEASURED` / `OBSERVED`)
- **Live JetStream (`/jsz` on `127.0.0.1:8222`):** `max_memory = 64 MB`, `max_storage = 128 MB`, `reserved_storage = 127,506,841 B` (`121.6 MB`, leaving only `6.40 MB` unreserved file space), `streams = 2`:
  - `MARKET_EVENTS`: `5,594` messages (`2,789,065 B`), durable consumer `medallion_lite_consumer` (`num_pending = 0`, `num_ack_pending = 0`).
  - `MARKET_DLQ`: `0` messages (`0 B`).
  - `api.total = 911`, `api.errors = 11`, `connections = 0`, `slow_consumers = 0`.
- **Workspace `./data/` Inventory (`OBSERVED`):**
  - `bronze/`: `352` files, `0.903 MB` (`946,521 B`) — `aggtrade` 170, `kline` 168, `rest_klines_15m` 10, `rest_klines_1m` 4.
  - `silver/`: `115` files, `1.412 MB` (`1,480,819 B`) — `klines/15m` 101 files (`ETHUSDT` 9,600 rows, 1 unclosed bar), `klines/1m` 4 files (`BTCUSDT` 1,446, `ETHUSDT` 1,446), `agg_trades` 10 files (`BTCUSDT` 2,816 rows, `ETHUSDT` 2,381 rows).
  - `gold/`: `2` files, `3.274 MB` (`3,432,670 B`) — `ETHUSDT 15m` `mart.parquet` (`9,600 x 14`) & `features.parquet` (`9,600 x 29`).
  - `checkpoints/`: `2` files, `0.002 MB` (`2,372 B`) — `analytics_BTCUSDT_1m.json`, `analytics_ETHUSDT_1m.json`.
  - `nats/`: `13` files, `2.662 MB` (`2,791,055 B`). `models/`: `0` files.
  - `crypto_market.db`: `4.539 MB` (`4,759,552 B`; `-shm` `0.031 MB`, `-wal` `0.0 MB`), `alembic_version = af2bd5126950`, `klines = 12,492` (`BTCUSDT 1m: 1,446`, `ETHUSDT 1m: 1,446`, `ETHUSDT 15m: 9,600`), `sync_checkpoints = 3`, `stream_checkpoints = 4`, `pipeline_runs = 2 (SUCCESS)`, `data_quality_runs = 16`, `data_lineage_edges = 33`, `forecast_records = 12`, `dead_letter_events = 0`.
  - **Observed Live Divergence on Disk (`data-eng` #9):** For `2026-11-17 05:43:00` (`1m`), SQL `klines` holds `is_closed = 0` (`BTCUSDT` close `64899.48`, `ETHUSDT` close `1836.22`), while Silver Parquet holds promoted `is_closed = True` (`BTCUSDT` close `64891.85`, `ETHUSDT` close `1836.02`) because SQL `save_klines_idempotent` / `_upsert_closed_klines_sql` skip existing `(symbol, timeframe, open_time)` rows.

---

## 4. Documentation vs. Host Drift

Existing documentation contains stale hardware and architecture claims from a previous environment (`docs/10-audit/hardware-capability-report.md:4-28`, `docs/30-architecture/system-architecture.md:4`, `docs/40-adr/ADR-001:5`, `README.md:260-268,340-344`):

| Item | Stale Docs Claim (`OBSERVED`) | Actual Host / Codebase Reality (`MEASURED` / `OBSERVED`) |
|---|---|---|
| **CPU / Host** | `DESKTOP-J7FA4CN`, `i5-12400F` / `i5-11400H` | `i5-10600KF @ 4.10GHz` (6C/12T) |
| **RAM** | `8,035.1 MB` (`1,418 MB` free) or `16 GB` | `31.89 GB` total, **`2.64 GB` available** (`91.7%` used under external load) |
| **Disk (`C:`)** | `17.09 GB` free / `50+ GB` SSD | `78.19 GB` free of `118.52 GB` NTFS SSD |
| **Python / Stack** | Python `3.12.9`, `FastAPI 0.115.8`, `DuckDB 1.2.0`, `PyArrow 19.0.0` | `.venv` Python `3.14.10`, `FastAPI 0.163.1`, `DuckDB 2.0.0`, `PyArrow 26.0.1` |
| **Docker / WSL2** | Docker CLI `28.5.1` + WSL2 distros (`Ubuntu`, `docker-desktop`) | **No Docker**, **no Redis**, **no PostgreSQL**, WSL2 unavailable/`UNVERIFIED` |
| **`ServingGatewayBridge`** | Claimed in `system-architecture.md:214-239` as cross-process NATS consumer `C3` | **Does not exist** in `backend/app/streaming/` (`DOCUMENTATION_ONLY`); API & `StreamWorker` have process split-brain when `embedded_in_api=False`. |

---

## 5. Measured Host Micro-Benchmarks

Executed in isolated `$env:TEMP` probes (`#14`, `#15`, `#16`) without mutating repository files or `./data/`:

| Probe | Exact Result (`MEASURED`) | Architectural Implication |
|---|---|---|
| **Sequential Disk Write (`32 MB` + `fsync`, n=3)** | `361.3`, `348.2`, `346.4 MB/s` | Sequential Lake/Warehouse writes are fast on `C:` SSD. |
| **Sequential Disk Read (`32 MB`, n=3)** | `1,162.9`, `1,176.4`, `1,466.4 MB/s` (OS page cache) | Hot Parquet/DuckDB reads are CPU/parse bound, not raw disk bound. |
| **Atomic Small Write (`4 KB`, `tmp+fsync+os.replace`, n=50)** | p50 **`0.55 ms`**, p95 **`1.79 ms`**, max `38.54 ms` | `LocalStorageBackend.write_bytes` atomic durability overhead is ~1–2 ms per micro-batch. |
| **Cold DuckDB 2.0.0 `:memory:` over 101 Silver Parquet files (`9,600` rows, `1.08 MB`)** | `count_all`: `80.3–117.5 ms`; `last_200`: `90.5–99.8 ms`; `agg_daily`: `70.5–72.4 ms` | Per-request cold `:memory:` Parquet globs incur a ~70–120 ms floor; persistent Warehouse snapshots cut query latency to `~12 ms`. |
| **DuckDB 2.0.0 Windows File Locking (`#15`, `12,500` rows)** | Cross-process RW + RO fails (`IOException`); in-process RW + RO fails (`ConnectionException`); `shutil.copy2` while RW open fails (`WinError 32`) | Single-writer staging + `CHECKPOINT` + `close()` + immutable `dw-v{N}.duckdb` snapshot swap (`1.43 ms` publish; `50.8–53.7 ms` RO open; `12.01 ms` query) is **mandatory** on Windows (`ADR-DP-004`). |
| **NATS JetStream KV & Core (`#16`, `nats-server v2.15.3`, `nats-py 2.16.0`)** | `StorageType.FILE` 8 MB fails (`insufficient storage`); `StorageType.MEMORY` 4 MB succeeds (`put` `0.231 ms` avg / `0.423 ms` p95; `get` `0.362 ms` avg / `0.644 ms` p95; `watch` `1.306 ms`; TTL verified); Core pub/sub `0.243 ms` avg / `0.421 ms` p95 | `hot_state` & `worker_heartbeats` KV buckets **must** use `StorageType.MEMORY` under LITE's `128 MB` file store budget (`ADR-DP-005`). |
| **Binance External Reachability (single probe each)** | REST `/ping` & `/time`: `200 OK` (`71–445 ms`); TCP `:9443` `stream.binance.vision`: `4,355 ms`, `stream.binance.com`: `283 ms` | `live` marker feasible on this host; live WS frame stability remains `UNVERIFIED` (`not streamed`). |

---

## 6. Test Suite & CI Baseline

- **Command Executed (`MEASURED`):** `.venv\Scripts\python.exe -m pytest -v` (shell env vars unset; `.env` present).
- **Result (`MEASURED`):** **`43 passed in 12.86s`** (PowerShell wall time `16.072s`), exit code `0`, `0` failed, `0` skipped; working tree remained clean post-run.
- **CI Audit (`.github/workflows/ci.yml` `OBSERVED`):**
  - Triggers only on `push`/`pull_request` to `main`/`master` (not `feat/*`).
  - `backend-tests` (`ubuntu-latest`, Python `3.12`) runs `alembic upgrade head` against SQLite and `APP_ENV=testing pytest tests/ -v`; **no NATS daemon runs in CI**, causing `test_live_nats_jetstream_publish_consume_nak_replay` (`tests/test_streaming_and_broker.py:181-182`) to skip in CI.
  - `frontend-build` (`Node.js 20`) runs `npm test` (`src/utils/formatters.test.ts` only) and `npm run build` (`tsc && vite build`).
- **Critical Test-Isolation Defect (`REQ-DP-SEC-03` / `TEST-ISO`):**
  - `tests/test_api_and_security.py:68-73` executes `POST /api/v1/governance/retention/run` **without overriding `settings.storage.data_dir`**. Because `GovernanceService.enforce_retention()` (`governance_service.py:458`) deletes files older than `retention_bronze_days = 3`, running pytest >3 days after live ingestion **deletes live workspace `./data/bronze/` files** (escaped during baseline only because `./data/` files were `0.02–0.03` days old).
  - `tests/conftest.py:10` omits `governance` from explicit model imports, and `backend/app/core/database.py:21-24` creates `./data/` at import time.

---

## 7. Reconciled AS-IS Component Status Matrix

| Component ID | Component | AS-IS Status | Key Verified Evidence & Primary Defects (`#6–#9`) |
|---|---|---|---|
| `COMP-DP-01` | **Ingestor** (`binance_ws.py`, `normalizer.py`, `producer.py`) | `PARTIALLY_IMPLEMENTED` | Normalizer & backpressure enqueue work (`test_streaming_and_broker.py:40-101`). Defects: `aggTrade` disconnect gaps never healed (`binance_ws.py:143-144`, `runtime.py:109-118`); `_record_malformed` blocks WS loop on inline DB (`binance_ws.py:98-115`); `BoundedEventProducer.stop` drops items on broker error/timeout (`producer.py:62-75,144-157`). |
| `COMP-DP-02` | **BrokerAdapter** (`broker.py`) | `PARTIALLY_IMPLEMENTED` | Live JetStream publish/pull/NAK/replay verified (`test_streaming_and_broker.py:179-233`). Defects: `connect()` overwrites `self._nc`/`_js` on disconnect, orphaning `MedallionStreamConsumer._sub` (`broker.py:178-198`); KV buckets not implemented. |
| `COMP-DP-03` | **StreamProcessor** (`consumers.py`) | `PARTIALLY_IMPLEMENTED` | Micro-batch write-commit-ACK happy path & DLQ routing tested (`test_streaming_and_broker.py:105-175`). Defects: **`BoundedDedupCache.seen()` mutates pre-commit** causing silent data loss on flush-failure redelivery (`consumers.py:242-247`); no `_flush_lock` mutex against `POST /streaming/flush`; mid-flush `DataQualityService` `db.commit()` (`consumers.py:373`); pre-commit closed-candle inference tasks (`consumers.py:294`); `_route_to_dlq` calls `msg.term()` even if both sinks fail (`consumers.py:213`). |
| `COMP-DP-04` | **LakeStorage + Manifests** (`storage/medallion.py`, `local.py`, `s3.py`) | `PARTIALLY_IMPLEMENTED` | `LocalStorageBackend` atomic writes & path guard verified (`test_medallion_and_governance.py:19-31`). Defects: lockless Silver `part-{dt}.parquet` read-modify-write races (`medallion.py:179-205`); Gold written under `dt={max_open_time}` causes multi-day duplicate rows (`medallion.py:367-375,407-419`); **snapshot manifests & dataset versioning MISSING** (`governance_service.py:41-160`); S3 untested & incompatible with `enforce_retention` (`governance_service.py:480`). |
| `COMP-DP-05` | **OperationalDB** (`core/database.py`, `models/*`, `alembic/*`) | `PARTIALLY_IMPLEMENTED` | All 14 ORM tables match Alembic `af2bd5126950` (`SQLite WAL`). Defects: `get_db()` commits on read-only `GET` (`database.py:107`); `NullPool` re-applies PRAGMAs per session (`database.py:35`); `DataCatalogEntry.size_bytes` is 32-bit `Integer`; `psycopg[binary]` missing for PostgreSQL; open->closed `Kline` promotion missing. |
| `COMP-DP-06` | **WarehouseService** (`duckdb_engine.py`, new `warehouse.py`) | `PARTIALLY_IMPLEMENTED` | Ephemeral `:memory:` DuckDB reader exists (`duckdb_engine.py:12-20`) with `query_parquet_glob` dead code (`0` prod callers). **Persistent DuckDB star schema & snapshot publisher MISSING.** |
| `COMP-DP-07` | **HotStateCache** | `MISSING` | No cache abstraction or NATS KV layer exists (`DOCUMENTATION_ONLY` Redis mentions in prior specs). |
| `COMP-DP-08` | **ServingGatewayBridge** | `DOCUMENTATION_ONLY` | Claimed in `system-architecture.md:214-239`, absent from code; `STANDARD`/`EXTENDED` multi-process mode hits process split-brain (`streaming.py:28,61,96,106`, `system.py:71`, `analytics.py:75`). |
| `COMP-DP-09` | **WorkflowEngine** (`pipeline_service.py`, `workers/sync_worker.py`) | `PARTIALLY_IMPLEMENTED` | Local recompute DAG runs (`test_medallion_and_governance.py:100-149`). Defects: runs in volatile `FastAPI.BackgroundTasks` with no lease/reaper/resume (`pipelines.py:135`); `trigger` returns no `run_id`; Task 1 retry lacks `rollback()` (`pipeline_service.py:240-252`); `sync_worker.py` is an un-leased sleep loop omitting `fill_gaps()`. |
| `COMP-DP-10` | **Governance / DQ / Retention** (`governance_service.py`, `data_quality_service.py`) | `PARTIALLY_IMPLEMENTED` | 10 SQL Kline DQ rules work (`test_data_platform.py:15-85`). Defects: **catalog sync writes/commits on `GET`** (`governance_service.py:282`); Gold row counts truncated at `5,000` (`governance_service.py:201,208`); zero `agg_trades` DQ or cross-layer parity; `detect_gaps` misses edge/trailing gaps; retention uses `mtime` (`governance_service.py:490`). |
| `COMP-DP-11` | **API Gateway** (`api/v1/*`, `main.py`) | `PARTIALLY_IMPLEMENTED` | Core contracts tested (`test_api_contract.py`). Defects: `POST /forecasts/generate`, `/forecasts/reconcile`, `/data-quality/evaluate` lack `require_admin_if_configured`; raw `str(e)` leaked (`pipelines.py:87`, `broker.py:360`, 400s); heavy `POST /models/train` & `POST /market/sync` run inline; `/health` probes no dependencies. |
| `COMP-DP-12` | **Observability** (`metrics.py`, `logging.py`, `telemetry.py`) | `PARTIALLY_IMPLEMENTED` | Prometheus `/metrics` & per-node telemetry exist (`test_api_and_security.py:26-40`, `test_streaming_and_broker.py:265-319`). Defects: sync `Path.rglob("*")` runs on event loop (`main.py:100`, `system.py:67`); `disk_free_gb` & host RAM missing from `/metrics`; frozen `DATA_FRESHNESS_SECONDS`/`CONSUMER_LAG` on stalls; batch paths emit zero failure metrics; `PipelineTelemetryTracker` is in-memory only. |
| `COMP-DP-13` | **IncrementalAnalytics** (`ml/incremental_analytics.py`) | `PARTIALLY_IMPLEMENTED` | Stream-vs-batch parity verified (`test_financial_correctness.py:43-118`). Defects: non-atomic `write_text()` checkpoints (`incremental_analytics.py:385-394`); silent reset on corrupt JSON (`line 380`); `last_open_time` idempotency guard (`bar_count` double-count risk on replay) incomplete across restarts. |
