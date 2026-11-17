# ADR-DP-005: Hot State Cache — NATS JetStream KV (`StorageType.MEMORY`) + In-Process `TTLCache` vs. Redis

- **Status:** Accepted (Phase 1 Baseline — Empirically Verified `#6`, `#16`)
- **Date:** 2026-11-17
- **Linked Requirements:** `REQ-DP-HOT-01`, `REQ-DP-SRV-01`
- **Linked Components:** `COMP-DP-07`, `COMP-DP-08`

---

## 1. Context & Empirical Evidence (`OBSERVED` / `MEASURED` `#6`, `#16`)
1. **Host Reality (`MEASURED` `#6`):** Windows 10 host has `31.89 GB` RAM with only **`2.64 GB` currently available** (`91.7%` occupied). **Redis (`redis-server`/`redis-cli`), Docker Desktop, and WSL2 are NOT installed/available on host.** Official Redis does not ship native Windows server builds.
2. **NATS JetStream KV Probe (`MEASURED` `#16` against live `.bin/nats-server.exe v2.15.3`):**
   - Pre-probe NATS `/jsz`: `max_memory=64 MB`, `max_storage=128 MB`, and `MARKET_EVENTS` + `MARKET_DLQ` already reserve `127,506,841 B` (`121.6 MB`), leaving only **`6.40 MB` unreserved file storage**.
   - `StorageType.FILE` KV (`max_bytes=8MB`) **FAILED**: `ServerError 10047: insufficient storage resources available`.
   - `StorageType.MEMORY` KV (`max_bytes=4MB`, `ttl=1.5s`, `history=1`) **SUCCEEDED**:
     - Bucket create: `0.858 ms`; `kv.watch`: `1.306 ms`
     - `kv.put` (100x ~512B): `avg 0.231 ms` (`p95 0.423 ms`)
     - `kv.get` (100x ~512B): `avg 0.362 ms` (`p95 0.644 ms`)
     - Server-side TTL expiration verified (`KeyNotFoundError` at `1.8s` for `ttl=1.5s`)
     - `varz.mem` delta during puts: `0 B` (`+1.62 MB` across entire probe).

## 2. Options Considered
1. **Option A — Mandate Redis (`redis-server`) for Hot State & Cache:** Rejected for `LITE` and single-node `STANDARD`. Adding Redis requires Docker/WSL2 or unsupported third-party Windows ports, consumes extra RAM on a `2.64 GB`-free workstation, and adds operational failure surface for functionality already covered by `nats-server.exe` + bounded Python LRU.
2. **Option B — NATS JetStream KV (`StorageType.FILE`):** Rejected (`MEASURED` `#16`); fails under `LITE` `128 MB` disk-store ceiling unless stream caps are severely shrunk, and adds unnecessary disk I/O for ephemeral hot snapshots.
3. **Option C — `HotStateCache` Abstraction (`IFC-DP-009`) Backed by NATS JetStream KV (`StorageType.MEMORY`) + Bounded In-Process `TTLCache` (`PROPOSED`):** Zero additional daemon, sub-millisecond cross-process state, Redis kept strictly optional/future for multi-replica horizontal API scaling.

## 3. Decision
Adopt **Option C**:
1. **Interface (`IFC-DP-009`, `backend/app/streaming/hot_state.py`):** Define `HotStateCache` protocol (`get_json`, `put_json`, `delete`, `list_prefix`, `invalidate_local`, `stats`, `close`) so callers depend on a clean abstraction rather than concrete transport.
2. **Default Single-Node Implementation:**
   - **Shared Cross-Process Hot State (`StreamWorker` <-> `WorkflowWorker` <-> `API`):** NATS JetStream KV using **`StorageType.MEMORY`** (`IFC-DP-004`):
     - `hot_state` bucket (`max_bytes`: `8 MB` LITE / `16 MB` STANDARD / `32 MB` EXTENDED, `history=1`, `ttl=300.0`s) holding `market.snapshot.{SYMBOL}` and `forecast.latest.{SYMBOL}`.
     - `worker_heartbeats` (`max_bytes`: `1 MB` LITE / `2 MB` STANDARD / `4 MB` EXTENDED, `history=1`, `ttl=15.0`s) holding `worker.<role>.<worker_id>` (`worker.stream.*`, `worker.workflow.*`) so dead workers auto-expire in 15s.
   - **API Read Cache:** Bounded in-process `TTLCache` (`<= 10 MB` cap, short TTL e.g. `15–60s`) for hot `/market/symbols` and `/analytics/*` summaries, actively invalidated when `ServingGatewayBridge` receives `serving.events.closed_bar`.
   - **Graceful Degradation:** If NATS is temporarily disconnected, `HotStateCache` falls back to local `TTLCache` / SQLite & Warehouse read-only queries without crashing requests.
3. **Stream Storage Headroom Adjustment (`IFC-DP-003`):** Lower `MARKET_EVENTS` stream reservation from `75%` (`broker.py:208`) to `70%` alongside `20%` DLQ (`10%` headroom) while keeping KV strictly in `StorageType.MEMORY` within `nats_max_mem_mb` (`64/128/256 MB`).
4. **Redis Scope:** `RedisHotStateAdapter` may be added later under `EXTENDED` multi-replica deployments (`redis://...` optional); it is **NOT** required or claimed active on the single-node host.

## 4. Consequences
- **Positive:** Sub-millisecond (`~0.23–0.36 ms`) cross-process hot state and TTL-based worker liveness with **0 extra OS daemons** and **0 MB additional RSS footprint** beyond the existing `nats-server.exe`.
- **Negative / Mitigation:** Memory-backed KV resets if `nats-server.exe` restarts; mitigated because `hot_state` is strictly ephemeral serving cache—canonical state always rebuilds cleanly from SQL `klines`, `IncrementalAnalyticsEngine` atomic checkpoints, and `dw-v{N}.duckdb`.
