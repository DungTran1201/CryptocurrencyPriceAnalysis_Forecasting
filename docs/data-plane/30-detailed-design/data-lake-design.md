# Data Lake & Kline Storage Detailed Design

**Scope:** `COMP-DP-04` (LakeStorage + ManifestService), `COMP-DP-05` (OperationalDB kline upsert rules)  
**Requirements:** `REQ-DP-LAKE-01`, `REQ-DP-LAKE-02`, `REQ-DP-LAKE-03`, `REQ-DP-LAKE-04`, `REQ-DP-LAKE-05`, `REQ-DP-LAKE-06`, `REQ-DP-KLN-01`  
**ADRs & Contracts:** `ADR-DP-002`, `ADR-DP-003`, `IFC-DP-005`, `IFC-DP-008`  
**Phase 2 Work Items:** `WI-DP-04`, `WI-DP-05`

---

## 1. AS-IS Baseline & Verified Defects `[OBSERVED]`

Empirical audit of `backend/app/storage/` (`medallion.py`, `local.py`, `s3.py`, `base.py`), `backend/app/services/sync_service.py`, `backend/app/streaming/consumers.py`, and on-disk `./data/` identified seven critical integrity defects:

1. **SQL vs Silver Parquet Divergence on Open Candles (`klines` vs `silver/klines`)**:
   - `parse_kline_payload` (`sync_service.py:143`) marks `is_closed = close_dt <= now_utc` and persists `is_closed=False` bars to both SQL and Silver Parquet.
   - `save_klines_idempotent` (`sync_service.py:190`) and `MedallionStreamConsumer._upsert_closed_klines_sql` (`consumers.py:471`) skip any `open_time` already in SQL (`if ot not in existing_times` / `continue`), never promoting `is_closed=False` rows when final OHLCV arrives.
   - Meanwhile `sync_incremental` (`sync_service.py:306-316`) resumes from `max(Kline.close_time) + 1`, skipping past unclosed candles whose `close_time` is in the future.
   - Simultaneously, `MedallionStorageManager.write_silver_klines` (`medallion.py:191-192`) unconditionally overwrites `(symbol, timeframe, open_time)` in Parquet.
   - **Observed divergence on disk (`data/crypto_market.db` vs `data/silver/source=binance/event_type=klines/timeframe=1m/dt=2026-11-17/`)**:
     - `BTCUSDT 1m 2026-11-17 05:43:00`: SQL = `(close=64899.48, vol=3.0708, is_closed=0)` vs Parquet = `(close=64891.85, vol=10.09861, is_closed=True, source=binance_ws)`.
     - `ETHUSDT 1m 2026-11-17 05:43:00`: SQL = `(close=1836.22, vol=33.8946, is_closed=0)` vs Parquet = `(close=1835.93, vol=64.6021, is_closed=True, source=binance_ws)`.
2. **Non-Atomic Dual Persistence (`sync_service.py:344-359, 446-450`)**:
   - `_persist_medallion_batch` executes mid-loop before `await db.commit()` and catches exceptions with `logger.warning` (`sync_service.py:348`) or silent `except Exception: pass` (`fill_gaps`, `sync_service.py:449-450`).
   - Result: SQL commits when disk writes fail, or batch-1 files persist permanently when batch-2 rolls back SQL.
3. **Lockless Read-Modify-Write & Silent Data Loss (`medallion.py:179-205, 268-287`)**:
   - `write_silver_klines` and `_compact_trade_partition` read existing `.parquet` files, merge in Python dicts, overwrite `part-{dt_key}.parquet` / `compacted-{dt_key}.parquet`, and unlink old keys with **zero cross-process or async locking**. Concurrent writers (`MedallionStreamConsumer`, `PipelineService`, `BinanceSyncService`) cause lost updates.
   - Read exceptions during merge (`medallion.py:188-189`, `275-276`) are caught and skipped (`pass`), rewriting the partition *without* those rows and permanently deleting data.
4. **Gold Full-History Multi-Day Duplication (`medallion.py:367-375, 418`)**:
   - `materialize_gold_marts` writes the entire multi-month dataset (e.g., `ETHUSDT 15m`: 9,600 rows spanning `2026-08-09`..`2026-11-17`) into a single partition `dt={max(open_time)}` (`dt=2026-11-17/symbol=ETHUSDT/mart.parquet`).
   - Re-running on a subsequent UTC day creates a second full-history file under `dt=2026-11-18`. `read_gold_dataset` (`medallion.py:418`) reads all Parquet files via `read_parquet([...])` without snapshot isolation or deduplication, returning duplicated rows.
