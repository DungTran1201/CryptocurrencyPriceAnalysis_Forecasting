# ADR-DP-003: Immutable Parquet Data Lake & SQL-Backed Snapshot Manifests

- **Status:** Accepted (Phase 1 Baseline)
- **Date:** 2026-11-17
- **Supersedes:** Mutable partition write pattern in `docs/40-adr/ADR-003-hybrid-medallion-storage-parquet-duckdb-sqlite-postgres.md`
- **Linked Requirements:** `REQ-DP-LAKE-01..06`, `REQ-DP-KLN-01`, `REQ-DP-SEC-03`
- **Linked Components:** `COMP-DP-04`, `COMP-DP-05`, `COMP-DP-10`

---

## 1. Context & Observed Evidence (`OBSERVED` `#7`, `#9`)
1. **Lockless In-Place Parquet Overwrites (`medallion.py:179-205`):** `write_silver_klines` reads all files in `dt={dt_key}`, merges in memory, overwrites `part-{dt_key}.parquet`, and deletes old fragments without concurrency control. Concurrent writes from `MedallionStreamConsumer`, `PipelineService`, and `BinanceSyncService` risk lost updates and reader `FileNotFoundError`. Errors reading existing fragments are caught and dropped silently (`188-189, 275-276`).
2. **Gold Multi-Day Duplication (`medallion.py:367-375, 407-419`):** `materialize_gold_marts` writes the entire historical DataFrame into `dt={max(open_time)}`. Subsequent days create overlapping multi-day files read back together by `read_gold_dataset` with zero deduplication.
3. **SQL vs Silver Divergence (`data/crypto_market.db` vs `data/silver/` `#9`):** Observed on disk that `BTCUSDT 1m` and `ETHUSDT 1m` (`05:43`) have `is_closed=0` in SQL vs `is_closed=True` in Silver Parquet because `save_klines_idempotent` (`sync_service.py:190`) and `_upsert_closed_klines_sql` (`consumers.py:471`) skip existing `open_time` keys instead of promoting open bars.
4. **Missing Manifests, Versioning & Retention Hazards (`governance_service.py:175-282, 458-520`):** `list_catalog` runs DuckDB scans (capped at 5000 rows) and commits SQL updates inside `GET` endpoints. `enforce_retention` uses filesystem `st_mtime` (bypassed on backfill rewrites), invokes `local_path` (breaks `S3StorageBackend`), and can delete active Gold files.
5. **Schema Drift (`medallion.py:24-39,378`, `governance_service.py:31-168`):** `SILVER_KLINE_SCHEMA` omits `taker_buy_*`; Gold relies on Pandas Arrow inference (`large_string`); WS and REST Bronze envelopes diverge.

## 2. Options Considered
1. **Option A — Adopt Apache Iceberg / Delta Lake (`pyiceberg` / `deltalake`):** Rejected; introduces heavy external dependency trees (`#6`, `AGENTS.md` Rule 10) and complexity unnecessary when we already have an ACID SQL metadata DB (`SQLite WAL` / `PostgreSQL`).
2. **Option B — Continue In-Place Parquet Overwrites with OS File Locks (`fcntl`/`msvcrt`):** Rejected; does not prevent TOCTOU reader errors, does not work over `S3StorageBackend` (`MinIO`), and offers no point-in-time snapshot rollback or lineage tie-in.
3. **Option C — Immutable Batch-Stamped Parquet Objects + SQL Snapshot Manifests (`PROPOSED`):** Write immutable Parquet objects and manage dataset state atomically via `lake_snapshots`, `lake_manifest_files`, and `batch_ledger` in SQLite/PostgreSQL.

## 3. Decision
Adopt **Option C**:
1. **Immutable Parquet Objects (`REQ-DP-LAKE-01`, `IFC-DP-005`):**
   - Silver and Gold writers emit new immutable batch-stamped files (`part-{dt}-{batch_id[:8]}.parquet`), partitioned strictly by each record's true UTC `open_time` date `dt=YYYY-MM-DD` (eliminating `dt={max_date}` Gold duplication).
   - Corrupt fragment exceptions raise explicitly and abort/NAK rather than silently dropping historical rows.
2. **SQL Snapshot Manifests (`REQ-DP-LAKE-02`):**
   - Each Lake write stages immutable files, populates `lake_snapshots` (`STAGING`) + `lake_manifest_files` (URI, row count, byte size, SHA-256, timestamp bounds) + `batch_ledger`, and atomically flips the previous `ACTIVE` snapshot to `SUPERSEDED` and the new snapshot to `ACTIVE` inside a single SQL transaction.
   - `DataCatalogEntry` (`row_count`/`size_bytes` upgraded to `BigInteger`) derives totals from `ACTIVE` `lake_snapshots` during writer/workflow commits—**zero DB writes on `GET` requests**.
3. **Compaction & Deferred Grace-TTL GC (`REQ-DP-LAKE-03`, `REQ-DP-LAKE-05`):**
   - Compaction writes a new merged Parquet object, atomically commits a new `ACTIVE` snapshot, and retains superseded physical files for at least a grace TTL (`>= 60s`) before deletion so concurrent readers never hit `FileNotFoundError`.
   - Retention evaluates partition `dt=` age and size budgets using `StorageBackend` v2 metadata (`IFC-DP-008`, no `local_path`), never deleting files referenced by an `ACTIVE` snapshot or pending `warehouse_checkpoints`.
4. **Unified Upsert & Explicit Arrow Schemas (`REQ-DP-KLN-01`, `REQ-DP-LAKE-06`):**
   - Unify Bronze WS/REST envelope; add `taker_buy_*` to `SILVER_KLINE_SCHEMA`; enforce explicit `GOLD_ANALYTICS_SCHEMA` & `GOLD_FEATURE_SCHEMA` (`pa.string()`).
   - Enforce identical `open->closed` promotion rules in both SQL (`ON CONFLICT DO UPDATE`) and Silver Parquet merges, plus accurate `SyncCheckpoint` tracking.

## 4. Consequences
- **Positive:** Eliminates concurrent writer corruption, Gold duplicate rows, SQL/Silver divergence, S3 retention breakage, and `GET`-endpoint DB mutations; gives full point-in-time auditability.
- **Negative / Mitigation:** Without periodic compaction, immutable micro-batching creates multiple small Parquet files per day. Scheduled `WorkflowEngine` compaction (`REQ-DP-LAKE-03`, `REQ-DP-ORC-03`) merges fragments while keeping manifests compact.
