# Data Plane Architecture Diagrams

**Document ID:** `DOC-DP-20-DIAGRAMS`  
**Version:** `1.0.0`  
**Status:** `APPROVED_PHASE_1_BASELINE`  
**Legend:** Every diagram is explicitly tagged `[AS-IS]`, `[TO-BE]`, or `[TRANSITION]`. Solid arrows denote synchronous or primary data flows; dashed arrows (`-.->`) denote asynchronous control, wakeups, metadata, or read paths.

---

## 1. `[TO-BE]` System Context Diagram

```mermaid
flowchart LR
    BWS["Binance Public WebSocket (aggTrade, kline_1m)"] -->|"TLS Stream (Async)"| DP["Single-Node Data Intelligence Platform"]
    BREST["Binance Public REST API (klines, aggTrades)"] -->|"HTTPS Backfill / Gap-Heal"| DP
    Analyst["Analyst / Operator Browser"] <-->|"HTTP REST & Coalesced WS (/api/v1/ws/market)"| DP
    Ops["Operator / Prometheus Scraper"] -->|"HTTP GET /metrics & /api/v1/system/resources"| DP
    DP -->|"LocalFS Atomic / Optional S3 (MinIO)"| Lake["Medallion Lakehouse & DuckDB Snapshots"]
    DP -->|"SQLite WAL / Optional PostgreSQL"| MetaDB["Operational Metadata & Workflow Ledger"]
```

---

## 2. `[AS-IS]` C4 Container & Coupling Diagnosis (Observed Defects `#7`, `#8`, `#9`)

```mermaid
flowchart TB
    subgraph ASIS_HOST["[AS-IS] Windows Host (embedded_in_api=True in LITE / Split-Brain in STANDARD)"]
        BWS_A["Binance WS & REST"] -->|"Inline or Unsynced"| API_PROC["FastAPI Uvicorn Process (Singleton stream_runtime)"]
        API_PROC -->|"BackgroundTasks (Volatile)"| BG["In-Memory Pipeline Tasks (No Lease/Reaper)"]
        API_PROC -->|"Volatile Queue + Pre-Commit Dedup"| NATS_A["NATS JetStream (MARKET_EVENTS)"]
        NATS_A -->|"Pull"| CONS_A["MedallionConsumer (No Flush Lock, Mid-Loop DQ Commit)"]
        CONS_A -->|"Overwrite In-Place"| PARQ_A["Silver/Gold Parquet (dt=max_date Dupes, No Manifests)"]
        CONS_A -->|"Direct SQLite (open->closed skipped)"| SQL_A["SQLite WAL (klines + checkpoints)"]
        API_PROC -->|"Analytics/ML Read SQL klines Only"| SQL_A
        SW_A["stream_worker.py (STANDARD Separate Process)"] -.->|"NO IPC BRIDGE -> Dead /ws/market & Zero Telemetry"| API_PROC
    end
```

---

## 3. `[TO-BE]` C4 Container Diagram (Decoupled Processes, Unified Contracts)

```mermaid
flowchart TB
    subgraph EXT["External Feeds"]
        BWS["Binance WS (aggTrade, kline_1m)"]
        BREST["Binance REST (klines, aggTrades)"]
    end

    subgraph BROKER["Message & Hot-State Plane (.bin/nats-server.exe v2.15.3)"]
        JS["JetStream File Store (MARKET_EVENTS + MARKET_DLQ)"]
        CORE["NATS Core Pub/Sub (serving.market.*, serving.control.*, workflow.wakeup)"]
        KV["JetStream KV MEMORY (hot_state TTL=300s, worker_heartbeats TTL=15s)"]
    end

    subgraph WORKERS["Data & Orchestration Workers (Embedded in LITE / Dedicated in STANDARD)"]
        SW["StreamWorker: Ingestor + Producer + MedallionStreamConsumer + IncrementalAnalytics"]
        WW["WorkflowWorker: SQL-Leased DAGs (Backfill, Gold, Warehouse ETL, Compaction, ML, Retention)"]
    end

    subgraph SERVING["Application Plane (FastAPI Process)"]
        API["FastAPI REST + /metrics + Admin Guard"]
        BRIDGE["ServingGatewayBridge + WSBroadcastHub + Bounded TTLCache"]
    end

    subgraph STORAGE["Persistence Plane"]
        SQL[("SQLite WAL / PostgreSQL: klines, manifests, batch_ledger, workflow_*")]
        LAKE[("Immutable Lake: Bronze zstd, Silver/Gold Parquet")]
        DW_STG[("DuckDB dw_staging.duckdb (Single RW Writer)")]
        DW_SNP[("Immutable Snapshots: dw-v{N}.duckdb (Concurrent RO Readers)")]
    end

    BWS -->|"Async WS"| SW
    BREST -.->|"Single-Flight Heal"| SW
    BREST -.->|"Scheduled / Manual Backfill"| WW
    SW -->|"Publish + Nats-Msg-Id"| JS
    JS -->|"Durable Pull + Post-Commit ACK"| SW
    SW -->|"Immutable Files"| LAKE
    SW -->|"Atomic Batch Commit"| SQL
    SW -.->|"Publish serving.market.<SYMBOL> / KV Put"| CORE
    SW -.->|"Put hot_state & heartbeat"| KV
    WW <-->|"Claim Lease / Heartbeat / Reaper"| SQL
    WW -->|"Gold Materialize & Compaction"| LAKE
    WW -->|"Serialized RW + CHECKPOINT + Close"| DW_STG
    DW_STG -->|"Atomic Snapshot Copy (1.43 ms)"| DW_SNP
    API <-->|"Sub serving.* & Req-Reply control.*"| CORE
    API -.->|"Read KV + TTL Cache"| KV
    API <-->|"Enqueue Workflow / Read Metadata"| SQL
    API -->|"Read-Only Queries"| DW_SNP
    API -->|"Manifest-Resolved Parquet Preview"| LAKE
```

