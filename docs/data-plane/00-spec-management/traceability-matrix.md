# End-to-End Traceability Matrix

**Document ID:** `DOC-DP-00-RTM`  
**Version:** `1.0.1`  
**Status:** `APPROVED_PHASE_1_BASELINE`  
**Cross-Reference:** Test cases `TC-DP-001..029`, `TC-DP-FI-01..14`, and `TC-DP-PERF-01..05` are formally specified in [`70-testing/test-case-catalog.md`](../70-testing/test-case-catalog.md) and [`70-testing/reliability-and-performance-test-spec.md`](../70-testing/reliability-and-performance-test-spec.md).

---

| Req ID | Requirement Summary | Component (`COMP-DP-*`) | ADR (`ADR-DP-*`) | Interface (`IFC-DP-*`) | Work Item (`WI-DP-*`) | Test Case(s) (`TC-DP-*`) |
|---|---|---|---|---|---|---|
| `REQ-DP-ING-01` | Reconnect heals 1m klines & `/aggTrades?fromId` (single-flight) | `COMP-DP-01`, `COMP-DP-04` | `ADR-DP-002` | `IFC-DP-001` | `WI-DP-03`, `WI-DP-04` | `TC-DP-014`, `TC-DP-FI-01` |
| `REQ-DP-ING-02` | Zero producer loss on shutdown/cancel (drain or atomic spill) | `COMP-DP-01` | `ADR-DP-002` | `IFC-DP-002` | `WI-DP-03` | `TC-DP-006`, `TC-DP-FI-03` |
| `REQ-DP-ING-03` | NATS reconnect uses lock & `_conn_epoch` (no orphan `_sub`) | `COMP-DP-02`, `COMP-DP-03` | `ADR-DP-002` | `IFC-DP-003` | `WI-DP-03`, `WI-DP-02` | `TC-DP-007`, `TC-DP-FI-02`, `TC-DP-PERF-02` |
| `REQ-DP-ING-04` | Non-blocking malformed-frame DLQ path on WS ingest | `COMP-DP-01` | `ADR-DP-002` | `IFC-DP-001` | `WI-DP-03` | `TC-DP-FI-09`, `TC-DP-FI-14` |
| `REQ-DP-DEL-01` | Two-phase `BoundedDedupCache` (commit keys only post-SQL) | `COMP-DP-03` | `ADR-DP-002` | `IFC-DP-003` | `WI-DP-02` | `TC-DP-002`, `TC-DP-FI-05` |
| `REQ-DP-DEL-02` | ACK strictly post-files + post-SQL; ACK fail never TERMs committed data | `COMP-DP-03` | `ADR-DP-002` | `IFC-DP-005` | `WI-DP-02` | `TC-DP-003`, `TC-DP-004`, `TC-DP-FI-04`, `TC-DP-FI-05`, `TC-DP-PERF-02` |
| `REQ-DP-DEL-03` | `TERM` only after durable DLQ persistence succeeds; else `NAK` | `COMP-DP-03` | `ADR-DP-002` | `IFC-DP-002` | `WI-DP-02` | `TC-DP-FI-09` |
| `REQ-DP-DEL-04` | Flush mutex + `DataQualityService(commit=False)` inside flush | `COMP-DP-03`, `COMP-DP-10` | `ADR-DP-002` | `IFC-DP-005` | `WI-DP-02` | `TC-DP-005`, `TC-DP-008`, `TC-DP-FI-10`, `TC-DP-FI-12` |
| `REQ-DP-DEL-05` | Closed-bar inference fires post-commit via bounded semaphore | `COMP-DP-03`, `COMP-DP-08` | `ADR-DP-002`, `ADR-DP-007` | `IFC-DP-002` | `WI-DP-02`, `WI-DP-08` | `TC-DP-028`, `TC-DP-FI-13` |
| `REQ-DP-DEL-06` | Atomic analytics checkpoints + idempotent redelivery trade state | `COMP-DP-13` | `ADR-DP-002` | `IFC-DP-005` | `WI-DP-02` | `TC-DP-024`, `TC-DP-FI-04`, `TC-DP-FI-08` |
| `REQ-DP-LAKE-01` | Immutable Parquet objects (no in-place partition overwrite) | `COMP-DP-04` | `ADR-DP-003` | `IFC-DP-005`, `IFC-DP-008` | `WI-DP-04` | `TC-DP-009`, `TC-DP-FI-12` |
| `REQ-DP-LAKE-02` | SQL Snapshot Manifests (`lake_snapshots`, `lake_manifest_files`, `batch_ledger`) | `COMP-DP-04`, `COMP-DP-05` | `ADR-DP-003` | `IFC-DP-005` | `WI-DP-05`, `WI-DP-04` | `TC-DP-009`, `TC-DP-FI-07` |
| `REQ-DP-LAKE-03` | Manifest-swapped Parquet compaction + grace-TTL GC | `COMP-DP-04`, `COMP-DP-10` | `ADR-DP-003` | `IFC-DP-005` | `WI-DP-04`, `WI-DP-09` | `TC-DP-FI-07`, `TC-DP-FI-12` |
| `REQ-DP-LAKE-04` | Gold Marts/Features partitioned by real `open_time` UTC `dt=` (no dupes) | `COMP-DP-04` | `ADR-DP-003` | `IFC-DP-005` | `WI-DP-04` | `TC-DP-011` |
| `REQ-DP-LAKE-05` | Manifest & `dt=` partition retention (S3-safe, no `mtime`, catalog off GET) | `COMP-DP-10` | `ADR-DP-003` | `IFC-DP-005`, `IFC-DP-008` | `WI-DP-09` | `TC-DP-001`, `TC-DP-018` |
| `REQ-DP-LAKE-06` | Explicit Arrow schemas (`taker_buy_*`, `pa.string()`) + schema version | `COMP-DP-04` | `ADR-DP-003` | `IFC-DP-005` | `WI-DP-04` | `TC-DP-009`, `TC-DP-010`, `TC-DP-FI-14` |
| `REQ-DP-KLN-01` | Unified SQL/Silver `ON CONFLICT` promotion (`open->closed`) + `SyncCheckpoint` | `COMP-DP-04`, `COMP-DP-05` | `ADR-DP-003` | `IFC-DP-005` | `WI-DP-04`, `WI-DP-05` | `TC-DP-010`, `TC-DP-012`, `TC-DP-013` |
| `REQ-DP-DW-01` | Persistent DuckDB Star Schema (`dim_*`, `fact_*`, `mart_*`, `warehouse_checkpoints`) | `COMP-DP-06` | `ADR-DP-004` | `IFC-DP-006` | `WI-DP-06` | `TC-DP-026`, `TC-DP-PERF-03` |
| `REQ-DP-DW-02` | Single serialized Warehouse writer (`WorkflowEngine` lease) | `COMP-DP-06`, `COMP-DP-09` | `ADR-DP-004`, `ADR-DP-006` | `IFC-DP-006`, `IFC-DP-007` | `WI-DP-06`, `WI-DP-07` | `TC-DP-026`, `TC-DP-FI-12` |
| `REQ-DP-DW-03` | Immutable `dw-v{N}.duckdb` snapshots for concurrent `read_only=True` readers | `COMP-DP-06` | `ADR-DP-004` | `IFC-DP-006` | `WI-DP-06`, `WI-DP-05` | `TC-DP-026`, `TC-DP-FI-07`, `TC-DP-PERF-03` |
| `REQ-DP-HOT-01` | `HotStateCache` on NATS KV (`StorageType.MEMORY`) + bounded `TTLCache` (no Redis) | `COMP-DP-07` | `ADR-DP-005` | `IFC-DP-004`, `IFC-DP-009` | `WI-DP-08` | `TC-DP-017`, `TC-DP-027` |
| `REQ-DP-ORC-01` | SQL job queue (`workflow_runs`): returns `run_id`, active run mutex | `COMP-DP-09` | `ADR-DP-006` | `IFC-DP-007` | `WI-DP-05`, `WI-DP-07`, `WI-DP-14` | `TC-DP-015`, `TC-DP-029` |
| `REQ-DP-ORC-02` | Worker lease, heartbeat, stale-lease reaper, step-level resume | `COMP-DP-09` | `ADR-DP-006` | `IFC-DP-007` | `WI-DP-07` | `TC-DP-015`, `TC-DP-016`, `TC-DP-FI-11` |
| `REQ-DP-ORC-03` | Persisted `workflow_schedules` replacing `sync_worker` & `cycle%600` | `COMP-DP-09` | `ADR-DP-006` | `IFC-DP-007` | `WI-DP-07` | `TC-DP-015`, `TC-DP-PERF-05` |
| `REQ-DP-ORC-04` | Offload heavy ML training/sync/catalog from API HTTP handlers | `COMP-DP-09`, `COMP-DP-11` | `ADR-DP-006` | `IFC-DP-007` | `WI-DP-13`, `WI-DP-09` | `TC-DP-018`, `TC-DP-029` |
| `REQ-DP-SRV-01` | Canonical `ServingGatewayBridge` keeping API/WS/control identical when decoupled | `COMP-DP-08`, `COMP-DP-11` | `ADR-DP-001`, `ADR-DP-007` | `IFC-DP-002`, `IFC-DP-004` | `WI-DP-08` | `TC-DP-017`, `TC-DP-PERF-05` |
| `REQ-DP-OBS-01` | Per-process metrics aggregation + active staleness/lag computation | `COMP-DP-12` | `ADR-DP-001`, `ADR-DP-007` | `IFC-DP-010` | `WI-DP-10` | `TC-DP-021`, `TC-DP-022` |
| `REQ-DP-OBS-02` | Export host RAM, disk free space, batch/ML failures to `/metrics` | `COMP-DP-12` | `ADR-DP-001` | `IFC-DP-010` | `WI-DP-10` | `TC-DP-022`, `TC-DP-FI-06` |
| `REQ-DP-OBS-03` | Off-event-loop directory sizing (`rglob` via `to_thread` / manifest) | `COMP-DP-12` | `ADR-DP-001` | `IFC-DP-010` | `WI-DP-10` | `TC-DP-023`, `TC-DP-PERF-04` |
| `REQ-DP-SEC-01` | Complete `ADMIN_API_TOKEN` coverage on all mutation routes | `COMP-DP-11` | `ADR-DP-007` | `IFC-DP-007` | `WI-DP-13` | `TC-DP-019` |
| `REQ-DP-SEC-02` | Zero raw `str(e)` / internal paths in HTTP/WS/stored error responses | `COMP-DP-11`, `COMP-DP-09` | `ADR-DP-007` | `IFC-DP-007` | `WI-DP-13`, `WI-DP-07` | `TC-DP-020` |
| `REQ-DP-SEC-03` | Mandatory `TEST-ISO` isolation in `conftest.py` (never touch live `./data/`) | `COMP-DP-05`, `COMP-DP-10` | `ADR-DP-003` | — | `WI-DP-12` | `TC-DP-001` |
| `REQ-DP-CFG-01` | Unified `config.yaml` + `.env` + `Settings`, pinned deps, `psycopg[binary]>=3.2.0,<4.0` + `postgresql+psycopg://`, NATS profile caps | `COMP-DP-02`, `COMP-DP-05` | `ADR-DP-001` | `IFC-DP-011` | `WI-DP-11` | `TC-DP-025`, `TC-DP-PERF-01`, `TC-DP-PERF-05` |
