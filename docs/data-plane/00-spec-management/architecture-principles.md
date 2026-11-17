# Architecture Principles & Engineering Invariants

**Document ID:** `DOC-DP-00-PRINCIPLES`  
**Version:** `1.0.0`  
**Status:** `APPROVED_PHASE_1_BASELINE`

---

These principles bind every component (`COMP-DP-01..13`), decision (`ADR-DP-001..007`), and Phase 2 work item (`WI-DP-01..15`), grounded in `AGENTS.md` and `.agent/rules/*.md`.

1. **Single-Node Resource Discipline (`PROPOSED`, grounded in `MEASURED` #6):**  
   Design for the measured workstation reality (`2.64 GB` currently available host RAM out of `31.89 GB`; zero Docker/WSL2/Redis/PostgreSQL on host). Every queue, micro-batch buffer, cache, NATS stream, KV bucket, and DuckDB connection enforces explicit bounded memory and disk limits.
2. **Same Semantics Across Profiles (`PROPOSED`, `AGENTS.md` Rule 6 & `ADR-001`):**  
   `LITE` (single-process composition) and `STANDARD`/`EXTENDED` (multi-process) MUST use the **exact same canonical bridges, state machines, schemas, and financial/ML math** (`ServingGatewayBridge`, `HotStateCache`, `WorkflowEngine`). Profile toggles scale bounds and process topology only—never correctness or API contract parity.
3. **Zero Silent Data Loss & Post-Commit Acknowledgment (`PROPOSED`):**  
   At-least-once delivery is enforced end-to-end. Deduplication caches (`BoundedDedupCache`), broker `ACK`s, and downstream inference triggers MUST fire **only after** durable file writes and SQL transaction commits succeed. Malformed messages may be `TERM`ed **only after** durable DLQ persistence succeeds.
4. **Immutability & Atomic Pointer Swaps Over In-Place Mutation (`PROPOSED`):**  
   Neither Silver/Gold Parquet files nor the active DuckDB Warehouse snapshot may be overwritten in place while concurrent readers access them. All Lake and Warehouse updates write immutable objects/staging artifacts first, `CHECKPOINT` / `fsync`, and commit an atomic SQL/pointer swap (`lake_snapshots`, `warehouse_snapshots`).
5. **Strict Separation of Stream Eventing vs Durable Workflow Orchestration (`PROPOSED`):**  
   NATS JetStream handles high-frequency ordered market telemetry (`aggTrade`, `kline`). Long-running, mutually exclusive batch DAGs (backfill, Gold refresh, Warehouse ETL, compaction, ML training, retention) execute via SQL-leased `WorkflowEngine` jobs with heartbeats and crash recovery—never via `FastAPI.BackgroundTasks` or HTTP request handlers.
6. **Truthfulness & Non-Zero Coercion (`OBSERVED` rule in `AGENTS.md` #4/#5, `PROPOSED` enforcement):**  
   Missing, empty, stale, and failed states are distinct first-class states. Never coerce unknown market metrics, worker metrics when decoupled, or uninitialized data to `$0.00` or `0.0%`, and never run DB writes/syncs inside `GET` endpoints.
7. **Schema & Contract First (`AGENTS.md` #3/#6):**  
   Every REST endpoint returns typed Pydantic response models (`MarketDataResponseSchema` preserved verbatim). All timestamps are normalized to UTC; raw exception strings (`str(exc)`), tracebacks, and local filesystem paths are never returned to public clients.
8. **Zero Heavy Dependencies Without Measured Justification (`MEASURED` #6/#16):**  
   Avoid adding external daemons (Redis, Kafka, Spark, Temporal) when native embedded/single-binary equivalents (`nats-server.exe` JetStream KV, SQLite WAL + Alembic, DuckDB `dw-v{N}.duckdb`) meet latency and durability targets within host RAM ceilings.
9. **Test Isolation Before Execution (`OBSERVED` defect in #6):**  
   Automated tests MUST isolate `DATA_DIR`, checkpoints, DB URLs, and NATS ports/store directories to `tmp_path`, guaranteeing zero mutation or retention deletion against user `./data/`.
