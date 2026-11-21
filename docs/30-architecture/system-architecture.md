# Resource-Efficient Single-Node Financial Data Intelligence Architecture

**Version:** 3.0.0 (Target Architecture Specification)  
**Target Environment:** Single-node workstation (Intel i5-12400F, 8 GB RAM, constrained C: disk)

---

## 0. Target vs. Currently Implemented Status (Phase 14 Verification)

> [!NOTE]
> The single-node 3-plane real-time platform (`v3.0.0`) is **implemented** on host native Windows (`LITE` / `STANDARD` code paths), including:
> - **Implemented & Verified**: Binance public WebSocket (`aggTrade`, `kline_1m`) + REST backfill -> canonical event normalizer -> bounded producer queue with backpressure -> NATS JetStream (`2.15.3`, durable pull consumer, explicit ACK/NAK/DLQ/replay) -> micro-batch Bronze (`zstd` JSONL) -> Silver (partitioned Parquet + SQLite WAL metadata) -> Gold (DuckDB + Parquet marts & ML feature sets), 10-rule Data Quality SLA, persisted Data Catalog (7 datasets) & Lineage DAG, retention policy enforcement, 15 incremental + batch financial/risk analytics, CPU scikit-learn walk-forward CV with naive baseline gating, forecast ledger & post-close reconciler, coalesced WS gateway (`/api/v1/ws/market`), Prometheus `/metrics`, and the 10-view React/TypeScript/Vite frontend.
> - **Validated Config Only / Not Runtime-Executed**: Docker Compose profiles (`lite`, `standard`, `extended` validated with `docker compose config --quiet`), optional EXTENDED containers (MinIO, Prometheus, Grafana), external PostgreSQL server runtime (migrations & SQLite WAL executed; live Postgres server not started due to stopped Docker Desktop and ~1.4-1.5 GB free RAM constraint on the 8 GB host), and remote MLflow server (`NOT_CONFIGURED` -> local SQLite/file fallback active).

---

## 1. Three-Plane Logical Architecture

1. **DATA PLANE:** External connectors (Binance WS + REST) -> Canonical Event Normalizer -> Bounded Queue -> NATS JetStream Broker -> Durable Pull Consumers -> Micro-Batch Bronze (`zstd` JSONL) -> Validated Silver (Partitioned Parquet + SQLite/Postgres metadata) -> Materialized Gold (DuckDB + Parquet Marts) -> Data Quality, Data Catalog, Data Lineage, Checkpoints, Replay, Retention.
2. **INTELLIGENCE PLANE:** Incremental Per-Symbol Analytics & Feature State (SMA, EMA, RSI, MACD, BB, ATR, VWAP, Returns, Log Returns, Volatility, VaR, CVaR, MDD, Correlation, Covariance) + Independent Batch Reference Analytics -> Offline Feature Generator -> CPU-Friendly ML Training (`Ridge`, `LogisticRegression`, `HistGradientBoosting`, Baselines) -> Walk-Forward CV & Gating -> Model Registry -> Triggered Realtime Inference -> Forecast Ledger & Reconciliation.
3. **APPLICATION PLANE:** FastAPI REST API + Coalesced WebSocket Gateway (`/api/v1/ws/market`) + Prometheus `/metrics` + Static React/Vite UI (Data Operations Overview, Live Market Monitor, Data Explorer & Catalog, Data Quality & Lineage, Pipeline Observatory, Financial & Risk Analytics, Prediction Studio, Forecast History, Model Lab, System Health).

---

## 2. Architecture Diagrams

### 2.1 System Context
```mermaid
flowchart LR
    BinanceWS["Binance Public WebSocket (aggTrade, kline_1m)"] --> Platform["Single-Node Financial Intelligence Platform"]
    BinanceREST["Binance Public REST API (Historical Klines)"] --> Platform
    User["Analyst / Trader Browser"] -->|HTTPS REST & Coalesced WS| Platform
    Ops["Operator / Prometheus"] -->|Metrics & Health Probes| Platform
    Platform -->|Local FS / Optional MinIO| Storage["Medallion Lakehouse & SQL DB"]
```

