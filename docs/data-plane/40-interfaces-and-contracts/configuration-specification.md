# Configuration Specification and Dependency Policy

- **Document ID:** `IFC-DP-011`
- **Status:** `PROPOSED` (Specification Baseline v1.0)
- **Owner:** `@stream-orch` (Phase 1 Step 2)
- **Traceability:**
  - Requirements: `REQ-DP-CFG-01`, `REQ-DP-ING-03`, `REQ-DP-HOT-01`, `REQ-DP-ORC-01..03`, `REQ-DP-DW-01..03`
  - Components: `COMP-DP-01..13`
  - ADRs: `ADR-DP-001`, `ADR-DP-004`, `ADR-DP-005`, `ADR-DP-006`, `ADR-DP-007`
  - Phase 2 Work Items: `WI-DP-11`

---

## 1. Purpose and AS-IS Configuration Drift (`[OBSERVED]`)

Audit findings (`#6`, `#7`, `#8`, `#9`) identified multiple configuration mismatches across `config.yaml`, `.env.example`, `backend/app/core/config.py`, `docker/nats/nats.conf`, `run.bat`, and `requirements.txt`:

1. **`config.yaml` Partial Ignorance (`config.py:328-383`)**: `Settings.load()` reads `app.profile`, `data.symbols` (non-LITE only), and `data.time.default_frame`, while silently ignoring `data.streams` (`config.yaml:14-16`), `data.api.*` (`26-31`), and `ml.*` (`33-39`, e.g., `walk_forward_folds: 4` vs `5` in `config.py:206`, `min_direction_accuracy: 0.50` vs `0.51` in `config.py:209`).
2. **`.env.example` Dead Env Overrides (`config.py:341-383`)**: `.env.example:40-41` declares `BINANCE_API_URL` and `BINANCE_FALLBACK_URL`, which `Settings.load()` never maps into `instance.sync.*`.
3. **Database URL Split**: `config.py:373-382` translates `postgresql://` -> `postgresql+asyncpg://` on `DATABASE_URL`, but leaves `sync_database_url` untouched if `DATABASE_URL` points to an alternate SQLite path unless `SYNC_DATABASE_URL` is separately set.
4. **Docker NATS Cap Mismatch (`docker/nats/nats.conf:7-8` vs `config.py:47-102`)**: `nats.conf` hardcodes `128MB / 512MB` across all Compose profiles (`lite` exceeds 128 MB file budget assumptions; `extended` expects `1024 MB`, forcing stream creation fallback).
5. **Launcher Gap (`run.bat:29-42, 160`)**: `run.bat standard` and `run.bat extended` set `embedded_in_api=False` (`config.py:285`) yet only launch `uvicorn`, leaving streaming dead without `stream_worker` or `workflow_worker`.
6. **Missing Sync Postgres Driver & Unpinned Dependencies (`requirements.txt:1-27`)**: `requirements.txt` uses unpinned `>=` ranges (yielding Python `3.14.10` / `duckdb 2.0.0` locally vs Python `3.12` in CI) and lacks `psycopg[binary]` required by `alembic` and `sync_engine` in PostgreSQL profiles.

---

## 2. Unified Precedence & Mapping Rules (`REQ-DP-CFG-01`)

Authoritative precedence order (lowest to highest):
1. Code defaults & `PROFILE_RESOURCE_DEFAULTS[selected_profile]`
2. `config.yaml` sections (`app`, `data`, `streaming`, `ml`, `workflow`, `warehouse`, `hot_state`, `serving`)
3. `.env` file loaded via Pydantic `BaseSettings`
4. Explicit OS environment variables (`PLATFORM_PROFILE`, `STREAM_*`, `DATABASE_URL`, `BINANCE_*`, etc.)

### 2.1 Required `Settings.load()` Wire-Up Fixes
- Map `config.yaml`:
  - `data.streams` -> `instance.streaming.streams` (unless `STREAM_STREAMS` env set)
  - `data.api.primary_url` / `fallback_url` / `batch_limit` / `max_retries` / `timeout_seconds` -> `instance.sync.*`
  - `ml.model_dir`, `default_horizon_steps`, `supported_horizons`, `walk_forward_folds`, `activation_margin_threshold`, `min_direction_accuracy` -> `instance.ml.*`
