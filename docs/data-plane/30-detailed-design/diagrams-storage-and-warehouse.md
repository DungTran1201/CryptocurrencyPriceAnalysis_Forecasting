# Storage & Data Warehouse Diagrams

All diagrams strictly denote `[AS-IS]` (observed current state), `[TO-BE]` (target architecture), or `[TRANSITION]`.

---

## 1. `[AS-IS]` Medallion Flow & Observed Divergence Hazards

```mermaid
flowchart LR
    WS["Binance WS\n(aggTrade, kline_1m)"] -->|"In-memory queue -> NATS"| CONS["MedallionStreamConsumer"]
    REST["Binance REST\n(/klines only)"] --> SYNC["BinanceSyncService"]

    CONS -->|"Writes canonical JSON\n(.jsonl.zst)"| BRZ["data/bronze/"]
    SYNC -->|"Writes raw_kline JSON\n(schema mismatch)"| BRZ

    CONS -->|"Lockless overwrite\npart-{dt}.parquet"| SIL_K["data/silver/klines/"]
    SYNC -->|"Lockless overwrite\npart-{dt}.parquet"| SIL_K
    CONS -->|"Appends until >=6 files,\nthen compacts"| SIL_T["data/silver/agg_trades/"]

    CONS -->|"INSERT if open_time missing\n(never promotes is_closed=0->1)"| SQL["SQLite/PG klines\n(Observed divergence 05:43)"]
    SYNC -->|"INSERT only; skips unclosed\ncursor & swallows disk errors"| SQL

    SQL -->|"PipelineService reads SQL;\nrewrites Silver source='silver_sync'"| SIL_K
    SQL -->|"Writes full history under\ndt=max(open_time)"| GLD["data/gold/\n(Multi-day dup hazard)"]
    GLD -->|"Ephemeral :memory: DuckDB\n(Explorer/Catalog limit=5000)"| API["FastAPI Read APIs"]
    SQL -->|"All Analytics, DQ, ML, Market\nread SQL directly"| API
```

---

## 2. `[TO-BE]` Immutable Lake, SQL Manifests & DuckDB Warehouse Flow

```mermaid
flowchart LR
    WS["Binance WS + REST\n(klines & /aggTrades)"] -->|"Canonical v1.1"| BRZ_W["Immutable Bronze Writer\n(unified envelope .jsonl.zst)"]
    BRZ_W -->|"Object + sha256"| OBJ_B["Bronze Objects"]

    PROC["StreamProcessor /\nSyncService (Upsert)"] -->|"Immutable Parquet\npart-{dt}-{snap}-{uuid}.parquet"| OBJ_S["Silver Objects\n(klines + agg_trades)"]
    PROC -->|"Single SQL TX:\nON CONFLICT DO UPDATE +\nManifest Flip"| META["Operational DB\n(klines, batch_ledger,\nlake_snapshots, lake_manifest_files)"]
    OBJ_B -.->|"Manifest tracked"| META
    OBJ_S -->|"Manifest tracked"| META

    META -->|"WorkflowWorker lease:\nIncremental Gold ETL\n(split by real open_time dt)"| OBJ_G["Gold Parquet Objects\n(mart & features)"]
    OBJ_G -->|"Manifest Flip"| META

    OBJ_S -->|"Incremental load\nvia ACTIVE manifest"| STG["DuckDB Staging\n(dw_staging.duckdb\nSingle Writer)"]
    STG -->|"CHECKPOINT + close()\n+ copyfile + os.replace"| SNAP["Immutable Snapshots\n(dw-v{N}.duckdb)"]
    SNAP -->|"read_only=True\n(Concurrent Readers)"| API["FastAPI Analytics &\nData Explorer APIs"]
    META -->|"warehouse_snapshots\nACTIVE pointer"| API
```

---

## 3. `[TO-BE]` Operational Metadata & Manifest ERD

```mermaid
erDiagram
    SYMBOLS ||--o{ KLINES : "logical symbol"
    SYMBOLS ||--o{ SYNC_CHECKPOINTS : "logical symbol"

    BATCH_LEDGER ||--o| LAKE_SNAPSHOTS : "produces"
    LAKE_SNAPSHOTS ||--o{ LAKE_MANIFEST_FILES : "contains"
    DATA_CATALOG_ENTRIES ||--o| LAKE_SNAPSHOTS : "active_snapshot_id"
    LAKE_SNAPSHOTS ||--o{ WAREHOUSE_SNAPSHOTS : "source_lake_snapshot_id"

    WORKFLOW_RUNS ||--|{ WORKFLOW_TASKS : "owns"
    WORKFLOW_SCHEDULES ||--o{ WORKFLOW_RUNS : "triggers"
    WORKFLOW_RUNS ||--o{ DATA_LINEAGE_EDGES : "run_id"

    DATA_QUALITY_RUNS ||--|{ DATA_QUALITY_RESULTS : "contains"
    MODEL_REGISTRY ||--|{ MODEL_EVALUATION_METRICS : "evaluates"

    BATCH_LEDGER {
        string batch_id PK
        string batch_type
        string idempotency_key UK
        string status
        bigint nats_seq_start
        bigint nats_seq_end
        string snapshot_id FK
        datetime committed_at
        datetime acked_at
    }

    LAKE_SNAPSHOTS {
        string snapshot_id PK
        string dataset_id
        bigint version_seq
        string parent_snapshot_id
        string schema_version
        string schema_hash
        string status
        int total_files
        bigint total_rows
        bigint total_bytes
        datetime published_at
    }

    LAKE_MANIFEST_FILES {
        int id PK
        string snapshot_id FK
        string object_key
        string partition_symbol
        string partition_timeframe
        string partition_dt
        bigint row_count
        bigint size_bytes
        string sha256
        boolean is_compacted
    }

    WAREHOUSE_SNAPSHOTS {
        string dw_snapshot_id PK
        bigint warehouse_version UK
        string source_lake_snapshot_id FK
        string file_path
        string sha256
        bigint size_bytes
        string status
        datetime published_at
    }

    WORKFLOW_RUNS {
        string id PK
        string workflow_type
        string symbol
        string timeframe
        string trigger_type
        string idempotency_key UK
        string status
        int priority
        int attempt
        int max_attempts
        datetime next_run_at
        string lease_owner
        string lease_token
        datetime lease_expires_at
        datetime heartbeat_at
        text params_json
        string error_code
        string error_summary
    }

    WORKFLOW_TASKS {
        string id PK
        string run_id FK
        string task_name
        int sequence_order
        string status
        int attempt
        int max_attempts
        text checkpoint_json
        bigint records_processed
        string error_code
        string error_summary
    }

    WORKFLOW_SCHEDULES {
        string schedule_id PK
        string workflow_type
        string symbol
        string timeframe
        int interval_seconds
        boolean enabled
        string last_run_id
        datetime next_trigger_at
    }
```

