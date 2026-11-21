# Storage, Manifest, Warehouse & Operational Database Contracts

**Contracts Defined:** `IFC-DP-005` (Data Lake Layout & Manifest SQL Schemas), `IFC-DP-006` (DuckDB Star Schema & Warehouse Snapshots), `IFC-DP-008` (StorageBackend v2 Protocol)  
**Requirements:** `REQ-DP-LAKE-01..06`, `REQ-DP-KLN-01`, `REQ-DP-DW-01..03`, `REQ-DP-CFG-01`  
**Phase 2 Work Items:** `WI-DP-04`, `WI-DP-05`, `WI-DP-06`, `WI-DP-11`

---

## 1. `IFC-DP-008`: `StorageBackend` v2 Contract (`backend/app/storage/base.py`)

To eliminate `LocalStorageBackend`-only coupling (such as `GovernanceService.enforce_retention` calling `storage.local_path(k)` and failing silently on S3), `StorageBackend` exposes object metadata natively across both `LocalStorageBackend` and `S3StorageBackend`:

```python
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

@dataclass(frozen=True)
class StorageObjectMeta:
    key: str
    size_bytes: int
    last_modified_utc: datetime
    etag: Optional[str] = None

class StorageBackend(ABC):
    @abstractmethod
    def resolve_uri(self, key: str) -> str: ...
    @abstractmethod
    def write_bytes(self, key: str, data: bytes) -> int: ...  # atomic tmp+fsync+replace locally; put_object on S3
    @abstractmethod
    def read_bytes(self, key: str) -> bytes: ...
    @abstractmethod
    def exists(self, key: str) -> bool: ...
    @abstractmethod
    def list_keys(self, prefix: str = "", suffix: str = "") -> List[str]: ...
    @abstractmethod
    def list_objects(self, prefix: str = "", suffix: str = "") -> List[StorageObjectMeta]: ...
    @abstractmethod
    def head_object(self, key: str) -> Optional[StorageObjectMeta]: ...
    @abstractmethod
    def delete(self, key: str) -> bool: ...
    @abstractmethod
    def stat_prefix(self, prefix: str = "") -> Dict[str, Any]: ...
    def local_path(self, key: str) -> Path:
        """Optional POSIX/Windows path for direct DuckDB read; raises NotImplementedError on S3."""
        raise NotImplementedError
```

- **`LocalStorageBackend` (`local.py`)**: Retains `_safe_path` traversal guard and atomic `.tmp` + `fsync` + `os.replace`. `list_objects` returns `StorageObjectMeta` using `stat()` (`st_mtime` converted to UTC naive `datetime`) in one pass.
- **`S3StorageBackend` (`s3.py`)**: Implements `list_objects` from `list_objects_v2` (`Size`, `LastModified`, `ETag`) and `head_object` from `head_object`. In `__init__`, `head_bucket` only invokes `create_bucket` on `404`/`NoSuchBucket` `ClientError` (never swallowing auth/network errors).

---

## 2. `IFC-DP-005`: Data Lake Paths, Arrow Schemas & SQL Manifest DDL

### 2.1 Object Key Formats
| Layer / Dataset | Canonical Relative Key Pattern |
|---|---|
| `bronze_market_events` | `bronze/source=binance/stream={stream}/dt={YYYY-MM-DD}/symbol={SYMBOL}/part-{YYYYMMDDTHHMMSS}-{batch8}-{uuid8}.jsonl.zst` |
| `silver_klines` (uncompacted) | `silver/source=binance/event_type=klines/timeframe={tf}/dt={YYYY-MM-DD}/symbol={SYMBOL}/part-{dt}-{snap8}-{uuid8}.parquet` |
| `silver_klines` (compacted) | `silver/source=binance/event_type=klines/timeframe={tf}/dt={YYYY-MM-DD}/symbol={SYMBOL}/compacted-{dt}-{snap8}-{uuid8}.parquet` |
| `silver_agg_trades` (part / compacted) | `silver/source=binance/event_type=agg_trades/dt={YYYY-MM-DD}/symbol={SYMBOL}/{part\|compacted}-{dt}-{snap8}-{uuid8}.parquet` |
| `gold_analytics_marts` | `gold/dataset=analytics_marts/timeframe={tf}/dt={YYYY-MM-DD}/symbol={SYMBOL}/mart-{dt}-{snap8}.parquet` |
| `gold_feature_sets` | `gold/dataset=feature_sets/timeframe={tf}/dt={YYYY-MM-DD}/symbol={SYMBOL}/features-{dt}-{snap8}.parquet` |