### 2.2 Three-Plane Architecture
```mermaid
flowchart TB
    subgraph DP["DATA PLANE"]
        Ing["WS & REST Ingestion"] --> NATS["NATS JetStream Broker"]
        NATS --> Cons["Durable Pull Consumers"]
        Cons --> Brz["Bronze (zstd JSONL)"]
        Brz --> Slv["Silver (Parquet + DQ)"]
        Slv --> Gld["Gold (DuckDB + Parquet Marts)"]
        Gld --> Gov["Catalog, Lineage & Retention"]
    end

    subgraph IP["INTELLIGENCE PLANE"]
        Cons --> Inc["Incremental Rolling State"]
        Slv --> Batch["Batch Reference & Gold Analytics"]
        Inc --> Feat["Online & Offline Features"]
        Feat --> ML["CPU ML Walk-Forward & Registry"]
        ML --> Inf["Triggered Inference & Reconciliation"]
    end

    subgraph AP["APPLICATION PLANE"]
        API["FastAPI REST + /metrics"]
        WSG["Coalesced WebSocket Gateway"]
        UI["React + Vite Static Dashboard"]
        API --> UI
        WSG --> UI
    end

    Gld --> API
    Inc --> WSG
    Inf --> API
    Gov --> API
```

### 2.3 Component Relationships
```mermaid
flowchart LR
    WS["BinanceWSClient"] -->|Bounded Queue| Prod["JetStreamProducer"]
    REST["BinanceSyncService"] --> Prod
    Prod --> Broker["NATS JetStream"]
    Broker -->|Pull Batch| C1["MedallionConsumer (Bronze & Silver)"]
    Broker -->|Pull Batch| C2["AnalyticsFeatureConsumer"]
    Broker -->|Pull Batch| C3["ServingGatewayBridge"]
    Broker -->|MaxDeliver Exceeded| DLQ["Dead-Letter Subject & Store"]
    C1 --> Store["StorageBackend (LocalFS / S3)"]
    C1 --> MetaDB["SQLite WAL / PostgreSQL"]
    C2 --> State["RollingState & Checkpoints"]
    C2 -->|Closed Candle Trigger| InfSvc["ForecastService"]
    Duck["DuckDB Engine"] --> Store
    FastAPI["FastAPI App"] --> Duck
    FastAPI --> MetaDB
    FastAPI --> C3
```

### 2.4 Ingestion Flow & Event Semantics
```mermaid
sequenceDiagram
    participant BWS as Binance WebSocket
    participant NRM as Canonical Normalizer
    participant BQ as Bounded Queue (maxsize)
    participant NATS as NATS JetStream

    BWS->>NRM: Raw aggTrade or kline_1m frame
    NRM->>NRM: Attach event_time, ingestion_time, schema_version, event_id
    alt Queue < 80% capacity
        NRM->>BQ: Enqueue canonical event
    else Queue >= 80% High Watermark
        NRM->>NRM: Increment backpressure metric & await drain (no silent drop)
        NRM->>BQ: Enqueue after drain
    end
    BQ->>NATS: Publish with Nats-Msg-Id (dedup window)
    NATS-->>BQ: PubAck (stream sequence persisted)
```

### 2.5 Broker and Consumer Flow
```mermaid
flowchart TD
    Stream["JetStream Stream: MARKET_EVENTS (WorkQueue/Limits, File Store)"]
    Stream --> Pull["Durable Pull Consumer (Batch=50..200, AckWait=30s)"]
    Pull --> Dedup{"Duplicate event_id / open_time?"}
    Dedup -->|Yes| AckDup["msg.ack() (Idempotent Skip)"]
    Dedup -->|No| Validate{"Canonical & OHLC Valid?"}
    Validate -->|Valid| Process["Micro-Batch Write / State Update"]
    Process -->|Commit OK| AckOK["msg.ack() + Update Watermark"]
    Process -->|Transient Error| Nak["msg.nak(delay=backoff)"]
    Validate -->|Malformed| DLQ["Publish to market.dlq + Persist DLQ Record + msg.ack()"]
    Nak -->|Exceeds max_deliver| DLQ
```