5. **Uncompacted `silver_agg_trades` Duplicates & Zero Gap Healing**:
   - `write_silver_trades` (`medallion.py:247-262`) writes un-deduplicated `part-*.parquet` fragments until fragment count reaches `>= 6`. Redeliveries prior to compaction create duplicate `(symbol, agg_trade_id)` rows across fragments.
   - `sync_service.py` has zero `/api/v3/aggTrades` REST backfill; `StreamPlatformRuntime._gap_heal_all` (`runtime.py:109-118`) heals only `1m` klines.
6. **Bronze Schema Mismatch & Micro-File Explosion**:
   - Streaming (`consumers.py:254`) writes `Canonical*Event` JSON (`event_id`, `event_type`); REST sync (`sync_service.py:279-289`) writes `raw_kline` arrays lacking `event_id` and `event_type`. No Bronze compaction exists (352 files for ~7 minutes of LITE runtime observed).
7. **Schema Drift & Hardcoded Versioning**:
   - `SILVER_KLINE_SCHEMA` (14 cols, `medallion.py:24-39`) drops `taker_buy_base_asset_volume` and `taker_buy_quote_asset_volume` stored in SQL `Kline`.
   - `PipelineService` (`pipeline_service.py:316`) overwrites `source="silver_sync"` across all historical Silver klines.
   - Gold writes `pa.Table.from_pandas` (`medallion.py:378, 382`) with no explicit PyArrow schema (producing `large_string` on disk vs `string` in Silver).
   - `DataCatalogEntry.version` (`governance_service.py:41-160`) is statically `"1.0.0"`.

---

## 2. TO-BE Data Lake Architecture `[PROPOSED]`

### 2.1 Immutable Object Storage Layout (`REQ-DP-LAKE-01`, `REQ-DP-LAKE-04`, `IFC-DP-005`)

Every persisted file in Bronze, Silver, and Gold is **write-once / immutable** and addressed by a run-stamped, UUID-suffixed object key. Objects are **never overwritten in place**; updates publish a new immutable file and flip the SQL `ACTIVE` snapshot manifest atomically (`ADR-DP-003`).

- **Bronze (Immutable Unified Raw Micro-Batches)**:
  - Path: `bronze/source=binance/stream={stream}/dt={YYYY-MM-DD}/symbol={SYMBOL}/part-{YYYYMMDDTHHMMSS}-{batch_id[:8]}-{uuid[:8]}.jsonl.zst`
  - Unified Bronze JSONL Envelope (`schema_version="1.1.0"`):
    ```json
    {
      "schema_version": "1.1.0",
      "event_id": "kline:BTCUSDT:1m:1763358180000:closed",
      "event_type": "kline|aggTrade|rest_kline",
      "source": "binance_ws|binance_rest",
      "symbol": "BTCUSDT",
      "timeframe": "1m",
      "event_time": "2026-11-17T05:43:59.999000",
      "ingestion_time": "2026-11-17T05:44:00.120000",
      "payload": {}
    }
    ```
  - For REST klines, `event_id` is deterministic: `rest_kline:{symbol}:{timeframe}:{open_ms}:{closed|open}`.

- **Silver Klines (Immutable Partitioned Parquet)**:
  - Path: `silver/source=binance/event_type=klines/timeframe={tf}/dt={YYYY-MM-DD}/symbol={SYMBOL}/part-{dt}-{snapshot_id[:8]}-{uuid[:8]}.parquet`
  - Partition `dt` is strictly `open_time.strftime("%Y-%m-%d")` (UTC).
  - Read queries NEVER `rglob` directories directly; they resolve the active file list from `lake_manifest_files` joined to `lake_snapshots.status = 'ACTIVE'`.

- **Silver Aggregate Trades (Immutable Partitioned Parquet)**:
  - Path: `silver/source=binance/event_type=agg_trades/dt={YYYY-MM-DD}/symbol={SYMBOL}/part-{dt}-{snapshot_id[:8]}-{uuid[:8]}.parquet`
  - Compaction writes a new immutable `compacted-{dt}-{snapshot_id[:8]}-{uuid[:8]}.parquet` (`is_compacted=True`) and publishes a new `ACTIVE` snapshot manifest referencing the compacted file in place of the superseded fragments (`REQ-DP-LAKE-03`).