### 2.2 Explicit PyArrow Schemas (`REQ-DP-LAKE-06`)

1. **`SILVER_KLINE_SCHEMA` (`version = "1.1.0"`)**:
   ```text
   symbol: string (not null)
   timeframe: string (not null)
   open_time: timestamp[us] (not null)
   close_time: timestamp[us] (not null)
   open: float64 (not null)
   high: float64 (not null)
   low: float64 (not null)
   close: float64 (not null)
   volume: float64 (not null)
   quote_asset_volume: float64 (nullable)
   number_of_trades: int64 (nullable)
   taker_buy_base_asset_volume: float64 (nullable)
   taker_buy_quote_asset_volume: float64 (nullable)
   is_closed: bool (not null)
   source: string (not null)
   ingestion_time: timestamp[us] (not null)
   ```
2. **`SILVER_TRADE_SCHEMA` (`version = "1.0.0"`)**:
   `symbol: string`, `agg_trade_id: int64`, `price: float64`, `quantity: float64`, `quote_quantity: float64`, `is_buyer_maker: bool`, `trade_time: timestamp[us]`, `event_time: timestamp[us]`, `ingestion_time: timestamp[us]`, `source: string`.
3. **`GOLD_ANALYTICS_SCHEMA` (`version = "1.0.0"`)**:
   `symbol: string`, `timeframe: string`, `open_time: timestamp[us]`, `close: float64`, `volume: float64`, `simple_return: float64`, `log_return: float64`, `atr_14: float64`, `vwap: float64`, `vol_7_ann_pct: float64`, `vol_14_ann_pct: float64`, `vol_30_ann_pct: float64`, `running_peak: float64`, `drawdown_pct: float64`.
4. **`GOLD_FEATURE_SCHEMA` (`version = "1.0.0"`)**:
   `symbol: string`, `timeframe: string`, `open_time: timestamp[us]`, `close: float64`, plus all 25 float64 feature columns from `ml.features.extract_features` (`return_1..24`, `ratio_*`, `volatility_*`, `rsi_*`, `boll_pct_b`, `macd_*`, `atr_norm`, `volume_*`, `lag_return_1..3`).

### 2.3 SQL Operational & Manifest Tables (Alembic Single Migration in `WI-DP-05`)

All `DateTime` columns store UTC-naive timestamps consistently across SQLite and PostgreSQL (`TIMESTAMP WITHOUT TIME ZONE`). All byte counts, row counts, sequence numbers, and trade IDs use `BigInteger` (preventing PostgreSQL 32-bit `INTEGER` overflow above `2 GiB`, e.g., `EXTENDED` 4,096 MB retention cap).

