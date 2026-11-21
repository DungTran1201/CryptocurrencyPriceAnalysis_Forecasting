# Persistent DuckDB Data Warehouse Detailed Design

**Scope:** `COMP-DP-06` (WarehouseService + DuckDB Warehouse Storage)  
**Requirements:** `REQ-DP-DW-01`, `REQ-DP-DW-02`, `REQ-DP-DW-03`  
**ADRs & Contracts:** `ADR-DP-004`, `IFC-DP-006`, `IFC-DP-011`  
**Phase 2 Work Items:** `WI-DP-06`, `WI-DP-05`

---

## 1. AS-IS Baseline & Empirical DuckDB 2.0.0 Findings `[OBSERVED / MEASURED]`

### 1.1 AS-IS Codebase Gaps `[OBSERVED]`
- `backend/app/storage/duckdb_engine.py:12-20` creates an ephemeral `duckdb.connect(":memory:")` per query and immediately closes it. Zero persistent `.duckdb` warehouse files exist (`data/warehouse/` does not exist).
- `query_parquet_glob` (`duckdb_engine.py:23-38`) is unused dead code and interpolates file paths directly into SQL literals (`f"'{p}'"`).
- `read_silver_klines_df` (`medallion.py:289-325`) is unused in production APIs; all analytical endpoints (`AnalyticsService`, `MarketService`, `DataQualityService`, `ModelService`, `ForecastService`, and `DataExplorer` for `silver_klines`) query SQLite/PostgreSQL `klines` directly.
- Per-request `:memory:` DuckDB scans over 101 Silver Parquet files (`ETHUSDT 15m`, 9,600 rows) incurred `~70–120 ms` cold floor per query (`#14`, `[MEASURED]`).

### 1.2 Empirical DuckDB 2.0.0 Windows File-Locking Measurements (`#15`, `[MEASURED]`)
Tested on Windows 10 (`Build 19045`), Python `3.14.10`, `duckdb 2.0.0` in isolated `$env:TEMP`:
1. **Cross-Process RW + RO Lock Failure**: When Process A holds `read_only=False` on `staging.duckdb` (`CHECKPOINT` executed), Process B calling `duckdb.connect(..., read_only=True)` **fails** with `IOException: The process cannot access the file because it is being used by another process`. `shutil.copy2` while RW is open also **fails** with `PermissionError [WinError 32]`.
2. **In-Process RW + RO Configuration Mismatch**: Even within the *same* Python process (`LITE` profile), opening `read_only=False` and `read_only=True` on the same `.duckdb` path **fails** with `ConnectionException: Can't open a connection to same database file with a different configuration than existing connections`.
3. **Immutable Versioned Snapshot Pattern (`staging -> CHECKPOINT -> close -> copyfile + os.replace -> dw-v{N}.duckdb`)**:
   - After `CHECKPOINT` + `conn.close()`, `staging.duckdb` (12,500 rows) is a clean single file (`536,576 bytes`, `wal_exists=False`).
   - Publishing snapshot (`shutil.copyfile` to `.tmp` + `os.replace` to `dw-v1.duckdb`): **`1.43 ms`**.
   - Opening `dw-v1.duckdb` (`read_only=True`): **`52.39 ms`**; executing `GROUP BY` query: **`12.01 ms`**.
   - Concurrent second process opening `dw-v1.duckdb` (`read_only=True`) while Reader 1 remains open: **SUCCEEDED** (`open_ms=53.66 ms`).
   - Incremental update (+1 row + `CHECKPOINT` + `close` + publish `dw-v2.duckdb`): **`68.09 ms`** total; Reader 3 opens `dw-v2.duckdb` in **`50.82 ms`**.
   - Unlinking `dw-v1.duckdb` while Reader 1 still held `read_only=True`: **SUCCEEDED** and Reader 1 closed cleanly.

**Binding Concurrency Conclusion (`ADR-DP-004`)**: Both single-process `LITE` and multi-process `STANDARD`/`EXTENDED` MUST separate the serialized writer's staging file (`data/warehouse/staging/dw_staging.duckdb`) from versioned immutable reader snapshots (`data/warehouse/snapshots/dw-v{N}.duckdb`).

---

## 2. TO-BE Persistent DuckDB Warehouse Architecture `[PROPOSED]`