- **Gold Analytics Marts & ML Feature Sets (Real `dt=` Partitioning)**:
  - Path (Analytics): `gold/dataset=analytics_marts/timeframe={tf}/dt={YYYY-MM-DD}/symbol={SYMBOL}/mart-{dt}-{snapshot_id[:8]}.parquet`
  - Path (Features): `gold/dataset=feature_sets/timeframe={tf}/dt={YYYY-MM-DD}/symbol={SYMBOL}/features-{dt}-{snapshot_id[:8]}.parquet`
  - **Fix for Multi-Day Duplication (`REQ-DP-LAKE-04`)**: Rolling-window indicators (`SMA_50`, `ATR_14`, `VOL_30`) and `extract_features` are computed over the full chronological window (including warm-up history from prior days), **then split by `open_time.dt.strftime("%Y-%m-%d")` before writing**! Each daily `dt=` partition contains *only* rows whose `open_time` belongs to that UTC date. Publishing a new `gold_*` `lake_snapshot` replaces the manifest entries for affected `(symbol, timeframe, dt)` partitions cleanly with zero cross-day duplication.

### 2.2 Explicit Arrow Schemas & Schema Evolution (`REQ-DP-LAKE-06`, `IFC-DP-005`)

All Silver and Gold Parquet writers must enforce explicit `pyarrow.Schema` contracts (never untyped `pa.Table.from_pandas`) with Snappy compression and embedded Parquet key-value metadata (`schema_version`, `schema_hash`, `snapshot_id`):

- **`SILVER_KLINE_SCHEMA` (`v1.1.0`)**: Adds nullable `taker_buy_base_asset_volume: float64` and `taker_buy_quote_asset_volume: float64` to match SQL `Kline` 1:1 (`IFC-DP-005`).
- **`SILVER_TRADE_SCHEMA` (`v1.0.0`)**: Retains `symbol`, `agg_trade_id`, `price`, `quantity`, `quote_quantity`, `is_buyer_maker`, `trade_time`, `event_time`, `ingestion_time`, `source`.
- **`GOLD_ANALYTICS_SCHEMA` (`v1.0.0`)** & **`GOLD_FEATURE_SCHEMA` (`v1.0.0`)**: Explicit `pa.string()` for `symbol`/`timeframe` (eliminating `large_string` drift), `pa.timestamp("us")` for `open_time`, and `pa.float64()` for all numeric metrics/features (`IFC-DP-005`).
- **Schema Evolution Rules**:
  1. Backward-compatible additions (new nullable columns) bump minor `schema_version` (`1.0.0 -> 1.1.0`) and recompute `schema_hash = sha256(canonical_schema_json)`.
  2. Readers pass `union_by_name=true` in DuckDB / PyArrow when reading across historical partitions within an `ACTIVE` manifest.
  3. Breaking type/column removals require a major version bump (`2.0.0`) and explicit backfill/re-materialization into a new snapshot rather than silent `except Exception` skipping.

### 2.3 SQL-Backed Snapshot Manifests & Commit Protocol (`REQ-DP-LAKE-02`, `IFC-DP-005`)

New SQL tables (defined normatively in `../40-interfaces-and-contracts/storage-and-database-schemas.md`) govern every lake commit:
- `batch_ledger`: Records batch lifecycle (`PREPARED -> FILES_WRITTEN -> COMMITTED -> ACKED` / `FAILED`) with deterministic `idempotency_key` and `staged_keys_json`.
- `lake_snapshots`: Monotonic per-dataset `version_seq`, `parent_snapshot_id`, `schema_version`, `schema_hash`, `status` (`STAGING`, `ACTIVE`, `SUPERSEDED`, `EXPIRED`), exact `total_files`, `total_rows`, `total_bytes`, and `[min_event_time, max_event_time]`.
- `lake_manifest_files`: Exact file inventory per `snapshot_id` with `object_key`, `(partition_symbol, partition_timeframe, partition_dt)`, `row_count`, `size_bytes`, `sha256`, `[min_ts, max_ts]`, and `is_compacted`.

