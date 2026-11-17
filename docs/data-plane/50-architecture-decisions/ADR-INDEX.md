# Architecture Decision Records Index (`ADR-DP-001..007`)

**Document ID:** `DOC-DP-50-ADR-INDEX`  
**Version:** `1.0.0`  
**Status:** `APPROVED_PHASE_1_BASELINE`

---

## 1. Decision Registry

| ADR ID | Title | Status | Legacy Supersession | Linked Requirements |
|---|---|---|---|---|
| [`ADR-DP-001`](ADR-DP-001-runtime-profiles-and-process-topology.md) | Runtime Profiles & Process Topology (`LITE` vs `STANDARD` vs Optional `EXTENDED`) | `Accepted (Phase 1)` | Supersedes process-coupling assumptions in `docs/40-adr/ADR-001` | `REQ-DP-CFG-01`, `REQ-DP-SRV-01`, `REQ-DP-OBS-01..03` |
| [`ADR-DP-002`](ADR-DP-002-microbatch-durability-and-post-commit-ack.md) | Micro-Batch Durability State Machine & Post-Commit Acknowledgment | `Accepted (Phase 1)` | Supersedes pre-commit dedup/flush semantics in `docs/40-adr/ADR-004` | `REQ-DP-ING-01..04`, `REQ-DP-DEL-01..06` |
| [`ADR-DP-003`](ADR-DP-003-immutable-data-lake-and-sql-manifests.md) | Immutable Parquet Data Lake & SQL-Backed Snapshot Manifests | `Accepted (Phase 1)` | Supersedes mutable Parquet assumptions in `docs/40-adr/ADR-003` | `REQ-DP-LAKE-01..06`, `REQ-DP-KLN-01`, `REQ-DP-SEC-03` |
| [`ADR-DP-004`](ADR-DP-004-persistent-duckdb-warehouse-and-snapshots.md) | Persistent DuckDB Star Schema Warehouse & Versioned Snapshots | `Accepted (Phase 1, Empirically Verified #15)` | Supersedes `:memory:`-only OLAP in `docs/40-adr/ADR-003` | `REQ-DP-DW-01..03` |
| [`ADR-DP-005`](ADR-DP-005-hot-state-cache-nats-kv-and-redis-evaluation.md) | Hot State Cache via NATS JetStream KV (`StorageType.MEMORY`) + In-Process `TTLCache` vs Redis | `Accepted (Phase 1, Empirically Verified #16)` | New decision | `REQ-DP-HOT-01` |
| [`ADR-DP-006`](ADR-DP-006-durable-sql-workflow-orchestrator.md) | SQL-Backed Durable Workflow Orchestrator (Separate from NATS JetStream) | `Accepted (Phase 1)` | Replaces `FastAPI.BackgroundTasks` in `docs/architecture/data-flow.md:97` | `REQ-DP-ORC-01..04` |
| [`ADR-DP-007`](ADR-DP-007-serving-gateway-bridge-over-nats.md) | Canonical `ServingGatewayBridge` Over NATS Core & JetStream KV | `Accepted (Phase 1)` | Realizes `ServingGatewayBridge` in `docs/30-architecture/system-architecture.md:79` | `REQ-DP-SRV-01`, `REQ-DP-SEC-01..02` |
