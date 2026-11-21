# Data Governance, Catalog, Lineage & Retention Design

**Scope:** `COMP-DP-10` (GovernanceService), `COMP-DP-04` (Manifest-aware Retention)  
**Requirements:** `REQ-DP-LAKE-03`, `REQ-DP-LAKE-05`, `REQ-DP-LAKE-06`, `REQ-DP-ORC-04`, `REQ-DP-SEC-02`  
**ADRs & Contracts:** `ADR-DP-003`, `IFC-DP-005`, `IFC-DP-008`  
**Phase 2 Work Items:** `WI-DP-09`, `WI-DP-04`

---

## 1. AS-IS Baseline & Defects `[OBSERVED]`

Audit of `backend/app/services/governance_service.py`, `backend/app/api/v1/governance.py`, and `data/crypto_market.db` identified five concrete governance defects:

1. **Read Endpoints Mutate SQLite & Scan Storage (`governance_service.py:280-282`)**:
   - `GovernanceService.list_catalog(db)` calls `sync_catalog_entries(db)` on every invocation, performing full storage scans, reading Parquet files via DuckDB/PyArrow, and executing `await db.commit()`.
   - Because `GET /api/v1/governance/catalog`, `GET /api/v1/data-explorer/datasets`, and `GET /api/v1/data-quality/lineage` all call `list_catalog` / `get_lineage_graph`, dashboard polling creates constant write-lock contention under SQLite WAL and runs blocking I/O on the event loop.
2. **Truncated & Inaccurate Catalog Statistics (`governance_service.py:193-216`)**:
   - `gold_analytics_marts` and `gold_feature_sets` row counts call `len(medallion.read_gold_dataset(..., limit=5000))` (`lines 201, 208`), loading rows into Python AND silently capping row counts at `5000`. **Observed on disk**: `ETHUSDT 15m` Gold files contain `9,600` rows, while `data_catalog_entries` recorded `5000`.
   - `silver_agg_trades` row count (`lines 193-196`) only scans the last 20 Parquet files (`[-20:]`) and swallows errors (`except Exception: pass`).
   - `bronze_market_events` row count (`line 216`) guesses `stream_events + kline_count` rather than reading actual persisted Bronze counts.
3. **Catalog Schema & Version Drift (`governance_service.py:31-168, 269-274`)**:
   - `sync_catalog_entries` inserts `schema_json` and `version="1.0.0"` once when `existing is None`, never updating them on subsequent syncs.
   - `CATALOG_DEFINITIONS` already disagrees with actual storage (`silver_klines`: 10 cols vs 14 in `SILVER_KLINE_SCHEMA` vs 17 in SQL `Kline`; `silver_agg_trades`: 5 vs 10; `gold_analytics_marts`: 7 vs 14; `gold_feature_sets`: 5 vs 29).
4. **Unsafe `mtime`-Based Retention & S3 Silent Failure (`governance_service.py:458-520`)**:
   - `enforce_retention` calls `storage.local_path(k)` (`line 480`) and catches `NotImplementedError` (`line 483`), making retention a silent no-op on `S3StorageBackend`.
   - Age pruning checks `st_mtime` (`lines 482, 491`), not partition `dt=`. Rewriting or compacting an old partition resets `mtime` to today, and historical backfills (e.g. `dt=2026-08-09` written today) bypass `retention_silver_days=14`.
   - Deleting Silver/Gold Parquet files does not update `DataCatalogEntry` or SQL `klines`, and size-cap pruning can delete active Gold `mart.parquet` / `features.parquet`.
   - No retention exists for `data/dlq/`, `data/checkpoints/`, `data/models/`, `data/warehouse/snapshots/`, or high-growth SQL audit tables (`data_quality_runs`, `data_lineage_edges`, `pipeline_runs`, `dead_letter_events`).
5. **32-Bit Overflow Risk on PostgreSQL (`models/governance.py:34`)**:
   - `DataCatalogEntry.size_bytes` is `Integer` (`max 2,147,483,647`), which overflows below the `EXTENDED` profile's `4096 MB` retention cap.

---

## 2. TO-BE Governance, Catalog & Lineage Design `[PROPOSED]`

### 2.1 Zero-Write Read Paths & Manifest-Backed Catalog (`REQ-DP-ORC-04`, `REQ-DP-LAKE-02`)
- **Pure Read Queries on `GET`**:
  - `GET /governance/catalog`, `GET /data-explorer/datasets`, and `GET /data-quality/lineage` perform **read-only SQL `SELECT`s** against `data_catalog_entries` + `lake_snapshots` (`status='ACTIVE'`) + `warehouse_snapshots` (`status='ACTIVE'`), **never** calling `sync_catalog_entries` or `commit()` on `GET`.
