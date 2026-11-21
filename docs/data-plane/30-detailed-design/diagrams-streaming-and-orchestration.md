# Streaming and Orchestration Diagrams

- **Document ID:** `DD-DP-DIAG-001`
- **Status:** `PROPOSED` (Specification Baseline v1.0)
- **Owner:** `@stream-orch` (Phase 1 Step 2)
- **Traceability:** `ADR-DP-001`, `ADR-DP-002`, `ADR-DP-005`, `ADR-DP-006`, `ADR-DP-007`, `WI-DP-02`, `WI-DP-03`, `WI-DP-07`, `WI-DP-08`

---

## 1. End-to-End Streaming & Control Data Flow (`[AS-IS]` vs `[TO-BE]`)

### 1.1 [AS-IS] Coupling & Split-Brain Flow (`[OBSERVED]`)

```mermaid
flowchart LR
    BWS["Binance WS"] --> IN["BinanceWebSocketIngestor"]
    IN --> PQ["BoundedEventProducer (asyncio.Queue)"]
    PQ --> NATS["NATS JetStream (MARKET_EVENTS)"]
    NATS --> CON["MedallionStreamConsumer"]
    CON -->|"pre-commit seen()"| DEDUP["BoundedDedupCache (in-mem)"]
    CON -->|"inline create_task BEFORE commit"| INF["Closed-Candle Inference (stale SQL)"]
    CON -->|"files first, mid-loop DQ commit"| FS["Bronze/Silver + SQLite/PG"]
    CON -->|"direct in-proc call"| HUB["WSBroadcastHub (process-local)"]
    API["FastAPI API (embedded=false)"] -.->|"NO IPC BRIDGE (returns 0s/idle)"| HUB
```

### 1.2 [TO-BE] Decoupled Streaming, Lake/Warehouse & Serving Bridge (`[PROPOSED]`)

```mermaid
flowchart LR
    BWS["Binance WS + REST Backfill"] --> ING["Ingestor (Single-Flight Gap Heal + Spool)"]
    ING --> NATS["NATS JetStream (MARKET_EVENTS / MARKET_DLQ)"]
    NATS --> PROC["StreamProcessor (Post-Commit Dedup + ACK)"]
    PROC --> LAKE["Immutable Bronze/Silver + SQL Manifests"]
    PROC --> SQL["Operational DB (Upsert Klines + Checkpoints)"]
    PROC -->|"post-commit KV & Core"| NBRIDGE["NATS Core serving.* + KV hot_state/worker_heartbeats"]
    NBRIDGE --> APIGW["FastAPI ServingGatewayBridge + WSBroadcastHub"]
    WW["WorkflowWorker (SQL Lease + Heartbeat)"] --> LAKE
    WW --> DW["DuckDB Warehouse (dw-vN.duckdb snapshots)"]
    APIGW --> UI["Browser REST + WS /api/v1/ws/market"]
    DW -->|"read_only snapshot"| APIGW
```

---

## 2. [TO-BE] Ingestion, Disconnect Gap-Heal, and Shutdown Sequence

```mermaid
sequenceDiagram
    participant B as Binance WS & REST
    participant I as BinanceWebSocketIngestor
    participant P as BoundedEventProducer
    participant N as NATS JetStream
    participant D as DeadLetter / Spool

    B->>I: WS frames (aggTrade, kline_1m)
    alt Malformed JSON or Schema Violation
        I->>D: Non-blocking enqueue to _malformed_q (never stalls WS loop)
    else Valid Canonical Event v1.1
        I->>P: await producer.enqueue() (backpressure at 80% / blocks at 100%)
        P->>N: js.publish(subject, payload, Nats-Msg-Id=event_id)
    end

    Note over B,I: Network disconnect or remote clean close
    I->>I: Exponential backoff + jitter, rotate primary/fallback URL
    I->>B: Reconnect WS & schedule single-flight gap heal
    I->>B: REST /klines (1m) + REST /aggTrades?fromId=...
    I->>N: Publish backfilled canonical events (idempotent event_id)

    Note over P,D: Graceful shutdown or timeout cancel
    P->>N: Retry drain in_flight + queue until deadline
    opt Timeout expired or NATS unreachable
        P->>D: Atomic write producer_spool.jsonl (replayed on next start)
    end
```

---

## 3. [TO-BE] Event Processing & `ServingGatewayBridge` Sequence