### 2.1 Directory Layout (`data/warehouse/`)
```text
data/warehouse/
  staging/
    dw_staging.duckdb          # Owned exclusively by serialized WorkflowWorker writer
  snapshots/
    dw-v000001.duckdb          # Immutable read-only snapshot v1
    dw-v000002.duckdb          # Immutable read-only snapshot v2
  LATEST                       # Atomic text file containing active version & relative path
```
The authoritative pointer is persisted in SQL table `warehouse_snapshots` (`IFC-DP-006`) and mirrored to `data/warehouse/LATEST` (written via `.tmp` + `fsync` + `os.replace`) so readers can resolve the latest immutable snapshot with zero SQL lock overhead if desired, and reconcile cleanly against SQL.

### 2.2 Star Schema Design (`REQ-DP-DW-01`, `IFC-DP-006`)

All analytical marts and cross-day queries read from a normalized Star Schema inside DuckDB:

1. **Dimension Tables**:
   - `dim_symbol`: Surrogate `symbol_key INTEGER PRIMARY KEY`, natural key `symbol VARCHAR UNIQUE`, `base_asset`, `quote_asset`, `is_active`, `first_seen_at`, `last_synced_at`.
   - `dim_timeframe`: Surrogate `timeframe_key INTEGER PRIMARY KEY`, natural key `timeframe VARCHAR UNIQUE`, `interval_seconds`, `periods_per_year`. Seeded deterministically for `1m`, `5m`, `15m`, `1h`, `4h`, `1d`.
   - `dim_date`: Integer key `date_key INTEGER PRIMARY KEY` (`YYYYMMDD`), `full_date DATE UNIQUE`, `year`, `quarter`, `month`, `day`, `day_of_week`, `is_weekend`. Populated on demand for all incoming bar UTC dates.
2. **Fact Tables**:
   - `fact_kline_bar`:
     - Grain: One row per `(symbol_key, timeframe_key, open_time)` (`PRIMARY KEY`).
     - Columns: `symbol_key`, `timeframe_key`, `date_key`, `open_time`, `close_time`, `open`, `high`, `low`, `close`, `volume`, `quote_asset_volume`, `number_of_trades`, `taker_buy_base_asset_volume`, `taker_buy_quote_asset_volume`, `is_closed`, pre-computed `simple_return`, `log_return`, `typical_price`, `source`, `ingested_at`.
   - `fact_risk_daily`:
     - Grain: One row per `(symbol_key, timeframe_key, date_key)` (`PRIMARY KEY`).
     - Columns: `bar_count`, `expected_bars`, `completeness_pct`, `day_open`, `day_high`, `day_low`, `day_close`, `total_volume`, `total_quote_volume`, `daily_return_pct`, `realized_vol_ann_pct`, `atr_14_last`, `vwap_session`, `var_95_pct`, `cvar_95_pct`, `max_drawdown_pct`, `computed_at`.
3. **Checkpoint Table**:
   - `warehouse_checkpoints`: Tracks `(dataset_name PK, warehouse_version, source_snapshot_id, last_open_time, rows_loaded, built_at)` inside DuckDB (mirrored in SQL `warehouse_snapshots`) for idempotent incremental ETL.
4. **Analytical Mart Views (`mart_*`)**:
   - `mart_market_overview`: Latest close, 24h rolling change %, high/low/volume, `bar_count_24h`, and data freshness per `(symbol, timeframe)` using `fact_kline_bar` + dimensions.
   - `mart_risk_summary`: Multi-day realized volatility, VaR(95), CVaR(95), ATR(14), VWAP, max drawdown, and completeness % over `fact_risk_daily`.
   - `mart_data_completeness`: Expected vs observed bar counts and missing-bar deltas per `(symbol, timeframe, full_date)`.

---

## 3. Single-Writer ETL, Incremental Builds & Snapshot Publishing (`REQ-DP-DW-02`, `REQ-DP-DW-03`)

### 3.1 Serialized Writer Lease (`WarehouseService`)
- Only `WorkflowWorker` executing a leased `WAREHOUSE_BUILD` job (`workflow_runs` + `warehouse_write_lease`) may open `dw_staging.duckdb` (`read_only=False`).
- In `LITE` profile or unit/integration tests, an additional in-process `asyncio.Lock` guards `WarehouseService` inside the single process so background/triggered builds never collide.