- **Event-Driven & Scheduled Catalog Updates**:
  - Whenever a commit publishes a new `ACTIVE` `lake_snapshots` row (`batch_ledger` commit in `StreamProcessor`, `SyncService`, or `WorkflowWorker`), `GovernanceService.refresh_catalog_from_snapshot(db, snapshot)` updates that dataset's `DataCatalogEntry` (`row_count = snapshot.total_rows`, `size_bytes = snapshot.total_bytes`, `version = snapshot.schema_version`, `schema_hash = snapshot.schema_hash`, `active_snapshot_id = snapshot.snapshot_id`, and canonical `schema_json`) inside the **same transaction**.
  - An explicit admin/workflow maintenance action (`POST /governance/catalog/sync` or `WorkflowWorker` periodic reconcile) can still audit and reconcile `data_catalog_entries` against `StorageBackend.list_objects()` and `lake_snapshots`.

### 2.2 End-to-End Lineage DAG (`DataLineageEdge`)
Every transformation stage records deterministic `DataLineageEdge` entries linked by `run_id` (workflow/pipeline) or `batch_id`:
- `binance_public_stream -> bronze_market_events` (WS stream / REST backfill)
- `bronze_market_events -> silver_klines` (Stream micro-batch / REST upsert / compaction)
- `bronze_market_events -> silver_agg_trades` (Stream trade micro-batch / compaction)
- `silver_klines -> gold_analytics_marts` (Real-`dt` mart materialization)
- `silver_klines -> gold_feature_sets` (Zero-lookahead feature materialization)
- `silver_klines -> warehouse_duckdb` (`WAREHOUSE_BUILD` incremental load + `dw-v{N}` snapshot publish)
- `gold_feature_sets -> forecast_records` (Post-commit inference & reconciliation)

Lineage edges include `source_snapshot_id` / `target_snapshot_id` in `metadata_json` so any forecast or analytical table can trace back to the exact dataset snapshot version.

### 2.3 Partition-Date & Snapshot-Safe Retention Policy (`REQ-DP-LAKE-05`)

Retention splits into two safe, independent phases executed by `WorkflowWorker` (`RETENTION_ENFORCE` scheduled job, replacing `StreamPlatformRuntime._maintenance_loop` `cycle % 600` at `runtime.py:181-182`):

#### Phase A: Logical Partition Expiration (By Partition `dt=` Date, Not `mtime`)
For each Medallion dataset (`bronze_market_events`, `silver_klines`, `silver_agg_trades`, `gold_analytics_marts`, `gold_feature_sets`):
1. Read `ACTIVE` `lake_manifest_files`. Parse `partition_dt` (`YYYY-MM-DD`); never rely on `st_mtime` except for unpartitioned orphan files.
2. **Age Pruning**: Exclude partitions where `(today_utc - partition_dt).days > retention_<layer>_days`.
3. **Byte-Cap Pruning**: If total `size_bytes` of the remaining `ACTIVE` files exceeds `retention_<layer>_max_mb * 1024 * 1024`, prune the **oldest `partition_dt`** groups first while preserving at least the most recent `min_retained_partitions_per_symbol` (e.g., latest 2 UTC days) unless emergency disk-pressure override triggers.
4. Publish a new `ACTIVE` `lake_snapshots` manifest excluding the expired `partition_dt` entries (marking superseded manifests `EXPIRED`/`SUPERSEDED`), and update `DataCatalogEntry`.
5. **SQL Synchronization Option**: When `silver_klines` expires a `partition_dt` older than `retention_silver_days`, optionally prune matching historical rows (or mark retention boundary in `SyncCheckpoint.first_open_time`) only if SQL `klines` retention is enabled; never silently mismatch catalog and SQL without recording the watermark.

#### Phase B: Physical Object Garbage Collection (`StorageBackend` v2, S3-Safe)
1. Query `StorageBackend.list_objects(prefix)` (`IFC-DP-008`) — works identically on `LocalStorageBackend` and `S3StorageBackend` with zero `local_path()` calls.
2. Build the **protected object key set**:
   - All `object_key`s in the `ACTIVE` snapshot of every dataset.
   - All `object_key`s in the latest `N = 3` `SUPERSEDED` snapshots per dataset.
   - All `object_key`s belonging to `STAGING` snapshots or `PREPARED`/`FILES_WRITTEN` `batch_ledger` entries younger than `gc_grace_sec = 300s`.
   - Any object whose `last_modified_utc` is within `gc_grace_sec` of `now_utc`.
3. Physically `delete(key)` only unprotected objects outside the grace window.
4. **Warehouse Snapshot GC**: Protect `ACTIVE` `warehouse_snapshots`, latest `3` `SUPERSEDED` snapshots, and any snapshot younger than `60s`; delete older `dw-v*.duckdb` files cleanly.
5. **SQL & Auxiliary Table Pruning**: Bound operational audit logs (`data_quality_runs` cascading to `data_quality_results`, `data_lineage_edges`, `workflow_runs`, `batch_ledger`, `dead_letter_events` with `status != 'QUARANTINED'`) via configurable `retention_audit_days` (e.g., `30d` in `LITE`) so SQLite file size stays bounded.

### 2.4 Audit Logging & Security Alignment (`SEC-02`)
- Every manual retention run (`POST /api/v1/governance/retention/run`), catalog sync, and DLQ replay requires `require_admin_if_configured` (`ADMIN_API_TOKEN`) and writes a structured log + `workflow_runs` audit entry without exposing host filesystem paths or raw exception tracebacks in API responses.