**Atomic Write-and-Publish Protocol**:
1. Acquire per-dataset/partition advisory lock (in-process `asyncio.Lock` for `LITE` or SQL workflow task lease for `WorkflowWorker`).
2. Create `batch_ledger` (`PREPARED`) and `lake_snapshots` (`STAGING`, `parent_snapshot_id = current ACTIVE`).
3. If modifying an existing `(symbol, timeframe, dt)` Silver Kline partition:
   - Read *only* the files listed for that `(symbol, timeframe, dt)` in the `parent_snapshot_id`'s `lake_manifest_files` (never `list_keys` over orphan temp/uncommitted files!).
   - **Never swallow corrupt/missing file errors**: if a manifest-registered file fails checksum/Parquet read, abort the batch (`FAILED`) and raise for operator/DQ repair rather than overwriting and losing history.
   - Apply the canonical Open-to-Closed Upsert Rule (Section 3) and write a **new** immutable `part-{dt}-{snapshot_id[:8]}-{uuid[:8]}.parquet`.
4. For `silver_agg_trades`: When writing new fragments, merge/dedup against any uncompacted fragment in the active manifest for `(symbol, dt)` if batch overlap is possible (or track watermark `max_agg_trade_id` per partition) so even uncompacted reads have deterministic uniqueness; trigger async/scheduled compaction via `WorkflowWorker` when fragment count per `(symbol, dt)` >= `compaction_fragment_threshold` (default `6`).
5. Compute `sha256`, `size_bytes`, `row_count`, `[min_ts, max_ts]` from the in-memory Arrow buffer before/during write (`StorageBackend.write_bytes`).
6. In **one single SQL transaction** (`COMMITTED`):
   - Insert `lake_manifest_files` (carrying forward unchanged partitions from `parent_snapshot_id` + replacing modified partitions with new immutable keys).
   - Flip previous `ACTIVE` `lake_snapshots` row for `dataset_id` to `SUPERSEDED` and new snapshot to `ACTIVE`.
   - Upsert SQL `klines`, `SyncCheckpoint` / `StreamCheckpoint`, `DataLineageEdge`, and update `DataCatalogEntry` metrics directly from the new `ACTIVE` snapshot.
   - Mark `batch_ledger.status = 'COMMITTED'`.
7. If SQL commit fails: delete only `staged_keys_json` objects created by this aborted `batch_id` (best-effort orphan cleanup; `ACTIVE` snapshot remains untouched!) and NAK/fail cleanly.

### 2.4 Compaction & Grace-TTL Garbage Collection (`REQ-DP-LAKE-03`, `REQ-DP-LAKE-05`)

- **Compaction (`WorkflowWorker` scheduled/triggered task)**:
  - **Silver `agg_trades` & `klines`**: Any `(dataset_id, symbol, timeframe?, dt)` with `> 1` uncompacted files (or `>= compaction_fragment_threshold`) is merged, deduplicated by primary key (`(symbol, timeframe, open_time)` or `(symbol, agg_trade_id)`), sorted ascending, written as a single `compacted-{dt}-...parquet`, and atomically swapped into a new `ACTIVE` snapshot.
  - **Bronze Compaction**: Daily or multi-part Bronze `.jsonl.zst` files older than the active streaming hour (`> 1h` old with `>= 10` micro-batch files in the same `(stream, dt, symbol)`) are merged, deduplicated by `event_id`, re-compressed into a single `compacted-{dt}-...jsonl.zst`, and swapped into the `bronze_market_events` manifest.
- **Snapshot-Aware Garbage Collection (Safe Deletion)**:
  - An object key `K` is eligible for physical `StorageBackend.delete(K)` **only if ALL hold**:
    1. `K` is NOT referenced by the `ACTIVE` snapshot or the latest `N` retained snapshots (`retention_keep_snapshots = 3`).
    2. All snapshots referencing `K` became `SUPERSEDED` or `EXPIRED` at least `snapshot_gc_grace_sec` ago (default `300s`), protecting any concurrent DuckDB/PyArrow readers.
  - **S3-Safe Metadata Listing (`IFC-DP-008`)**: `StorageBackend.list_objects(prefix, suffix)`, `head_object(key)`, and `stat_prefix(prefix)` return typed `StorageObjectMeta(key, size_bytes, last_modified_utc, etag)` without calling `local_path()` (fixing S3 retention silent no-op).

---

## 3. Unified SQL vs Silver `Kline` Upsert & `SyncCheckpoint` Rules (`REQ-DP-KLN-01`)

### 3.1 Canonical Promotion Matrix (Identical in SQL `klines` & Silver Parquet)