```mermaid
sequenceDiagram
    participant N as NATS JetStream
    participant C as MedallionStreamConsumer
    participant FS as Lake & Atomic Checkpoints
    participant DB as SQL DB (Manifest + Kline + Ckpt)
    participant KV as NATS KV (hot_state)
    participant API as FastAPI ServingGatewayBridge
    participant WS as Browser WS Clients

    C->>N: pull_subscribe.fetch(batch) (checked against conn_epoch)
    C->>C: Validate schema + check read-only dedup.contains(event_id)
    C->>C: Stage batch under _flush_lock
    C->>FS: asyncio.to_thread(write immutable Bronze/Silver + atomic analytics tmp)
    C->>DB: Single txn: Upsert Klines (open->closed) + Manifest + Monotonic StreamCheckpoint
    DB-->>C: COMMIT OK
    C->>C: dedup.commit_keys(staged_ids)
    C->>N: ack() committed messages
    C->>KV: kv.put("market.snapshot.{SYM}", state)
    C->>N: Core pub serving.market.<SYMBOL> & serving.events.closed_bar
    N-->>API: serving.* (~0.24 ms)
    API->>API: Evict L1 TTLCache & enqueue WSBroadcastHub
    API->>WS: Coalesced tick_batch JSON
```

---

## 4. [TO-BE] Micro-Batch Durability State Machine

```mermaid
stateDiagram-v2
    [*] --> RECEIVED: Pull batch from JetStream
    RECEIVED --> QUARANTINED_DLQ: Invalid UTF-8 / JSON
    RECEIVED --> VALIDATED: Canonical schema v1.1 valid
    VALIDATED --> QUARANTINED_DLQ: Validation error
    VALIDATED --> ACK_DUP: dedup.contains(event_id) == True
    VALIDATED --> PREPARED: Stage in uncommitted batch buffer
    PREPARED --> NAK_RETRY: Disk/Parquet write error (deliveries < max_deliver)
    PREPARED --> QUARANTINED_DLQ: Disk/Parquet write error (deliveries >= max_deliver)
    PREPARED --> FILES_WRITTEN: Acquire _flush_lock & write immutable files
    FILES_WRITTEN --> NAK_RETRY: SQL commit error -> rollback (deliveries < max_deliver)
    FILES_WRITTEN --> QUARANTINED_DLQ: SQL commit error -> rollback (deliveries >= max_deliver)
    FILES_WRITTEN --> SQL_COMMITTED: Single atomic db.commit() succeeds
    SQL_COMMITTED --> ACKED: commit_keys() + post-commit triggers + ack() all
    SQL_COMMITTED --> NAK_POST_COMMIT: ack() fails after commit -> nak un-acked subset ONLY
    QUARANTINED_DLQ --> [*]: term() ONLY if NATS DLQ or SQL DLQ succeeded (else nak)
    ACK_DUP --> [*]
    NAK_RETRY --> [*]
    NAK_POST_COMMIT --> [*]
    ACKED --> [*]
```

---

## 5. [TO-BE] Failure & Recovery Sequence (Pre-Commit vs Post-Commit Failure)

```mermaid
sequenceDiagram
    participant N as NATS JetStream
    participant C as MedallionStreamConsumer
    participant D as BoundedDedupCache
    participant DB as SQL DB

    Note over N,DB: Case A — Files written, SQL commit FAILS
    N->>C: Deliver batch (delivery_count=1)
    C->>D: contains(id) -> False (NOT inserted yet)
    C->>DB: Attempt single txn -> FAILS -> rollback()
    C->>N: nak(delay=2s) (D remains empty!)
    N->>C: Redeliver batch (delivery_count=2)
    C->>D: contains(id) -> False (re-processes cleanly!)
    C->>DB: Single txn -> COMMIT OK
    C->>D: commit_keys(ids)
    C->>N: ack() -> Zero data loss!

    Note over N,DB: Case B — SQL commits, ACK FAILS
    N->>C: Deliver batch (msg 1..50)
    C->>DB: COMMIT OK (batch_ledger + StreamCheckpoint.last_stream_seq updated)
    C->>D: commit_keys(ids)
    C->>N: ack() fails at msg 26
    C->>N: nak(delay=2s) ONLY msgs 26..50 (NEVER DLQ/term!)
    N->>C: Redeliver 26..50 -> D.contains()==True -> safe ack() (or idempotent upsert after restart)
```

---

## 6. [TO-BE] Durable Workflow DAG & Task Lease State Machine

```mermaid
stateDiagram-v2
    [*] --> QUEUED: POST /pipelines/trigger (returns run_id)
    QUEUED --> RUNNING: WorkflowWorker atomic claim (lease_owner, lease_token, ttl=60s)
    RUNNING --> RUNNING: Heartbeat renews lease_expires_at every 15s
    RUNNING --> RETRY_WAIT: Task failed or worker crashed -> Stale-Lease Reaper (attempt < max)
    RETRY_WAIT --> RUNNING: next_run_at <= now_utc & atomic claim
    RUNNING --> SUCCESS: All DAG tasks completed (skipping prior SUCCESS tasks on resume)
    RUNNING --> FAILED: Non-retryable error or attempt >= max_attempts
    QUEUED --> CANCELLED: Operator cancel
    RUNNING --> CANCELLED: Operator cancel (fenced by lease_token)
    SUCCESS --> [*]
    FAILED --> [*]
    CANCELLED --> [*]
```
