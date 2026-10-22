# Enterprise Data Flow & Lifecycle Architecture

**Document Version**: 2.0.0  
**Application**: Binance Predict Value & Trend  
**Layered Architecture**: Medallion Pipeline (Bronze $\rightarrow$ Silver $\rightarrow$ Gold $\rightarrow$ Features $\rightarrow$ Serving)

---

## 1. End-to-End Medallion Data Lifecycle

```mermaid
flowchart TD
    subgraph Ingestion["1. Bronze Ingestion Layer"]
        A[Binance Public Spot REST API] -->|GET /api/v3/klines| B[Bronze Ingestion Buffer]
        B -->|Raw Bar Validation & Deduplication| C[(Database: raw_market_klines)]
    end

    subgraph SilverLayer["2. Silver Validation Layer"]
        C --> D[Data Quality Rule Engine]
        D -->|Evaluate 10 Data Contracts| E{Contract SLA Pass?}
        E -->|Yes| F[(Database: validated_market_klines)]
        E -->|No / Violations| G[(Database: data_quality_runs & results)]
    end

    subgraph GoldLayer["3. Gold Analytical Marts"]
        F --> H1[Returns Mart: Simple, Log, Kurtosis, Skew]
        F --> H2[Volatility Mart: 7d, 14d, 30d Annualized]
        F --> H3[Drawdowns Mart: Running Peak & Max Drawdown]
        F --> H4[Cross-Asset Correlation Matrix]
        H1 & H2 & H3 & H4 --> I[(Database: analytical_gold_marts)]
    end

    subgraph FeatureEngineering["4. Technical Features (Zero Leakage)"]
        F --> J1[SMA 7, 25, 99]
        F --> J2[EMA 12, 26, MACD & Signal]
        F --> J3[RSI 14 & Bollinger Bands]
        J1 & J2 & J3 --> K[(Database: ml_feature_sets)]
    end

    subgraph ModelingObservability["5. Model Training & Gating"]
        K --> L[Walk-Forward Time-Series Splitter]
        L --> M[Train Candidate Model: GradientBoosting / Random Forest]
        M --> N{Beats Naive Baseline?}
        N -->|Yes| O[Register as ACTIVE Model]
        N -->|No| P[Flag CANDIDATE_REJECTED]
        O --> Q[MLflow Tracking / Local Registry]
    end

    subgraph PredictionServing["6. Prediction Serving & Audit Ledger"]
        O & F --> R[Prediction Studio Engine]
        R --> S[Point Prediction + CI 95% Bounds + Probability]
        S --> T[(Database: immutable_forecast_records)]
        T --> U[Historical Reconciler Worker]
        U -->|Compare Forecast vs Actual Closed Price| V[Hit Rate & Accuracy Metrics]
    end
```

---

## 2. Market-Data Ingestion & Incremental Synchronization

```mermaid
sequenceDiagram
    autonumber
    actor User as User / Scheduler
    participant API as FastAPI Backend (/api/v1/market/sync)
    participant SyncSvc as MarketSyncService
    participant Binance as Binance Public REST API
    participant DB as SQLite / PostgreSQL (AsyncSession)

    User->>API: POST /api/v1/market/sync {symbol: "BTCUSDT", timeframe: "1h", lookback_days: 30}
    API->>SyncSvc: sync_market_candles(symbol, timeframe, lookback_days)
    SyncSvc->>DB: Query latest stored candle open_time (Watermark Checkpoint)
    DB-->>SyncSvc: Latest timestamp (or NULL if fresh)
    
    alt Watermark exists
        SyncSvc->>Binance: Fetch klines from (latest_timestamp + 1ms)
    else First-time sync
        SyncSvc->>Binance: Fetch klines from (now - lookback_days)
    end
    
    Binance-->>SyncSvc: Raw OHLCV Kline Bars JSON
    SyncSvc->>SyncSvc: Parse & Validate Geometry (High >= Low, etc.)
    SyncSvc->>DB: Bulk Upsert Validated Candles (deduplicating on (symbol, timeframe, open_time))
    DB-->>SyncSvc: Commit confirmation
    SyncSvc-->>API: Result {symbol, added_candles, status: "SUCCESS"}
    API-->>User: 200 OK JSON Response
```

---

## 3. Synchronous vs Asynchronous Task Execution

| Workflow Stage | Execution Mode | Database Session Owner | Error Handling & Observability |
| :--- | :--- | :--- | :--- |
| **Incremental Sync** (`/market/sync`) | Synchronous (bounded to 1000 candles per batch) | Route handler `AsyncSession` | Returns HTTP 400/502 with error details; rolls back transaction on error. |
| **Full Pipeline Trigger** (`/pipelines/trigger?sync_mode=false`) | Asynchronous Background Task (`FastAPI.BackgroundTasks`) | Worker-dedicated `AsyncSession` context manager | Writes execution state (`RUNNING` $\rightarrow$ `SUCCESS` / `FAILED`) to `pipeline_runs` table with detailed stage logs. |
| **Data Quality Audit** (`/data-quality/evaluate`) | Synchronous or Background | Isolated session per audit run | Records per-rule pass/fail count, severity, and violation payload samples. |
| **Walk-Forward Model Training** (`/models/train`) | Synchronous compute (bounded sample size) | Dedicated session | Enforces baseline promotion gatekeeper; logs MAE, RMSE, and MAPE metrics. |
| **Forecast Reconciliation** (`/forecasts/reconcile`) | Synchronous batch reconcile | Dedicated session | Reconciles open forecasts against closed bars and marks them `RECONCILED`. |

---

## 4. Frontend State Machine & Error Handling

```mermaid
stateDiagram-v2
    [*] --> Idle: Mount View
    Idle --> Loading: Fetch API Request
    Loading --> Success: HTTP 200 OK & Schema Validated
    Loading --> Empty: HTTP 200 OK & Record Count = 0
    Loading --> Error: HTTP 4xx/5xx or Network Failure
    
    Success --> Stale: Data age exceeds Freshness SLA
    Stale --> Loading: User Triggers Sync / Refresh
    Empty --> Loading: User Clicks "Seed / Sync Data"
    Error --> Loading: User Clicks "Retry"
```