```sql
-- 1. Micro-Batch / Ingestion Commit Ledger
CREATE TABLE batch_ledger (
    batch_id VARCHAR(36) PRIMARY KEY,
    batch_type VARCHAR(32) NOT NULL,         -- STREAM_MICROBATCH | REST_BACKFILL | PARQUET_COMPACTION | GOLD_MATERIALIZE | WAREHOUSE_BUILD
    producer_name VARCHAR(64) NOT NULL,
    symbol VARCHAR(32),
    timeframe VARCHAR(16),
    idempotency_key VARCHAR(128) NOT NULL UNIQUE,
    status VARCHAR(24) NOT NULL,             -- PREPARED | FILES_WRITTEN | COMMITTED | ACKED | FAILED
    nats_seq_start BIGINT,
    nats_seq_end BIGINT,
    records_received INTEGER NOT NULL DEFAULT 0,
    records_written INTEGER NOT NULL DEFAULT 0,
    records_rejected INTEGER NOT NULL DEFAULT 0,
    staged_keys_json TEXT,
    snapshot_id VARCHAR(36),
    error_code VARCHAR(64),
    created_at TIMESTAMP NOT NULL,
    committed_at TIMESTAMP,
    acked_at TIMESTAMP
);
CREATE INDEX ix_batch_ledger_status ON batch_ledger (status, created_at);

-- 2. Immutable Dataset Snapshot Version Table
CREATE TABLE lake_snapshots (
    snapshot_id VARCHAR(36) PRIMARY KEY,
    dataset_id VARCHAR(64) NOT NULL,
    version_seq BIGINT NOT NULL,
    parent_snapshot_id VARCHAR(36),
    schema_version VARCHAR(32) NOT NULL,
    schema_hash VARCHAR(64) NOT NULL,
    batch_id VARCHAR(36) REFERENCES batch_ledger(batch_id) ON DELETE SET NULL,
    status VARCHAR(24) NOT NULL,             -- STAGING | ACTIVE | SUPERSEDED | EXPIRED
    total_files INTEGER NOT NULL DEFAULT 0,
    total_rows BIGINT NOT NULL DEFAULT 0,
    total_bytes BIGINT NOT NULL DEFAULT 0,
    min_event_time TIMESTAMP,
    max_event_time TIMESTAMP,
    created_at TIMESTAMP NOT NULL,
    published_at TIMESTAMP,
    CONSTRAINT uq_lake_snapshot_ds_ver UNIQUE (dataset_id, version_seq)
);
CREATE INDEX ix_lake_snapshots_ds_status ON lake_snapshots (dataset_id, status);

-- 3. Snapshot Manifest File Inventory
CREATE TABLE lake_manifest_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,    -- PostgreSQL: SERIAL / IDENTITY
    snapshot_id VARCHAR(36) NOT NULL REFERENCES lake_snapshots(snapshot_id) ON DELETE CASCADE,
    object_key VARCHAR(512) NOT NULL,
    partition_symbol VARCHAR(32),
    partition_timeframe VARCHAR(16),
    partition_dt VARCHAR(10),
    file_format VARCHAR(16) NOT NULL,        -- PARQUET | JSONL_ZSTD
    row_count BIGINT NOT NULL,
    size_bytes BIGINT NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    min_ts TIMESTAMP,
    max_ts TIMESTAMP,
    is_compacted BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL,
    CONSTRAINT uq_manifest_snap_key UNIQUE (snapshot_id, object_key)
);
CREATE INDEX ix_manifest_lookup ON lake_manifest_files (snapshot_id, partition_symbol, partition_timeframe, partition_dt);

-- 4. Warehouse Snapshot Pointer & GC Ledger
CREATE TABLE warehouse_snapshots (
    dw_snapshot_id VARCHAR(36) PRIMARY KEY,
    warehouse_version BIGINT NOT NULL UNIQUE,
    source_lake_snapshot_id VARCHAR(36) REFERENCES lake_snapshots(snapshot_id) ON DELETE SET NULL,
    file_path VARCHAR(512) NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    size_bytes BIGINT NOT NULL,
    row_count_total BIGINT NOT NULL DEFAULT 0,
    status VARCHAR(24) NOT NULL,             -- STAGING | ACTIVE | SUPERSEDED | EXPIRED
    created_at TIMESTAMP NOT NULL,
    published_at TIMESTAMP
);
CREATE INDEX ix_warehouse_snap_status ON warehouse_snapshots (status, warehouse_version);

-- 5. Durable Workflow Orchestration Tables (IFC-DP-007, COMP-DP-09, ADR-DP-006)
CREATE TABLE workflow_runs (
    id VARCHAR(36) PRIMARY KEY,
    workflow_type VARCHAR(32) NOT NULL,      -- MEDALLION_DAG | MARKET_SYNC | GAP_HEAL | PARQUET_COMPACT | WAREHOUSE_BUILD | ML_TRAIN | FORECAST_RECONCILE | RETENTION_ENFORCE
    symbol VARCHAR(32),
    timeframe VARCHAR(16),
    trigger_type VARCHAR(24) NOT NULL,       -- MANUAL | SCHEDULED | RECONNECT | RETRY
    idempotency_key VARCHAR(128) NOT NULL,
    status VARCHAR(24) NOT NULL,             -- QUEUED | RUNNING | RETRY_WAIT | SUCCESS | FAILED | CANCELLED
    priority INTEGER NOT NULL DEFAULT 5,
    attempt INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    next_run_at TIMESTAMP NOT NULL,
    lease_owner VARCHAR(64),
    lease_token VARCHAR(36),
    lease_expires_at TIMESTAMP,
    heartbeat_at TIMESTAMP,
    params_json TEXT,
    result_json TEXT,
    error_code VARCHAR(64),
    error_summary VARCHAR(512),              -- Sanitized public summary only (no raw str(e))
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    duration_seconds DOUBLE PRECISION,
    created_at TIMESTAMP NOT NULL
);
CREATE INDEX ix_workflow_runs_claim ON workflow_runs (status, next_run_at, priority);
CREATE INDEX ix_workflow_runs_lease ON workflow_runs (status, lease_expires_at);
CREATE UNIQUE INDEX uq_workflow_active_idempotency
    ON workflow_runs (idempotency_key)
    WHERE status IN ('QUEUED', 'RUNNING', 'RETRY_WAIT');

CREATE TABLE workflow_tasks (
    id VARCHAR(36) PRIMARY KEY,
    run_id VARCHAR(36) NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
    task_name VARCHAR(64) NOT NULL,
    sequence_order INTEGER NOT NULL,
    depends_on VARCHAR(128),
    status VARCHAR(24) NOT NULL,             -- PENDING | RUNNING | SUCCESS | FAILED | SKIPPED
    attempt INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 2,
    checkpoint_json TEXT,
    records_processed BIGINT NOT NULL DEFAULT 0,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    duration_seconds DOUBLE PRECISION,
    error_code VARCHAR(64),
    error_summary VARCHAR(512)
);
CREATE INDEX ix_workflow_tasks_run_seq ON workflow_tasks (run_id, sequence_order);

CREATE TABLE workflow_schedules (
    schedule_id VARCHAR(64) PRIMARY KEY,
    workflow_type VARCHAR(32) NOT NULL,
    symbol VARCHAR(32),
    timeframe VARCHAR(16),
    interval_seconds INTEGER NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    params_json TEXT,
    last_run_id VARCHAR(36) REFERENCES workflow_runs(id) ON DELETE SET NULL,
    last_triggered_at TIMESTAMP,
    next_trigger_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);
```