---

## 4. `[TO-BE]` Component Architecture (`COMP-DP-01..13`)

```mermaid
flowchart LR
    C01["COMP-DP-01 Ingestor"] -->|"Async Bounded Queue + Spill"| C02["COMP-DP-02 BrokerAdapter"]
    C02 -->|"Pull Batch"| C03["COMP-DP-03 StreamProcessor"]
    C03 -->|"Atomic Checkpoint"| C13["COMP-DP-13 IncrementalAnalytics"]
    C03 -->|"Immutable Objects"| C04["COMP-DP-04 LakeStorage + Manifests"]
    C03 -->|"Single Atomic Tx"| C05["COMP-DP-05 OperationalDB"]
    C03 -.->|"Post-Commit serving.* & KV"| C08["COMP-DP-08 ServingGatewayBridge"]
    C08 <--> C07["COMP-DP-07 HotStateCache"]
    C09["COMP-DP-09 WorkflowEngine"] -->|"Serialized Lease"| C06["COMP-DP-06 WarehouseService"]
    C09 -->|"Runs"| C10["COMP-DP-10 Governance/DQ/Retention"]
    C04 -->|"ACTIVE Manifests"| C06
    C06 -->|"dw-v{N}.duckdb RO"| C11["COMP-DP-11 API Gateway"]
    C07 --> C11
    C08 --> C11
    C12["COMP-DP-12 Observability"] -.->|"Scrapes / Aggregates"| C11
```

---

## 5. `[TO-BE]` Deployment & Single-Node Resource Allocation Diagram

```mermaid
flowchart TB
    subgraph HOST["Windows 10 Enterprise Host (i5-10600KF 6C/12T | 31.89 GB RAM, 2.64 GB Free | C: 78.19 GB Free)"]
        subgraph NATS_PROC["Process 0: .bin/nats-server.exe v2.15.3 (Shared Core)"]
            N_JS["JetStream File: 128MB (LITE) / 512MB (STD)"]
            N_KV["JetStream Mem KV: 9MB within 64MB (LITE) / 17MB within 128MB (STD)"]
        end

        subgraph LITE_MODE["Profile LITE (<= 450 MB RSS Total)"]
            L_API["Process 1: uvicorn (API + Embedded StreamRuntime + Async Workflow Loop)"]
            L_DB["SQLite WAL + Immutable Lake + dw-v{N}.duckdb (128MB DuckDB Cap)"]
            L_API --> NATS_PROC
            L_API --> L_DB
        end

        subgraph STD_MODE["Profile STANDARD (<= 950 MB RSS Native)"]
            S_API["Process 1: uvicorn API + ServingGatewayBridge (RO dw-v{N})"]
            S_STR["Process 2: workers.stream_worker (WS + Producer + Consumer)"]
            S_WF["Process 3: workers.workflow_worker (DAGs + Single Warehouse Writer)"]
            S_DB["SQLite WAL (or Optional Postgres) + Immutable Lake + Warehouse"]
            S_API --> NATS_PROC
            S_STR --> NATS_PROC
            S_WF --> NATS_PROC
            S_API --> S_DB
            S_STR --> S_DB
            S_WF --> S_DB
        end
    end
```

---

## 6. `[TRANSITION]` Phased Upgrade Roadmap (`Wave 0` -> `Wave 3`)

```mermaid
flowchart LR
    W0["Wave 0: Spec Pack (WI-DP-01), Test Isolation (WI-DP-12), Single Alembic Migration (WI-DP-05), Config/Deps (WI-DP-11)"] --> W1["Wave 1: Consumer Post-Commit ACK (WI-DP-02), Ingest/NATS Reconnect (WI-DP-03), Immutable Lake + Promotion (WI-DP-04), WorkflowEngine (WI-DP-07), Observability (WI-DP-10)"]
    W1 --> W2["Wave 2: DuckDB Warehouse Snapshots (WI-DP-06), ServingGatewayBridge + KV (WI-DP-08), Manifest Governance (WI-DP-09), Security + ML Offload (WI-DP-13)"]
    W2 --> W3["Wave 3: Frontend Contracts (WI-DP-14), Fault Injection S1..S14 & Load Tests, Docs Reconciliation (WI-DP-15)"]
```