- Map environment variables:
  - `BINANCE_API_URL`, `BINANCE_FALLBACK_URL`, `BINANCE_WS_BASE_URL`, `BINANCE_WS_FALLBACK_URL`
  - `DATABASE_URL`: automatically normalize `postgresql://` and `postgresql+asyncpg://` -> `postgresql+psycopg://` for `sync_database_url` (both in `DatabaseSettings` / `Settings.load()` and `alembic/env.py`), and symmetrically map `sqlite+aiosqlite:///...` <-> `sqlite:///...` when `SYNC_DATABASE_URL` is unset.

---

## 3. New & Extended Data Plane Settings (`IFC-DP-011`)

Added/extended in `Settings` (`backend/app/core/config.py`):

### 3.1 `WorkflowSettings` (`workflow: WorkflowSettings`)
| Field | Default (`LITE` / `STD` / `EXT`) | Description |
|---|---|---|
| `poll_interval_sec` | `2.0` | SQL durable job poll cadence (accelerated via `workflow.wakeup`) |
| `lease_ttl_sec` | `60` | Worker lease duration before stale-lease reaper reclaims |
| `heartbeat_interval_sec` | `15` | Active task lease renewal interval |
| `reaper_interval_sec` | `15` | Stale `RUNNING` job recovery scan interval |
| `max_concurrent_jobs` | `1` / `2` / `3` | Concurrent non-exclusive workflow tasks per worker |
| `max_attempts_default` | `3` | Default retry ceiling before `FAILED` |
| `graceful_shutdown_sec` | `15.0` | Drain wait before releasing active lease |
| `memory_throttle_pct` | `90.0` | Defer non-urgent scheduled jobs above RSS/host memory ceiling |

### 3.2 `WarehouseSettings` (`warehouse: WarehouseSettings`)
| Field | Default (`LITE` / `STD` / `EXT`) | Description |
|---|---|---|
| `enabled` | `True` | Enable persistent DuckDB warehouse & snapshots |
| `warehouse_dir` | `"./data/warehouse"` | Root directory for `staging/dw_staging.duckdb` & `snapshots/dw-v{N}.duckdb` |
| `retain_snapshots` | `3` / `3` / `5` | Number of immutable `dw-v{N}.duckdb` snapshots retained |
| `reader_grace_ttl_sec` | `60` | Minimum age before superseded snapshot file deletion |
| `query_timeout_ms` | `5000` | Bounded analytical query wall-clock limit |

### 3.3 `HotStateSettings` (`hot_state: HotStateSettings`)
| Field | Default (`LITE` / `STD` / `EXT`) | Description |
|---|---|---|
| `backend` | `"nats_kv"` | `"nats_kv"` (single-node default), `"memory"` (tests), `"redis"` (future external) |
| `kv_bucket` | `"hot_state"` | JetStream KV bucket name (`StorageType.MEMORY`) |
| `heartbeat_bucket` | `"worker_heartbeats"` | JetStream KV bucket for worker liveness (`StorageType.MEMORY`) |
| `kv_max_bytes_mb` | `8` / `16` / `32` | `hot_state` bucket cap within `nats_max_mem_mb` |
| `heartbeat_max_bytes_mb` | `1` / `2` / `4` | `worker_heartbeats` bucket cap |
| `kv_ttl_sec` | `300.0` | Hot snapshot expiry in seconds |
| `heartbeat_ttl_sec` | `15.0` | Worker heartbeat expiry in seconds |
| `l1_cache_maxsize` | `512` / `1024` / `2048` | Bounded in-process API `TTLCache` item cap |
| `l1_cache_ttl_sec` | `2.0` | Fast API L1 snapshot TTL (invalidated via NATS Core) |