### 3.2 Incremental ETL Flow from Silver Manifests
1. Query SQL for the `ACTIVE` `lake_snapshots` record of `silver_klines` (and its `lake_manifest_files`).
2. Compare against `warehouse_checkpoints` to determine which `(symbol, timeframe, partition_dt)` files are new or updated since `source_snapshot_id` (or `max_ts >= last_open_time - warmup_overlap`).
   - *Warm-up overlap*: Re-compute returns (`simple_return`, `log_return`) and `fact_risk_daily` using a trailing lookback buffer (e.g., prior 30 bars per `(symbol, timeframe)`) so day-boundary `simple_return`, `atr_14`, and rolling volatility match batch reference parity.
3. Open `data/warehouse/staging/dw_staging.duckdb` (`read_only=False`, bounded `memory_limit` & `threads` per profile). If a prior crash left a `.wal`, DuckDB replays it cleanly on open.
4. Inside a DuckDB transaction:
   - Ensure `dim_symbol`, `dim_timeframe`, `dim_date` contain all keys from the incoming Silver slice.
   - Load incremental Silver Parquet files via explicit file list (`read_parquet([...], union_by_name=true)` — never unescaped glob or unfiltered directory scan).
   - Upsert `fact_kline_bar` via `INSERT OR REPLACE` / `MERGE` enforcing the open-to-closed promotion rule (`existing.is_closed = FALSE OR excluded.is_closed = TRUE`).
   - Recompute affected `(symbol_key, timeframe_key, date_key)` rows in `fact_risk_daily` (preserving exact parity with `ml.incremental_analytics.compute_batch_reference_metrics`).
   - Update `warehouse_checkpoints`.
5. Commit DuckDB transaction, run `CHECKPOINT;`, verify `wal` flushed, and call `conn.close()`.
6. **Snapshot Publish**:
   - Determine `next_version = (max_version in warehouse_snapshots) + 1` (e.g., `dw-v000007.duckdb`).
   - Copy `dw_staging.duckdb` to `snapshots/.dw-v000007.duckdb.tmp`, `fsync`, and `os.replace` to `snapshots/dw-v000007.duckdb`. Compute `sha256` and `size_bytes`.
   - In one SQL transaction: insert `warehouse_snapshots` (`status="ACTIVE"`, `warehouse_version=7`, `source_lake_snapshot_id=...`, `file_path=...`), mark prior `ACTIVE` row `SUPERSEDED`, and update `LATEST` pointer file atomically.

### 3.3 Bounded Reader Execution & Fallback (`AnalyticsService` + API)
- **Reader Resolution (`get_warehouse_reader()`)**:
  1. Resolve `ACTIVE` `dw-v{N}.duckdb` path (via SQL `warehouse_snapshots` or `LATEST` file cached briefly in memory).
  2. Open `duckdb.connect(snapshot_path, read_only=True)` with `SET memory_limit='{settings.resources.duckdb_memory_limit}'` and `SET threads={settings.resources.duckdb_threads}` inside `asyncio.to_thread(...)` (never blocking the FastAPI event loop).
  3. **Pooled / Short-Lived Connection**: Execute bounded query (`LIMIT` enforced) and close in `finally:` so file handles are released promptly.
  4. **Graceful Degradation (Cold Start)**: Before the first Warehouse snapshot is built (or if snapshot is temporarily unavailable), `AnalyticsService` cleanly falls back to SQL `klines` (preserving API availability and explicit freshness metadata).

### 3.4 Snapshot Retention, Backup & Restore
- **Snapshot GC**: Keep the latest `WarehouseSettings.retain_snapshots` (`3 / 3 / 5` across `LITE / STANDARD / EXTENDED`) `SUPERSEDED` snapshots and enforce a `WarehouseSettings.reader_grace_ttl_sec` (`60s`) cooldown before deleting older `.duckdb` files. Never delete `ACTIVE` or `dw_staging.duckdb`.
- **Backup & Restore**: Because `dw-v{N}.duckdb` is a single self-contained, checkpointed, immutable file (`wal_exists=False`), backup is a direct file copy + SHA-256 verification. Restore copies a verified `dw-v{N}.duckdb` into `dw_staging.duckdb` and resets `LATEST` / `warehouse_snapshots` (or rebuilds `dw_staging.duckdb` idempotently from `silver_klines` `ACTIVE` snapshot manifest).