---

## 4. `[TO-BE]` Persistent DuckDB Warehouse Star Schema

```mermaid
erDiagram
    DIM_SYMBOL ||--o{ FACT_KLINE_BAR : "symbol_key"
    DIM_TIMEFRAME ||--o{ FACT_KLINE_BAR : "timeframe_key"
    DIM_DATE ||--o{ FACT_KLINE_BAR : "date_key"

    DIM_SYMBOL ||--o{ FACT_RISK_DAILY : "symbol_key"
    DIM_TIMEFRAME ||--o{ FACT_RISK_DAILY : "timeframe_key"
    DIM_DATE ||--o{ FACT_RISK_DAILY : "date_key"

    DIM_SYMBOL {
        int symbol_key PK
        string symbol UK
        string base_asset
        string quote_asset
        boolean is_active
        timestamp first_seen_at
        timestamp last_synced_at
    }

    DIM_TIMEFRAME {
        int timeframe_key PK
        string timeframe UK
        int interval_seconds
        int periods_per_year
    }

    DIM_DATE {
        int date_key PK
        date full_date UK
        smallint year
        tinyint quarter
        tinyint month
        tinyint day
        tinyint day_of_week
        boolean is_weekend
    }

    FACT_KLINE_BAR {
        int symbol_key PK
        int timeframe_key PK
        int date_key
        timestamp open_time PK
        timestamp close_time
        double open
        double high
        double low
        double close
        double volume
        double quote_asset_volume
        bigint number_of_trades
        double taker_buy_base_asset_volume
        double taker_buy_quote_asset_volume
        boolean is_closed
        double simple_return
        double log_return
        double typical_price
        string source
        timestamp ingested_at
    }

    FACT_RISK_DAILY {
        int symbol_key PK
        int timeframe_key PK
        int date_key PK
        int bar_count
        int expected_bars
        double completeness_pct
        double day_open
        double day_high
        double day_low
        double day_close
        double total_volume
        double total_quote_volume
        double daily_return_pct
        double realized_vol_ann_pct
        double atr_14_last
        double vwap_session
        double var_95_pct
        double cvar_95_pct
        double max_drawdown_pct
        timestamp computed_at
    }

    WAREHOUSE_CHECKPOINTS {
        string dataset_name PK
        bigint warehouse_version
        string source_snapshot_id
        timestamp last_open_time
        bigint rows_loaded
        timestamp built_at
    }
```

---

## 5. `[TO-BE]` Warehouse Snapshot Publish & Concurrent Reader Sequence

```mermaid
sequenceDiagram
    participant WW as WorkflowWorker Single Writer
    participant STG as dw_staging.duckdb
    participant FS as snapshots/dw-vN.duckdb
    participant SQL as SQL warehouse_snapshots
    participant API as FastAPI Reader

    WW->>SQL: Acquire WAREHOUSE_BUILD lease
    WW->>STG: connect with read_only=False
    WW->>STG: Load incremental ACTIVE Silver Parquet and upsert facts and dims
    WW->>STG: COMMIT and CHECKPOINT
    WW->>STG: close to release Windows OS RW lock
    WW->>FS: copyfile staging to tmp, fsync, and os.replace dw-vN
    WW->>SQL: TX mark previous SUPERSEDED, insert ACTIVE, update LATEST
    WW->>SQL: Release lease

    API->>SQL: Resolve ACTIVE snapshot path
    API->>FS: connect dw-vN.duckdb with read_only=True
    FS-->>API: Concurrent RO query without blocking writer
    API->>FS: close
```

---

## 6. `[TO-BE]` Snapshot-Aware Data Lifecycle, Compaction & Retention

```mermaid
stateDiagram-v2
    [*] --> WRITTEN_IMMUTABLE: Micro-batch or REST write
    WRITTEN_IMMUTABLE --> ACTIVE_MANIFEST: SQL tx flips lake_snapshots ACTIVE
    ACTIVE_MANIFEST --> COMPACTING: Fragment count reaches threshold
    COMPACTING --> ACTIVE_MANIFEST: New compacted Parquet and manifest flip
    ACTIVE_MANIFEST --> SUPERSEDED_GRACE: Replaced by newer snapshot
    COMPACTING --> SUPERSEDED_GRACE: Old fragments superseded
    ACTIVE_MANIFEST --> EXPIRED_MANIFEST: Partition dt exceeds age or size cap
    EXPIRED_MANIFEST --> SUPERSEDED_GRACE: Manifest excludes expired dt
    SUPERSEDED_GRACE --> DELETED_OBJECT: Unreferenced by retained snapshots and past grace TTL
    DELETED_OBJECT --> [*]
```