### 2.6 Medallion Flow
```mermaid
flowchart LR
    Src["Binance WS & REST"] -->|Immutable JSONL.zst| Bronze["Bronze Layer (data/bronze/stream=...)"]
    Bronze -->|Schema + Dedup + DQ Gate| Silver["Silver Layer (data/silver/.../*.parquet + klines metadata)"]
    Silver -->|DuckDB Aggregation & Compaction| Gold["Gold Marts (returns, volatility_risk, drawdowns, correlations, features Parquet)"]
    Gold -->|Queryable Views| Serving["REST Explorer, Analytics & ML Training"]
```

### 2.7 Database ERD (Operational Metadata)
```mermaid
erDiagram
    SYMBOLS ||--o{ KLINES : tracks
    SYMBOLS ||--o{ SYNC_CHECKPOINTS : checkpoints
    PIPELINE_RUNS ||--o{ PIPELINE_TASK_RUNS : contains
    DATA_QUALITY_RUNS ||--o{ DATA_QUALITY_RESULTS : records
    MODEL_REGISTRY ||--o{ MODEL_EVALUATION_METRICS : scores
    MODEL_REGISTRY ||--o{ FORECAST_RECORDS : produces
    DATA_CATALOG_ENTRIES ||--o{ DATA_LINEAGE_EDGES : sources
    DATA_CATALOG_ENTRIES ||--o{ DATA_LINEAGE_EDGES : targets
    DEAD_LETTER_EVENTS {
        string id PK
        string subject
        string symbol
        string error_reason
        datetime created_at
    }
    DATA_CATALOG_ENTRIES {
        string dataset_id PK
        string layer
        string format
        string storage_location
        int row_count
        string retention_policy
        string version
    }
    DATA_LINEAGE_EDGES {
        string id PK
        string run_id
        string source_dataset
        string target_dataset
        string transformation
        int records_in
        int records_out
    }
```

### 2.8 Data Catalog and Lineage
```mermaid
flowchart LR
    C_SRC["binance_public_ws_rest (SOURCE)"] -->|Ingest & Normalize| C_BRZ["bronze_market_events (BRONZE zstd JSONL)"]
    C_BRZ -->|DQ Validate & Dedup| C_SLV["silver_klines & silver_trades (SILVER Parquet)"]
    C_SLV -->|DuckDB Aggregate| C_GLD["gold_analytics_marts (GOLD Parquet)"]
    C_SLV -->|Zero-Leakage Calc| C_FEA["gold_feature_sets (FEATURES Parquet)"]
    C_FEA -->|Walk-Forward Train| C_MOD["model_registry (ML ARTIFACTS)"]
    C_MOD -->|Triggered Inference| C_FC["forecast_records (SERVING LEDGER)"]
```

### 2.9 Financial Analytics (Incremental + Batch Reference)
```mermaid
flowchart TD
    ClosedBar["Closed Candle / Trade Tick"] --> IncEngine["Per-Symbol Incremental State (Welford Var, Wilder RSI, EMA, VWAP, ATR)"]
    IncEngine --> Checkpoint["Persisted JSON State Checkpoint"]
    IncEngine --> WSG["Coalesced WS Snapshot"]
    SilverPQ["Silver Parquet Partition"] --> DuckBatch["DuckDB + NumPy/SciPy Batch Reference"]
    DuckBatch --> Metrics["Returns, Log Returns, Vol, VaR, CVaR, MDD, Corr, Cov"]
    IncEngine -.->|Parity Test Assertion| DuckBatch
```