On conflict `(symbol, timeframe, open_time)`:

| Existing Row (`is_closed`) | Incoming Row (`is_closed`) | Action in BOTH SQL & Silver Parquet |
|---|---|---|
| Not present | `False` or `True` | **INSERT** full row + `source` + `ingestion_time` |
| `False` (forming) | `True` (closed) | **UPDATE / PROMOTE** OHLCV, `quote_asset_volume`, `number_of_trades`, `taker_buy_*`, `close_time`, `is_closed=True`, `source` |
| `False` (forming) | `False` (newer forming tick) | **UPDATE** OHLCV & `volume` if incoming `close_time >= existing.close_time` and `volume >= existing.volume` (else keep existing) |
| `True` (closed) | `False` (stale/late forming) | **NO-OP** (never downgrade finalized candle) |
| `True` (closed) | `True` (closed) | **NO-OP** by default; **UPDATE** only when `force_reconcile=True` and OHLCV differs |

- **SQL Implementation**: Use dialect-native single-statement upsert (`sqlalchemy.dialects.sqlite.insert` / `sqlalchemy.dialects.postgresql.insert`) with `.on_conflict_do_update(index_elements=["symbol", "timeframe", "open_time"], set_={...}, where=(...))`. This eliminates `SELECT`-then-`INSERT` races (`sync_service.py:176-196`, `consumers.py:465-494`) and guarantees open-to-closed promotion.
- **Provenance Integrity**: Preserve original `source` (`binance_ws` vs `binance_rest`). `PipelineService` recomputation must read from Silver or SQL without overwriting `source` with `"silver_sync"`.

### 3.2 Incremental Sync Cursor, Gap Detection & `aggTrades` Backfill (`REQ-DP-ING-01`, `REQ-DP-KLN-01`)

1. **Safe Resume Cursor (`sync_incremental`)**:
   - Query `min_unclosed_open = SELECT MIN(open_time) FROM klines WHERE symbol=:s AND timeframe=:tf AND is_closed=false`.
   - Query `max_closed_close = SELECT MAX(close_time) FROM klines WHERE symbol=:s AND timeframe=:tf AND is_closed=true`.
   - If `min_unclosed_open` is not `NULL`, start at `datetime_to_ms(min_unclosed_open)` (re-fetching and promoting any stranded `is_closed=False` bar!). Else if `max_closed_close` is not `NULL`, start at `datetime_to_ms(max_closed_close) + 1`. Else seed from `now_utc - lookback_days_if_empty`.
   - Commit SQL + Silver snapshot **per bounded batch** (e.g., per 1000-bar Binance page) rather than holding one uncommitted transaction across multi-day loops.
   - Catch upstream/processing errors and persist `SyncCheckpoint(last_sync_status="FAILED", last_error=sanitized_code)`.
2. **Unified `SyncCheckpoint` Updates**:
   - Update `SyncCheckpoint` in the **same SQL transaction** for *both* `BinanceSyncService` and `MedallionStreamConsumer` closed-kline commits.
   - Fix `last_open_time` semantics: `last_open_time = MAX(Kline.open_time)` (both on insert and update), and add `first_open_time = MIN(Kline.open_time)` so full range bounds are explicit (`IFC-DP-005`).
3. **Complete Gap Detection (`detect_gaps`)**:
   - Reject unknown timeframes (`ValueError`, replacing silent `1h` fallback at `sync_service.py:63`).
   - Check **leading gap** (when `start_time` is provided and `open_times[0] - start_time > tolerance`), **interior gaps** (`open_times[i] - open_times[i-1] > 1.5 * delta`), and **trailing staleness gap** (`now_utc - last_closed_close_time > 1.5 * delta` when `end_time` is `None` or `> last_closed`).
4. **Aggregate Trade Sequence Gap Detection & Backfill**:
   - Track `last_agg_trade_id` per `symbol` in `SyncCheckpoint` / `StreamCheckpoint` state.
   - Detect sequence jumps (`curr_agg_id - prev_agg_id > 1`) in `silver_agg_trades` partitions or on WS reconnect.
   - Backfill missing ranges via Binance REST `GET /api/v3/aggTrades?symbol={SYM}&fromId={start_id}&limit=1000` (bounded per reconnect/workflow run via `max_aggtrade_backfill_batches` budget so REST rate limits and LITE memory are respected).