### 3.4 `ServingBridgeSettings` (`serving: ServingBridgeSettings`) & Streaming/Resource Extensions
| Field | Namespace | Default (`LITE` / `STD` / `EXT`) | Description |
|---|---|---|---|
| `control_timeout_sec` | `serving` | `5.0` | NATS request-reply timeout for `serving.control.*` |
| `heartbeat_interval_sec` | `serving` | `2.0` | Worker heartbeat publish cadence |
| `closed_bar_inference_queue_max` | `serving` | `32` | Bounded sequential queue for post-commit closed-candle inference |
| `aggtrade_backfill_max_batches` | `streaming` | `5` / `10` / `20` | Max REST `/aggTrades` pages per reconnect gap-heal pass |
| `bronze_buffer_max_mb` | `resources` | `16` / `32` / `64` | Bounded producer/consumer in-memory buffer ceiling (MB) |
| `producer_spool_max_mb` | `resources` | `16` / `32` / `64` | Bounded local disk spool cap on producer shutdown timeout |

---

## 4. Profile Resource Budget Matrix (`LITE` / `STANDARD` / `EXTENDED`)

| Resource Control | `LITE` | `STANDARD` | `EXTENDED` |
|---|---|---|---|
| `max_python_procs` | `1` (API + embedded Stream/Workflow) | `3` (API, Stream, Workflow) | `4` |
| `total_memory_mb` | `450` | `950` | `2048` |
| `embedded_in_api` | `True` | `False` | `False` |
| `stream_queue_maxsize` | `1000` | `5000` | `10000` |
| `consumer_batch_size` | `50` | `200` | `500` |
| `bronze_flush_max_records` | `250` | `1000` | `2000` |
| `bronze_buffer_max_mb` | `16` | `32` | `64` |
| `producer_spool_max_mb` | `16` | `32` | `64` |
| `nats_max_mem_mb` | `64` | `128` | `256` |
| `nats_max_file_mb` | `128` | `512` | `1024` |
| `hot_state` + `worker_heartbeats` KV | `8 + 1 MB` (`MEMORY`) | `16 + 2 MB` (`MEMORY`) | `32 + 4 MB` (`MEMORY`) |
| `duckdb_memory_limit` / `threads` | `128MB` / `2` | `256MB` / `4` | `512MB` / `4` |

- **Docker Compose Alignment (`docker/docker-compose.yml` & `docker/nats/`)**: Parameterize NATS memory/file limits per profile (so `lite` does not use `512MB` and `extended` allows `1024MB`), add `workflow-worker` service (`standard`/`extended`), and run `alembic upgrade head` in container startup/init before starting API/workers.
- **Windows Launcher Alignment (`run.bat`)**: Update `run.bat standard|extended` to start `stream_worker` and `workflow_worker` background jobs alongside `uvicorn` (and stop workers + `nats-server` gracefully on exit, switching `stop_nats.ps1` to graceful quit before force kill).

---

## 5. Dependency Pinning & Database Driver Policy (`WI-DP-11`)

1. **Standardized PostgreSQL Sync Driver (`[OBSERVED]` #9)**: Add `psycopg[binary]>=3.2.0,<4.0` to `requirements.txt` and automatically rewrite `postgresql://` / `postgresql+asyncpg://` -> `postgresql+psycopg://` for `sync_database_url` in `DatabaseSettings` (`core/config.py`) and `alembic/env.py` so `alembic` and `SyncSessionLocal` operate cleanly in `STANDARD`/`EXTENDED` deployments.
2. **Upper-Bounded Dependency Pinning**: Replace unconstrained `>=` specifiers in `requirements.txt` and `requirements-extended.txt` with compatible upper bounds (`~=X.Y` or `>=X.Y,<Z`) and maintain a verified `requirements.lock` (or `pip freeze` constraint snapshot) aligned with the CI Python target (`3.12` / `3.14` explicitly tested) to prevent silent major-version drift (e.g., `duckdb 2.0.0`, `pyarrow 26.0.1`, `SQLAlchemy 2.1.9`).