### 2.10 ML Pipeline
```mermaid
flowchart LR
    Silver["Silver Klines (Parquet/DB)"] --> Prep["Zero-Leakage Feature Prep"]
    Prep --> Split["Expanding Walk-Forward Splits"]
    Split --> Train["CPU Models (Ridge, Logistic, HistGBT)"]
    Split --> Base["Naive & Rolling Baselines"]
    Train --> Gate{"Beats Naive MAE & Dir Threshold?"}
    Base --> Gate
    Gate -->|Yes| Active["Promote ACTIVE in Model Registry"]
    Gate -->|No| Cand["Store INACTIVE Candidate"]
    ClosedTrigger["Closed 1m/1h Candle Trigger"] --> OnlineFeat["Online Feature State"]
    OnlineFeat --> Active
    Active --> Ledger["Persist ForecastRecord (PENDING)"]
    Ledger --> Reconcile["Post-Target Reconciliation -> RECONCILED"]
```

### 2.11 Deployment Architecture (Adaptive Profiles)
```mermaid
flowchart TB
    subgraph LITE["Profile A: LITE (Native <= 450 MB RAM)"]
        L_NATS["nats-server.exe (-js, 128MB store)"]
        L_API["Uvicorn FastAPI + Embedded Consumers + Static UI"]
        L_DB["SQLite WAL + Local Parquet + DuckDB"]
        L_API --> L_NATS
        L_API --> L_DB
    end

    subgraph STD["Profile B: STANDARD (Native or Docker Compose)"]
        S_NATS["NATS JetStream (512MB store)"]
        S_PG["PostgreSQL 16 (256MB cap)"]
        S_ING["Ingestor & Consumer Worker"]
        S_API["FastAPI + DuckDB + Static Nginx/UI"]
        S_ING --> S_NATS
        S_ING --> S_PG
        S_API --> S_PG
        S_API --> S_NATS
    end

    subgraph EXT["Profile C: EXTENDED (Optional Extensions)"]
        E_MINIO["MinIO S3 Storage"]
        E_PROM["Prometheus + Grafana"]
    end
    STD -.->|Enable compose profile extended| EXT
```

### 2.12 Failure Recovery
```mermaid
flowchart TD
    Fail1["WebSocket Disconnect"] -->|Exponential Backoff + Jitter| Reconnect["Reconnect Stream"]
    Reconnect -->|Check Watermark| GapHeal["REST Backfill Gap Healing"]
    Fail2["Consumer Crash / Restart"] -->|Load Durable Consumer Offset| NATSReplay["NATS Redeliver Unacked Msgs"]
    Fail3["Corrupted Downstream State"] -->|Trigger Replay by Time/Seq| Replay["JetStream Replay -> Recompute Silver/Gold"]
    Fail4["Malformed Event Payload"] -->|MaxDeliver Reached| DLQ["Dead-Letter Store + Alert Metric"]
```

---

## 3. Streaming, Storage, Resource & Security Policies

### Streaming Semantics
- **Event Time (`event_time`)**: Exchange candle open/close or trade timestamp (`T` / `E` from Binance), stored in UTC.
- **Ingestion Time (`ingestion_time`)**: UTC timestamp recorded when the WS/REST connector receives the frame.
- **Processing Time (`processing_time`)**: UTC timestamp recorded when a consumer processes/persists the record.
- **Partition Key**: `symbol` (for NATS subject sharding `market.<stream>.<symbol>`) and `(source, event_type, dt, symbol)` for Parquet paths.
- **Watermark & Late Events**: Per-symbol high-watermark tracks latest closed `open_time`. If a late/corrected closed candle arrives (`open_time <= watermark`), consumers upsert idempotently (`(symbol, timeframe, open_time)`), rewrite the affected daily Silver partition, mark Gold mart stale for recomputation, and log a late-event metric.

### Security Architecture
- No Binance API keys required (public market data only).
- Strict input validation on symbols (`^[A-Z0-9]{3,20}$`), timeframes, dataset identifiers, and pagination bounds.
- CORS restricted to configured origins; security response headers (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`) enforced.
- Sanitized HTTP/WS errors (no tracebacks, SQL, env vars, or filesystem paths exposed publicly).
- Optional API admin token (`ADMIN_API_TOKEN`) support for privileged mutation endpoints when deployed beyond localhost.