### 2.4 Updates to Existing ORM Tables (`WI-DP-05`)
- **`data_catalog_entries` (`models/governance.py`)**: Alter `row_count` and `size_bytes` to `BigInteger`; add `active_snapshot_id VARCHAR(36) NULL` and `schema_hash VARCHAR(64) NULL`.
- **`stream_checkpoints` (`models/governance.py`)**: Alter `last_stream_seq`, `processed_count`, `error_count` to `BigInteger`.
- **`sync_checkpoints` (`models/market.py`)**: Add `first_open_time TIMESTAMP NULL`, `last_agg_trade_id BIGINT NULL`, `completeness_status VARCHAR(24) NOT NULL DEFAULT 'UNPOPULATED'`; fix `last_open_time` to track `MAX(Kline.open_time)` on both insert and update.
- **`klines` (`models/market.py`)**: Drop redundant `ix_kline_lookup` (covered by `uq_symbol_tf_opentime` prefix) to reduce SQLite write-index overhead; add `completeness` / `is_closed` query index if benchmarked necessary.
- **SQLite & PostgreSQL Engine Hygiene (`core/database.py`, `requirements.txt`, `docker/`)**:
  - **PostgreSQL Sync Driver Fix (`REQ-DP-CFG-01`)**: Add `psycopg[binary]>=3.2.0,<4.0` to `requirements.txt` and normalize `postgresql://` -> `postgresql+psycopg://` in `Settings` / `alembic/env.py` for synchronous `alembic upgrade head` and `sync_engine` (`asyncpg` alone causes `ModuleNotFoundError` in `STANDARD`/`EXTENDED` Docker deployments).
  - **SQLite Connection & Transaction Hygiene**: Remove unconditional `await session.commit()` on teardown in `get_db()` (`database.py:107`) — callers performing writes commit explicitly; read-only `GET` handlers never issue unnecessary commits. Replace per-call `NullPool` connection churn with bounded `AsyncAdaptedQueuePool` (or pooled SQLite WAL with `busy_timeout=15000` consistent with `timeout=30` and `foreign_keys=ON` verified).
  - **Docker Migrations**: Run `alembic upgrade head` in container entrypoint before `uvicorn` or `stream_worker` starts, rather than relying solely on `Base.metadata.create_all`.

---

## 3. `IFC-DP-006`: DuckDB Persistent Warehouse Star Schema DDL

Executed exclusively by `WarehouseService` against `data/warehouse/staging/dw_staging.duckdb`:

```sql
CREATE TABLE IF NOT EXISTS dim_symbol (
    symbol_key INTEGER PRIMARY KEY,
    symbol VARCHAR NOT NULL UNIQUE,
    base_asset VARCHAR NOT NULL,
    quote_asset VARCHAR NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    first_seen_at TIMESTAMP,
    last_synced_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS dim_timeframe (
    timeframe_key INTEGER PRIMARY KEY,
    timeframe VARCHAR NOT NULL UNIQUE,
    interval_seconds INTEGER NOT NULL,
    periods_per_year INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_date (
    date_key INTEGER PRIMARY KEY,              -- YYYYMMDD
    full_date DATE NOT NULL UNIQUE,
    year SMALLINT NOT NULL,
    quarter TINYINT NOT NULL,
    month TINYINT NOT NULL,
    day TINYINT NOT NULL,
    day_of_week TINYINT NOT NULL,
    is_weekend BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS fact_kline_bar (
    symbol_key INTEGER NOT NULL,
    timeframe_key INTEGER NOT NULL,
    date_key INTEGER NOT NULL,
    open_time TIMESTAMP NOT NULL,
    close_time TIMESTAMP NOT NULL,
    open DOUBLE NOT NULL,
    high DOUBLE NOT NULL,
    low DOUBLE NOT NULL,
    close DOUBLE NOT NULL,
    volume DOUBLE NOT NULL,
    quote_asset_volume DOUBLE,
    number_of_trades BIGINT,
    taker_buy_base_asset_volume DOUBLE,
    taker_buy_quote_asset_volume DOUBLE,
    is_closed BOOLEAN NOT NULL,
    simple_return DOUBLE,
    log_return DOUBLE,
    typical_price DOUBLE,
    source VARCHAR NOT NULL,
    ingested_at TIMESTAMP NOT NULL,
    PRIMARY KEY (symbol_key, timeframe_key, open_time)
);

CREATE TABLE IF NOT EXISTS fact_risk_daily (
    symbol_key INTEGER NOT NULL,
    timeframe_key INTEGER NOT NULL,
    date_key INTEGER NOT NULL,
    bar_count INTEGER NOT NULL,
    expected_bars INTEGER NOT NULL,
    completeness_pct DOUBLE NOT NULL,
    day_open DOUBLE NOT NULL,
    day_high DOUBLE NOT NULL,
    day_low DOUBLE NOT NULL,
    day_close DOUBLE NOT NULL,
    total_volume DOUBLE NOT NULL,
    total_quote_volume DOUBLE,
    daily_return_pct DOUBLE,
    realized_vol_ann_pct DOUBLE,
    atr_14_last DOUBLE,
    vwap_session DOUBLE,
    var_95_pct DOUBLE,
    cvar_95_pct DOUBLE,
    max_drawdown_pct DOUBLE,
    computed_at TIMESTAMP NOT NULL,
    PRIMARY KEY (symbol_key, timeframe_key, date_key)
);

CREATE TABLE IF NOT EXISTS warehouse_checkpoints (
    dataset_name VARCHAR PRIMARY KEY,
    warehouse_version BIGINT NOT NULL,
    source_snapshot_id VARCHAR,
    last_open_time TIMESTAMP,
    rows_loaded BIGINT NOT NULL,
    built_at TIMESTAMP NOT NULL
);

CREATE OR REPLACE VIEW mart_market_overview AS
SELECT
    s.symbol,
    tf.timeframe,
    k.open_time,
    k.close_time,
    k.close,
    k.volume,
    k.simple_return,
    k.is_closed,
    k.source
FROM fact_kline_bar k
JOIN dim_symbol s ON k.symbol_key = s.symbol_key
JOIN dim_timeframe tf ON k.timeframe_key = tf.timeframe_key;

CREATE OR REPLACE VIEW mart_risk_summary AS
SELECT
    s.symbol,
    tf.timeframe,
    d.full_date,
    r.bar_count,
    r.expected_bars,
    r.completeness_pct,
    r.day_close,
    r.total_volume,
    r.daily_return_pct,
    r.realized_vol_ann_pct,
    r.atr_14_last,
    r.vwap_session,
    r.var_95_pct,
    r.cvar_95_pct,
    r.max_drawdown_pct
FROM fact_risk_daily r
JOIN dim_symbol s ON r.symbol_key = s.symbol_key
JOIN dim_timeframe tf ON r.timeframe_key = tf.timeframe_key
JOIN dim_date d ON r.date_key = d.date_key;

CREATE OR REPLACE VIEW mart_data_completeness AS
SELECT
    s.symbol,
    tf.timeframe,
    d.full_date,
    r.bar_count,
    r.expected_bars,
    (r.expected_bars - r.bar_count) AS missing_bars,
    r.completeness_pct
FROM fact_risk_daily r
JOIN dim_symbol s ON r.symbol_key = s.symbol_key
JOIN dim_timeframe tf ON r.timeframe_key = tf.timeframe_key
JOIN dim_date d ON r.date_key = d.date_key;
```
