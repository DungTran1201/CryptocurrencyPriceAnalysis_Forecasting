# ADR-DP-004: Persistent DuckDB Star Schema Warehouse & Immutable Versioned Snapshots

- **Status:** Accepted (Phase 1 Baseline — Empirically Verified `#14`, `#15`)
- **Date:** 2026-11-17
- **Supersedes:** Ephemeral `:memory:`-only DuckDB query model in `docs/40-adr/ADR-003`
- **Linked Requirements:** `REQ-DP-DW-01`, `REQ-DP-DW-02`, `REQ-DP-DW-03`
- **Linked Components:** `COMP-DP-06`, `COMP-DP-09`

---

## 1. Context & Empirical Evidence (`OBSERVED` / `MEASURED` `#7`, `#9`, `#14`, `#15`)
1. **AS-IS Ephemeral Query Latency (`OBSERVED` + `MEASURED` `#14`):** `backend/app/storage/duckdb_engine.py:12-20` opens a fresh `duckdb.connect(":memory:")` per call; `AnalyticsService` bypasses DuckDB completely and queries SQLite `klines`. `@sre-qa` (`#14`) measured cold `:memory:` DuckDB scans over 101 Silver `15m` Parquet files (`9,600` rows, `memory_limit=128MB`, `threads=2`) at **`70.5–117.5 ms`** per request due to connection setup + Parquet globbing.
2. **Windows DuckDB 2.0.0 File-Locking Reality (`MEASURED` `#15`):**
   - When Process A holds a `read_write` connection on `staging.duckdb` (`CHECKPOINT` took `110.61 ms` for 12.5k rows):
     - Process B `duckdb.connect(staging, read_only=True)` **FAILS** (`IOException: The process cannot access the file because it is being used by another process`).
     - Process B2 `read_only=False` **FAILS** (`IOException`).
     - `shutil.copy2` while Process A holds RW **FAILS** (`PermissionError: [WinError 32]`).
     - Same-process mixed `read_only=False` + `read_only=True` **FAILS** (`ConnectionException`).
   - **Immutable Snapshot Pattern (`MEASURED` `#15`):** After `CHECKPOINT` + `close()` (`536,576 B`, `wal_exists=False`):
     - Snapshot publish (`shutil.copyfile` + `os.replace` -> `dw-v{N}.duckdb`): **`1.43 ms`**.
     - Concurrent Process B + Process C `read_only=True` connections on `dw-v1.duckdb` **SUCCEEDED** (`52.39 ms` / `53.66 ms` open, `12.01 ms` `GROUP BY` query).
     - Incremental update (`+1` row) + `CHECKPOINT` + `close()` + publish `dw-v2.duckdb`: **`68.09 ms`** total; Reader 3 opened `dw-v2` in **`50.82 ms`**.

## 2. Options Considered
1. **Option A — Ephemeral `:memory:` Parquet Queries Only:** Rejected; pays `70–118 ms+` cold glob/parse penalty per analytical call (`#14`) as file counts grow, lacks materialized Star Schema dimensions/facts/mart views, and fails the explicit persistent DuckDB Data Warehouse requirement.
2. **Option B — Single Shared `.duckdb` File with Direct Concurrent RW + RO:** Rejected (`MEASURED` `#15`); impossible on Windows DuckDB 2.0.0 across processes (`IOException`) or even within one process (`ConnectionException`).
3. **Option C — Single Serialized Writer (`dw_staging.duckdb`) + Immutable Versioned Snapshots (`dw-v{N}.duckdb`) (`PROPOSED`):** Write exclusively to `data/warehouse/staging/dw_staging.duckdb` under a workflow lease, `CHECKPOINT` + `close()`, atomically copy/swap to immutable `snapshots/dw-v{N}.duckdb`, and serve concurrent `read_only=True` readers.

## 3. Decision
Adopt **Option C**:
1. **Warehouse Star Schema (`data/warehouse/`, `IFC-DP-006`):**
   - Dimensions: `dim_symbol`, `dim_timeframe`, `dim_date`.
   - Facts & Watermarks: `fact_kline_bar`, `fact_risk_daily`, `warehouse_checkpoints`.
   - Analytical Views: `mart_market_overview`, `mart_risk_summary`, `mart_data_completeness`.
2. **Single Serialized Writer (`REQ-DP-DW-02`):**
   - Only `WarehouseService` executing inside a `WorkflowEngine` (`workflow_worker` / single-writer SQL lease) opens `data/warehouse/staging/dw_staging.duckdb` (`read_only=False`), runs incremental ETL from `ACTIVE` Silver/Gold `lake_snapshots`, executes `CHECKPOINT`, and **closes** the connection.
3. **Immutable Versioned Snapshot Serving (`REQ-DP-DW-03`):**
   - While `dw_staging.duckdb` is closed, `WarehouseService` copies to `snapshots/.tmp-{uuid}` + `os.replace` -> `snapshots/dw-v{N}.duckdb`, atomically commits the `warehouse_snapshots` SQL pointer (`warehouse_version=N`, `status='ACTIVE'`, marking previous `'SUPERSEDED'`), and writes a fallback `LATEST` pointer file.
   - API readers (`AnalyticsService`, `DataExplorer`) resolve the active `dw-v{N}.duckdb` and open `read_only=True` (enforcing `duckdb_memory_limit` and `duckdb_threads`), enabling lock-free concurrent reads in both `LITE` and `STANDARD`.
   - GC enforces `WarehouseSettings.retain_snapshots = 3 / 3 / 5` (`N=3` for `LITE` and `STANDARD`) plus `reader_grace_ttl_sec >= 60` before unlinking old `dw-v*.duckdb` files.

## 4. Consequences
- **Positive:** Eliminates Windows DuckDB lock crashes, isolates long ETL writes from fast `~12 ms` analytical reads, preserves atomic rollback (`dw-v{N-1}`), and stays bounded within `128 MB` (`LITE`) / `256 MB` (`STANDARD`) DuckDB caps.
- **Negative / Mitigation:** Slight snapshot storage overhead (`N=3` copies, ~`0.5–5 MB` each at current scale) and snapshot lag bounded by the Warehouse refresh schedule; mitigates disk growth via retention & `N=3` GC.
